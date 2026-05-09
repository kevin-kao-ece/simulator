# Modbus TCP 馬達模擬器

本專案是一個基於 Python 的 **Modbus TCP** 馬達模擬器。

## 1. 系統規範
* **通訊協定**: Modbus TCP
* **通訊埠 (Port)**: `16001`
* **模式**: 單執行緒 Server + 背景模擬執行緒（每 100 ms 更新）
* **位元組順序 (Endianness)**:
  * Modbus register 本身是 16-bit word
  * 本模擬器將數值以 **Little-Endian bytes** 填入連續 holding registers

## 2. 配置的設備記憶體 (Device Memory)

### 位元（Bit）
* **Coil 0**: `Motor_Control`（啟動/停止命令）
  * 讀取：**FC01 Read Coils**（起始位址 0，數量 1）
  * 寫入：**FC05 Write Single Coil**（位址 0，值 0/1）或 **FC15 Write Multiple Coils**
* **Discrete Input 0**: `Motor_Run`（運轉回授，1=運轉中，0=停止）
  * 讀取：**FC02 Read Discrete Inputs**（起始位址 0，數量 1）
* **Discrete Input 10**: `Motor_Fault`（故障位，RPM > 1800 置位）
  * 讀取：**FC02 Read Discrete Inputs**（起始位址 10，數量 1）

### Holding Registers（0-based address）
| Holding Register | 功能 | 資料型態 | 說明 |
| :--- | :--- | :--- | :--- |
| **HR 0** | `Legacy_Start_Mirror` | uint16(bitmask) | bit0=1 視為啟動命令，會同步到 Coil 0（讀寫用 FC03/06/16） |
| **HR 10–11** | `Current_RPM` | float32 (2 regs) | 目前轉速 RPM（以 little-endian bytes 存放於兩個連續暫存器；讀取用 FC03） |
| **HR 12–13** | `Current_Amps` | float32 (2 regs) | 目前電流 Amps（little-endian bytes；FC03） |
| **HR 14** | `Target_RPM` | uint16 (1 reg) | 目標轉速 Target RPM（寫入用 FC06/16） |
| **HR 15** | `ErrScaled` | int16 (1 reg) | 轉速誤差×100：\((target-rpm)\times100\)（FC03） |
| **HR 16–17** | `Runtime_Ticks` | uint32 (2 regs) | Tick 計數（100 ms / tick；FC03） |
| **HR 18–19** | `Encoder` | int32 (2 regs) | Encoder 演示值（FC03） |
| **HR 20–23** | `Energy_kWh` | float64 (4 regs) | 累積電能 kWh（演示；FC03） |
| **HR 24** | `BusV_x10` | uint16 (1 reg) | DC Bus 電壓×10（演示；FC03） |
| **HR 25** | `RPM_BCD` | uint16 (1 reg) | RPM 的 BCD 四位數（0–9999；FC03） |

> Holding Registers 的讀寫對應 Modbus Function Code：**FC03/FC06/FC16**。

## 3. 模擬馬達邏輯 (Simulated Motor Logic)
* **初始狀態**: 預設 **Coil 0 = 1（ON）**，目標轉速 **HR14 = 1200**
* **加速 / 減速（每 100 ms）**:
  * 啟動加速：每 tick 約 `+50.5` RPM，直到達到目標轉速
  * 停止減速：每 tick 約 `-30.2` RPM，降到 0 後 `Motor_Run` 變為 0
* **故障**: 若 RPM > `1800`，則 `Motor_Fault=1`，否則為 0

## 4. 技術實作說明
* 使用 `pymodbus 2.5.x` 的 `StartTcpServer`（sync）啟動 Modbus TCP
* 背景執行緒定期更新 coils/discrete inputs/holding registers，並保留 HR0 bit0 作為 legacy start mirror

## 5. 快速開始
1. 安裝依賴：`pip install -r requirements.txt`
2. 啟動模擬器：`python main.py`
3. 客戶端連線至 `127.0.0.1:16001`，讀寫 coils / discrete inputs / holding registers

### Docker / Compose
* Build/Run:
  * `docker build -t modbus-server:1.0 .`
  * `docker run --rm -p 16001:16001 modbus-server:1.0`
* Compose:
  * `docker compose up -d --build`
