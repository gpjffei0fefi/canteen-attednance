/*
  Canteen Attendance System — Fingerprint Scanner Firmware
  ----------------------------------------------------------
  Hardware:
    - Arduino Uno/Nano
    - Optical Fingerprint Sensor (Adafruit Fingerprint Sensor /
      FPM10A / R305 / R307 — all compatible, same UART protocol family)
    - 16x2 LCD with I2C backpack (PCF8574-based, address usually 0x27
      or 0x3F — see docs/WIRING.md if the screen stays blank)
    - DS1302 RTC module (3-wire interface: CLK/DAT/RST — NOT I2C,
      uses the "Rtc by Makuna" library, separate from the LCD's I2C bus)

  What this sketch does:
  - Continuously waits for a finger on the sensor.
  - On a successful match, prints a single line to Serial:
        MATCH:<id>
    where <id> is the fingerprint's stored slot number (1-127).
  - On enrollment mode (triggered by sending "ENROLL:<id>" over Serial
    from the PC), walks through the two-scan enrollment process and
    reports success/failure.
  - All matching happens ON the sensor itself — no fingerprint images
    or biometric data ever leave the device. Only an integer ID is
    transmitted. This keeps the system privacy-conscious by design.
  - Keeps real time via the DS1302 RTC (survives power loss with its
    backup battery — the Arduino's own millis()-based timing resets
    to zero on every reboot, which is why a dedicated RTC chip matters
    here rather than just counting milliseconds since boot).
  - Shows a live clock on the LCD when idle. On receiving a DISPLAY
    command from the PC (sent right after the PC logs an attendance
    event), temporarily shows that scan's result instead, then reverts
    to the clock after a few seconds.

  IMPORTANT DESIGN NOTE — why the LCD shows an ID number, not a name:
  The Arduino has no knowledge of employee names; that mapping lives
  in the Python backend's database, by design (see serial_listener.py
  and database.py in the repo). Keeping names off the Arduino avoids
  duplicating that data on two devices that could drift out of sync.
  Likewise, IN/OUT is decided by the PC (which checks the real
  attendance log) and sent back to the Arduino to display — the
  Arduino does not guess this itself, so the LCD always matches what
  actually got recorded.

  Wiring (Arduino Uno/Nano — uses SoftwareSerial for the fingerprint
  sensor since these boards only have one hardware serial port, which
  stays reserved for USB/PC communication):

      Fingerprint Sensor Pin    Arduino Pin
      ----------------------    -----------
      VCC                       5V   (check your module's datasheet — some need 3.3V)
      GND                       GND
      TX                        Pin 2 (Arduino RX)
      RX                        Pin 3 (Arduino TX)

      DS1302 RTC Pin            Arduino Pin
      --------------            -----------
      VCC                       5V (or 3.3V — check your module)
      GND                       GND
      CLK / SCLK                Pin 5
      DAT / IO                  Pin 4
      RST / CE                  Pin 6

      I2C LCD Pin               Arduino Pin
      ------------              -----------
      VCC                       5V
      GND                       GND
      SDA                       A4  (fixed I2C pin on Uno/Nano)
      SCL                       A5  (fixed I2C pin on Uno/Nano)

  See docs/WIRING.md in the repo for a full diagram and notes on
  power quirks and the LCD's I2C address.

  Required libraries (install via Arduino IDE Library Manager):
    - Adafruit Fingerprint Sensor Library
    - LiquidCrystal_I2C  (by Frank de Brabander, or the Marco Schwartz fork)
    - Rtc by Makuna       (provides ThreeWire + RtcDS1302)

  Serial protocol (Arduino <-> PC), 9600 baud:
    PC -> Arduino:
      ENROLL:<id>             start enrollment for the given slot ID
      DELETE:<id>              delete a stored fingerprint
      PING                     health check, Arduino replies "PONG"
      DISPLAY:<IN|OUT>:<id>:<HH:MM>
                               show this scan result on the LCD for a
                               few seconds, then revert to the clock.
                               Sent by the PC right after it decides
                               and logs IN vs OUT, so the LCD always
                               reflects what's actually in the database.
      SETTIME:<YYYY-MM-DD>:<HH:MM:SS>
                               set the RTC's date/time (useful the
                               first time the RTC is powered, or if it
                               drifts — the PC can send its own clock)

    Arduino -> PC:
      MATCH:<id>               fingerprint matched, here's the ID
      NOMATCH                   finger scanned but no match found
      ENROLL_OK:<id>            enrollment succeeded for that ID
      ENROLL_FAIL:<reason>      enrollment failed
      PONG                      reply to PING
      READY                     sent once at startup when sensor is online
      RTC_FAIL                  sent at startup if the RTC isn't responding
*/

#include <Adafruit_Fingerprint.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ThreeWire.h>
#include <RtcDS1302.h>

// ---- Fingerprint sensor (SoftwareSerial) ----
// Sensor TX -> Arduino pin 2 (this is the Arduino's RX)
// Sensor RX -> Arduino pin 3 (this is the Arduino's TX)
SoftwareSerial fingerSerial(2, 3);
Adafruit_Fingerprint finger(&fingerSerial);

