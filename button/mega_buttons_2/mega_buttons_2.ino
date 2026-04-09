/*
 * Arduino Mega #2 button input
 * Key range: 45-88
 * MIDI range: 65-108 (F4-C8)
 */

const int BUTTON_COUNT = 44;
const int MIDI_START = 65;  // F4

// Use Mega digital pins for 44 buttons.
// Special wiring:
//   C#7 -> pin 50
//   D#7 -> pin 52
//   G7  -> pin 51
const int buttonPins[] = {
  2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
  14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
  26, 27, 28, 29, 30, 31, 32, 33, 50, 35, 52, 37,
  38, 39, 51, 41, 42, 43, 44, 45
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

  Serial.print("READY - Arduino Mega #2 - MIDI ");
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
            Serial.print(MIDI_START + i);
            Serial.print(":PIN:");
            Serial.println(buttonPins[i]);
            lastPressTime[i] = now;
          }
        } else {
          Serial.print("NOTE_OFF:");
          Serial.print(MIDI_START + i);
          Serial.print(":PIN:");
          Serial.println(buttonPins[i]);
        }
      }
    }

    lastReading[i] = reading;
  }
}
