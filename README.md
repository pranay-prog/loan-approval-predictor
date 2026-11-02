# LoanSense: Loan Approval Predictor (containerised with Podman)

**21CSE216P – Linux and Container Technologies · Capstone Project**
Pranay Jain · RA2411003011032 · CSE Core P1 · SRM Institute of Science and Technology, Kattankulathur

> **Problem statement.** Predict whether a loan application will be approved.
> The app loads applicant data (income, credit history, loan amount, …), handles missing values, encodes categorical columns, trains a **Decision Tree** or **Logistic Regression** model, predicts approval for new input and reports accuracy.
> It runs as a two-container Podman deployment with a custom image, a user-defined network, persistent storage and port mapping.

---

## 1. What the application does

| Screen | What you can do |
|---|---|
| **Predict** | Enter an applicant with toggles, sliders and live EMI calculation. You get an approval probability gauge, the decision, a **"why" explanation** (the decision-tree path, or logistic-regression factor contributions) and both models compared side by side. There is an optional *live prediction* mode. |
| **Dashboard** | KPIs (total, approval rate, average loan, average income) plus charts by property area, credit history, day and probability band. |
| **History** | Every prediction is stored in PostgreSQL. You can search, filter by decision or source, page through, delete, export to CSV, or clear. |
| **Batch upload** | Upload a CSV of applicants. Each row is validated, scored and saved, and bad rows are reported. A template is downloadable. |
| **Model lab** | Accuracy, precision, recall, F1, ROC-AUC and 5-fold CV for both models, plus the confusion matrix, feature importance and training history. You can **retrain with your own hyper-parameters** and switch the active model. |
| **Dataset** | Missing values per column, class balance, a preview with NaNs highlighted, and the preprocessing pipeline. You can upload a new training CSV, which triggers retraining. |
| **Container** | Container ID, uptime, DB status, mount paths, a deployment diagram and ready-to-copy `curl` commands for the REST API. |

### Tech stack
- **Backend:** Python 3.12, Flask, gunicorn, scikit-learn, pandas
- **Frontend:** HTML, CSS and vanilla JavaScript with hand-drawn SVG charts. It has no CDN dependency, so it works offline.
- **Database:** PostgreSQL 16 in its own container. SQLite is used automatically when you run without containers.
- **Containers:** Podman (rootless), Containerfile, a user-defined bridge network, a named volume and bind mounts

### Architecture

```
                 Host machine  (browser → http://localhost:8080)
                          │  port mapping  -p 8080:5000
 ┌────────────────────────┼──────────── Podman network: loan-net ───────────┐
 │  ┌─────────────────────▼─────┐          ┌──────────────────────────┐     │
 │  │ loan-app (custom image)    │  SQL     │ loan-db                  │     │
 │  │ Flask + gunicorn :5000     │────────▶ │ postgres:16-alpine :5432 │     │
 │  │ scikit-learn models        │ DNS name │ (no host port published) │     │
 │  └──────┬──────────┬──────────┘ "loan-db"└────────────┬─────────────┘     │
 └─────────┼──────────┼──────────────────────────────────┼───────────────────┘
   volume  │   bind   │ ./data  ./logs            volume │
   loan-models        ▼  (dataset, app.log)       loan-pgdata
   (trained models)                               (prediction history)
```

### Project layout
```
loan-approval-predictor/
├── app/
│   ├── main.py            Flask app + REST API + validation + logging
│   ├── ml.py              preprocessing, training, metrics, explanations, model store
│   ├── db.py              PostgreSQL / SQLite persistence
│   ├── templates/index.html
│   └── static/            css/style.css, js/app.js
├── data/loan_data.csv     training data (614 rows, with missing values)
├── scripts/generate_dataset.py
├── tests/test_app.py      19 automated tests (pytest)
├── train.py               CLI training script
├── wsgi.py                gunicorn entry point
├── Containerfile          custom image definition
├── entrypoint.sh          seeds empty mounts, then exec's gunicorn
├── .containerignore
├── requirements.txt
├── podman/                build / up / down / lifecycle / network / persistence / push / troubleshoot scripts
├── podman-compose.yml     optional compose alternative
├── Makefile               short aliases for the scripts
└── docs/PROPOSAL.md       1-page project proposal
```

---

## 2. Quick start

**Prerequisites:** Podman 4+ on Linux. On Windows or macOS, run `podman machine init && podman machine start` first. You also need `curl` and `git`.

```bash
git clone https://github.com/<your-github-username>/loan-approval-predictor.git
cd loan-approval-predictor
chmod +x podman/*.sh entrypoint.sh

./podman/build.sh      # build the custom image
./podman/up.sh         # create network + volumes, start loan-db and loan-app
# open http://localhost:8080
```