// ---- DS1302 RTC (3-wire, not I2C — separate bus from the LCD) ----
// Pin order for ThreeWire is (IO, SCLK, CE) — note this is NOT the
// same order as the physical module silkscreen, which usually reads
// CLK/DAT/RST left-to-right. Double check against docs/WIRING.md if
// the RTC doesn't respond.
ThreeWire rtcWire(4, 5, 6); // IO=4 (DAT), SCLK=5 (CLK), CE=6 (RST)
RtcDS1302<ThreeWire> rtc(rtcWire);

// ---- 16x2 I2C LCD ----
// Common I2C addresses for these backpacks are 0x27 or 0x3F. If the
// screen stays blank with correct wiring, try the other address —
// see docs/WIRING.md for how to scan for it.
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Debounce / polling interval for checking the fingerprint sensor
const unsigned long SCAN_INTERVAL_MS = 200;
unsigned long lastScanAt = 0;

// Debounce for refreshing the idle clock display (no need to rewrite
// the LCD every loop iteration — once a second is plenty and avoids
// visible flicker on cheap I2C backpacks)
const unsigned long CLOCK_REFRESH_MS = 1000;
unsigned long lastClockRefreshAt = 0;

// How long a scan result stays on the LCD before reverting to the clock
const unsigned long DISPLAY_RESULT_DURATION_MS = 4000;
unsigned long displayResultShownAt = 0;
bool showingScanResult = false;


void setup() {
  Serial.begin(9600);
  while (!Serial) {
    // wait for serial on boards that need it (e.g. Leonardo)
  }

  // ---- LCD init ----
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Canteen Att.Sys");
  lcd.setCursor(0, 1);
  lcd.print("Starting...");

  // ---- RTC init ----
  rtc.Begin();
  if (rtc.GetIsWriteProtected()) {
    rtc.SetIsWriteProtected(false);
  }
  if (!rtc.GetIsRunning()) {
    rtc.SetIsRunning(true);
  }
  // If the RTC has never been set (e.g. brand new, dead/missing
  // battery), its date will read as invalid or far in the past. We
  // don't auto-set it to the compile time here, unlike many DS1302
  // tutorials — that approach silently resets the clock to a stale
  // build date on every re-upload, which is the wrong default for a
  // device that's supposed to track real attendance times. Instead,
  // we flag it and wait for the PC to send a SETTIME command, since
  // the PC's system clock is the more trustworthy source of truth
  // day-to-day.
  if (!rtc.IsDateTimeValid()) {
    Serial.println("RTC_FAIL");
  }

  // ---- Fingerprint sensor init ----
  fingerSerial.begin(57600);
  delay(50);

  if (finger.verifyPassword()) {
    Serial.println("READY");
  } else {
    Serial.println("ENROLL_FAIL:SENSOR_NOT_FOUND");
    // Keep going anyway — PC side will see no READY/MATCH and can alert.
  }

  finger.getParameters();

  lcd.clear();
}

void loop() {
  handleIncomingCommands();

  unsigned long now = millis();

  if (now - lastScanAt >= SCAN_INTERVAL_MS) {
    lastScanAt = now;
    checkForFingerprintMatch();
  }

  // If we're showing a scan result, check whether it's time to revert
  // to the idle clock. Otherwise, keep the clock refreshed.
  if (showingScanResult) {
    if (now - displayResultShownAt >= DISPLAY_RESULT_DURATION_MS) {
      showingScanResult = false;
      lcd.clear();
      lastClockRefreshAt = 0; // force an immediate clock redraw
    }
  } else if (now - lastClockRefreshAt >= CLOCK_REFRESH_MS) {
    lastClockRefreshAt = now;
    showIdleClock();
  }
}

// Reads one line of text from Serial (PC side), if available, and
// dispatches it to the right handler. Non-blocking.
void handleIncomingCommands() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  if (line == "PING") {
    Serial.println("PONG");
  } else if (line.startsWith("ENROLL:")) {
    int id = line.substring(7).toInt();
    enrollFingerprint(id);
  } else if (line.startsWith("DELETE:")) {
    int id = line.substring(7).toInt();
    deleteFingerprint(id);
  } else if (line.startsWith("DISPLAY:")) {
    handleDisplayCommand(line.substring(8));
  } else if (line.startsWith("SETTIME:")) {
    handleSetTimeCommand(line.substring(8));
  }
}

// Parses "IN:23:08:03" (already stripped of the "DISPLAY:" prefix)
// and shows it on the LCD for DISPLAY_RESULT_DURATION_MS milliseconds.
void handleDisplayCommand(String payload) {
  int firstColon = payload.indexOf(':');
  int secondColon = payload.indexOf(':', firstColon + 1);
  if (firstColon == -1 || secondColon == -1) return; // malformed, ignore

  String eventType = payload.substring(0, firstColon);
  String idStr = payload.substring(firstColon + 1, secondColon);
  String timeStr = payload.substring(secondColon + 1);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("ID #");
  lcd.print(idStr);
  lcd.print(" ");
  lcd.print(eventType); // "IN" or "OUT"

  lcd.setCursor(0, 1);
  lcd.print(timeStr);

  showingScanResult = true;
  displayResultShownAt = millis();
}

