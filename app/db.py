"""
Persistence layer for prediction history.

* In the Podman deployment the app talks to a separate PostgreSQL container
  (`loan-db`) over the `loan-net` Podman network; the database files live on
  the `loan-pgdata` named volume.
* For local development (no DATABASE_URL) it falls back to SQLite.

Queries are written with '?' placeholders and converted for psycopg2.
"""
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

log = logging.getLogger("loan.db")

COLUMNS = [
    "created_at", "applicant_name", "gender", "married", "dependents", "education",
    "self_employed", "applicant_income", "coapplicant_income", "loan_amount",
    "loan_term", "credit_history", "property_area", "decision", "probability",
    "model", "model_version", "source",
]

SCHEMA_BODY = """
    created_at TEXT NOT NULL,
    applicant_name TEXT,
    gender TEXT,
    married TEXT,
    dependents TEXT,
    education TEXT,
    self_employed TEXT,
    applicant_income REAL,
    coapplicant_income REAL,
    loan_amount REAL,
    loan_term REAL,
    credit_history REAL,
    property_area TEXT,
    decision TEXT NOT NULL,
    probability REAL NOT NULL,
    model TEXT,
    model_version TEXT,
    source TEXT DEFAULT 'form'
"""


class Database:
    def __init__(self, url: str | None):
        self.url = url or ""
        self.is_pg = self.url.startswith(("postgres://", "postgresql://"))
        if self.is_pg:
            import psycopg2  # noqa: F401  (imported lazily: only needed in containers)
            self.backend = "postgresql"
        else:
            self.path = self.url.replace("sqlite:///", "") if self.url else "loan_app.db"
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            self.backend = "sqlite"

    # ------------------------------------------------------------------
    @contextmanager
    def conn(self):
        if self.is_pg:
            import psycopg2
            c = psycopg2.connect(self.url, connect_timeout=5)
        else:
            c = sqlite3.connect(self.path, timeout=10)
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _q(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_pg else sql

    def execute(self, sql, params=(), fetch=None):
        with self.conn() as c:
            cur = c.cursor()
            cur.execute(self._q(sql), params)
            if fetch == "one":
                row = cur.fetchone()
            elif fetch == "all":
                row = cur.fetchall()
            else:
                row = None
            cols = [d[0] for d in cur.description] if cur.description else []
            return row, cols

    def _dicts(self, rows, cols):
        return [dict(zip(cols, r)) for r in rows]

    # ------------------------------------------------------------------
    def wait_until_ready(self, attempts: int = 30, delay: float = 2.0):
        """The DB container may still be starting: retry before giving up."""
        for i in range(1, attempts + 1):
            try:
                self.execute("SELECT 1", fetch="one")
                log.info("Database ready (%s) after %d attempt(s)", self.backend, i)
                return True
            except Exception as exc:  # noqa: BLE001
                log.warning("Database not ready (%s/%s): %s", i, attempts, exc)
                time.sleep(delay)
        raise RuntimeError("Could not connect to the database")

    def init_schema(self):
        pk = "id SERIAL PRIMARY KEY" if self.is_pg else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        self.execute(f"CREATE TABLE IF NOT EXISTS predictions ({pk}, {SCHEMA_BODY})")
        self.execute("CREATE INDEX IF NOT EXISTS idx_pred_created ON predictions(created_at)")

    def ping(self) -> bool:
        try:
            self.execute("SELECT 1", fetch="one")
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    def insert_prediction(self, rec: dict) -> int:
        rec = dict(rec)
        rec.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        values = [rec.get(c) for c in COLUMNS]
        placeholders = ",".join("?" for _ in COLUMNS)
        sql = f"INSERT INTO predictions ({','.join(COLUMNS)}) VALUES ({placeholders})"
        with self.conn() as c:
            cur = c.cursor()
            if self.is_pg:
                cur.execute(self._q(sql + " RETURNING id"), values)
                return int(cur.fetchone()[0])
            cur.execute(sql, values)
            return int(cur.lastrowid)

    def _filters(self, search=None, decision=None, source=None):
        where, params = [], []
        if search:
            where.append("(LOWER(applicant_name) LIKE ? OR LOWER(property_area) LIKE ? OR CAST(id AS TEXT) = ?)")
            s = f"%{search.lower()}%"
            params += [s, s, search]
        if decision in ("Approved", "Rejected"):
            where.append("decision = ?")
            params.append(decision)
        if source:
            where.append("source = ?")
            params.append(source)
        return (" WHERE " + " AND ".join(where)) if where else "", params

    def list_predictions(self, limit=50, offset=0, search=None, decision=None, source=None):
        w, p = self._filters(search, decision, source)
        rows, cols = self.execute(
            f"SELECT * FROM predictions{w} ORDER BY id DESC LIMIT ? OFFSET ?",
            p + [int(limit), int(offset)], fetch="all")
        total, _ = self.execute(f"SELECT COUNT(*) FROM predictions{w}", p, fetch="one")
        return self._dicts(rows, cols), int(total[0])

    def get_prediction(self, pid: int):
        row, cols = self.execute("SELECT * FROM predictions WHERE id = ?", [pid], fetch="one")
        return dict(zip(cols, row)) if row else None

    def delete_prediction(self, pid: int) -> bool:
        with self.conn() as c:
            cur = c.cursor()
            cur.execute(self._q("DELETE FROM predictions WHERE id = ?"), [pid])
            return cur.rowcount > 0

    def clear(self) -> int:
        with self.conn() as c:
            cur = c.cursor()
            cur.execute("DELETE FROM predictions")
            return cur.rowcount

    def stats(self) -> dict:
        r, _ = self.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN decision='Approved' THEN 1 ELSE 0 END), "
            "AVG(loan_amount), AVG(probability), AVG(applicant_income + COALESCE(coapplicant_income,0)) "
            "FROM predictions", fetch="one")
        total = int(r[0] or 0)
        approved = int(r[1] or 0)

        def grouped(col):
            rows, _ = self.execute(
                f"SELECT {col}, COUNT(*), SUM(CASE WHEN decision='Approved' THEN 1 ELSE 0 END) "
                f"FROM predictions GROUP BY {col} ORDER BY {col}", fetch="all")
            return [{"key": "Unknown" if k is None else str(k), "total": int(t), "approved": int(a or 0)}
                    for k, t, a in rows]

        daily, _ = self.execute(
            "SELECT SUBSTR(created_at,1,10) AS d, COUNT(*), "
            "SUM(CASE WHEN decision='Approved' THEN 1 ELSE 0 END) "
            "FROM predictions GROUP BY SUBSTR(created_at,1,10) ORDER BY d DESC LIMIT 14", fetch="all")

        buckets, _ = self.execute(
            "SELECT CASE WHEN probability < 0.2 THEN 0 WHEN probability < 0.4 THEN 1 "
            "WHEN probability < 0.6 THEN 2 WHEN probability < 0.8 THEN 3 ELSE 4 END AS b, COUNT(*) "
            "FROM predictions GROUP BY 1 ORDER BY 1", fetch="all")
        hist = [0] * 5
        for b, cnt in buckets:
            hist[int(b)] = int(cnt)

        return {
            "total": total,
            "approved": approved,
            "rejected": total - approved,
            "approval_rate": round(approved / total, 4) if total else 0,
            "avg_loan_amount": round(float(r[2]), 1) if r[2] is not None else 0,
            "avg_probability": round(float(r[3]), 4) if r[3] is not None else 0,
            "avg_total_income": round(float(r[4]), 0) if r[4] is not None else 0,
            "by_property_area": grouped("property_area"),
            "by_credit_history": grouped("credit_history"),
            "by_education": grouped("education"),
            "by_model": grouped("model"),
            "daily": [{"date": d, "total": int(t), "approved": int(a or 0)} for d, t, a in reversed(daily)],
            "probability_histogram": hist,
        }
