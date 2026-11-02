"""
Loan Approval Predictor - Flask application (REST API + web UI).

Environment variables (all optional):
    DATABASE_URL   postgresql://user:pass@loan-db:5432/loans   (default: SQLite file)
    MODEL_DIR      where trained models are stored  (Podman volume: loan-models)
    DATA_DIR       folder holding loan_data.csv      (bind mount: ./data)
    LOG_DIR        folder for app.log                (bind mount: ./logs)
    APP_VERSION    shown in the UI / health endpoint
"""
import csv
import io
import logging
import os
import platform
import socket
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from flask import Flask, Response, jsonify, render_template, request

from .db import Database
from .ml import ALGORITHMS, RAW_INPUT, ModelManager, dataset_summary, load_dataset

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPTIONS = {
    "Gender": ["Male", "Female"],
    "Married": ["Yes", "No"],
    "Dependents": ["0", "1", "2", "3+"],
    "Education": ["Graduate", "Not Graduate"],
    "Self_Employed": ["No", "Yes"],
    "Property_Area": ["Urban", "Semiurban", "Rural"],
    "Credit_History": [1, 0],
}
NUMERIC_RULES = {  # field: (min, max)
    "ApplicantIncome": (0, 1_000_000),
    "CoapplicantIncome": (0, 1_000_000),
    "LoanAmount": (1, 10_000),
    "Loan_Amount_Term": (6, 600),
}

# form/JSON key -> DB column
DB_MAP = {
    "Gender": "gender", "Married": "married", "Dependents": "dependents",
    "Education": "education", "Self_Employed": "self_employed",
    "ApplicantIncome": "applicant_income", "CoapplicantIncome": "coapplicant_income",
    "LoanAmount": "loan_amount", "Loan_Amount_Term": "loan_term",
    "Credit_History": "credit_history", "Property_Area": "property_area",
}


def setup_logging(log_dir: str):
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()          # -> `podman logs loan-app`
        sh.setFormatter(fmt)
        root.addHandler(sh)
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(log_dir, "app.log"), maxBytes=2_000_000, backupCount=3)
        fh.setFormatter(fmt)
        root.addHandler(fh)                   # -> ./logs/app.log on the host (bind mount)
    except OSError as exc:
        root.warning("File logging disabled: %s", exc)


def validate(payload: dict) -> tuple[dict, dict]:
    """Return (clean_record, errors)."""
    clean, errors = {}, {}
    for field, allowed in OPTIONS.items():
        val = payload.get(field)
        if field == "Credit_History":
            try:
                val = int(float(val))
            except (TypeError, ValueError):
                val = None
        if val in (None, ""):
            errors[field] = "Required"
        elif val not in allowed:
            errors[field] = f"Must be one of {allowed}"
        else:
            clean[field] = val
    for field, (lo, hi) in NUMERIC_RULES.items():
        raw = payload.get(field)
        if field == "CoapplicantIncome" and raw in (None, ""):
            raw = 0
        try:
            val = float(raw)
        except (TypeError, ValueError):
            errors[field] = "Must be a number"
            continue
        if not lo <= val <= hi:
            errors[field] = f"Must be between {lo:,} and {hi:,}"
        else:
            clean[field] = val
    name = str(payload.get("applicant_name") or "").strip()[:80]
    clean["applicant_name"] = name or None
    return clean, errors


def to_db_row(rec: dict, result: dict, source: str) -> dict:
    row = {DB_MAP[k]: rec.get(k) for k in DB_MAP}
    row.update({
        "applicant_name": rec.get("applicant_name"),
        "decision": result["decision"],
        "probability": result["probability"],
        "model": result["model"],
        "model_version": result["model_version"],
        "source": source,
    })
    return row