// Parses "2026-06-23:14:32:07" and sets the RTC to that date/time.
// Used so the PC's system clock (which the admin can trust to be
// correct) can correct the RTC — e.g. on first setup, or if the
// RTC's backup battery died and it lost track of time.
void handleSetTimeCommand(String payload) {
  // Expected format: YYYY-MM-DD:HH:MM:SS
  if (payload.length() < 19) return; // malformed, ignore

  String datePart = payload.substring(0, 10);   // "2026-06-23"
  String timePart = payload.substring(11);        // "14:32:07"

  int year = datePart.substring(0, 4).toInt();
  int month = datePart.substring(5, 7).toInt();
  int day = datePart.substring(8, 10).toInt();
  int hour = timePart.substring(0, 2).toInt();
  int minute = timePart.substring(3, 5).toInt();
  int second = timePart.substring(6, 8).toInt();

  RtcDateTime newTime(year, month, day, hour, minute, second);
  rtc.SetDateTime(newTime);
}

// Draws the current date/time on the LCD. Only called when we're not
// mid-way through showing a scan result.
void showIdleClock() {
  if (!rtc.IsDateTimeValid()) {
    lcd.setCursor(0, 0);
    lcd.print("RTC not set!    ");
    lcd.setCursor(0, 1);
    lcd.print("Set time via PC ");
    return;
  }

  RtcDateTime now = rtc.GetDateTime();

  char dateBuf[17];
  snprintf(dateBuf, sizeof(dateBuf), "%04u-%02u-%02u    ",
           now.Year(), now.Month(), now.Day());

  char timeBuf[17];
  snprintf(timeBuf, sizeof(timeBuf), "%02u:%02u:%02u  Ready",
           now.Hour(), now.Minute(), now.Second());

  lcd.setCursor(0, 0);
  lcd.print(dateBuf);
  lcd.setCursor(0, 1);
  lcd.print(timeBuf);
}

// Polls the sensor for a finger. If present, attempts to capture +
// search the fingerprint library. Reports MATCH:<id> or NOMATCH.
void checkForFingerprintMatch() {
  uint8_t result = finger.getImage();
  if (result != FINGERPRINT_OK) {
    // No finger present (most common case) or read error — just return.
    return;
  }

  result = finger.image2Tz();
  if (result != FINGERPRINT_OK) {
    return; // couldn't convert image to a usable template, skip silently
  }

  result = finger.fingerSearch();
  if (result == FINGERPRINT_OK) {
    Serial.print("MATCH:");
    Serial.println(finger.fingerID);
  } else {
    Serial.println("NOMATCH");
  }
}

// Two-scan enrollment process for a new fingerprint at the given ID slot.
void enrollFingerprint(int id) {
  if (id <= 0 || id > 127) {
    Serial.println("ENROLL_FAIL:INVALID_ID");
    return;
  }

  Serial.println("ENROLL_WAITING:PLACE_FINGER");
  if (!waitForFinger()) {
    Serial.println("ENROLL_FAIL:TIMEOUT");
    return;
  }

  if (finger.image2Tz(1) != FINGERPRINT_OK) {
    Serial.println("ENROLL_FAIL:IMAGE_ERROR");
    return;
  }

  Serial.println("ENROLL_WAITING:REMOVE_FINGER");
  delay(1500);
  while (finger.getImage() != FINGERPRINT_NOFINGER) {
    delay(50);
  }

  Serial.println("ENROLL_WAITING:PLACE_FINGER_AGAIN");
  if (!waitForFinger()) {
    Serial.println("ENROLL_FAIL:TIMEOUT");
    return;
  }

  if (finger.image2Tz(2) != FINGERPRINT_OK) {
    Serial.println("ENROLL_FAIL:IMAGE_ERROR");
    return;
  }

  if (finger.createModel() != FINGERPRINT_OK) {
    Serial.println("ENROLL_FAIL:PRINTS_DID_NOT_MATCH");
    return;
  }

  if (finger.storeModel(id) != FINGERPRINT_OK) {
    Serial.println("ENROLL_FAIL:STORAGE_ERROR");
    return;
  }

  Serial.print("ENROLL_OK:");
  Serial.println(id);
}

// Blocks (with timeout) until a finger is detected and an image captured.
bool waitForFinger() {
  unsigned long start = millis();
  const unsigned long timeoutMs = 10000; // 10 second timeout

  while (millis() - start < timeoutMs) {
    uint8_t result = finger.getImage();
    if (result == FINGERPRINT_OK) {
      return true;
    }
    delay(100);
  }
  return false;
}

void deleteFingerprint(int id) {
  uint8_t result = finger.deleteModel(id);
  if (result == FINGERPRINT_OK) {
    Serial.print("DELETE_OK:");
    Serial.println(id);
  } else {
    Serial.print("DELETE_FAIL:");
    Serial.println(id);
  }
}
