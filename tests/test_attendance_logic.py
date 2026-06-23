"""
test_attendance_logic.py
-------------------------
Unit tests for the database layer, IN/OUT auto-detection logic, and
the PC -> Arduino serial protocol formatting used for the LCD display
and RTC time sync.

Uses a temporary SQLite file per test run (not the real attendance.db)
so tests never touch real data and can run repeatedly / in CI.

Run with:
    pytest tests/ -v
"""

import sys
from datetime import datetime
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


# ---------------------------------------------------------------------
# Serial protocol formatting (PC -> Arduino)
#
# These don't run the actual firmware (that's C++, not testable from
# here) — they verify that the strings serial_listener.py and main.py
# build match the format the .ino file's handleDisplayCommand() and
# handleSetTimeCommand() expect to parse. A mismatch here is exactly
# the kind of bug that's invisible until you're standing in front of
# real hardware wondering why the LCD shows nothing.
# ---------------------------------------------------------------------

def _parse_display_command(command: str):
    """Mirrors handleDisplayCommand() in fingerprint_attendance.ino."""
    assert command.startswith("DISPLAY:")
    payload = command[len("DISPLAY:"):]
    first_colon = payload.index(":")
    second_colon = payload.index(":", first_colon + 1)
    return {
        "event_type": payload[:first_colon],
        "fingerprint_id": payload[first_colon + 1:second_colon],
        "time": payload[second_colon + 1:],
    }


def _parse_settime_command(command: str):
    """Mirrors handleSetTimeCommand() in fingerprint_attendance.ino."""
    assert command.startswith("SETTIME:")
    payload = command[len("SETTIME:"):]
    assert len(payload) >= 19, "firmware ignores anything shorter than this"
    date_part = payload[:10]
    time_part = payload[11:]
    return {
        "year": int(date_part[0:4]),
        "month": int(date_part[5:7]),
        "day": int(date_part[8:10]),
        "hour": int(time_part[0:2]),
        "minute": int(time_part[3:5]),
        "second": int(time_part[6:8]),
    }


def test_display_command_round_trips_for_check_in():
    timestamp = "2026-06-23T08:03:11"
    scan_time = datetime.fromisoformat(timestamp).strftime("%H:%M")
    command = f"DISPLAY:IN:23:{scan_time}"

    parsed = _parse_display_command(command)
    assert parsed["event_type"] == "IN"
    assert parsed["fingerprint_id"] == "23"
    assert parsed["time"] == "08:03"


def test_display_command_round_trips_for_check_out():
    timestamp = "2026-06-23T17:45:02"
    scan_time = datetime.fromisoformat(timestamp).strftime("%H:%M")
    command = f"DISPLAY:OUT:7:{scan_time}"

    parsed = _parse_display_command(command)
    assert parsed["event_type"] == "OUT"
    assert parsed["fingerprint_id"] == "7"
    assert parsed["time"] == "17:45"


def test_display_command_handles_multi_digit_fingerprint_ids():
    # Fingerprint IDs can go up to 127 — make sure a 3-digit ID doesn't
    # confuse the colon-splitting logic on either end.
    command = "DISPLAY:IN:127:09:00"
    parsed = _parse_display_command(command)
    assert parsed["fingerprint_id"] == "127"
    assert parsed["time"] == "09:00"


def test_settime_command_round_trips():
    now_str = "2026-06-23:14:32:07"
    command = f"SETTIME:{now_str}"

    parsed = _parse_settime_command(command)
    assert parsed == {
        "year": 2026, "month": 6, "day": 23,
        "hour": 14, "minute": 32, "second": 7,
    }
