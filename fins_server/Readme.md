# FINS Server（OMRON FINS UDP）模擬器

本專案提供一個以 Python 實作的 **OMRON FINS（UDP）** 模擬器，支援基本的 **記憶體區讀取/寫入**（Memory Area Read `0101` / Memory Area Write `0102`）。模擬器內建一組馬達背景邏輯，會持續更新 DM/CIO 等區域資料，方便 HMI/SCADA 或客戶端程式進行整合測試。

## 1. 系統規範
* **通訊協定**：OMRON FINS / UDP
* **通訊埠**：`16004`（預設；由 `config.yaml` 控制）
* **支援區域（Word/Bit）**：`D`、`CIO`、`W`、`H`、`E0`（可在 `config.yaml` 調整 Area Code）
* **更新頻率**：馬達背景邏輯每 `0.1s` 更新一次（見 `main.py`）

## 2. 配置的設備記憶體 (Device Memory)

模擬器啟動時會讀取同目錄的 `config.yaml`，用來設定：
* `network.host` / `network.port`
* `areas.*`：各區域的 Word/Bit Area Code
* `simulator.init.*`：啟動時的預設狀態
* `simulator.demo.*`：示範資料預載（demo）

## 3. 模擬馬達邏輯 (Simulated Motor Logic)

### Bits（CIO bit area）
* **CIO 0.0**：`Motor_Start`（啟動/停止命令）
* **CIO 0.1**：`Motor_Run`（運轉回授）
* **CIO 0.10**：`Motor_Fault`（故障位；RPM > 1800）

同時保留相容/鏡射行為（legacy/mirror）：
* **D0.0**（DM bit）會被視為啟動/停止命令，並鏡射到 CIO 0.0
* **D3.0**（DM bit）會鏡射運轉回授（等同 CIO 0.1）

### Words（D area；對齊 `D10..D25` 語意）
* **D10..D11**：目前轉速 RPM（`float32`）
* **D12..D13**：目前電流 Amps（`float32`）
* **D14**：目標轉速 Target RPM（`uint16`）
* **D15**：轉速誤差 ×100（`int16`，\((target - rpm) \times 100\)）
* **D16..D17**：運轉 tick 計數（`uint32`）
* **D18..D19**：Encoder 演示值（`int32`）
* **D20..D23**：累積電能 kWh（`float64`）
* **D24**：DC Bus 電壓×10（`uint16`）
* **D25**：RPM BCD（`uint16`，0..9999）

## 4. 技術實作說明
* **指令**：Memory Area Read=`0101`、Memory Area Write=`0102`
* **封包位址格式**：`<Area Code 1B> <Word Address 2B> <Bit Address 1B> <Count 2B>`
* **位址解析**：FINS 封包中的 `Word Address` 以 Big-Endian 解析（`start_addr` 用 `>H`）
* **數值編碼注意**：為了配合既有測試/解析方式，部分跨多個 word 的數值在 DM buffer 內以 **Little-Endian bytes** 寫入（例如 `struct.pack('<f', ...)`）
* **參考資料**：`readmem.md` 提供更完整的 OMRON Memory Area Code / 資料型別整理

## 5. 快速開始
1. 安裝依賴：`pip install -r requirements.txt`
2. 啟動模擬器：`python main.py`
3. 客戶端以 UDP 連線至 `127.0.0.1:16004`，可使用 `client.py` 做快速驗證

### Docker / Compose
* Build/Run:
  * `docker build -t fins-server:1.0 .`
  * `docker run --rm -p 16004:16004/udp fins-server:1.0`
* Compose:
  * `docker compose up -d --build`
