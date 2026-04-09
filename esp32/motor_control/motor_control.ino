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

// {MIDI, board, channel, p0, p180, press_angle, release_angle}
int N[][7] = {
  {21, 0, 0, 600, 150, 27, 13},
  {22, 0, 1, 150, 600, 35, 13},
  {23, 0, 2, 600, 150, 22, 5},
  {24, 0, 3, 600, 150, 33, 15},
  {25, 0, 4, 150, 600, 35, 14},
  {26, 0, 5, 600, 150, 33, 11},
  {27, 0, 6, 150, 600, 50, 17},
  {28, 0, 7, 600, 150, 33, 18},
  {29, 0, 8, 600, 150, 31, 15},
  {30, 0, 9, 150, 600, 30, 5},
  {31, 0, 10, 600, 150, 33, 17},
  {32, 0, 11, 600, 150, 33, 10},
  {33, 0, 12, 600, 150, 45, 25},
  {34, 0, 13, 150, 600, 33, 13},
  {35, 0, 14, 600, 150, 38, 18},
  {36, 0, 15, 600, 150, 38, 17},
  {37, 1, 0, 150, 600, 17, 0},
  {38, 1, 1, 600, 150, 33, 12},
  {39, 1, 2, 150, 600, 38, 12},
  {40, 1, 3, 600, 150, 25, 2},
  {41, 1, 4, 600, 150, 25, 2},
  {42, 1, 5, 150, 600, 32, 6},
  {43, 1, 6, 600, 150, 32, 10},
  {44, 1, 7, 600, 150, 25, 8},
  {45, 1, 8, 600, 150, 33, 16},
  {46, 1, 9, 150, 600, 20, 0},
  {47, 1, 10, 600, 150, 25, 8},
  {48, 1, 11, 600, 150, 23, 10},
  {49, 1, 12, 150, 600, 45, 30},
  {50, 1, 13, 600, 150, 16, 0},
  {51, 1, 14, 150, 600, 28, 10},
  {52, 1, 15, 600, 150, 15, 0},
  {53, 2, 0, 600, 150, 20, 0},
  {54, 2, 1, 150, 600, 43, 25},
  {55, 2, 2, 600, 150, 18, 0},
  {56, 2, 3, 600, 150, 38, 20},
  {57, 2, 4, 600, 150, 19, 0},
  {58, 2, 5, 150, 600, 50, 30},
  {59, 2, 6, 600, 150, 20, 0},
  {60, 2, 7, 600, 150, 17, 0},
  {61, 2, 8, 150, 600, 30, 10},
  {62, 2, 9, 600, 150, 15, 0},
  {63, 2, 10, 150, 600, 36, 18},
  {64, 2, 11, 600, 150, 18, 0},
  {65, 2, 12, 600, 150, 23, 0},
  {66, 2, 13, 150, 600, 40, 18},
  {67, 2, 14, 600, 150, 15, 0},
  {68, 2, 15, 600, 150, 25, 5},
  {69, 3, 0, 600, 150, 28, 8},
  {70, 3, 1, 150, 600, 33, 8},
  {71, 3, 2, 600, 150, 25, 0},
  {72, 3, 3, 600, 150, 20, 0},
  {73, 3, 4, 150, 600, 30, 10},
  {74, 3, 5, 600, 150, 25, 0},
  {75, 3, 6, 150, 600, 35, 10},
  {76, 3, 7, 600, 150, 22, 0},
  {77, 3, 8, 600, 150, 20, 0},
  {78, 3, 9, 150, 600, 30, 5},
  {79, 3, 10, 600, 150, 18, 0},
  {80, 3, 11, 600, 150, 30, 15},
  {81, 3, 12, 600, 150, 17, 0},
  {82, 3, 13, 150, 600, 35, 15},
  {83, 3, 14, 600, 150, 25, 0},
  {84, 3, 15, 600, 150, 26, 0},
  {85, 4, 0, 150, 600, 20, 0},
  {86, 4, 1, 600, 150, 20, 0},
  {87, 4, 2, 150, 600, 20, 0},
  {88, 4, 3, 600, 150, 45, 10},
  {89, 4, 4, 600, 150, 45, 25},
  {90, 4, 5, 150, 600, 30, 0},
  {91, 4, 6, 600, 150, 30, 10},
  {92, 4, 7, 600, 150, 45, 15},
  {93, 4, 8, 600, 150, 40, 15},
  {94, 4, 9, 150, 600, 20, 0},
  {95, 4, 10, 600, 150, 30, 5},
  {96, 4, 11, 600, 150, 30, 0},
  {97, 4, 12, 150, 600, 40, 0},
  {98, 4, 13, 600, 150, 30, 0},
  {99, 4, 14, 150, 600, 40, 0},
  {100, 4, 15, 600, 150, 30, 0},
  {101, 5, 0, 600, 150, 30, 0},
  {102, 5, 1, 150, 600, 40, 0},
  {103, 5, 2, 600, 150, 30, 0},
  {104, 5, 3, 600, 150, 40, 0},
  {105, 5, 4, 600, 150, 30, 0},
  {106, 5, 5, 150, 600, 40, 0},
  {107, 5, 6, 600, 150, 30, 0},
  {108, 5, 7, 600, 150, 30, 0},

};

