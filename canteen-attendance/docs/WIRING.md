# Wiring Guide

This system works with optical fingerprint sensors that use the
Adafruit Fingerprint Sensor protocol — this covers the sensor commonly
bundled in Arduino-compatible kits, as well as the R305, R307, and
FPM10A modules. They all speak the same UART command set under the
hood.

## What you need

- Arduino Uno or Nano (anything with at least one spare digital I/O
  pair for SoftwareSerial — a Mega/Leonardo with a free hardware
  serial port works too and is slightly more reliable)
- Optical fingerprint sensor module (4-pin or 6-pin JST connector,
  usually: VCC, GND, TX, RX, and sometimes a touch-detect/wake pin)
- USB cable (Arduino to PC)
- Jumper wires

## Wiring diagram

```
   Fingerprint Sensor              Arduino Uno / Nano
   -------------------              ------------------
        VCC  ───────────────────────  5V *
        GND  ───────────────────────  GND
        TX   ───────────────────────  Pin 2  (D2, acts as RX)
        RX   ───────────────────────  Pin 3  (D3, acts as TX)
```

\* **Check your specific module's voltage rating before powering it
up.** Most optical sensors in this family run at 3.3–5V, but some are
strictly 3.3V only and will be damaged by 5V. If your module's
datasheet says 3.3V, use the Arduino's 3.3V pin instead, or run it
through a logic-level shifter if your board doesn't have a 3.3V rail
with enough current headroom.

## Why pins 2 and 3?

The sketch uses `SoftwareSerial` on pins 2/3 to talk to the
fingerprint sensor, leaving the Arduino's actual hardware serial port
(pins 0/1, also used by the USB connection) free for communicating
with the PC. This is the standard approach on boards like the Uno
and Nano that only expose one hardware UART. If you're using a board
with multiple hardware serial ports (Mega, Leonardo, certain ESP32
boards), you can rewire to use a free hardware serial port instead —
it tends to be more stable at higher baud rates, though for this
project's needs SoftwareSerial is plenty reliable.

## Common issues

**Sensor not detected / `ENROLL_FAIL:SENSOR_NOT_FOUND` in Serial Monitor**
- Double check TX/RX aren't swapped — sensor TX goes to Arduino pin 2,
  sensor RX goes to Arduino pin 3. This is the single most common
  mistake.
- Confirm the sensor is getting power (most have a small LED that
  lights briefly on power-up or when a finger is detected).
- Some clones default to a different baud rate than 57600 — check
  your specific module's datasheet if it's not responding.

**Inconsistent reads / random disconnects**
- A weak or shared 5V supply is the usual culprit. If you're powering
  other components off the same Arduino 5V rail, the sensor may be
  voltage-starved during a scan. Try a separate 5V supply if problems
  persist.

**Works in Arduino Serial Monitor but not when the PC app connects**
- Only one program can hold the serial port open at a time — make
  sure the Arduino IDE's Serial Monitor is closed before starting the
  Python backend.
