"""
Machine-learning layer: preprocessing, training, evaluation, prediction and
explanations for the Loan Approval Predictor.

Two algorithms are supported, as required by the project statement:
  * decision_tree        -> sklearn DecisionTreeClassifier
  * logistic_regression  -> sklearn LogisticRegression

Both are wrapped in a scikit-learn Pipeline so that missing-value handling
and categorical encoding are part of the saved model (no train/serve skew).
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

log = logging.getLogger("loan.ml")

TARGET = "Loan_Status"
CATEGORICAL = ["Married", "Dependents", "Education",
               "Self_Employed", "Property_Area", "Credit_History"]
NUMERIC = ["ApplicantIncome", "CoapplicantIncome", "LoanAmount",
           "Loan_Amount_Term", "TotalIncome", "LoanToIncome", "EMI"]
# NOTE: Gender is collected and stored for record keeping but deliberately NOT
# used as a model feature (fairness: a loan decision should not depend on it).
RAW_INPUT = ["Gender", "Married", "Dependents", "Education", "Self_Employed",
             "ApplicantIncome", "CoapplicantIncome", "LoanAmount",
             "Loan_Amount_Term", "Credit_History", "Property_Area"]

ALGORITHMS = {
    "decision_tree": "Decision Tree",
    "logistic_regression": "Logistic Regression",
}

FRIENDLY = {
    "Gender": "Gender", "Married": "Marital status", "Dependents": "Dependents",
    "Education": "Education", "Self_Employed": "Self-employed",
    "Property_Area": "Property area", "Credit_History": "Credit history",
    "ApplicantIncome": "Applicant income", "CoapplicantIncome": "Co-applicant income",
    "LoanAmount": "Loan amount", "Loan_Amount_Term": "Loan term",
    "TotalIncome": "Total income", "LoanToIncome": "Loan-to-income ratio",
    "EMI": "Monthly instalment (EMI)",
}


# --------------------------------------------------------------------------
# Data preparation
# --------------------------------------------------------------------------
def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise types and add engineered features. NaNs are kept on purpose:
    the pipeline's imputers handle them."""
    df = df.copy()
    for col in ["ApplicantIncome", "CoapplicantIncome", "LoanAmount", "Loan_Amount_Term"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    # Credit_History is a 0/1 flag -> treat as a category ("1"/"0")
    ch = pd.to_numeric(df.get("Credit_History"), errors="coerce")
    df["Credit_History"] = ch.map(lambda v: np.nan if pd.isna(v) else str(int(v))).astype(object)

    for col in ["Gender", "Married", "Dependents", "Education", "Self_Employed", "Property_Area"]:
        s = df.get(col)
        df[col] = s.map(lambda v: np.nan if pd.isna(v) or str(v).strip() == "" else str(v).strip()).astype(object)
    df["Dependents"] = df["Dependents"].replace({"3": "3+"})

    df["CoapplicantIncome"] = df["CoapplicantIncome"].fillna(0)
    total = df["ApplicantIncome"].fillna(0) + df["CoapplicantIncome"]
    df["TotalIncome"] = total
    term = df["Loan_Amount_Term"].fillna(360).replace(0, 360)
    df["EMI"] = (df["LoanAmount"] * 1000) / term
    df["LoanToIncome"] = (df["LoanAmount"] * 1000) / total.replace(0, np.nan)
    return df


def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in RAW_INPUT + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing columns: {', '.join(missing)}")
    return df


def dataset_summary(path: str) -> dict:
    df = load_dataset(path)
    miss = df[RAW_INPUT].isna().sum()
    status = df[TARGET].astype(str).str.upper().value_counts().to_dict()
    head = df.head(8)
    preview = head.astype(object).where(pd.notna(head), None).to_dict(orient="records")
    numeric = df[["ApplicantIncome", "CoapplicantIncome", "LoanAmount"]].describe().round(1)
    return {
        "path": os.path.basename(path),
        "rows": int(len(df)),
        "columns": list(df.columns),
        "missing": {k: int(v) for k, v in miss.items()},
        "missing_total": int(miss.sum()),
        "class_balance": {"approved": int(status.get("Y", 0)), "rejected": int(status.get("N", 0))},
        "numeric_summary": numeric.replace({np.nan: None}).to_dict(),
        "preview": preview,
    }


# --------------------------------------------------------------------------
# Model building
# --------------------------------------------------------------------------
def build_pipeline(algorithm: str, params: dict | None = None) -> Pipeline:
    params = params or {}
    scale = algorithm == "logistic_regression"   # trees don't need scaling
    num_steps = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    pre = ColumnTransformer([
        ("num", Pipeline(num_steps), NUMERIC),
        ("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), CATEGORICAL),
    ])
    if algorithm == "decision_tree":
        clf = DecisionTreeClassifier(
            max_depth=int(params.get("max_depth", 4)),
            min_samples_leaf=int(params.get("min_samples_leaf", 10)),
            criterion=params.get("criterion", "gini"),
            random_state=42,
        )
    elif algorithm == "logistic_regression":
        clf = LogisticRegression(C=float(params.get("C", 1.0)), max_iter=2000)
    else:
        raise ValueError(f"Unknown algorithm '{algorithm}'")
    return Pipeline([("pre", pre), ("clf", clf)])


def feature_names(pipe: Pipeline) -> list[str]:
    return list(pipe.named_steps["pre"].get_feature_names_out())


def _base_feature(transformed_name: str) -> str:
    """'cat__Property_Area_Urban' -> 'Property_Area'; 'num__EMI' -> 'EMI'."""
    name = transformed_name.split("__", 1)[1]
    for col in CATEGORICAL:
        if name.startswith(col + "_"):
            return col
    return name


def aggregated_importance(pipe: Pipeline) -> list[dict]:
    clf = pipe.named_steps["clf"]
    names = feature_names(pipe)
    if hasattr(clf, "feature_importances_"):
        raw = clf.feature_importances_
    else:
        raw = np.abs(clf.coef_[0])
    agg: dict[str, float] = {}
    for n, v in zip(names, raw):
        b = _base_feature(n)
        agg[b] = agg.get(b, 0.0) + float(v)
    total = sum(agg.values()) or 1.0
    out = [{"feature": k, "label": FRIENDLY.get(k, k), "importance": round(v / total, 4)}
           for k, v in agg.items()]
    return sorted(out, key=lambda d: d["importance"], reverse=True)


def train_model(data_path: str, algorithm: str, params: dict | None = None,
                test_size: float = 0.2) -> tuple[Pipeline, dict]:
    t0 = time.time()
    raw = load_dataset(data_path)
    raw = raw[raw[TARGET].notna()]
    df = clean_frame(raw)
    X = df[NUMERIC + CATEGORICAL]
    y = (df[TARGET].astype(str).str.upper() == "Y").astype(int)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y)
    pipe = build_pipeline(algorithm, params)
    pipe.fit(X_tr, y_tr)
    # Average transformed training row: used as the baseline for explanations
    Xt_tr = pipe.named_steps["pre"].transform(X_tr)
    pipe.baseline_ = np.asarray(Xt_tr.mean(axis=0)).ravel()

    pred = pipe.predict(X_te)
    proba = pipe.predict_proba(X_te)[:, 1]
    cv = cross_val_score(build_pipeline(algorithm, params), X, y, cv=5, scoring="accuracy")
    cm = confusion_matrix(y_te, pred, labels=[1, 0])  # rows: actual Y,N

    meta = {
        "algorithm": algorithm,
        "algorithm_label": ALGORITHMS[algorithm],
        "version": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": params or {},
        "dataset": os.path.basename(data_path),
        "rows": int(len(df)),
        "train_rows": int(len(X_tr)),
        "test_rows": int(len(X_te)),
        "test_size": test_size,
        "missing_values_imputed": int(raw[RAW_INPUT].isna().sum().sum()),
        "metrics": {
            "accuracy": round(float(accuracy_score(y_te, pred)), 4),
            "precision": round(float(precision_score(y_te, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_te, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_te, pred, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y_te, proba)), 4),
            "cv_accuracy_mean": round(float(cv.mean()), 4),
            "cv_accuracy_std": round(float(cv.std()), 4),
        },
        "confusion_matrix": {
            "labels": ["Approved", "Rejected"],
            "matrix": cm.tolist(),
        },
        "feature_importance": aggregated_importance(pipe),
        "training_seconds": round(time.time() - t0, 3),
    }
    log.info("Trained %s v%s accuracy=%.3f", algorithm, meta["version"], meta["metrics"]["accuracy"])
    return pipe, meta


# --------------------------------------------------------------------------
# Explanations
# --------------------------------------------------------------------------
def _describe_split(fname: str, threshold: float, went_left: bool) -> str:
    name = fname.split("__", 1)[1]
    for col in CATEGORICAL:
        if name.startswith(col + "_"):
            val = name[len(col) + 1:]
            label = FRIENDLY[col]
            if col == "Credit_History":
                val = "good (1)" if val == "1" else "poor (0)"
            # one-hot <= 0.5 means "not this category"
            return f"{label} is {'not ' if went_left else ''}{val}"
    label = FRIENDLY.get(name, name)
    if name in ("LoanToIncome",):
        thr = f"{threshold:.2f}x"
    elif name in ("Loan_Amount_Term",):
        thr = f"{threshold:.0f} months"
    elif name == "LoanAmount":
        thr = f"₹{threshold:,.0f}k"
    else:
        thr = f"₹{threshold:,.0f}"
    return f"{label} {'≤' if went_left else '>'} {thr}"


def explain(pipe: Pipeline, X: pd.DataFrame) -> dict:
    clf = pipe.named_steps["clf"]
    pre = pipe.named_steps["pre"]
    Xt = pre.transform(X)
    if hasattr(Xt, "toarray"):
        Xt = Xt.toarray()
    names = feature_names(pipe)

    if isinstance(clf, DecisionTreeClassifier):
        tree = clf.tree_
        node_ids = clf.decision_path(Xt).indices
        steps = []
        for node in node_ids:
            if tree.children_left[node] == tree.children_right[node]:
                continue  # leaf
            f = tree.feature[node]
            thr = tree.threshold[node]
            went_left = Xt[0, f] <= thr
            steps.append(_describe_split(names[f], thr, went_left))
        leaf = node_ids[-1]
        counts = tree.value[leaf][0]
        return {"type": "decision_path", "rules": steps,
                "leaf_samples": int(tree.n_node_samples[leaf]),
                "leaf_approval_share": round(float(counts[1] / counts.sum()), 3)}

    # Logistic regression: contribution = coefficient * (value - average applicant)
    baseline = getattr(pipe, "baseline_", np.zeros(Xt.shape[1]))
    contrib = (Xt[0] - baseline) * clf.coef_[0]
    agg: dict[str, float] = {}
    for n, c in zip(names, contrib):
        b = _base_feature(n)
        agg[b] = agg.get(b, 0.0) + float(c)
    items = sorted(agg.items(), key=lambda kv: abs(kv[1]), reverse=True)[:6]
    return {"type": "contributions",
            "factors": [{"feature": k, "label": FRIENDLY.get(k, k),
                         "impact": round(v, 3),
                         "direction": "positive" if v > 0 else "negative"} for k, v in items]}


# --------------------------------------------------------------------------
# Model manager (persistence on the Podman volume)
# --------------------------------------------------------------------------
class ModelManager:
    """Stores models as <algo>.joblib + <algo>.json in MODEL_DIR and keeps
    track of the active one in active.json. Reloads automatically when files
    change, so every gunicorn worker sees a retrained model."""

    def __init__(self, model_dir: str, data_path: str):
        self.model_dir = model_dir
        self.data_path = data_path
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Pipeline, dict]] = {}
        os.makedirs(model_dir, exist_ok=True)

    # paths
    def _p(self, name): return os.path.join(self.model_dir, name)

    def active_algorithm(self) -> str:
        try:
            with open(self._p("active.json")) as fh:
                algo = json.load(fh).get("algorithm")
            if algo in ALGORITHMS:
                return algo
        except (OSError, ValueError):
            pass
        return "decision_tree"

    def set_active(self, algorithm: str):
        if algorithm not in ALGORITHMS:
            raise ValueError("Unknown algorithm")
        if not os.path.exists(self._p(f"{algorithm}.joblib")):
            raise FileNotFoundError(f"{algorithm} has not been trained yet")
        tmp = self._p("active.json.tmp")
        with open(tmp, "w") as fh:
            json.dump({"algorithm": algorithm, "changed_at": datetime.now(timezone.utc).isoformat()}, fh)
        os.replace(tmp, self._p("active.json"))
        log.info("Active model set to %s", algorithm)

    def ensure_models(self):
        """Train any missing model on startup (first run on an empty volume)."""
        for algo in ALGORITHMS:
            if not os.path.exists(self._p(f"{algo}.joblib")):
                log.info("No saved %s model found in %s - training", algo, self.model_dir)
                self.train(algo)
        if not os.path.exists(self._p("active.json")):
            self.set_active("decision_tree")

    def train(self, algorithm: str, params: dict | None = None, test_size: float = 0.2) -> dict:
        pipe, meta = train_model(self.data_path, algorithm, params, test_size)
        with self._lock:
            tmp = self._p(f"{algorithm}.joblib.tmp")
            joblib.dump(pipe, tmp)
            os.replace(tmp, self._p(f"{algorithm}.joblib"))
            with open(self._p(f"{algorithm}.json"), "w") as fh:
                json.dump(meta, fh, indent=2)
            self._cache.pop(algorithm, None)
        self._append_history(meta)
        return meta

    def _append_history(self, meta: dict):
        path = self._p("training_history.json")
        try:
            with open(path) as fh:
                hist = json.load(fh)
        except (OSError, ValueError):
            hist = []
        hist.append({k: meta[k] for k in ("algorithm", "version", "trained_at", "rows", "params")}
                    | {"accuracy": meta["metrics"]["accuracy"]})
        with open(path, "w") as fh:
            json.dump(hist[-50:], fh, indent=2)

    def history(self) -> list:
        try:
            with open(self._p("training_history.json")) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return []

    def load(self, algorithm: str) -> tuple[Pipeline, dict]:
        path = self._p(f"{algorithm}.joblib")
        mtime = os.path.getmtime(path)
        cached = self._cache.get(algorithm)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        with self._lock:
            pipe = joblib.load(path)
            with open(self._p(f"{algorithm}.json")) as fh:
                meta = json.load(fh)
            self._cache[algorithm] = (mtime, pipe, meta)
        return pipe, meta

    def metadata(self, algorithm: str) -> dict | None:
        try:
            with open(self._p(f"{algorithm}.json")) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def predict(self, records: list[dict], algorithm: str | None = None, with_explanation=True) -> list[dict]:
        algorithm = algorithm or self.active_algorithm()
        pipe, meta = self.load(algorithm)
        df = clean_frame(pd.DataFrame(records, columns=RAW_INPUT))
        # Use exactly the columns this saved model was trained on, so models
        # left on the volume by an older image version keep working.
        cols = list(getattr(pipe, "feature_names_in_", NUMERIC + CATEGORICAL))
        X = df[cols]
        proba = pipe.predict_proba(X)[:, 1]
        out = []
        for i, p in enumerate(proba):
            item = {
                "decision": "Approved" if p >= 0.5 else "Rejected",
                "probability": round(float(p), 4),
                "model": algorithm,
                "model_label": ALGORITHMS[algorithm],
                "model_version": meta["version"],
                "emi": None if pd.isna(df["EMI"].iloc[i]) else round(float(df["EMI"].iloc[i]), 2),
                "loan_to_income": None if pd.isna(df["LoanToIncome"].iloc[i]) else round(float(df["LoanToIncome"].iloc[i]), 3),
            }
            if with_explanation:
                item["explanation"] = explain(pipe, X.iloc[[i]])
            out.append(item)
        return out
