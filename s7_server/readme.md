# Siemens S7 PLC 協議模擬器 (Snap7)

本專案是一個基於 Python 的工業級 **Siemens S7 通訊協議** 模擬器。利用 `python-snap7` 庫構建，模擬真實 PLC 的記憶體配置（DB, I, Q, M），並內建馬達物理引擎與**故障安全連鎖 (Safety Interlock)** 邏輯。

## 1. 系統規格
* **通訊協定**: Siemens S7 Communication (S7Comm)
* **預設通訊埠**: `6002` (若權限不足則自動降級至標準 `102`)
* **資料格式**: Big-Endian (大端序)

## 2. 配置與支援區域
模擬器根據 `config.yaml` 分配區域：
* **PE**: 輸入 (I 區)
* **PA**: 輸出 (Q 區)
* **MK**: 標記 (M 區)
* **DB**: 資料塊 (支援 DB1, DB2 等)

## 3. 模擬邏輯說明
* **馬達物理**: 模擬 `Q0.0` 啟動後的運行回授。
* **故障機制**: 監控 `M100.0`。若觸發，則強制清除所有 `Q` 輸出並在 `DB1.DBW10` 顯示故障碼 `999`。

## 4. 位址映射 (Mapping)
| 功能 | 位址 | 類型 | 
| :--- | :--- | :--- |
| 馬達控制 | Q0.0 | Bool |
| 故障模擬 | M100.0 | Bool |
| 溫度數據 | DB1.DBD0 | Real |
| 轉速數據 | DB1.DBW4 | Int |
| 故障代碼 | DB1.DBW10 | Int |

## 5. 快速開始
1. 安裝必要組件：`pip install setuptools python-snap7 pyyaml`
2. 確保系統已安裝 `snap7` 核心庫 (`libsnap7-dev`)。
3. 執行 `python main.py`。
4. 使用 HMI 或 Client 工具連線至 `127.0.0.1:6002`。