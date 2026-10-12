"""
A tiny Flask web app:
  - shows an image (static/logo.svg)
  - shows a table of "people" stored in PostgreSQL
  - lets you add / edit / delete rows (6 fields each)

The database runs as a SECOND container in the SAME Kubernetes pod,
so the app reaches it on 127.0.0.1:5432 (containers in a pod share a network).
"""
import os
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, abort

app = Flask(__name__)

# ---- Configuration comes from environment variables (set by Helm) ----
APP_TITLE = os.getenv("APP_TITLE", "My Team Directory")
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "appdb"),
    "user": os.getenv("DB_USER", "appuser"),
    "password": os.getenv("DB_PASSWORD", "changeme"),
}

# The 6 editable fields in our table
FIELDS = ["name", "email", "role", "department", "location", "start_date"]


@contextmanager
def db_cursor():
    """Open a connection, give back a cursor, commit and close afterwards."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()


def init_db(retries: int = 30, delay: int = 2) -> None:
    """Create the table if it doesn't exist. Waits for Postgres to start."""
    for attempt in range(1, retries + 1):
        try:
            with db_cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS people (
                        id          SERIAL PRIMARY KEY,
                        name        TEXT NOT NULL,
                        email       TEXT,
                        role        TEXT,
                        department  TEXT,
                        location    TEXT,
                        start_date  DATE
                    )
                    """
                )
            print("Database ready.", flush=True)
            return
        except psycopg2.OperationalError as exc:
            print(f"Waiting for database ({attempt}/{retries}): {exc}", flush=True)
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database")


def form_values():
    """Read the 6 fields from the submitted form (empty -> None)."""
    return [request.form.get(f, "").strip() or None for f in FIELDS]


# ---------------------------- Routes ----------------------------
@app.route("/")
def index():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM people ORDER BY id")
        rows = cur.fetchall()
    return render_template("index.html", title=APP_TITLE, rows=rows, fields=FIELDS)


@app.route("/add", methods=["POST"])
def add():
    values = form_values()
    if not values[0]:
        return redirect(url_for("index"))  # name is required
    with db_cursor() as cur:
        cur.execute(
            f"INSERT INTO people ({', '.join(FIELDS)}) VALUES ({', '.join(['%s'] * len(FIELDS))})",
            values,
        )
    return redirect(url_for("index"))


@app.route("/edit/<int:row_id>", methods=["GET", "POST"])
def edit(row_id):
    if request.method == "POST":
        values = form_values()
        set_clause = ", ".join(f"{f} = %s" for f in FIELDS)
        with db_cursor() as cur:
            cur.execute(f"UPDATE people SET {set_clause} WHERE id = %s", values + [row_id])
        return redirect(url_for("index"))

    with db_cursor() as cur:
        cur.execute("SELECT * FROM people WHERE id = %s", (row_id,))
        row = cur.fetchone()
    if row is None:
        abort(404)
    return render_template("edit.html", title=APP_TITLE, row=row, fields=FIELDS)


@app.route("/delete/<int:row_id>", methods=["POST"])
def delete(row_id):
    with db_cursor() as cur:
        cur.execute("DELETE FROM people WHERE id = %s", (row_id,))
    return redirect(url_for("index"))


# Health endpoints used by Kubernetes probes
@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/ready")
def ready():
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
        return "ready", 200
    except Exception:  # noqa: BLE001
        return "database not ready", 503


# Create the table when the app starts
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
