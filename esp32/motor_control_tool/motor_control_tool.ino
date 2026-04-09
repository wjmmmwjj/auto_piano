#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#define SDA_PIN 21
#define SCL_PIN 22

Adafruit_PWMServoDriver pwm[6] = {
  Adafruit_PWMServoDriver(0x40), Adafruit_PWMServoDriver(0x41),
  Adafruit_PWMServoDriver(0x42), Adafruit_PWMServoDriver(0x43),
  Adafruit_PWMServoDriver(0x44), Adafruit_PWMServoDriver(0x45)
};

const uint8_t PWM_BOARD_COUNT = 6;
const uint8_t PWM_ADDRESSES[PWM_BOARD_COUNT] = {0x40, 0x41, 0x42, 0x43, 0x44, 0x45};
bool pwmReady[PWM_BOARD_COUNT] = {false, false, false, false, false, false};
bool pwmWarned[PWM_BOARD_COUNT] = {false, false, false, false, false, false};

// Same 88-key mapping as the main firmware:
// {MIDI, board, channel, p0, p180, press_angle, release_angle}
int N[][7] = {
  {21, 0, 0, 600, 150, 30,  0},
  {22, 0, 1, 150, 600, 40,  0},
  {23, 0, 2, 600, 150, 30,  0},
  {24, 0, 3, 600, 150, 30,  0},
  {25, 0, 4, 150, 600, 40,  0},
  {26, 0, 5, 600, 150, 30,  0},
  {27, 0, 6, 150, 600, 40,  0},
  {28, 0, 7, 600, 150, 30,  0},
  {29, 0, 8, 600, 150, 30,  0},
  {30, 0, 9, 150, 600, 40,  0},
  {31, 0, 10, 600, 150, 30,  0},
  {32, 0, 11, 600, 150, 40,  0},
  {33, 0, 12, 600, 150, 30,  0},
  {34, 0, 13, 150, 600, 40,  0},
  {35, 0, 14, 600, 150, 30,  0},
  {36, 0, 15, 600, 150, 30,  0},
  {37, 1, 0, 150, 600, 40,  0},
  {38, 1, 1, 600, 150, 30,  0},
  {39, 1, 2, 150, 600, 40,  0},
  {40, 1, 3, 600, 150, 30,  0},
  {41, 1, 4, 600, 150, 30,  0},
  {42, 1, 5, 150, 600, 40,  0},
  {43, 1, 6, 600, 150, 30,  0},
  {44, 1, 7, 600, 150, 40,  0},
  {45, 1, 8, 600, 150, 30,  0},
  {46, 1, 9, 150, 600, 40,  0},
  {47, 1, 10, 600, 150, 30,  0},
  {48, 1, 11, 600, 150, 30,  0},
  {49, 1, 12, 150, 600, 40,  0},
  {50, 1, 13, 600, 150, 30,  0},
  {51, 1, 14, 150, 600, 40,  0},
  {52, 1, 15, 600, 150, 30,  0},
  {53, 2, 0, 600, 150, 30,  0},
  {54, 2, 1, 150, 600, 40,  0},
  {55, 2, 2, 600, 150, 30,  0},
  {56, 2, 3, 600, 150, 40,  0},
  {57, 2, 4, 600, 150, 30,  0},
  {58, 2, 5, 150, 600, 40,  0},
  {59, 2, 6, 600, 150, 30,  0},
  {60, 2, 7, 600, 150, 30,  0},
  {61, 2, 8, 150, 600, 40,  0},
  {62, 2, 9, 600, 150, 30,  0},
  {63, 2, 10, 150, 600, 40,  0},
  {64, 2, 11, 600, 150, 30,  0},
  {65, 2, 12, 600, 150, 30,  0},
  {66, 2, 13, 150, 600, 40,  0},
  {67, 2, 14, 600, 150, 30,  0},
  {68, 2, 15, 600, 150, 40,  0},
  {69, 3, 0, 600, 150, 30,  0},
  {70, 3, 1, 150, 600, 40,  0},
  {71, 3, 2, 600, 150, 30,  0},
  {72, 3, 3, 600, 150, 30,  0},
  {73, 3, 4, 150, 600, 40,  0},
  {74, 3, 5, 600, 150, 30,  0},
  {75, 3, 6, 150, 600, 40,  0},
  {76, 3, 7, 600, 150, 30,  0},
  {77, 3, 8, 600, 150, 30,  0},
  {78, 3, 9, 150, 600, 40,  0},
  {79, 3, 10, 600, 150, 30,  0},
  {80, 3, 11, 600, 150, 40,  0},
  {81, 3, 12, 600, 150, 30,  0},
  {82, 3, 13, 150, 600, 40,  0},
  {83, 3, 14, 600, 150, 30,  0},
  {84, 3, 15, 600, 150, 30,  0},
  {85, 4, 0, 150, 600, 40,  0},
  {86, 4, 1, 600, 150, 30,  0},
  {87, 4, 2, 150, 600, 40,  0},
  {88, 4, 3, 600, 150, 30,  0},
  {89, 4, 4, 600, 150, 30,  0},
  {90, 4, 5, 150, 600, 40,  0},
  {91, 4, 6, 600, 150, 30,  0},
  {92, 4, 7, 600, 150, 40,  0},
  {93, 4, 8, 600, 150, 30,  0},
  {94, 4, 9, 150, 600, 40,  0},
  {95, 4, 10, 600, 150, 30,  0},
  {96, 4, 11, 600, 150, 30,  0},
  {97, 4, 12, 150, 600, 40,  0},
  {98, 4, 13, 600, 150, 30,  0},
  {99, 4, 14, 150, 600, 40,  0},
  {100, 4, 15, 600, 150, 30,  0},
  {101, 5, 0, 600, 150, 30,  0},
  {102, 5, 1, 150, 600, 40,  0},
  {103, 5, 2, 600, 150, 30,  0},
  {104, 5, 3, 600, 150, 40,  0},
  {105, 5, 4, 600, 150, 30,  0},
  {106, 5, 5, 150, 600, 40,  0},
  {107, 5, 6, 600, 150, 30,  0},
  {108, 5, 7, 600, 150, 30,  0},
};