const int NC = 88;
const int SAFE_ZERO_DEFAULT_DELAY_MS = 40;
const int SAFE_ZERO_SETTLE_MS = 400;

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

bool ensurePwmBoardReady(int boardIndex) {
  if (boardIndex < 0 || boardIndex >= PWM_BOARD_COUNT) {
    Serial.println("WARN:BAD_PWM_BOARD");
    return false;
  }

  if (pwmReady[boardIndex]) {
    return true;
  }

  if (!pwmWarned[boardIndex]) {
    printMissingPwmMessage("WARN", boardIndex);
    pwmWarned[boardIndex] = true;
  }

  return false;
}

void hit(int m) {
  for(int i = 0; i < NC; i++) {
    if(N[i][0] == m) {
      if (!ensurePwmBoardReady(N[i][1])) {
        return;
      }
      pwm[N[i][1]].setPWM(N[i][2], 0, map(N[i][5], 0, 180, N[i][3], N[i][4]));
      return;
    }
  }
}

void rst(int m) {
  for(int i = 0; i < NC; i++) {
    if(N[i][0] == m) {
      if (!ensurePwmBoardReady(N[i][1])) {
        return;
      }
      pwm[N[i][1]].setPWM(N[i][2], 0, map(N[i][6], 0, 180, N[i][3], N[i][4]));
      return;
    }
  }
}

void slowResetAllKeys(int perKeyDelayMs) {
  perKeyDelayMs = clampInt(perKeyDelayMs, 5, 200);
  for(int i = 0; i < NC; i++) {
    rst(N[i][0]);
    delay(perKeyDelayMs);
  }
  delay(SAFE_ZERO_SETTLE_MS);
}

bool isIntToken(String token) {
  token.trim();
  if(token.length() == 0) return false;
  int i = 0;
  if(token[0] == '-') i = 1;
  if(i >= token.length()) return false;
  for(; i < token.length(); i++) {
    if(!isDigit(token[i])) return false;
  }
  return true;
}

int clampInt(int value, int low, int high) {
  if(value < low) return low;
  if(value > high) return high;
  return value;
}

String normalizeLine(String line) {
  line.trim();
  line.replace("\r", "");
  line.replace("\t", "");
  line.replace(" ", "");
  line.replace("(", "");
  line.replace(")", "");
  line.replace("[", "");
  line.replace("]", "");
  line.replace("{", "");
  line.replace("}", "");
  return line;
}

int parseNotesList(String text, int *notes, int maxNotes) {
  text = normalizeLine(text);
  int count = 0;
  String token = "";

  for(int i = 0; i <= text.length(); i++) {
    char ch = (i < text.length()) ? text[i] : ',';
    if(ch == '+' || ch == '|' || ch == ',' || ch == ';') {
      if(token.length() > 0 && count < maxNotes && isIntToken(token)) {
        notes[count++] = token.toInt();
      }
      token = "";
    } else {
      token += ch;
    }
  }

  return count;
}

