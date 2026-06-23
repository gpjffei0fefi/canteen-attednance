# Setup Guide

Step-by-step instructions to get this running on a fresh PC at the
canteen. Written assuming basic familiarity with installing software,
not assuming prior Arduino or Python experience.

## 1. Hardware setup

Follow [WIRING.md](WIRING.md) to connect the fingerprint sensor to
your Arduino, then connect the Arduino to the PC via USB.

## 2. Flash the Arduino

1. Install the [Arduino IDE](https://www.arduino.cc/en/software) if
   you don't already have it.
2. Install three libraries via **Sketch → Include Library → Manage
   Libraries…**, searching for and installing each of these:
   - **Adafruit Fingerprint Sensor Library**
   - **LiquidCrystal_I2C** (by Frank de Brabander — there are a couple
     of similarly-named forks; this one is the most common and matches
     the API the firmware expects)
   - **Rtc by Makuna** (provides the `ThreeWire` and `RtcDS1302`
     classes used for the DS1302 module)
3. Open `arduino/fingerprint_attendance/fingerprint_attendance.ino`
   in the Arduino IDE.
4. Select your board and port under **Tools**, then click **Upload**.
5. Open **Tools → Serial Monitor**, set the baud rate to 9600. You
   should see `READY` printed once the fingerprint sensor initializes
   correctly. The LCD should show a brief "Starting..." message, then
   settle into showing the date and a "RTC not set!" message if the
   DS1302 hasn't been given a time yet — this is expected and corrects
   itself automatically once you start the Python backend (step 4).
   If the sensor instead prints `ENROLL_FAIL:SENSOR_NOT_FOUND`, recheck
   your wiring (see WIRING.md's troubleshooting section).
6. **Close the Serial Monitor** before moving to the next step — only
   one program can use the serial port at a time, and the Python
   backend needs it next.

## 3. Set up the Python backend

You'll need [Python 3.10+](https://www.python.org/downloads/)
installed.

```bash
cd backend
python -m venv venv

# On Windows:
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

## 4. Run the app

```bash
uvicorn main:app --reload --port 8000
```

You should see something like:

```
[startup] Connected to Arduino on /dev/ttyUSB0
[startup] Synced Arduino RTC to PC time (2026-06-23:14:32:07)
INFO:     Uvicorn running on http://127.0.0.1:8000
```

That second line means the backend just set the DS1302's clock to
match your PC's current time — this happens automatically every time
the app starts, so the LCD's clock stays accurate without you ever
needing to set it by hand.

If instead you see a warning that no Arduino was found, the app will
still run (you can browse the dashboard), but fingerprint scanning
won't work until you:
- Confirm the Arduino is plugged in and shows up in your OS's device
  list (Device Manager on Windows, `ls /dev/tty*` on macOS/Linux)
- Restart the app

Then open **http://localhost:8000** in a browser.

## 5. Enroll your first employee

1. In the dashboard, scroll to **Add an employee**.
2. Enter their name and (optionally) role, then click **Start
   enrollment**.
3. Have the employee place their finger on the sensor when the status
   message asks them to, then lift it and place it again when
   prompted a second time. Two scans are required to build a reliable
   fingerprint template — this is normal and expected.
4. On success, they'll appear in the **Employees** list and in
   today's attendance table.

## 6. Day-to-day use

From here on, employees just place a finger on the sensor when they
arrive and when they leave. The system automatically figures out
whether a scan is a check-in or check-out based on their most recent
scan that day — no buttons or modes to select.

Leave the app running throughout the day (e.g. minimize the terminal
window) — it needs to stay running to keep listening for scans.

## Running automatically on startup (optional)

If you want the canteen PC to start the system automatically without
someone having to open a terminal each morning:

**Windows:** Create a `.bat` file with the activation + uvicorn
commands from step 4, then add a shortcut to it in the Startup folder
(`shell:startup` in the Run dialog).

**macOS/Linux:** Consider a simple `systemd` service (Linux) or
`launchd` agent (macOS) that runs the uvicorn command on boot. This is
a good area to extend the project if you want to add it to your
portfolio write-up.

## Running the test suite

```bash
cd backend
pip install -r requirements-dev.txt
cd ..
pytest tests/ -v
```

These tests cover the database logic and the IN/OUT auto-detection
rules, using a temporary database so they never touch real attendance
data.
