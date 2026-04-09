/*
 * Arduino Mega #1 button input
 * Key range: 1-44
 * MIDI range: 21-64 (A0-E4)
 */

const int BUTTON_COUNT = 44;
const int MIDI_START = 21;  // A0

// Use Mega digital pins 2-45 for 44 buttons.
const int buttonPins[] = {
  2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
  14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
  26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37,
  38, 39, 40, 41, 42, 43, 44, 45
};

int lastReading[BUTTON_COUNT];
int buttonState[BUTTON_COUNT];
unsigned long lastDebounceTime[BUTTON_COUNT];
unsigned long lastPressTime[BUTTON_COUNT];

const unsigned long debounceDelay = 5;
const unsigned long minPressInterval = 10;

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < BUTTON_COUNT; i++) {
    pinMode(buttonPins[i], INPUT_PULLUP);
    lastReading[i] = digitalRead(buttonPins[i]);
    buttonState[i] = lastReading[i];
    lastDebounceTime[i] = 0;
    lastPressTime[i] = 0;
  }

  Serial.print("READY - Arduino Mega #1 - MIDI ");
  Serial.print(MIDI_START);
  Serial.print("-");
  Serial.println(MIDI_START + BUTTON_COUNT - 1);
}

void loop() {
  unsigned long now = millis();

  for (int i = 0; i < BUTTON_COUNT; i++) {
    int reading = digitalRead(buttonPins[i]);

    if (reading != lastReading[i]) {
      lastDebounceTime[i] = now;
    }

    if ((now - lastDebounceTime[i]) > debounceDelay) {
      if (reading != buttonState[i]) {
        buttonState[i] = reading;

        if (buttonState[i] == LOW) {
          if ((now - lastPressTime[i]) >= minPressInterval) {
            Serial.print("NOTE_ON:");
            Serial.println(MIDI_START + i);
            lastPressTime[i] = now;
          }
        } else {
          Serial.print("NOTE_OFF:");
          Serial.println(MIDI_START + i);
        }
      }
    }

    lastReading[i] = reading;
  }
}