bool applyNotesCommand(String text, bool pressedState) {
  int notes[50];
  int count = parseNotesList(text, notes, 50);
  if(count <= 0) {
    replyError("NO_NOTES");
    return false;
  }

  for(int i = 0; i < count; i++) {
    if(pressedState) hit(notes[i]);
    else rst(notes[i]);
  }

  Serial.println("OK");
  return true;
}

void buildLegacyArpOffsets(int count, int spread, int *offsets) {
  for(int i = 0; i < count; i++) {
    offsets[i] = i * spread;
  }
}

void playArp(int *notes, int count, int durationMs, int *pressOffsets, int releaseStepMs) {
  int pressEnd = pressOffsets[count - 1];
  int releaseSpan = releaseStepMs * (count - 1);
  int holdMs = durationMs - pressEnd - releaseSpan;
  if(holdMs < 0) holdMs = 0;

  int elapsed = 0;
  for(int i = 0; i < count; i++) {
    int waitMs = pressOffsets[i] - elapsed;
    if(waitMs > 0) delay(waitMs);
    elapsed = pressOffsets[i];
    hit(notes[i]);
  }

  delay(holdMs);

  for(int i = count - 1; i >= 0; i--) {
    rst(notes[i]);
    if(i > 0 && releaseStepMs > 0) delay(releaseStepMs);
  }
}

void replyError(const char *code) {
  Serial.print("ERR:");
  Serial.println(code);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);

  initializePwmBoards();

  slowResetAllKeys(SAFE_ZERO_DEFAULT_DELAY_MS);

  Serial.println("READY - 88 Keys");
}

