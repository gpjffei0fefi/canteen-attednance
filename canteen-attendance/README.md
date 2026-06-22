# Canteen Attendance System

A fingerprint-based attendance tracker built for a local canteen,
combining an Arduino-driven biometric scanner with a Python/FastAPI
backend and a lightweight web dashboard — all running locally on a
single PC, no internet or cloud dependency required.

Employees check in and out by placing a finger on a sensor. The
system automatically determines whether each scan is a check-in or
check-out, logs it with a timestamp, and surfaces it on a dashboard
the canteen admin can glance at throughout the day.

![Status](https://img.shields.io/badge/status-active-success)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Tests](https://github.com/YOUR-USERNAME/canteen-attendance/actions/workflows/tests.yml/badge.svg)

## Why this exists

Small food-service operations rarely have attendance systems beyond a
paper logbook — easy to forget, easy to falsify, and tedious to total
up at payroll time. This project replaces that with a tap-and-go
fingerprint scan and an always-up-to-date digital record, built
specifically for a single-location operation where a cloud platform
would be overkill.

## How it works

```
┌─────────────────┐      USB Serial       ┌──────────────────┐
│   Fingerprint    │ ───────────────────▶  │   Python/FastAPI │
│   Sensor +       │   "MATCH:<id>"        │   Backend         │
│   Arduino        │ ◀───────────────────  │   (SQLite)        │
└─────────────────┘   "ENROLL:<id>" etc.   └──────────────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │  Local Web        │
                                            │  Dashboard         │
                                            │  (localhost:8000)  │
                                            └──────────────────┘
```

- The fingerprint **matching itself happens on the sensor module**,
  not in software — the Arduino only ever transmits an integer ID,
  never raw biometric data. This keeps the design privacy-conscious
  by construction rather than as an afterthought.
- The backend listens on the Arduino's serial port in a background
  thread, looks up which employee owns that fingerprint ID, and
  decides IN vs. OUT based on their last logged event *today* — first
  scan of the day is always IN, and it alternates from there.
- Everything is stored in a single SQLite file. No database server to
  configure, no network ports to open, no internet connection needed.

## Features

- 🔒 **Privacy-respecting biometrics** — fingerprint templates never
  leave the sensor hardware.
- 🔁 **Automatic IN/OUT detection** — no mode switches or separate
  buttons for employees to think about.
- 📋 **Admin dashboard** — today's attendance at a glance, live scan
  feed, per-employee history, and self-service enrollment flow.
- 🔌 **Resilient to USB hiccups** — the serial connection
  auto-reconnects if the Arduino is unplugged and replugged.
- 🧪 **Tested core logic** — the attendance/IN-OUT rules are covered
  by an automated test suite, not just manually eyeballed.
- 🪶 **Zero external services** — SQLite + a single Python process;
  nothing to host, nothing recurring to pay for.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Sensor firmware | Arduino (C++) + Adafruit Fingerprint library | Standard, well-documented protocol for optical fingerprint modules |
| Backend | Python + FastAPI | Modern, async-friendly, minimal boilerplate, great for a small local API |
| Database | SQLite | Zero-config, single-file, ideal for one-PC deployments |
| Frontend | Vanilla HTML/CSS/JS | No build step, nothing to break on a kiosk PC with infrequent maintenance |

## Project structure

```
canteen-attendance/
├── arduino/
│   └── fingerprint_attendance/
│       └── fingerprint_attendance.ino   # Arduino firmware
├── backend/
│   ├── main.py                          # FastAPI app & routes
│   ├── database.py                      # SQLite schema & queries
│   ├── serial_listener.py               # Arduino <-> backend bridge
│   ├── requirements.txt
│   └── static/                          # Dashboard (HTML/CSS/JS)
├── docs/
│   ├── WIRING.md                        # Sensor wiring diagram & troubleshooting
│   └── SETUP.md                         # Full setup walkthrough
└── tests/
    └── test_attendance_logic.py         # Automated tests for the core logic
```

## Getting started

> **Before you push to GitHub:** replace `YOUR-USERNAME` in the
> Tests badge URL above with your actual GitHub username, so the
> badge links to your repo's own Actions runs instead of a
> placeholder.

See [docs/SETUP.md](docs/SETUP.md) for the full walkthrough, and
[docs/WIRING.md](docs/WIRING.md) for hardware wiring. Short version:

```bash
# 1. Wire the fingerprint sensor to the Arduino (see docs/WIRING.md)
# 2. Flash arduino/fingerprint_attendance/fingerprint_attendance.ino via the Arduino IDE

# 3. Run the backend
cd backend
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 4. Open http://localhost:8000
```

## Running tests

```bash
cd backend
pip install -r requirements-dev.txt
cd ..
pytest tests/ -v
```

Tests run automatically on every push via GitHub Actions (see
[.github/workflows/tests.yml](.github/workflows/tests.yml)) — including
a check that the backend boots and serves the dashboard cleanly even
with no Arduino attached, since that's the actual state of a
freshly-cloned CI runner (and often, a freshly-cloned laptop).

## Hardware used

- Arduino Uno (or Nano/Mega/Leonardo — anything with a spare serial
  pair works)
- Optical fingerprint sensor module (Adafruit Fingerprint Sensor
  protocol family — R305/R307/FPM10A and compatible clones)

## Possible extensions

A few directions this could grow in, listed honestly rather than as
a marketing wishlist:

- **Payroll export** — a CSV/Excel export of hours worked per pay
  period, computed from IN/OUT pairs.
- **Multi-location support** — would require moving off SQLite to a
  networked database and adding authentication; a meaningfully bigger
  project, not a small tweak.
- **Late/undertime flags** — comparing scans against expected shift
  schedules.
- **Offline-first sync** — if ever deployed across multiple sites,
  queuing scans locally and syncing when connectivity is available.

## Contributing

This started as a single-canteen tool, so the contribution process is
intentionally lightweight — see [CONTRIBUTING.md](CONTRIBUTING.md)
for setup notes and a few conventions the codebase follows.

## License

MIT — see [LICENSE](LICENSE).

---

Built as a practical tool for a local canteen, and shared here as a
portfolio piece demonstrating embedded/software integration, API
design, and pragmatic engineering decisions for a real-world,
resource-constrained deployment.
