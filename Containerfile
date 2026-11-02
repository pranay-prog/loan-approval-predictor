# =============================================================================
#  Loan Approval Predictor - custom Podman image
#  21CSE216P Linux and Container Technologies - Capstone Project
#
#  Build :  podman build --format docker -t loan-approval-predictor:1.0.0 .
#  (--format docker keeps the HEALTHCHECK instruction; OCI format drops it)
# =============================================================================

# 1. Base image: small official Python runtime from Docker Hub
FROM docker.io/library/python:3.12-slim

# 2. Build-time argument used for image versioning (1.0.0, 1.1.0 ...)
ARG APP_VERSION=1.0.0

# 3. Image metadata (shown by `podman inspect`)
LABEL org.opencontainers.image.title="loan-approval-predictor" \
      org.opencontainers.image.description="Flask + scikit-learn loan approval predictor (Decision Tree / Logistic Regression)" \
      org.opencontainers.image.authors="Pranay Jain <pj7700@srmist.edu.in>" \
      org.opencontainers.image.version="${APP_VERSION}" \
      course="21CSE216P Linux and Container Technologies" \
      institution="SRM Institute of Science and Technology"

# 4. Runtime configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_VERSION=${APP_VERSION} \
    MODEL_DIR=/app/models \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs \
    PORT=5000

# 5. Working directory inside the container
WORKDIR /app

# 6. Unprivileged user (never run the app as root)
RUN useradd --uid 1001 --user-group --no-create-home --shell /usr/sbin/nologin appuser

# 7. Install Python dependencies first (separate layer = faster rebuilds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 8. Copy the application source
COPY . .

# 9. Train baseline models at build time, keep a seed copy of the dataset,
#    and give the app user ownership of its writable folders
RUN mkdir -p models data logs \
 && python train.py \
 && cp -r data /app/seed-data \
 && chmod +x /app/entrypoint.sh \
 && chown -R appuser:appuser /app

# 10. Drop root privileges
USER appuser

# 11. Document the port gunicorn listens on (published with -p 8080:5000)
EXPOSE 5000

# 12. Trained models persist on a named volume
VOLUME ["/app/models"]

# 13. Container health check -> `podman healthcheck run loan-app`
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4)" || exit 1

# 14. Entrypoint seeds empty mounts, then runs CMD
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", \
     "--timeout", "120", "--preload", "--access-logfile", "-", "wsgi:app"]
