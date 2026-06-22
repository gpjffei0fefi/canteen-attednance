# Contributing

Thanks for taking an interest in this project. It started as a
practical tool for one local canteen, so the contribution process
here is intentionally lightweight — no CLA, no formal RFC process,
just the basics that keep a small hardware-coupled project healthy.

## Before you start

This project has a real-world hardware dependency (an optical
fingerprint sensor + Arduino), which makes it a little different to
contribute to than a pure web app:

- **Software-only changes** (backend logic, dashboard UI, tests,
  docs) can be developed and tested without any hardware at all —
  the backend runs and degrades gracefully with no Arduino attached,
  and the test suite uses a temporary SQLite database, not a real
  sensor.
- **Firmware changes** (`arduino/fingerprint_attendance/*.ino`)
  ideally need to be tested against real hardware before a PR is
  merged, since the serial protocol between the Arduino and the
  backend is easy to break in ways that only show up with an actual
  sensor attached. If you don't have the hardware, that's still a
  useful PR — just say so, and it can be tested by someone who does
  before merging.

## Getting set up

1. Fork and clone the repo.
2. Follow [docs/SETUP.md](docs/SETUP.md) to get the backend running
   locally. You can do most development without a fingerprint sensor
   attached — the dashboard, API, and database logic all work
   independently of hardware.
3. Install dev dependencies and run the test suite to confirm your
   environment is set up correctly:
   ```bash
   cd backend
   pip install -r requirements.txt -r requirements-dev.txt
   cd ..
   pytest tests/ -v
   ```

## Making a change

1. Create a branch off `main` with a short, descriptive name
   (e.g. `add-payroll-export`, `fix-timezone-bug`).
2. Make your change. A few conventions this codebase follows that
   are worth keeping consistent with:
   - **No ORM** — `database.py` uses plain `sqlite3` with visible SQL.
     This is a deliberate choice for a project this size; please don't
     introduce SQLAlchemy or similar without discussing it in an issue
     first.
   - **No frontend framework** — the dashboard is vanilla HTML/CSS/JS
     on purpose (see the comment at the top of `app.js` for why).
   - **Comments explain *why*, not just *what*** — if you're making a
     non-obvious design choice, leave a short note explaining the
     reasoning, the way the rest of the codebase does.
3. If you changed any logic in `database.py` or `serial_listener.py`,
   add or update tests in `tests/test_attendance_logic.py` to cover
   it. PRs that touch the IN/OUT detection logic especially need test
   coverage — that's the easiest part of this system to subtly break.
4. Run the test suite locally before opening a PR:
   ```bash
   pytest tests/ -v
   ```
   This also runs automatically via GitHub Actions on every PR, but
   catching failures locally first saves a round trip.

## Opening a pull request

- Keep PRs focused on one change. A PR that fixes a bug *and*
  refactors an unrelated module is harder to review and harder to
  revert if something goes wrong.
- Describe what you changed and why in the PR description — assume
  the reviewer doesn't have the same context you do.
- If your change affects setup or wiring steps, update
  [docs/SETUP.md](docs/SETUP.md) or [docs/WIRING.md](docs/WIRING.md)
  in the same PR. Docs that fall out of sync with the code are worse
  than no docs.

## Reporting bugs

Open an issue with:
- What you expected to happen
- What actually happened
- Whether it's reproducible without hardware (software-only bug) or
  only shows up with the sensor attached (hardware/firmware bug)
- Your Python version and OS, if it seems environment-related

## Ideas for contributions

If you're looking for somewhere to start, the "Possible extensions"
section in the [README](README.md#possible-extensions) lists a few
directions this project could grow in — payroll export and
late/undertime tracking are probably the most approachable for a
first contribution, since they're additive and don't touch the core
attendance logic.
