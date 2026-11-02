"""WSGI entry point used by gunicorn inside the container: `gunicorn wsgi:app`."""
import os

from app.main import create_app

app = create_app()

if __name__ == "__main__":
    # Local development: python wsgi.py  ->  http://localhost:5000
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
