# EtherNet/IP（CIP Tag）Motor Simulator

本專案是一個以 Python + `cpppo` 實作的 **EtherNet/IP (CIP)** 模擬器，提供 Logix-like 的 **CIP Tag**（可被 HMI/SCADA/Client 讀寫）。  
此外內建馬達模擬邏輯：用啟動命令與目標轉速驅動，持續更新轉速/電流/能量等監控資料。

## 1. 系統規範
* **通訊協定**: EtherNet/IP (CIP) – Tag Read/Write
* **通訊埠 (Port)**: `16005`（預設；可在 `config.yaml` 調整）
* **更新頻率**: 每 `0.1s` 更新一次（`main.py` background logic）

## 2. 配置的設備記憶體 (Device Memory)

本模擬器以 **CIP Tag** 方式提供資料；可在 `config.yaml` 調整：

* `server.host` / `server.port`
* `simulator.*`（初始狀態、加減速、fault 門檻）
* `tags.*`（Tag 命名）

## 3. 模擬馬達邏輯 (Simulated Motor Logic)

### 控制 / 回授（CIP Tag）
* **`Motor_Control` (BOOL)**：啟動/停止命令
* **`Motor_Run` (BOOL)**：運轉回授
* **`Motor_Fault` (BOOL)**：故障位（預設規則：RPM > 1800 置位）

### 主要數值（對齊 `D10..D25` 語意）
* **`Target_Speed` (INT)**：目標 RPM（等同 D14）
* **`Current_Speed` (REAL)**：目前 RPM（float32；等同 D10..D11）
* **`Current_Amps` (REAL)**：目前電流（float32；等同 D12..D13）
* **`ErrScaled` (INT)**：\((Target\_Speed - Current\_Speed) \times 100\)（等同 D15）
* **`RuntimeTicks` (DINT)**：tick 計數（每 0.1s +1；等同 D16..D17）
* **`Encoder` (DINT)**：encoder 演示（等同 D18..D19）
* **`Energy_kWh` (LREAL)**：累積電能（float64；等同 D20..D23）
* **`BusV_x10` (INT)**：DC bus 電壓×10（等同 D24）
* **`RPM_BCD` (INT)**：RPM 的 4 digits BCD（等同 D25）

## 4. 技術實作說明
* `main.py` 會啟動 **Server thread**（CIP Tag server）與 **Logic thread**（client loop 回寫 tags）
* 背景邏輯以「像真客戶端一樣」透過 CIP Tag 讀/寫更新資料，不需依賴 cpppo 內部資料結構

> 操作方式提示：一般 client 會使用 CIP 的 Tag Read / Tag Write（以 tag 名稱讀寫），並依 tag 宣告型別（BOOL/INT/REAL/LREAL...）做解碼。

## 5. 快速開始
1. 安裝依賴：`pip install -r requirements.txt`
2. 啟動模擬器：`python main.py`
3. 使用 client 連線至 `127.0.0.1:16005` 讀寫 tags

### Docker / Compose
* Build/Run:
  * `docker build -t ethernet-ip-server:1.0 .`
  * `docker run --rm -p 16005:16005 ethernet-ip-server:1.0`
* Compose:
  * `docker compose up -d --build`
