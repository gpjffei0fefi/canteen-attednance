/*
  Canteen Attendance System — Fingerprint Scanner Firmware
  ----------------------------------------------------------
  Hardware: Arduino Uno/Nano + Optical Fingerprint Sensor
            (Adafruit Fingerprint Sensor / FPM10A / R305 / R307 — all
            compatible, they share the same UART protocol family)

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

  Wiring (Arduino Uno/Nano — uses SoftwareSerial since these boards
  only have one hardware serial port, which is reserved for USB/PC
  communication):

      Sensor Pin      Arduino Pin
      ----------      -----------
      VCC             5V   (check your module's datasheet — some need 3.3V)
      GND             GND
      TX              Pin 2 (Arduino RX)
      RX              Pin 3 (Arduino TX)

  See docs/WIRING.md in the repo for a full diagram and notes on
  power quirks.

  Serial protocol (Arduino <-> PC), 9600 baud:
    PC -> Arduino:
      ENROLL:<id>        start enrollment for the given slot ID
      DELETE:<id>         delete a stored fingerprint
      PING                health check, Arduino replies "PONG"

    Arduino -> PC:
      MATCH:<id>          fingerprint matched, here's the ID
      NOMATCH              finger scanned but no match found
      ENROLL_OK:<id>       enrollment succeeded for that ID
      ENROLL_FAIL:<reason> enrollment failed
      PONG                 reply to PING
      READY                sent once at startup when sensor is online
*/

#include <Adafruit_Fingerprint.h>
#include <SoftwareSerial.h>

// ---- Pin configuration ----
// Sensor TX -> Arduino pin 2 (this is the Arduino's RX)
// Sensor RX -> Arduino pin 3 (this is the Arduino's TX)
SoftwareSerial fingerSerial(2, 3);
Adafruit_Fingerprint finger(&fingerSerial);

// Debounce / polling interval for checking the sensor
const unsigned long SCAN_INTERVAL_MS = 200;
unsigned long lastScanAt = 0;

void setup() {
  Serial.begin(9600);
  while (!Serial) {
    // wait for serial on boards that need it (e.g. Leonardo)
  }

  fingerSerial.begin(57600);
  delay(50);

  if (finger.verifyPassword()) {
    Serial.println("READY");
  } else {
    Serial.println("ENROLL_FAIL:SENSOR_NOT_FOUND");
    // Keep going anyway — PC side will see no READY/MATCH and can alert.
  }

  finger.getParameters();
}

void loop() {
  handleIncomingCommands();

  unsigned long now = millis();
  if (now - lastScanAt >= SCAN_INTERVAL_MS) {
    lastScanAt = now;
    checkForFingerprintMatch();
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
  }
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
