# Wiring Guide

This system works with optical fingerprint sensors that use the
Adafruit Fingerprint Sensor protocol — this covers the sensor commonly
bundled in Arduino-compatible kits, as well as the R305, R307, and
FPM10A modules. They all speak the same UART command set under the
hood. It also drives a 16x2 I2C LCD and a DS1302 RTC module, both
wired to the same Arduino.

## What you need

- Arduino Uno or Nano (anything with at least one spare digital I/O
  pair for SoftwareSerial, plus 3 more free digital pins for the RTC —
  a Mega/Leonardo with a free hardware serial port works too and is
  slightly more reliable for the fingerprint sensor specifically)
- Optical fingerprint sensor module (4-pin or 6-pin JST connector,
  usually: VCC, GND, TX, RX, and sometimes a touch-detect/wake pin)
- 16x2 character LCD with an I2C backpack (4-pin: VCC, GND, SDA, SCL)
- DS1302 RTC module (5-pin: VCC, GND, CLK, DAT, RST)
- USB cable (Arduino to PC)
- Jumper wires

## Wiring diagram — fingerprint sensor

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

## Wiring diagram — DS1302 RTC module

```
   DS1302 RTC                       Arduino Uno / Nano
   -----------                       ------------------
        VCC  ───────────────────────  5V (or 3.3V — check your module)
        GND  ───────────────────────  GND
        CLK  ───────────────────────  Pin 5
        DAT  ───────────────────────  Pin 4
        RST  ───────────────────────  Pin 6
```

The DS1302 uses a 3-wire interface (sometimes called "SPI-like" but
it isn't real SPI) — it is **not** I2C, so it doesn't share the SDA/SCL
bus with the LCD. It needs its own three digital pins. The firmware
uses the `Rtc by Makuna` library's `ThreeWire` class for this, with
pin order `(IO, SCLK, CE)` — note that's a different order than the
module's own CLK/DAT/RST silkscreen labeling, so double check against
the code comments in the `.ino` file if the RTC doesn't respond.

**About the backup battery:** most DS1302 modules have a small coin
cell (often CR2032 or a rechargeable equivalent) that keeps the clock
running when the Arduino is powered off. If the battery is dead,
missing, or this is a brand new module, the RTC will report an
invalid date on boot — the firmware detects this and shows "RTC not
set!" on the LCD rather than guessing. The Python backend automatically
sends the correct time on every app startup, so in practice this
self-corrects the moment you run the app — you don't need to set it
manually unless the backend can't reach the Arduino yet.

## Wiring diagram — I2C LCD

```
   I2C LCD Backpack                 Arduino Uno / Nano
   -----------------                 ------------------
        VCC  ───────────────────────  5V
        GND  ───────────────────────  GND
        SDA  ───────────────────────  A4  (fixed I2C pin)
        SCL  ───────────────────────  A5  (fixed I2C pin)
```

On the Uno and Nano, the I2C pins are fixed at A4 (SDA) and A5 (SCL) —
you can't move these to other pins the way you can with the
SoftwareSerial or ThreeWire connections above.

**Finding your LCD's I2C address:** most I2C LCD backpacks default to
address `0x27` or `0x3F`, and the firmware assumes `0x27`. If the
screen stays blank (backlight on, but no text) even with correct
wiring, your module is probably on `0x3F` instead. You can confirm
this by running a basic I2C scanner sketch (search "Arduino I2C
scanner" for a short example sketch — it's a standard 20-line program
that just lists every address that responds), then change the address
in the `.ino` file:

```cpp
LiquidCrystal_I2C lcd(0x27, 16, 2);  // change 0x27 to 0x3F if needed
```

## Why pins 2 and 3 for the fingerprint sensor?

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

**LCD backlight is on but shows nothing, or shows garbled characters**
- Wrong I2C address — see the address troubleshooting note above.
- Loose SDA/SCL connection — these are the two most failure-prone
  jumpers since a marginal connection can produce garbled text rather
  than a clean blank screen.
- Contrast potentiometer (a small blue trimmer screw on most I2C
  backpacks) may need adjusting if characters show as solid blocks or
  are invisible.

**RTC always shows "RTC not set!" even after running the app**
- Confirm the Arduino is actually connected when the backend starts —
  the time sync only happens once, right after the app successfully
  connects to the Arduino. If the Arduino was unplugged at that
  moment, restart the backend after plugging it in.
- Check the RTC's backup battery isn't dead — a healthy battery should
  read roughly 2.7–3.3V across its terminals when measured with a
  multimeter (with the module disconnected from the Arduino).

**Inconsistent reads / random disconnects**
- A weak or shared 5V supply is the usual culprit. If you're powering
  other components off the same Arduino 5V rail, the sensor may be
  voltage-starved during a scan. Try a separate 5V supply if problems
  persist.

**Works in Arduino Serial Monitor but not when the PC app connects**
- Only one program can hold the serial port open at a time — make
  sure the Arduino IDE's Serial Monitor is closed before starting the
  Python backend.
