/*
 * Arduino Mega pin tester for the highest key block.
 *
 * Upload this sketch to Mega #2, open Serial Monitor at 115200,
 * then press/release the suspect keys and watch which pins change.
 *
 * It monitors:
 * - Current high-note pins: 41, 42, 44, 45, 50, 51, 52
 * - Previous candidate pins for remapped notes: 34, 36, 40
 */

const int TEST_PIN_COUNT = 10;
const int LED_PIN = 13;

const int testPins[TEST_PIN_COUNT] = {
  34, 36, 40,
  41, 42, 44, 45,
  50, 51, 52
};

int lastState[TEST_PIN_COUNT];

void flashLed() {
  digitalWrite(LED_PIN, HIGH);
  delay(25);
  digitalWrite(LED_PIN, LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  for (int i = 0; i < TEST_PIN_COUNT; i++) {
    pinMode(testPins[i], INPUT_PULLUP);
    lastState[i] = digitalRead(testPins[i]);
  }

  Serial.println("MEGA_PIN_TESTER_READY");
  Serial.println("Watching pins: 34, 36, 40, 41, 42, 44, 45, 50, 51, 52");
}

void loop() {
  for (int i = 0; i < TEST_PIN_COUNT; i++) {
    int reading = digitalRead(testPins[i]);
    if (reading == lastState[i]) {
      continue;
    }

    lastState[i] = reading;

    Serial.print("PIN ");
    Serial.print(testPins[i]);
    Serial.print(" -> ");
    if (reading == LOW) {
      Serial.println("LOW (pressed)");
      flashLed();
    } else {
      Serial.println("HIGH (released)");
    }
  }
}