Or with `make`: `make build && make up`

**Without containers (development):**
```bash
pip install -r requirements.txt
python wsgi.py           # http://localhost:5000  (uses SQLite)
python -m pytest -q      # run the tests
```

---

## 3. Every Podman command used (step by step)

The scripts in `podman/` run exactly these commands and print each one before running it. These are the manual equivalents for the report and the viva.

### 3.1 Custom image (Containerfile → image)
```bash
podman build --format docker --build-arg APP_VERSION=1.0.0 \
  -t localhost/loan-approval-predictor:1.0.0 \
  -t localhost/loan-approval-predictor:latest -f Containerfile .

podman images localhost/loan-approval-predictor
podman image history localhost/loan-approval-predictor:1.0.0
podman inspect localhost/loan-approval-predictor:1.0.0
```
`--format docker` is used because the OCI format drops the `HEALTHCHECK` instruction.

**Containerfile instructions used:** `FROM`, `ARG`, `LABEL`, `ENV`, `WORKDIR`, `RUN`, `COPY`, `USER`, `EXPOSE`, `VOLUME`, `HEALTHCHECK`, `ENTRYPOINT`, `CMD`.

| Instruction | Why |
|---|---|
| `FROM python:3.12-slim` | A small official base image |
| `ARG APP_VERSION` + `LABEL` | Image versioning and metadata (`podman inspect`) |
| `ENV …` | Configuration: paths, port, unbuffered logs |
| `RUN useradd …` + `USER appuser` | Runs as a non-root user (uid 1001) |
| `COPY requirements.txt` then `RUN pip install` | Dependency layer is cached, so code changes rebuild fast |
| `RUN python train.py` | Bakes baseline models into the image |
| `EXPOSE 5000` | Documents the gunicorn port |
| `VOLUME /app/models` | Trained models persist outside the container |
| `HEALTHCHECK` | Calls `/api/health` every 30 s |
| `ENTRYPOINT` + `CMD` | Seeds empty mounts, then starts gunicorn with 2 workers |

### 3.2 Network
```bash
podman network create --driver bridge loan-net
podman network ls
podman network inspect loan-net
```

### 3.3 Persistent storage
```bash
podman volume create loan-pgdata          # PostgreSQL data directory
podman volume create loan-models          # trained model files
podman volume ls
podman volume inspect loan-pgdata
mkdir -p data logs                        # bind-mounted from the project folder
podman unshare chown -R 1001:1001 data logs   # rootless: let uid 1001 in the container write
```

### 3.4 Run the containers (with port mapping)
```bash
# Database: attached to loan-net only, not published to the host
podman run -d --name loan-db --network loan-net \
  -e POSTGRES_USER=loanuser -e POSTGRES_PASSWORD=loanpass -e POSTGRES_DB=loans \
  -v loan-pgdata:/var/lib/postgresql/data:Z \
  --health-cmd "pg_isready -U loanuser -d loans" --restart on-failure \
  docker.io/library/postgres:16-alpine

# Application: custom image, published on host port 8080
podman run -d --name loan-app --network loan-net \
  -p 8080:5000 \
  -e DATABASE_URL=postgresql://loanuser:loanpass@loan-db:5432/loans \
  -v loan-models:/app/models:Z \
  -v ./data:/app/data:Z \
  -v ./logs:/app/logs:Z \
  --restart on-failure \
  localhost/loan-approval-predictor:1.0.0

curl http://localhost:8080/api/health
```
The app reaches the database at the hostname **`loan-db`**, the container name resolved by Podman's DNS on `loan-net`. `:Z` relabels mounts for SELinux on Fedora and RHEL.

### 3.5 Container management (lifecycle)
Run `./podman/lifecycle-demo.sh` for a guided walkthrough, or use the commands directly:
```bash
podman ps                                  # running containers
podman ps -a                               # include stopped
podman inspect loan-app                    # full JSON (IP, mounts, health, env)
podman port loan-app                       # 5000/tcp -> 0.0.0.0:8080
podman logs -f loan-app                    # live logs
podman top loan-app                        # processes in the container
podman stats --no-stream                   # CPU / memory
podman exec -it loan-app /bin/bash         # shell inside
podman exec loan-app python -m pytest -q   # run the tests inside the container
podman exec -it loan-app python train.py --algorithm logistic_regression --activate
podman healthcheck run loan-app            # trigger the HEALTHCHECK
podman stop loan-app && podman start loan-app
podman restart loan-app
podman pause loan-app && podman unpause loan-app
podman rm -f loan-app                      # remove (data on the volumes survives)
podman exec -it loan-db psql -U loanuser -d loans -c "SELECT id, applicant_name, decision FROM predictions ORDER BY id DESC LIMIT 5;"
```