void loop() {
  if(!Serial.available()) return;

  String l = normalizeLine(Serial.readStringUntil('\n'));
  if(l.length() == 0) return;

  String hand = "";
  if(l.length() >= 2 && (l.startsWith("L:") || l.startsWith("R:"))) {
    hand = l.substring(0, 1);
    l = l.substring(2);
  }

  if(l == "PING" || l.startsWith("PING,")) {
    Serial.println("READY");
    return;
  }

  if(l == "SAFEZERO" || l == "RESETALL" || l == "HOMEALL") {
    slowResetAllKeys(SAFE_ZERO_DEFAULT_DELAY_MS);
    Serial.println("OK");
    return;
  }

  if(l.startsWith("SAFEZERO,") || l.startsWith("RESETALL,") || l.startsWith("HOMEALL,")) {
    int commaIndex = l.indexOf(',');
    String msText = l.substring(commaIndex + 1);
    if(!isIntToken(msText)) {
      replyError("BAD_SAFEZERO_MS");
      return;
    }
    slowResetAllKeys(msText.toInt());
    Serial.println("OK");
    return;
  }

  int firstComma = l.indexOf(',');
  if(firstComma < 0) {
    replyError("BAD_FORMAT");
    return;
  }

  String head = l.substring(0, firstComma);
  String tail = l.substring(firstComma + 1);
  head.trim();
  tail.trim();

  if(head == "WAIT" || head == "REST" || head == "R" || head == "0") {
    if(!isIntToken(tail)) {
      replyError("BAD_MS");
      return;
    }
    delay(tail.toInt());
    Serial.println("OK");
    return;
  }

  if(head == "ON") {
    applyNotesCommand(tail, true);
    return;
  }

  if(head == "OFF") {
    applyNotesCommand(tail, false);
    return;
  }

  if(head == "NOTE" || head == "N" || head == "1") {
    int noteComma = tail.indexOf(',');
    if(noteComma < 0) {
      replyError("BAD_NOTE");
      return;
    }

    String noteText = tail.substring(0, noteComma);
    String msText = tail.substring(noteComma + 1);
    noteText.trim();
    msText.trim();

    if(!isIntToken(noteText) || !isIntToken(msText)) {
      replyError("BAD_NOTE");
      return;
    }

    int note = noteText.toInt();
    int ms = msText.toInt();
    hit(note);
    delay(ms);
    rst(note);
    Serial.println("OK");
    return;
  }

  if(head == "CHORD" || head == "C" || head == "3") {
    int chordComma = tail.lastIndexOf(',');
    if(chordComma < 0) {
      replyError("BAD_CHORD");
      return;
    }

    String notesPart = tail.substring(0, chordComma);
    String msText = tail.substring(chordComma + 1);
    notesPart.trim();
    msText.trim();

    if(!isIntToken(msText)) {
      replyError("BAD_MS");
      return;
    }

    int notes[50];
    int count = parseNotesList(notesPart, notes, 50);
    if(count <= 0) {
      replyError("NO_NOTES");
      return;
    }

    int ms = msText.toInt();
    for(int i = 0; i < count; i++) hit(notes[i]);
    delay(ms);
    for(int i = 0; i < count; i++) rst(notes[i]);
    Serial.println("OK");
    return;
  }

  if(head == "ARP" || head == "A" || head == "4") {
    int firstCommaTail = tail.indexOf(',');
    if(firstCommaTail < 0) {
      replyError("BAD_ARP");
      return;
    }

    String notesPart = tail.substring(0, firstCommaTail);
    String restPart = tail.substring(firstCommaTail + 1);
    int secondCommaTail = restPart.indexOf(',');
    if(secondCommaTail < 0) {
      replyError("BAD_ARP");
      return;
    }

    String msText = restPart.substring(0, secondCommaTail);
    String spreadOrOffsetsText = restPart.substring(secondCommaTail + 1);
    notesPart.trim();
    msText.trim();
    spreadOrOffsetsText.trim();

    if(!isIntToken(msText)) {
      replyError("BAD_ARP");
      return;
    }

    int notes[50];
    int count = parseNotesList(notesPart, notes, 50);
    if(count <= 0) {
      replyError("NO_NOTES");
      return;
    }

    int ms = msText.toInt();
    int offsets[50];
    int releaseStep = 15;

    int thirdCommaTail = spreadOrOffsetsText.indexOf(',');
    if(thirdCommaTail >= 0) {
      String offsetsText = spreadOrOffsetsText.substring(0, thirdCommaTail);
      String releaseText = spreadOrOffsetsText.substring(thirdCommaTail + 1);
      offsetsText.trim();
      releaseText.trim();

      if(!isIntToken(releaseText)) {
        replyError("BAD_ARP_RELEASE");
        return;
      }

      int parsedOffsets = parseNotesList(offsetsText, offsets, 50);
      if(parsedOffsets != count) {
        replyError("BAD_ARP_OFFSETS");
        return;
      }

      releaseStep = clampInt(releaseText.toInt(), 0, 120);
    } else {
      if(!isIntToken(spreadOrOffsetsText)) {
        replyError("BAD_ARP");
        return;
      }
      int spread = clampInt(spreadOrOffsetsText.toInt(), 10, 200);
      buildLegacyArpOffsets(count, spread, offsets);
      releaseStep = clampInt(spread / 2, 0, 80);
    }

    playArp(notes, count, ms, offsets, releaseStep);
    Serial.println("OK");
    return;
  }

  if(head.indexOf('+') >= 0 || head.indexOf('|') >= 0) {
    if(!isIntToken(tail)) {
      replyError("BAD_MS");
      return;
    }

    int notes[50];
    int count = parseNotesList(head, notes, 50);
    if(count <= 0) {
      replyError("NO_NOTES");
      return;
    }

    int ms = tail.toInt();
    for(int i = 0; i < count; i++) hit(notes[i]);
    delay(ms);
    for(int i = 0; i < count; i++) rst(notes[i]);
    Serial.println("OK");
    return;
  }

  if(isIntToken(head) && isIntToken(tail)) {
    int note = head.toInt();
    int ms = tail.toInt();
    hit(note);
    delay(ms);
    rst(note);
    Serial.println("OK");
    return;
  }

  replyError("BAD_FORMAT");
}



