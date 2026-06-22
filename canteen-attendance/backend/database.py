"""
database.py
-----------
SQLite data layer for the canteen attendance system.

Schema:
  employees
    id              INTEGER PRIMARY KEY
    fingerprint_id  INTEGER UNIQUE   -- matches the slot ID stored on the
                                        Arduino's fingerprint sensor
    full_name       TEXT
    role            TEXT             -- e.g. "Cook", "Cashier", "Server"
    active          INTEGER          -- 1 = active, 0 = deactivated
    created_at      TEXT

  attendance_logs
    id              INTEGER PRIMARY KEY
    employee_id     INTEGER          -- FK -> employees.id
    timestamp       TEXT             -- ISO 8601
    event_type      TEXT             -- "IN" or "OUT"

We use plain sqlite3 (no ORM) on purpose: this is a small, single-PC,
single-process app. An ORM would add a dependency and a learning curve
without buying anything here. Keeping the SQL visible and readable is
also a better portfolio signal — it shows you understand what's
actually happening under the hood.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "attendance.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint_id INTEGER UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('IN', 'OUT')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE INDEX IF NOT EXISTS idx_logs_employee_timestamp
    ON attendance_logs(employee_id, timestamp);
"""


@contextmanager
def get_connection():
    """Yields a SQLite connection with foreign keys enabled and
    row access by column name. Closes automatically on exit."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Creates tables if they don't already exist. Safe to call on
    every app startup."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------
# Employee operations
# ---------------------------------------------------------------------

def create_employee(fingerprint_id: int, full_name: str, role: str = "") -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO employees (fingerprint_id, full_name, role, active, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            (fingerprint_id, full_name, role, datetime.now().isoformat()),
        )
        return cursor.lastrowid


def get_employee_by_fingerprint_id(fingerprint_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE fingerprint_id = ? AND active = 1",
            (fingerprint_id,),
        ).fetchone()
        return dict(row) if row else None


def get_employee_by_id(employee_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        return dict(row) if row else None


def list_employees(include_inactive: bool = False):
    query = "SELECT * FROM employees"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY full_name"
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]


def deactivate_employee(employee_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE employees SET active = 0 WHERE id = ?", (employee_id,)
        )


def next_available_fingerprint_id() -> int:
    """Finds the lowest unused fingerprint slot ID, starting from 1.
    Useful for the enrollment UI so the admin doesn't have to track
    which slots are taken on the sensor."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT fingerprint_id FROM employees ORDER BY fingerprint_id"
        ).fetchall()
        used = {r["fingerprint_id"] for r in rows}
        candidate = 1
        while candidate in used:
            candidate += 1
        return candidate


# ---------------------------------------------------------------------
# Attendance log operations
# ---------------------------------------------------------------------

def get_last_event_today(employee_id: int):
    """Returns the most recent attendance event for this employee,
    restricted to today's date, or None if they haven't scanned yet
    today. This is what powers the IN/OUT auto-detection."""
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM attendance_logs
               WHERE employee_id = ? AND timestamp LIKE ?
               ORDER BY timestamp DESC LIMIT 1""",
            (employee_id, f"{today_prefix}%"),
        ).fetchone()
        return dict(row) if row else None


def log_attendance(employee_id: int, event_type: str) -> dict:
    timestamp = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO attendance_logs (employee_id, timestamp, event_type)
               VALUES (?, ?, ?)""",
            (employee_id, timestamp, event_type),
        )
        return {
            "id": cursor.lastrowid,
            "employee_id": employee_id,
            "timestamp": timestamp,
            "event_type": event_type,
        }


def get_logs(date_from: str = None, date_to: str = None, employee_id: int = None):
    """Returns attendance logs joined with employee names, optionally
    filtered by date range (ISO date strings, e.g. '2026-06-01') and/or
    a specific employee."""
    query = """
        SELECT logs.id, logs.timestamp, logs.event_type,
               employees.id AS employee_id, employees.full_name, employees.role
        FROM attendance_logs logs
        JOIN employees employees ON employees.id = logs.employee_id
        WHERE 1=1
    """
    params = []

    if date_from:
        query += " AND logs.timestamp >= ?"
        params.append(date_from)
    if date_to:
        query += " AND logs.timestamp <= ?"
        params.append(date_to + "T23:59:59")
    if employee_id:
        query += " AND logs.employee_id = ?"
        params.append(employee_id)

    query += " ORDER BY logs.timestamp DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_todays_summary():
    """Returns one row per employee showing their first IN and last OUT
    today, for the dashboard's daily view."""
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.role,
                MIN(CASE WHEN l.event_type = 'IN' THEN l.timestamp END) AS time_in,
                MAX(CASE WHEN l.event_type = 'OUT' THEN l.timestamp END) AS time_out
            FROM employees e
            LEFT JOIN attendance_logs l
                ON l.employee_id = e.id AND l.timestamp LIKE ?
            WHERE e.active = 1
            GROUP BY e.id
            ORDER BY e.full_name
            """,
            (f"{today_prefix}%",),
        ).fetchall()
        return [dict(r) for r in rows]
