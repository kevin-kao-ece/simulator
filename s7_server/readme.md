# Siemens S7 PLC 協議模擬器 (Snap7)

本專案是一個基於 Python 的工業級 **Siemens S7 通訊協議** 模擬器。利用 `python-snap7` 庫構建，模擬真實 PLC 的記憶體配置（DB, I, Q, M），並內建馬達物理引擎與**故障安全連鎖 (Safety Interlock)** 邏輯。

## 1. 系統規格
* **通訊協定**: Siemens S7 Communication (S7Comm)
* **預設通訊埠**: `6002` (若權限不足則自動降級至標準 `102`)
* **資料格式**: Big-Endian (大端序，符合西門子標準)
* **運行環境: 支援 Python 3.12+ (需配合特定 setuptools 版本)

## 2. 配置與支援區域
模擬器根據 `config.yaml` 分配區域：
* **PE**: 輸入 (I 區)
* **PA**: 數位量輸出 (Q 區) —— 馬達啟動指令在此接收
* **MK**: 內部輔助接點 (M 區) —— 故障觸發點
* **DB**: 資料塊 —— 存放感測器數據與狀態回饋

## 3. 模擬邏輯說明
* **馬達物理引擎**:
- 監控 Q0.0 (Motor Control) 指令。
- 指令為 True 時，轉速 (RPM) 逐漸升至 1500，溫度隨之升高。
- 指令為 False 時，轉速逐漸下降至 0。
* **故障安全連鎖 (Safety Interlock)**: 
- 監控 M100.0 (Fault Trigger)。
- 觸發時 (True)：強制清除所有 Q 輸出（馬達立即跳脫），轉速歸零，並在 DB1.DBW10 寫入故障碼 999。


## 4. 位址映射 (Mapping)
| 功能 | 位址 | 類型 | 預設值 | 說明
| :--- | :--- | :--- | :--- | :--- |
| 馬達啟動控制 | Q0.0 | Bool | False | 寫入 True 啟動馬達模擬
| 故障模擬觸發 | M100.0 | Bool | False | 寫入 True 進入故障安全模式
| 馬達運行回報 | DB1.DBX6.0 | BOOL | False | 反饋馬達實際運行狀態
| 馬達溫度數據 | DB1.DBD0 | Int | 25.0 | 隨運行時間與轉速變動
| 馬達轉速數據 | DB1.DBW2 | Int | 0 | 範圍 0 - 1500 RPM
| 系統故障代碼 | DB1.DBW10 | Int | 0 | 正常為 0，故障時為 999

## 5. 快速開始
1. 安裝必要組件：`pip install setuptools python-snap7 pyyaml`
2. 確保系統已安裝 `snap7` 核心庫 (`libsnap7-dev`)。
3. 執行 `python main.py`。
4. 使用 HMI 或 Client 工具連線至 `127.0.0.1:6002`。