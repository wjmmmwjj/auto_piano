# Auto Piano 硬體架構圖

本文件描述 Auto Piano 系統的硬體連接方式，包含演奏端（ESP32 + PCA9685 + 伺服馬達）與輸入端（Arduino Mega + 按鍵）。

## 整體架構

```mermaid
graph TB
    subgraph PC_Group["電腦 (Windows PC)"]
        PC["Python 主程式<br/>song_workflow.py / launcher.py / midi_bridge.py"]
    end

    subgraph Playback["演奏端 (Playback)"]
        ESP32["ESP32<br/>主控制器<br/>115200 baud"]
        subgraph PWM_Group["6 × PCA9685 PWM 驅動板"]
            P0["PCA9685 #0<br/>I2C 0x40"]
            P1["PCA9685 #1<br/>I2C 0x41"]
            P2["PCA9685 #2<br/>I2C 0x42"]
            P3["PCA9685 #3<br/>I2C 0x43"]
            P4["PCA9685 #4<br/>I2C 0x44"]
            P5["PCA9685 #5<br/>I2C 0x45"]
        end
        SERVO["88 顆伺服馬達<br/>對應 MIDI 21 ~ 108"]
    end

    subgraph Input["輸入端 (Input / 按鍵偵測)"]
        KEYS["88 顆鋼琴按鍵<br/>(實體琴鍵)"]
        MEGA1["Arduino Mega #1<br/>MIDI 21 ~ 64<br/>44 顆按鈕"]
        MEGA2["Arduino Mega #2<br/>MIDI 65 ~ 108<br/>44 顆按鈕"]
    end

    PSU["5V 30A 電源供應器<br/>(伺服主電源)"]

    PC <-->|"USB Serial 115200"| ESP32
    ESP32 -->|"I2C SDA / SCL"| P0
    ESP32 -->|"I2C SDA / SCL"| P1
    ESP32 -->|"I2C SDA / SCL"| P2
    ESP32 -->|"I2C SDA / SCL"| P3
    ESP32 -->|"I2C SDA / SCL"| P4
    ESP32 -->|"I2C SDA / SCL"| P5

    P0 -->|"PWM × 16ch"| SERVO
    P1 -->|"PWM × 16ch"| SERVO
    P2 -->|"PWM × 16ch"| SERVO
    P3 -->|"PWM × 16ch"| SERVO
    P4 -->|"PWM × 16ch"| SERVO
    P5 -->|"PWM × 16ch"| SERVO

    SERVO -.->|"機械敲擊"| KEYS
    KEYS -->|"按下 / 釋放"| MEGA1
    KEYS -->|"按下 / 釋放"| MEGA2
    MEGA1 -->|"USB Serial 115200"| PC
    MEGA2 -->|"USB Serial 115200"| PC

    PSU ==>|"V+ / GND"| SERVO
    PSU ==>|"V+ / GND"| P0
    PSU ==>|"V+ / GND"| P1
    PSU ==>|"V+ / GND"| P2
    PSU ==>|"V+ / GND"| P3
    PSU ==>|"V+ / GND"| P4
    PSU ==>|"V+ / GND"| P5

    classDef pcStyle fill:#dbeafe,stroke:#1e40af,stroke-width:2px,color:#0b1f4d
    classDef mcuStyle fill:#fde68a,stroke:#b45309,stroke-width:2px,color:#3b2200
    classDef pwmStyle fill:#bbf7d0,stroke:#15803d,stroke-width:1px,color:#053018
    classDef servoStyle fill:#fecaca,stroke:#b91c1c,stroke-width:2px,color:#450a0a
    classDef inputStyle fill:#e9d5ff,stroke:#6b21a8,stroke-width:2px,color:#2c0a4a
    classDef psuStyle fill:#fca5a5,stroke:#7f1d1d,stroke-width:3px,color:#1a0202

    class PC pcStyle
    class ESP32,MEGA1,MEGA2 mcuStyle
    class P0,P1,P2,P3,P4,P5 pwmStyle
    class SERVO servoStyle
    class KEYS inputStyle
    class PSU psuStyle
```

## 元件清單

| 元件 | 數量 | 用途 |
|------|------|------|
| Windows PC | 1 | 跑 Python 轉譜 / 播放管線（song_workflow.py、launcher.py、midi_bridge.py） |
| ESP32 | 1 | 主控制器，透過 USB Serial 115200 接收電腦命令，發送 I2C 給 PCA9685 |
| PCA9685 PWM 板 | 6 | I2C 位址 0x40 ~ 0x45，每塊 16 通道 PWM，共可驅動 96 顆伺服 |
| 伺服馬達 | 88 | 對應 MIDI 21 ~ 108，機械敲擊鋼琴鍵 |
| Arduino Mega | 2 | #1 偵測 MIDI 21 ~ 64、#2 偵測 MIDI 65 ~ 108，各 44 顆按鈕 |
| 5V 30A 電源供應器 | 1 | 提供伺服與 PCA9685 邏輯電源（共 88 顆伺服的尖峰電流） |

## 訊號流向

### 播放流程（PC → 鋼琴）
1. PC 上 Python 解析 SCORE / ESP32_LINES。
2. 透過 USB Serial（115200 baud）送 ON / OFF / WAIT 命令到 ESP32。
3. ESP32 用 I2C 對 6 塊 PCA9685 寫入 PWM duty。
4. PCA9685 輸出 PWM 訊號給 88 顆伺服。
5. 伺服旋轉到 press / release 角度，物理敲擊琴鍵。

### 輸入流程（鋼琴 → PC）
1. 使用者按下實體鍵。
2. Arduino Mega 用 INPUT_PULLUP + 防彈跳偵測。
3. 透過 USB Serial 把按鍵事件送回 PC。
4. midi_bridge.py 轉換為 MIDI 並輸出聲音。

## 電源注意事項

- **5V 30A 電源供應器** 只給伺服與 PCA9685 的 V+ 用，**不要**接到 ESP32 / Arduino 的邏輯電源（避免突波回灌）。
- ESP32 與 Arduino Mega 透過 USB 供電。
- 所有 GND 必須共地，PCA9685 的 V+ 與邏輯 VCC 分離。
- 88 顆伺服同時動作時的尖峰電流接近 30A，需確認電源線徑與接線端子能承受。
