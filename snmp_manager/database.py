import sqlite3
import os
import threading

DB_DIR = os.path.expanduser("~/.snmp-manager")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "snmp_manager.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    oid_from TEXT NOT NULL,
    oid_to TEXT,
    status TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    export_path TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA foreign_keys = ON")
    return _local.conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)

    # Clean up legacy tables to eliminate duplicate and conflicting configuration storage
    conn.execute("DROP TABLE IF EXISTS mib_modules")
    conn.execute("DROP TABLE IF EXISTS devices")

    # Mark any stale running query_history from previous crashes/restarts as stopped
    conn.execute("UPDATE query_history SET status = 'stopped' WHERE status = 'running'")
    conn.commit()


def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()} if row else None