### 3.6 Networking verification
`./podman/network-test.sh` checks that:
- both containers have IPs on `loan-net`
- `loan-app` resolves `loan-db` by name and opens TCP 5432
- only `loan-app` is published (8080), so the database is private

### 3.7 Persistence verification
`./podman/persistence-test.sh` saves a prediction, then **deletes both containers**, recreates them, and shows the record is still there because it lives on the `loan-pgdata` volume. The host file `logs/app.log`, from the bind mount, also keeps growing across restarts.

### 3.8 Versioning, push and pull (registry)
```bash
# new version
VERSION=1.1.0 ./podman/build.sh            # tags :1.1.0 and :latest
podman images localhost/loan-approval-predictor

# push (quay.io shown; Docker Hub works the same with docker.io)
podman login quay.io
podman tag localhost/loan-approval-predictor:1.0.0 quay.io/<user>/loan-approval-predictor:1.0.0
podman tag localhost/loan-approval-predictor:1.0.0 quay.io/<user>/loan-approval-predictor:latest
podman push quay.io/<user>/loan-approval-predictor:1.0.0
podman push quay.io/<user>/loan-approval-predictor:latest

# pull it back / run anywhere
podman rmi quay.io/<user>/loan-approval-predictor:1.0.0
podman pull quay.io/<user>/loan-approval-predictor:1.0.0
podman run -d -p 8080:5000 quay.io/<user>/loan-approval-predictor:1.0.0
```
`REGISTRY_USER=<user> ./podman/push.sh` does all of the above. On quay.io, set the repository to **Public** after the first push.

**Public image:** `quay.io/<user>/loan-approval-predictor:1.0.0` ← fill this in after pushing

### 3.9 Stop and clean up
```bash
./podman/down.sh            # stop + remove containers, keep volumes
./podman/down.sh --purge    # also remove volumes + network
podman image prune          # remove dangling images
```

### 3.10 Extras
```bash
podman generate kube loan-app loan-db > podman/loan-kube.yaml   # Kubernetes YAML from running containers
podman compose up -d --build                                    # compose alternative (podman-compose.yml)
```

---

## 4. Testing and troubleshooting

**Automated tests (19):** these cover data loading, missing values, feature engineering, both algorithms' accuracy, model sanity (a strong applicant scores higher than a risky one), every REST endpoint, validation errors, batch upload with a bad row, retraining and switching models, export, and 404 handling.
```bash
python -m pytest -q                         # local
podman exec loan-app python -m pytest -q    # inside the container
```

**Manual API tests**
```bash
curl http://localhost:8080/api/health
curl -X POST http://localhost:8080/api/predict -H "Content-Type: application/json" -d '{
  "applicant_name":"API test","Gender":"Male","Married":"Yes","Dependents":"0","Education":"Graduate",
  "Self_Employed":"No","ApplicantIncome":5000,"CoapplicantIncome":1500,"LoanAmount":150,
  "Loan_Amount_Term":360,"Credit_History":1,"Property_Area":"Urban","source":"api"}'
curl http://localhost:8080/api/stats
curl http://localhost:8080/api/model
curl -X POST http://localhost:8080/api/predict -H "Content-Type: application/json" -d '{"Gender":"X"}'   # → 422 with field errors
```

**Troubleshooting report:** `./podman/troubleshoot.sh` collects status, exit codes, health, network, volumes, port check, logs from both containers, DB readiness, row count and mount ownership. It saves everything to `logs/troubleshoot-*.txt`.

| Problem | Cause | Fix |
|---|---|---|
| `address already in use` on 8080 | Another process is on that port | `HOST_PORT=8081 ./podman/up.sh` |
| App restarts with "Could not connect to the database" | `loan-db` is not running or not ready | `podman start loan-db`; `podman logs loan-db` |
| `Permission denied` writing `/app/logs` | Rootless UID mapping on the bind mount | `podman unshare chown -R 1001:1001 data logs` |
| SELinux `avc: denied` | Mount not relabelled | Keep the `:Z` suffix on `-v` |
| Code changes not visible | Old image still in use | `./podman/build.sh && podman rm -f loan-app && ./podman/up.sh` |
| `HEALTHCHECK` ignored | Image built in OCI format | Build with `--format docker` |
| Can't edit `data/` from the host after running | Folder is owned by the container uid | `podman unshare chown -R 0:0 data logs` |
| Start completely fresh | — | `./podman/down.sh --purge && ./podman/up.sh` |

