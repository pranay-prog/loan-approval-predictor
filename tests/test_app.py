"""
Automated tests: run with `pytest -q` locally, or inside the container:
    podman exec -it loan-app python -m pytest -q
"""
import io
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.main import create_app  # noqa: E402
from app.ml import ALGORITHMS, ModelManager, clean_frame, load_dataset  # noqa: E402

DATA = os.path.join(ROOT, "data", "loan_data.csv")

GOOD = {
    "applicant_name": "Test Good", "Gender": "Female", "Married": "Yes", "Dependents": "1",
    "Education": "Graduate", "Self_Employed": "No", "ApplicantIncome": 8500,
    "CoapplicantIncome": 3000, "LoanAmount": 160, "Loan_Amount_Term": 360,
    "Credit_History": 1, "Property_Area": "Semiurban",
}
BAD = dict(GOOD, applicant_name="Test Bad", Credit_History=0, ApplicantIncome=2100,
           CoapplicantIncome=0, LoanAmount=320, Property_Area="Rural", Married="No")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("lap")
    data_dir = tmp / "data"
    data_dir.mkdir()
    shutil.copy(DATA, data_dir / "loan_data.csv")
    app = create_app({
        "DATABASE_URL": f"sqlite:///{tmp / 'test.db'}",
        "MODEL_DIR": str(tmp / "models"),
        "DATA_DIR": str(data_dir),
        "LOG_DIR": str(tmp / "logs"),
    })
    app.testing = True
    return app.test_client()


# ---------------------------------------------------------------- ML layer
def test_dataset_has_missing_values():
    df = load_dataset(DATA)
    assert len(df) >= 100
    assert df.isna().sum().sum() > 0, "dataset should contain missing values to impute"


def test_clean_frame_engineers_features():
    df = clean_frame(load_dataset(DATA).head(20))
    for col in ("TotalIncome", "EMI", "LoanToIncome"):
        assert col in df.columns


@pytest.mark.parametrize("algo", list(ALGORITHMS))
def test_models_train_with_reasonable_accuracy(tmp_path, algo):
    mgr = ModelManager(str(tmp_path), DATA)
    meta = mgr.train(algo)
    assert meta["metrics"]["accuracy"] > 0.65
    assert os.path.exists(tmp_path / f"{algo}.joblib")
    assert len(meta["feature_importance"]) > 0


def test_good_applicant_beats_bad_applicant(tmp_path):
    mgr = ModelManager(str(tmp_path), DATA)
    mgr.ensure_models()
    for algo in ALGORITHMS:
        g, b = mgr.predict([GOOD, BAD], algo)
        assert g["probability"] > b["probability"]
        assert g["decision"] == "Approved" and b["decision"] == "Rejected"


def test_prediction_handles_missing_optional_values(tmp_path):
    mgr = ModelManager(str(tmp_path), DATA)
    mgr.ensure_models()
    rec = dict(GOOD, Self_Employed=None, Dependents=None)
    out = mgr.predict([rec])[0]
    assert 0 <= out["probability"] <= 1


# ---------------------------------------------------------------- API
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok" and body["database"]["connected"]


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Loan" in r.data


def test_predict_and_history(client):
    r = client.post("/api/predict", json=GOOD)
    assert r.status_code == 200
    body = r.get_json()
    assert body["decision"] in ("Approved", "Rejected") and body["id"]
    assert "explanation" in body
    hist = client.get("/api/predictions?search=test good").get_json()
    assert hist["total"] >= 1


def test_predict_without_saving(client):
    before = client.get("/api/stats").get_json()["total"]
    client.post("/api/predict", json=dict(GOOD, save=False))
    assert client.get("/api/stats").get_json()["total"] == before


def test_validation_errors(client):
    r = client.post("/api/predict", json={"Gender": "Robot", "LoanAmount": -5})
    assert r.status_code == 422
    fields = r.get_json()["fields"]
    assert "Gender" in fields and "LoanAmount" in fields and "Credit_History" in fields


def test_compare_returns_both_models(client):
    r = client.post("/api/compare", json=GOOD).get_json()
    assert set(r) == set(ALGORITHMS)


def test_stats(client):
    client.post("/api/predict", json=BAD)
    s = client.get("/api/stats").get_json()
    assert s["total"] >= 2 and 0 <= s["approval_rate"] <= 1
    assert sum(s["probability_histogram"]) == s["total"]


def test_delete_prediction(client):
    pid = client.post("/api/predict", json=GOOD).get_json()["id"]
    assert client.delete(f"/api/predictions/{pid}").status_code == 200
    assert client.get(f"/api/predictions/{pid}").status_code == 404


def test_batch_upload(client):
    tpl = client.get("/api/batch/template").data
    bad_row = b"\nBroken,Robot,Yes,0,Graduate,No,abc,0,100,360,1,Urban"
    r = client.post("/api/batch", data={"file": (io.BytesIO(tpl + bad_row), "b.csv")},
                    content_type="multipart/form-data")
    body = r.get_json()
    assert r.status_code == 200
    assert len(body["results"]) == 3 and len(body["errors"]) == 1


def test_retrain_and_switch_model(client):
    r = client.post("/api/model/train", json={"algorithm": "decision_tree", "max_depth": 3, "activate": True})
    assert r.status_code == 200 and r.get_json()["params"]["max_depth"] == 3
    assert client.get("/api/model").get_json()["active"] == "decision_tree"
    r = client.post("/api/model/activate", json={"algorithm": "logistic_regression"})
    assert r.get_json()["active"] == "logistic_regression"
    assert client.post("/api/model/activate", json={"algorithm": "svm"}).status_code == 400


def test_dataset_summary(client):
    d = client.get("/api/dataset").get_json()
    assert d["rows"] > 0 and d["missing_total"] > 0


def test_export_csv(client):
    r = client.get("/api/predictions/export")
    assert r.status_code == 200 and r.mimetype == "text/csv"


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.get_json()["error"]
