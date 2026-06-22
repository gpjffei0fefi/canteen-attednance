"""
serial_listener.py
-------------------
Bridges the Arduino (connected over USB serial) to the attendance
database. Runs as a background thread inside the FastAPI app.

Responsibilities:
  - Open and maintain the serial connection to the Arduino.
  - Parse incoming lines (MATCH:<id>, NOMATCH, ENROLL_OK:<id>, etc).
  - On a MATCH, look up the employee and decide whether this scan is
    a check-IN or check-OUT (auto-detected: if their last event today
    was IN, this scan is OUT, and vice versa; if no event yet today,
    it's IN).
  - Push results onto an in-memory queue that the web dashboard can
    poll, so the UI can show "Juan Dela Cruz checked IN at 8:03 AM"
    in near-real-time without needing websockets.
  - Auto-reconnect if the Arduino is unplugged/replugged, since this
    is a long-running local kiosk process and USB hiccups happen.

This module is intentionally decoupled from FastAPI — it only depends
on `database.py` and the standard library plus pyserial. That makes it
testable in isolation (see tests/test_attendance_logic.py) and easy to
run as a standalone script for debugging the Arduino link without
spinning up the whole web server.
"""

import queue
import threading
import time
from datetime import datetime

import serial
import serial.tools.list_ports

import database

# Events for the dashboard to consume, most recent scan results.
recent_events: "queue.Queue[dict]" = queue.Queue(maxsize=50)

_stop_flag = threading.Event()
_serial_connection: serial.Serial | None = None
_lock = threading.Lock()


def find_arduino_port() -> str | None:
    """Best-effort auto-detection of the Arduino's serial port. Looks
    for common identifying strings in the USB descriptor. Falls back
    to None if nothing obvious is found — the caller should then ask
    the user to specify the port manually (see SETUP.md)."""
    candidates = []
    for port in serial.tools.list_ports.comports():
        description = (port.description or "").lower()
        manufacturer = (port.manufacturer or "").lower()
        if "arduino" in description or "arduino" in manufacturer or "ch340" in description:
            candidates.append(port.device)
    return candidates[0] if candidates else None


def determine_event_type(employee_id: int) -> str:
    """Auto-detect IN vs OUT based on the employee's last logged
    event today. First scan of the day is always IN."""
    last_event = database.get_last_event_today(employee_id)
    if last_event is None:
        return "IN"
    return "OUT" if last_event["event_type"] == "IN" else "IN"


def _handle_line(line: str):
    line = line.strip()
    if not line:
        return

    if line.startswith("MATCH:"):
        try:
            fingerprint_id = int(line.split(":", 1)[1])
        except (IndexError, ValueError):
            return

        employee = database.get_employee_by_fingerprint_id(fingerprint_id)
        if employee is None:
            recent_events.put({
                "type": "UNKNOWN_FINGERPRINT",
                "fingerprint_id": fingerprint_id,
                "timestamp": datetime.now().isoformat(),
            })
            return

        event_type = determine_event_type(employee["id"])
        log_entry = database.log_attendance(employee["id"], event_type)

        recent_events.put({
            "type": "ATTENDANCE_LOGGED",
            "employee_id": employee["id"],
            "full_name": employee["full_name"],
            "event_type": event_type,
            "timestamp": log_entry["timestamp"],
        })

    elif line == "NOMATCH":
        recent_events.put({
            "type": "NO_MATCH",
            "timestamp": datetime.now().isoformat(),
        })

    elif line.startswith("ENROLL_OK:") or line.startswith("ENROLL_FAIL") \
            or line.startswith("ENROLL_WAITING") or line == "READY" \
            or line == "PONG" or line.startswith("DELETE_"):
        # These are surfaced via the enrollment-specific helper
        # functions below (send_command + read loop), not the
        # general attendance event queue.
        recent_events.put({
            "type": "DEVICE_MESSAGE",
            "message": line,
            "timestamp": datetime.now().isoformat(),
        })


def _listen_loop(port: str, baud: int = 9600):
    global _serial_connection

    while not _stop_flag.is_set():
        try:
            with _lock:
                _serial_connection = serial.Serial(port, baud, timeout=1)
            time.sleep(2)  # Arduino resets on serial connect; give it time to boot

            while not _stop_flag.is_set():
                try:
                    raw = _serial_connection.readline()
                except serial.SerialException:
                    break  # device likely disconnected — drop to reconnect loop

                if raw:
                    try:
                        line = raw.decode("utf-8", errors="ignore")
                    except UnicodeDecodeError:
                        continue
                    _handle_line(line)

        except serial.SerialException:
            # Couldn't open the port (unplugged, wrong port, etc).
            # Wait and retry rather than crashing the whole app.
            time.sleep(3)
        finally:
            with _lock:
                if _serial_connection is not None:
                    try:
                        _serial_connection.close()
                    except Exception:
                        pass
                    _serial_connection = None


_listener_thread: threading.Thread | None = None


def start(port: str | None = None, baud: int = 9600):
    """Starts the background serial listener thread. If no port is
    given, attempts auto-detection."""
    global _listener_thread

    resolved_port = port or find_arduino_port()
    if resolved_port is None:
        raise RuntimeError(
            "Could not find an Arduino on any serial port. "
            "Plug it in, or specify the port manually in config "
            "(see docs/SETUP.md)."
        )

    _stop_flag.clear()
    _listener_thread = threading.Thread(
        target=_listen_loop, args=(resolved_port, baud), daemon=True
    )
    _listener_thread.start()
    return resolved_port


def stop():
    _stop_flag.set()
    if _listener_thread is not None:
        _listener_thread.join(timeout=5)


def send_command(command: str) -> bool:
    """Sends a command line to the Arduino (e.g. 'ENROLL:5'). Returns
    True if the write succeeded, False if there's no active
    connection to write to."""
    with _lock:
        if _serial_connection is None or not _serial_connection.is_open:
            return False
        try:
            _serial_connection.write((command + "\n").encode("utf-8"))
            return True
        except serial.SerialException:
            return False


def is_connected() -> bool:
    with _lock:
        return _serial_connection is not None and _serial_connection.is_open
