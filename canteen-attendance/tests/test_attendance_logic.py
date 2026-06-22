"""
test_attendance_logic.py
-------------------------
Unit tests for the database layer and IN/OUT auto-detection logic.

Uses a temporary SQLite file per test run (not the real attendance.db)
so tests never touch real data and can run repeatedly / in CI.

Run with:
    pytest tests/ -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import database  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Points the database module at a throwaway SQLite file for the
    duration of one test, then lets it get cleaned up automatically."""
    test_db_path = tmp_path / "test_attendance.db"
    monkeypatch.setattr(database, "DB_PATH", test_db_path)
    database.init_db()
    yield test_db_path


def test_create_and_fetch_employee(temp_db):
    employee_id = database.create_employee(fingerprint_id=1, full_name="Juan Dela Cruz", role="Cook")
    employee = database.get_employee_by_id(employee_id)

    assert employee is not None
    assert employee["full_name"] == "Juan Dela Cruz"
    assert employee["role"] == "Cook"
    assert employee["active"] == 1


def test_get_employee_by_fingerprint_id(temp_db):
    database.create_employee(fingerprint_id=7, full_name="Maria Santos")
    employee = database.get_employee_by_fingerprint_id(7)

    assert employee is not None
    assert employee["full_name"] == "Maria Santos"


def test_unknown_fingerprint_returns_none(temp_db):
    assert database.get_employee_by_fingerprint_id(999) is None


def test_deactivated_employee_not_returned_by_fingerprint(temp_db):
    employee_id = database.create_employee(fingerprint_id=3, full_name="Pedro Reyes")
    database.deactivate_employee(employee_id)

    assert database.get_employee_by_fingerprint_id(3) is None


def test_next_available_fingerprint_id_starts_at_one(temp_db):
    assert database.next_available_fingerprint_id() == 1


def test_next_available_fingerprint_id_fills_gaps(temp_db):
    database.create_employee(fingerprint_id=1, full_name="A")
    database.create_employee(fingerprint_id=2, full_name="B")
    database.create_employee(fingerprint_id=4, full_name="C")

    # Slot 3 is free even though 4 is taken — should be reused.
    assert database.next_available_fingerprint_id() == 3


def test_first_scan_of_day_has_no_prior_event(temp_db):
    employee_id = database.create_employee(fingerprint_id=1, full_name="Juan")
    assert database.get_last_event_today(employee_id) is None


def test_log_attendance_records_event(temp_db):
    employee_id = database.create_employee(fingerprint_id=1, full_name="Juan")
    entry = database.log_attendance(employee_id, "IN")

    assert entry["event_type"] == "IN"
    assert entry["employee_id"] == employee_id

    last_event = database.get_last_event_today(employee_id)
    assert last_event["event_type"] == "IN"


def test_in_out_alternation(temp_db):
    """Mirrors the logic in serial_listener.determine_event_type:
    first scan today -> IN, next scan -> OUT, next -> IN, etc."""
    employee_id = database.create_employee(fingerprint_id=1, full_name="Juan")

    # First scan: no prior event today -> should be IN
    last_event = database.get_last_event_today(employee_id)
    assert last_event is None
    database.log_attendance(employee_id, "IN")

    # Second scan: last was IN -> should be OUT
    last_event = database.get_last_event_today(employee_id)
    assert last_event["event_type"] == "IN"
    database.log_attendance(employee_id, "OUT")

    # Third scan: last was OUT -> should be IN again
    last_event = database.get_last_event_today(employee_id)
    assert last_event["event_type"] == "OUT"
    database.log_attendance(employee_id, "IN")

    logs = database.get_logs(employee_id=employee_id)
    assert [log["event_type"] for log in logs] == ["IN", "OUT", "IN"]


def test_todays_summary_shows_first_in_and_last_out(temp_db):
    employee_id = database.create_employee(fingerprint_id=1, full_name="Juan")
    database.log_attendance(employee_id, "IN")
    database.log_attendance(employee_id, "OUT")
    database.log_attendance(employee_id, "IN")

    summary = database.get_todays_summary()
    row = next(r for r in summary if r["employee_id"] == employee_id)

    assert row["time_in"] is not None  # first IN of the day
    assert row["time_out"] is not None  # last OUT of the day


def test_todays_summary_includes_employees_with_no_activity(temp_db):
    database.create_employee(fingerprint_id=1, full_name="Juan")

    summary = database.get_todays_summary()
    assert len(summary) == 1
    assert summary[0]["time_in"] is None
    assert summary[0]["time_out"] is None


def test_logs_filtered_by_employee(temp_db):
    emp1 = database.create_employee(fingerprint_id=1, full_name="Juan")
    emp2 = database.create_employee(fingerprint_id=2, full_name="Maria")

    database.log_attendance(emp1, "IN")
    database.log_attendance(emp2, "IN")

    juan_logs = database.get_logs(employee_id=emp1)
    assert len(juan_logs) == 1
    assert juan_logs[0]["full_name"] == "Juan"