def create_app(config: dict | None = None) -> Flask:
    cfg = {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "MODEL_DIR": os.environ.get("MODEL_DIR", os.path.join(BASE, "models")),
        "DATA_DIR": os.environ.get("DATA_DIR", os.path.join(BASE, "data")),
        "LOG_DIR": os.environ.get("LOG_DIR", os.path.join(BASE, "logs")),
        "APP_VERSION": os.environ.get("APP_VERSION", "1.0.0"),
    }
    cfg.update(config or {})
    if not cfg["DATABASE_URL"]:
        cfg["DATABASE_URL"] = "sqlite:///" + os.path.join(cfg["MODEL_DIR"], "loan_app.db")

    setup_logging(cfg["LOG_DIR"])
    log = logging.getLogger("loan.app")

    app = Flask(__name__)
    app.config.update(cfg)
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    started = time.time()

    data_path = os.path.join(cfg["DATA_DIR"], "loan_data.csv")
    db = Database(cfg["DATABASE_URL"])
    db.wait_until_ready(attempts=int(os.environ.get("DB_WAIT_ATTEMPTS", 30)))
    db.init_schema()
    models = ModelManager(cfg["MODEL_DIR"], data_path)
    models.ensure_models()
    log.info("Loan Approval Predictor v%s ready | db=%s | models=%s | data=%s",
             cfg["APP_VERSION"], db.backend, cfg["MODEL_DIR"], data_path)

    app.extensions["db"] = db
    app.extensions["models"] = models

    def err(msg, code=400, **extra):
        return jsonify({"error": msg, **extra}), code

    # ------------------------------------------------------------------ UI
    @app.get("/")
    def index():
        return render_template("index.html", version=cfg["APP_VERSION"])

    # ------------------------------------------------------------- health
    @app.get("/api/health")
    def health():
        db_ok = db.ping()
        algo = models.active_algorithm()
        meta = models.metadata(algo) or {}
        body = {
            "status": "ok" if db_ok else "degraded",
            "version": cfg["APP_VERSION"],
            "hostname": socket.gethostname(),       # = container ID inside Podman
            "python": platform.python_version(),
            "uptime_seconds": int(time.time() - started),
            "database": {"backend": db.backend, "connected": db_ok},
            "model": {"active": algo, "version": meta.get("version")},
            "paths": {"models": cfg["MODEL_DIR"], "data": cfg["DATA_DIR"], "logs": cfg["LOG_DIR"]},
            "in_container": os.path.exists("/run/.containerenv") or os.path.exists("/.dockerenv"),
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return jsonify(body), (200 if db_ok else 503)

    @app.get("/api/meta")
    def meta():
        return jsonify({"options": OPTIONS, "numeric": NUMERIC_RULES, "algorithms": ALGORITHMS})

    # ---------------------------------------------------------- predict
    @app.post("/api/predict")
    def predict():
        payload = request.get_json(silent=True) or request.form.to_dict()
        rec, errors = validate(payload)
        if errors:
            return err("Validation failed", 422, fields=errors)
        algo = payload.get("algorithm") or None
        if algo and algo not in ALGORITHMS:
            return err("Unknown algorithm")
        result = models.predict([rec], algo)[0]
        source = payload.get("source", "form") if payload.get("source") in ("form", "api") else "form"
        pid = None
        if payload.get("save", True) not in (False, "false", 0, "0"):
            pid = db.insert_prediction(to_db_row(rec, result, source))
        log.info("Prediction #%s %s p=%.3f model=%s", pid, result["decision"], result["probability"], result["model"])
        return jsonify({"id": pid, "input": rec, **result})

    @app.post("/api/compare")
    def compare():
        payload = request.get_json(silent=True) or {}
        rec, errors = validate(payload)
        if errors:
            return err("Validation failed", 422, fields=errors)
        return jsonify({a: models.predict([rec], a, with_explanation=False)[0] for a in ALGORITHMS})

    # ---------------------------------------------------------- history
    @app.get("/api/predictions")
    def list_predictions():
        limit = min(int(request.args.get("limit", 25)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        rows, total = db.list_predictions(limit, offset, request.args.get("search") or None,
                                          request.args.get("decision") or None,
                                          request.args.get("source") or None)
        return jsonify({"items": rows, "total": total, "limit": limit, "offset": offset})

    @app.get("/api/predictions/<int:pid>")
    def get_prediction(pid):
        row = db.get_prediction(pid)
        return jsonify(row) if row else err("Not found", 404)

    @app.delete("/api/predictions/<int:pid>")
    def delete_prediction(pid):
        if db.delete_prediction(pid):
            log.info("Deleted prediction #%s", pid)
            return jsonify({"deleted": pid})
        return err("Not found", 404)

    @app.delete("/api/predictions")
    def clear_predictions():
        n = db.clear()
        log.warning("Cleared %s predictions", n)
        return jsonify({"deleted": n})

    @app.get("/api/predictions/export")
    def export_predictions():
        rows, _ = db.list_predictions(100_000, 0)
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=predictions.csv"})

    @app.get("/api/stats")
    def stats():
        return jsonify(db.stats())

    # ------------------------------------------------------------ model
    @app.get("/api/model")
    def model_info():
        return jsonify({
            "active": models.active_algorithm(),
            "models": {a: models.metadata(a) for a in ALGORITHMS},
            "history": models.history()[-15:],
        })

    @app.post("/api/model/train")
    def model_train():
        p = request.get_json(silent=True) or {}
        algo = p.get("algorithm", "decision_tree")
        if algo not in ALGORITHMS:
            return err("Unknown algorithm")
        params = {}
        try:
            if algo == "decision_tree":
                params["max_depth"] = max(1, min(int(p.get("max_depth", 4)), 20))
                params["min_samples_leaf"] = max(1, min(int(p.get("min_samples_leaf", 10)), 100))
                params["criterion"] = p.get("criterion", "gini") if p.get("criterion") in ("gini", "entropy") else "gini"
            else:
                params["C"] = max(0.001, min(float(p.get("C", 1.0)), 100.0))
            test_size = max(0.1, min(float(p.get("test_size", 0.2)), 0.5))
        except (TypeError, ValueError):
            return err("Invalid hyper-parameters")
        meta = models.train(algo, params, test_size)
        if p.get("activate"):
            models.set_active(algo)
        return jsonify(meta)

    @app.post("/api/model/activate")
    def model_activate():
        algo = (request.get_json(silent=True) or {}).get("algorithm")
        try:
            models.set_active(algo)
        except (ValueError, FileNotFoundError) as exc:
            return err(str(exc))
        return jsonify({"active": algo})

    # ---------------------------------------------------------- dataset
    @app.get("/api/dataset")
    def dataset():
        try:
            return jsonify(dataset_summary(data_path))
        except (OSError, ValueError) as exc:
            return err(str(exc), 500)

    @app.post("/api/dataset/upload")
    def dataset_upload():
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".csv"):
            return err("Upload a .csv file")
        tmp = data_path + ".upload"
        f.save(tmp)
        try:
            df = load_dataset(tmp)
            if len(df) < 50:
                raise ValueError("Need at least 50 rows to train")
        except Exception as exc:  # noqa: BLE001
            os.remove(tmp)
            return err(f"Invalid dataset: {exc}")
        backup = data_path + f".{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
        if os.path.exists(data_path):
            os.replace(data_path, backup)
        os.replace(tmp, data_path)
        log.info("New dataset uploaded (%s rows); previous saved as %s", len(df), os.path.basename(backup))
        retrained = {}
        if request.form.get("retrain", "true") != "false":
            for a in ALGORITHMS:
                retrained[a] = models.train(a)["metrics"]
        return jsonify({"rows": len(df), "retrained": retrained})

    # ------------------------------------------------------------ batch
    @app.get("/api/batch/template")
    def batch_template():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["applicant_name"] + RAW_INPUT)
        w.writerow(["Asha Rao", "Female", "Yes", "1", "Graduate", "No", 6200, 1800, 140, 360, 1, "Semiurban"])
        w.writerow(["Vikram Singh", "Male", "No", "0", "Not Graduate", "Yes", 2300, 0, 210, 360, 0, "Rural"])
        w.writerow(["Meera Iyer", "Female", "No", "0", "Graduate", "No", 9500, 0, 120, 180, 1, "Urban"])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=batch_template.csv"})

    @app.post("/api/batch")
    def batch():
        f = request.files.get("file")
        if not f:
            return err("Upload a CSV file")
        try:
            text = f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return err("File must be UTF-8 CSV")
        reader = csv.DictReader(io.StringIO(text))
        results, bad = [], []
        for i, row in enumerate(reader, start=2):
            if i > 1001:
                break
            rec, errors = validate(row)
            if errors:
                bad.append({"row": i, "errors": errors})
                continue
            res = models.predict([rec], with_explanation=False)[0]
            pid = db.insert_prediction(to_db_row(rec, res, "batch"))
            results.append({"row": i, "id": pid, "applicant_name": rec["applicant_name"],
                            "decision": res["decision"], "probability": res["probability"]})
        log.info("Batch: %s predicted, %s invalid rows", len(results), len(bad))
        return jsonify({"results": results, "errors": bad,
                        "approved": sum(r["decision"] == "Approved" for r in results)})

    @app.errorhandler(404)
    def not_found(_):
        if request.path.startswith("/api/"):
            return err("Not found", 404)
        return render_template("index.html", version=cfg["APP_VERSION"]), 200

    @app.errorhandler(413)
    def too_large(_):
        return err("File too large (max 5 MB)", 413)

    @app.errorhandler(500)
    def server_error(e):
        log.exception("Unhandled error: %s", e)
        return err("Internal server error", 500)

    return app
