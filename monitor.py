import os
import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
  id         INTEGER PRIMARY KEY,
  round_at   TEXT    NOT NULL,
  interval_s INTEGER NOT NULL,
  target     TEXT    NOT NULL,
  check_type TEXT    NOT NULL,
  ok         INTEGER NOT NULL CHECK (ok IN (0, 1)),
  latency_ms REAL,
  error      TEXT
);
CREATE INDEX IF NOT EXISTS checks_round_at ON checks (round_at);
"""


def default_db_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return pathlib.Path(base) / "internettester" / "checks.db"


def open_db(path):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save_result(conn, round_at, interval_s, result):
    with conn:
        conn.execute(
            "INSERT INTO checks (round_at, interval_s, target, check_type, ok, latency_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (round_at, interval_s, *result),
        )
