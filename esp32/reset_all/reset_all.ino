#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ESP32-WROOM-32 預設 I2C 腳位
#define SDA_PIN 21
#define SCL_PIN 22

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  pwm.begin();
  pwm.setPWMFreq(60);
  
  // 個別設定每個通道的角度 (歸零)
  pwm.setPWM(0, 0, map(0, 0, 180, 600, 150));   // 通道 0
  pwm.setPWM(1, 0, map(0, 0, 180, 150, 600));   // 通道 1黑
  pwm.setPWM(2, 0, map(0, 0, 180, 600, 150));   // 通道 2
  pwm.setPWM(3, 0, map(0, 0, 180, 150, 600));   // 通道 3黑
  pwm.setPWM(4, 0, map(0, 0, 180, 600, 150));   // 通道 4
  pwm.setPWM(5, 0, map(0, 0, 180, 600, 150));   // 通道 5
  pwm.setPWM(6, 0, map(0, 0, 180, 150, 600));   // 通道 6黑
  pwm.setPWM(7, 0, map(0, 0, 180, 600, 150));   // 通道 7
  pwm.setPWM(8, 0, map(0, 0, 180, 600, 150));   // 通道 8
  pwm.setPWM(9, 0, map(0, 0, 180, 600, 150));   // 通道 9
  pwm.setPWM(10, 0, map(0, 0, 180, 150, 600));  // 通道 10黑
  pwm.setPWM(11, 0, map(0, 0, 180, 600, 150));  // 通道 11
  
}

void loop() {}