const int NC = 88;

bool probePwmAddress(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

void printMissingPwmMessage(const char *level, int boardIndex) {
  Serial.print(level);
  Serial.print(":MISSING_PWM,");
  Serial.print(boardIndex);
  Serial.print(",0x");
  if (PWM_ADDRESSES[boardIndex] < 0x10) {
    Serial.print("0");
  }
  Serial.println(PWM_ADDRESSES[boardIndex], HEX);
}

void initializePwmBoards() {
  for (int i = 0; i < PWM_BOARD_COUNT; i++) {
    pwmReady[i] = probePwmAddress(PWM_ADDRESSES[i]);
    if (pwmReady[i]) {
      pwm[i].begin();
      pwm[i].setPWMFreq(60);
      Serial.print("INFO:PWM_READY,");
      Serial.print(i);
      Serial.print(",0x");
      if (PWM_ADDRESSES[i] < 0x10) {
        Serial.print("0");
      }
      Serial.println(PWM_ADDRESSES[i], HEX);
    } else {
      printMissingPwmMessage("WARN", i);
    }
  }
}

bool ensurePwmBoardReady(int boardIndex, bool errorMode) {
  if (boardIndex < 0 || boardIndex >= PWM_BOARD_COUNT) {
    Serial.println("ERR:BAD_PWM_BOARD");
    return false;
  }

  if (pwmReady[boardIndex]) {
    return true;
  }

  if (errorMode) {
    printMissingPwmMessage("ERR", boardIndex);
  } else if (!pwmWarned[boardIndex]) {
    printMissingPwmMessage("WARN", boardIndex);
    pwmWarned[boardIndex] = true;
  }

  return false;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);

  initializePwmBoards();

  Serial.println("TUNER_READY");
}

bool setMotor(int pitch, int angle) {
  for (int i = 0; i < NC; i++) {
    if (N[i][0] == pitch) {
      if (!ensurePwmBoardReady(N[i][1], true)) {
        return false;
      }
      pwm[N[i][1]].setPWM(N[i][2], 0, map(angle, 0, 180, N[i][3], N[i][4]));
      return true;
    }
  }

  Serial.println("ERR:UNKNOWN_MIDI");
  return false;
}

void loop() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  if (line == "PING" || line.startsWith("PING,")) {
    Serial.println("TUNER_READY");
    return;
  }

  if (line.startsWith("S,")) {
    int c1 = line.indexOf(',', 2);
    int pitch = line.substring(2, c1).toInt();
    int angle = line.substring(c1 + 1).toInt();
    if (setMotor(pitch, angle)) {
      Serial.println("OK");
    }
    return;
  }

  if (line.startsWith("H,")) {
    int c1 = line.indexOf(',', 2);
    int c2 = line.indexOf(',', c1 + 1);
    int pitch = line.substring(2, c1).toInt();
    int releaseAngle = line.substring(c1 + 1, c2).toInt();
    int pressAngle = line.substring(c2 + 1).toInt();

    if (!setMotor(pitch, releaseAngle)) {
      return;
    }
    delay(200);
    if (!setMotor(pitch, pressAngle)) {
      return;
    }
    delay(200);
    if (setMotor(pitch, releaseAngle)) {
      Serial.println("OK");
    }
    return;
  }
}
