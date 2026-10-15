// 激光云台 + 激光驱动（配套上位机 laser_strike/main.py）
// 协议（ASCII，每行以 \n 结尾）：
//   P<0-180>  设置水平舵机角度
//   T<0-180>  设置俯仰舵机角度
//   L1 / L0   激光 开/关
//   S         急停（回中心 + 关激光）
//
// 接线：
//   水平舵机信号 -> D9   俯仰舵机信号 -> D10
//   激光驱动(经MOS/三极管) -> D11
//   舵机电源独立 5V 供电，GND 与 Arduino 共地
#include <Servo.h>

Servo panServo;
Servo tiltServo;

const int PAN_PIN = 9;
const int TILT_PIN = 10;
const int LASER_PIN = 11;
const int PAN_CENTER = 90;
const int TILT_CENTER = 90;

String buf = "";

void setLaser(bool on) {
  digitalWrite(LASER_PIN, on ? HIGH : LOW);
}

void estop() {
  panServo.write(PAN_CENTER);
  tiltServo.write(TILT_CENTER);
  setLaser(false);
}

void setup() {
  Serial.begin(115200);
  panServo.attach(PAN_PIN);
  tiltServo.attach(TILT_PIN);
  pinMode(LASER_PIN, OUTPUT);
  estop();  // 上电默认：回中 + 关激光
  Serial.println("LASER_GIMBAL_READY");
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (buf.length() > 0) {
        char cmd = buf[0];
        if (cmd == 'P') {
          panServo.write(constrain(buf.substring(1).toInt(), 0, 180));
        } else if (cmd == 'T') {
          tiltServo.write(constrain(buf.substring(1).toInt(), 0, 180));
        } else if (cmd == 'L') {
          setLaser(buf == "L1");
        } else if (cmd == 'S') {
          estop();
        }
        buf = "";
      }
    } else {
      buf += c;
      if (buf.length() > 10) buf = "";
    }
  }
}
