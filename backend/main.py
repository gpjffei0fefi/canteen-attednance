"""
main.py
-------
FastAPI application for the canteen attendance system.

This serves two things:
  1. A small REST API for employee management, enrollment, and
     attendance reporting.
  2. The static dashboard (HTML/CSS/JS) the canteen admin uses
     day-to-day, served from /static.

Run with:
    uvicorn main:app --reload --port 8000

Then open http://localhost:8000 in a browser.

Design notes for anyone reading this as a portfolio piece:
  - This app is meant to run locally on a single PC at the canteen.
    There's no auth layer because it's not exposed to the internet —
    if you adapt this for a networked/multi-location deployment, add
    authentication before doing so.
  - The serial listener runs as a background thread started on
    FastAPI's startup event, decoupled from request/response cycles.
  - Enrollment is a short multi-step interaction (place finger twice),
    so the enroll endpoint is async and polls device messages with a
    timeout rather than blocking forever.
"""

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import serial_listener


class EmployeeCreate(BaseModel):
    full_name: str
    role: str = ""


class EnrollRequest(BaseModel):
    full_name: str
    role: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    try:
        port = serial_listener.start()
        print(f"[startup] Connected to Arduino on {port}")

        # Give the Arduino a moment to finish its own setup() (sensor
        # init, LCD init) before we start writing to it — otherwise
        # the SETTIME command can arrive before the board is ready to
        # read it and gets silently dropped.
        await asyncio.sleep(2)

        now = time.strftime("%Y-%m-%d:%H:%M:%S")
        synced = serial_listener.send_command(f"SETTIME:{now}")
        if synced:
            print(f"[startup] Synced Arduino RTC to PC time ({now})")
        else:
            print("[startup] WARNING: Could not sync RTC — Arduino connection "
                  "not ready yet. The clock on the LCD may be stale until the "
                  "next manual sync.")
    except RuntimeError as e:
        print(f"[startup] WARNING: {e}")
        print("[startup] App will run, but fingerprint scanning is unavailable "
              "until an Arduino is connected and the app is restarted.")
    yield
    serial_listener.stop()


app = FastAPI(title="Canteen Attendance System", lifespan=lifespan)


# ---------------------------------------------------------------------
# Employee management
# ---------------------------------------------------------------------

@app.get("/api/employees")
def list_employees(include_inactive: bool = False):
    return database.list_employees(include_inactive=include_inactive)


@app.post("/api/employees/enroll")
async def enroll_employee(req: EnrollRequest):
    """Drives the Arduino through fingerprint enrollment, then creates
    the employee record once the sensor confirms success.

    This is a multi-second interaction: the admin will be prompted
    (via the dashboard) to have the employee place their finger twice.
    """
    if not serial_listener.is_connected():
        raise HTTPException(503, "Arduino is not connected.")

    fingerprint_id = database.next_available_fingerprint_id()

    sent = serial_listener.send_command(f"ENROLL:{fingerprint_id}")
    if not sent:
        raise HTTPException(503, "Failed to send command to Arduino.")

    result = await _await_enrollment_result(timeout_seconds=30)

    if result is None:
        raise HTTPException(504, "Enrollment timed out. Make sure the "
                                  "employee places their finger when prompted.")

    if result.startswith("ENROLL_OK"):
        employee_id = database.create_employee(
            fingerprint_id=fingerprint_id,
            full_name=req.full_name,
            role=req.role,
        )
        return {
            "success": True,
            "employee_id": employee_id,
            "fingerprint_id": fingerprint_id,
        }
    else:
        reason = result.split(":", 1)[1] if ":" in result else "unknown error"
        raise HTTPException(400, f"Enrollment failed: {reason}")


async def _await_enrollment_result(timeout_seconds: int) -> str | None:
    """Polls the serial listener's event queue for an ENROLL_OK/FAIL
    message, up to a timeout. Runs the blocking queue check in a
    thread so it doesn't stall the FastAPI event loop."""
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        message = await asyncio.to_thread(_pop_device_message, 1.0)
        if message and (message.startswith("ENROLL_OK") or message.startswith("ENROLL_FAIL")):
            return message
    return None


def _pop_device_message(timeout: float) -> str | None:
    try:
        event = serial_listener.recent_events.get(timeout=timeout)
        if event.get("type") == "DEVICE_MESSAGE":
            return event["message"]
        return None
    except Exception:
        return None


@app.delete("/api/employees/{employee_id}")
def deactivate_employee(employee_id: int):
    employee = database.get_employee_by_id(employee_id)
    if employee is None:
        raise HTTPException(404, "Employee not found.")
    database.deactivate_employee(employee_id)
    return {"success": True}


# ---------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------

@app.get("/api/attendance/today")
def todays_attendance():
    return database.get_todays_summary()


@app.get("/api/attendance/logs")
def attendance_logs(date_from: str = None, date_to: str = None, employee_id: int = None):
    return database.get_logs(date_from=date_from, date_to=date_to, employee_id=employee_id)


@app.get("/api/attendance/recent-events")
def recent_events():
    """Drains and returns any pending scan events for the dashboard's
    live activity feed (polled every few seconds by the frontend)."""
    events = []
    while not serial_listener.recent_events.empty():
        try:
            events.append(serial_listener.recent_events.get_nowait())
        except Exception:
            break
    return events


# ---------------------------------------------------------------------
# Device status
# ---------------------------------------------------------------------

@app.get("/api/device/status")
def device_status():
    return {"connected": serial_listener.is_connected()}


# ---------------------------------------------------------------------
# Static dashboard
# ---------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def dashboard():
    return FileResponse("static/index.html")
