# Siemens S7 PLC 協議模擬器 (Snap7)

本專案是一個基於 Python 的工業級 **Siemens S7 通訊協議** 模擬器。利用 `python-snap7` 庫構建，模擬真實 PLC 的記憶體配置（DB, I, Q, M），並內建與 `melsec_server` 一致的**馬達物理引擎**與**過載故障 (Overload Trip)** 模擬邏輯。

## 1. 系統規格
* **通訊協定**: Siemens S7 Communication (S7Comm)
* **預設通訊埠**: `6002` (若權限不足則自動降級至標準 `102`)
* **資料格式**: Big-Endian (大端序，符合西門子標準)
* **運行環境**: 支援 Python 3.12+ (需配合特定 setuptools 版本)

## 2. 配置與支援區域
模擬器根據 `config.yaml` 分配區域：
* **PE**: 輸入 (I 區)
* **PA**: 數位量輸出 (Q 區) —— 馬達啟動指令在此接收
* **MK**: 內部輔助接點 (M 區) —— 故障觸發點
* **DB**: 資料塊 —— 存放感測器數據與狀態回饋

## 3. 模擬邏輯說明（對齊 `melsec_server`）
* **初始狀態**:
- 預設 **Q0.0 = 1（ON）**，啟動後馬達會自動運轉。
- 預設目標轉速 **DB1.DBW28 = 1200**。
* **控制 / 回授（對應 MELSEC: Y0 / X0）**:
- **Q0.0**：啟動/停止命令（等同 `melsec_server` 的 **Y0**）。
- **I0.0**：運轉回授（等同 `melsec_server` 的 **X0**；運轉中=1、停止=0）。
* **轉速斜率（每 100 ms 更新）**:
- 啟動時加速：每 tick 約 `+50.5` RPM，直到達到目標轉速。
- 停止時減速：每 tick 約 `-30.2` RPM，降到 0 後回授 I0.0 變為 0。
* **過載故障（對應 MELSEC: M10）**:
- 若 RPM > `1800`，則置位 **M10.0**（Merker）為 1；否則為 0。


## 4. 位址映射 (Mapping)
| 功能 | 位址 | 類型 | 預設值 | 說明
| :--- | :--- | :--- | :--- | :--- |
| 馬達啟動控制（Y0） | Q0.0 | Bool | True | 寫入 1 啟動、寫入 0 停止
| 運轉回授（X0） | I0.0 | Bool | False | 運轉中=1、停止=0
| 過載故障（M10） | M10.0 | Bool | False | RPM > 1800 置位
| 目標轉速（D14） | DB1.DBW28 | UInt16 | 1200 | 目標 RPM
| 目前轉速（D10..D11） | DB1.DBD20 | Real | 0.0 | FLOAT32（4 bytes）
| 目前電流（D12..D13） | DB1.DBD24 | Real | 0.0 | FLOAT32（4 bytes）
| 轉速誤差×100（D15） | DB1.DBW30 | Int16 | 0 | 有號 16-bit
| Tick 計數（D16..D17） | DB1.DBD32 | UInt32 | 0 | 無號 32-bit
| Encoder（D18..D19） | DB1.DBD36 | Int32 | 0 | 有號 32-bit
| 累積電能 kWh（D20..D23） | DB1.DBD40 | Real64 | 0.0 | FLOAT64（8 bytes）
| DC Bus 電壓×10（D24） | DB1.DBW48 | UInt16 | 0 | 演示用
| RPM BCD（D25） | DB1.DBW50 | UInt16 | 0 | 0–9999 以 4 digits BCD
| 鏡射目標轉速（W100） | DB1.DBW200 | UInt16 | - | 演示用 mirror
| TN0（演示） | DB1.DBW300 | UInt16 | - | 低 16-bit tick
| CN0（演示） | DB1.DBW302 | UInt16 | - | 依轉速遞增
| TS0（演示） | M0.0 | Bool | - | 約 5s ON / 5s OFF

## 5. 快速開始
1. 安裝依賴：`pip install -r requirements.txt`
2. 確保系統已可載入 Snap7 原生函式庫（依平台安裝/設定）。
3. 執行：`python main.py`
4. 使用 HMI 或 Client 工具連線至 `127.0.0.1:6002`