---

## 5. Machine-learning details

- **Data:** `data/loan_data.csv` has 614 applicants with the same schema as the public "Loan Prediction" dataset (Gender, Married, Dependents, Education, Self_Employed, ApplicantIncome, CoapplicantIncome, LoanAmount, Loan_Amount_Term, Credit_History, Property_Area, Loan_Status). It contains **149 missing values**. The data is generated by `scripts/generate_dataset.py` with realistic distributions. You can drop in the Kaggle CSV with the same columns and retrain from the Dataset page or with `python train.py`.
- **Feature engineering:** total income, approximate EMI (loan ÷ term), and loan-to-income ratio.
- **Missing values:** `SimpleImputer` uses the median for numeric columns and the most frequent value for categorical ones. It lives inside the saved pipeline, so training and serving use the same logic.
- **Encoding:** `OneHotEncoder(handle_unknown="ignore")`. `StandardScaler` is applied for Logistic Regression only.
- **Models:** `DecisionTreeClassifier` (default max_depth 4, min_samples_leaf 10) and `LogisticRegression` (default C 1.0). Evaluation uses an 80/20 stratified split plus 5-fold cross-validation.
- **Typical results:** Logistic Regression is about 81% accurate and the Decision Tree about 72–77%. Credit history is by far the most important feature.
- **Fairness:** Gender is collected and stored, but it is **not used as a model feature**.
- **Explainability:**
  - *Decision Tree:* the human-readable path through the tree, e.g. "Credit history is good (1) → Property area is not Rural → …".
  - *Logistic Regression:* each feature's contribution compared with an average applicant.

### REST API
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health, container hostname, DB and model status |
| POST | `/api/predict` | Predict and save (`"save": false` for preview only) |
| POST | `/api/compare` | Run both models on one applicant |
| GET | `/api/predictions` | History (`search`, `decision`, `source`, `limit`, `offset`) |
| GET/DELETE | `/api/predictions/<id>` | Fetch or delete one prediction |
| DELETE | `/api/predictions` | Clear history |
| GET | `/api/predictions/export` | Download CSV |
| GET | `/api/stats` | Dashboard aggregates |
| GET | `/api/model` | Metrics for both models plus training history |
| POST | `/api/model/train` | Retrain with hyper-parameters |
| POST | `/api/model/activate` | Switch the active model |
| GET | `/api/dataset` | Dataset summary and missing values |
| POST | `/api/dataset/upload` | Replace the training CSV and retrain |
| POST | `/api/batch` | Score a CSV of applicants |
| GET | `/api/batch/template` | Sample CSV |

---

## 6. Capstone requirement checklist

| Guideline requirement | Where it is met |
|---|---|
| A small working application | Flask web app + REST API (sections 1 and 5) |
| A custom Containerfile | `Containerfile` (13 instruction types, non-root, healthcheck) |
| A custom Podman image | `localhost/loan-approval-predictor:1.0.0` via `podman/build.sh` |
| At least one running container | `loan-app` + `loan-db` |
| A Podman network | `loan-net` bridge with DNS by container name (`network-test.sh`) |
| Persistent storage (volume or bind mount) | Volumes `loan-pgdata` and `loan-models`; bind mounts `./data` and `./logs` (`persistence-test.sh`) |
| Port mapping | `-p 8080:5000` |
| Basic container management and troubleshooting | `lifecycle-demo.sh`, `troubleshoot.sh`, section 4 |
| README containing the commands used | This file, section 3 |
| Live demonstration | Predict → Dashboard → Model lab retrain → persistence test |
| Upload the project to GitHub | Push this folder (CI workflow in `.github/workflows/ci.yml`) |
| Push/pull from a registry and versioning images | `push.sh`, section 3.8 |
| Screenshots or logs of build / run / push / inspect | Every script prints its commands; `logs/app.log`; `logs/troubleshoot-*.txt` |

### Suggested 10-minute demo flow
1. `./podman/build.sh`, showing the layers and image size (1 min)
2. `./podman/up.sh` → `podman ps` → open http://localhost:8080 (1 min)
3. Predict "Sample: strong" and "Sample: risky", explaining the decision path and the model comparison (2 min)
4. Dashboard and History: search and export (1 min)
5. Model lab: retrain the tree with max_depth 6 and watch the metrics change (1 min)
6. `./podman/network-test.sh` (1 min)
7. `./podman/persistence-test.sh`: data survives container deletion (1.5 min)
8. `podman logs`, `podman exec … pytest`, `podman inspect`, and the registry link (1.5 min)
