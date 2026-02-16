# PCS Modbus TCP 模擬器說明文件

本模擬器模擬一台整合了 PV（太陽能）、Battery（電池儲能）、Load（負載監測）與 Backup（備援系統）功能的工業級 **PCS (Power Conversion System)**。

## 1. 系統通訊規範
* **通訊協定**: Modbus TCP
* **預設埠號**: `7002`
* **資料序 (Endianness)**: 32 位元數據 (U32/S32) 採用 **Big Endian** 格式（高位暫存器在前）。
* **更新頻率**: 每 3 秒執行一次邏輯運算與資料更新。

---

## 2. 暫存器清單 (Tag List)

### A. 即時電力與環境量測 (Read Only)
| 地址 (Addr) | Tag Name | 類型 | 單位與說明 |
| :--- | :--- | :--- | :--- |
| **4097 - 4099** | l1Voltage / Current / Power | U16 | L1 相電壓(0.1V), 電流(0.1A), 功率(1W) |
| **4101** | l1Frequency | U16 | L1 頻率 (0.01 Hz) |
| **4112 - 4114** | mppt1Voltage / Current / Power | U16 | MPPT 1 直流側參數 |
| **4124** | innerTemp | S16 | 內部溫度 (0.1 °C) |
| **4168** | pvTotalInputPower | U32 | PV 總輸入功率 (W) |
| **4890 - 4892** | Grid L1/L2/L3-N phase voltage | U16 | 電網各相電壓 (0.1V) |
| **4920** | Frequency of grid | U16 | 電網頻率 (0.01 Hz) |



### B. 電力總和與能源統計 (Read Only)
| 地址 (Addr) | Tag Name | 類型 | 單位與說明 |
| :--- | :--- | :--- | :--- |
| **5024** | Phase L1 watt of grid sum | S32 | L1 電網功率 (正：饋網, 負：買電) |
| **5026** | Phase L2 watt of grid sum | S32 | L2 電網功率 |
| **5028** | Phase L3 watt of grid sum | S32 | L3 電網功率 |
| **5030** | Phase L1 watt of load sum | S32 | L1 負載總有功功率 (W) |
| **5032** | Phase L2 watt of load sum | S32 | L2 負載總有功功率 (W) |
| **5034** | Phase L3 watt of load sum | S32 | L3 負載總有功功率 (W) |
| **5036** | Daily energy of load sum | U32 | 當日負載總消耗能量 (0.01 kWh) |
| **5038** | Monthly energy of load sum | U32 | 當月負載總消耗能量 (0.01 kWh) |
| **5040** | Accumulated energy of load sum | U32 | 累積負載總消耗能量 (0.01 kWh) |
| **5080** | PVI daily generating energy sum | U32 | PVI 當日發電量統計 |
| **5082** | PVI accumulated energy sum | U32 | PVI 累積發電量統計 |
| **5084** | Totally input DC watt sum | U32 | 直流側總輸入功率 (W) |

### C. 備援與電池監控 (Read Only)
| 地址 (Addr) | Tag Name | 類型 | 單位與說明 |
| :--- | :--- | :--- | :--- |
| **5044 - 5048** | Phase L1/L2/L3 watt sum of Backup | S32 | 備援輸出有功功率 (W) |
| **5050 - 5054** | Phase L1/L2/L3 apparent power Backup | U32 | 備援輸出視在功率 (VA) |
| **5056** | Daily support energy sum to Backup | U32 | 當日備援供電累計 |
| **5058** | Accumulated support energy sum to Backup | U32 | 累積備援供電累計 |
| **5086** | Battery power sum | S32 | 電池總功率 (正：充電, 負：放電) |
| **5088** | Battery daily charge energy | U32 | 電池當日充電量 |
| **5090** | Battery accumulated charge energy | U32 | 電池累積充電量 |
| **5092** | Battery daily discharge energy | U32 | 電池當日放電量 |
| **5094** | Battery accumulated discharge energy | U32 | 電池累積放電量 |
| **8192** | Battery SOC | U16 | 剩餘電量百分比 (0.1%) |
| **8193** | Battery temperature | S16 | 電池溫度 (0.1 °C) |
| **8198** | Battery voltage | U16 | 電池總電壓 (0.1V) |
| **8199** | Battery current | S32 | 電池總電流 (0.01A) |
| **8201** | Battery power S32 | S32 | 電池即時功率 (W) |
| **8211** | Battery maximum cycles times | U16 | 電池最高循環次數 |
| **8214** | Battery average SOH | U16 | 平均健康度 (1%) |
| **8215** | Battery maximum cell voltage | U16 | 最高單體電壓 (mV) |
| **8216** | number of maximum cell voltage | U16 | 最高電壓單體編號 |
| **8217** | Battery minimum cell voltage | U16 | 最低單體電壓 (mV) |
| **8218** | number of minimum cell voltage | U16 | 最低電壓單體編號 |
| **8219** | Battery average cell temperature | S16 | 平均單體溫度 (0.1 °C) |
| **8220** | Battery maximum cell temperature | S16 | 最高單體溫度 (0.1 °C) |
| **8222** | Battery minimum cell temperature | S16 | 最低單體溫度 (0.1 °C) |



### D. 系統控制與設定 (Writable)
| 地址 (Addr) | Tag Name | 類型 | 說明 |
| :--- | :--- | :--- | :--- |
| **12288** | year | U16 | 設定年份 (如 2026) |
| **12289** | month_day | U16 | High Byte:月 / Low Byte:日 |
| **12290** | hour_minute | U16 | High Byte:時 / Low Byte:分 |
| **12291** | second | U16 | High Byte:秒 / Low Byte:0 |
| **12293** | power derating percent by modbus | U16 | 功率降額百分比 (%) |
| **12350** | modbus Address | U16 | PCS 通訊地址設定 |
| **12364** | rs485 baudrate | U16 | 通訊波特率設定 |
| **12464** | digital meter modbus address | U16 | 外部電表通訊地址 |
| **12465** | digital meter type | U16 | 電表型號代碼 |
| **12466** | power flow direction | U16 | 0:停用, 1:外部裝置, 2:CT, 3:電表 |
| **12468** | power limit CT ratio | U16 | 限電 CT 變比 |
| **12469** | meter location | U16 | 0:電網端, 1:負載端 |
| **12473** | maximum fed in grid power | U32 | 最大饋網功率限制 (W) |
| **20480** | first connect start time | U16 | 初次併網啟動時間 (s) |
| **20481** | reconnect time | U16 | 重新併網時間 (s) |

---

## 3. 模擬邏輯說明

1. **時間封裝 (Byte-Packing)**: 
   針對暫存器 `12289` (月日) 與 `12290` (時分)，模擬器會自動將兩個 8-bit 的數據合成一個 16-bit 寫入暫存器，完全符合工業級 Modbus 協定要求。
2. **電力連動計算**:
   模擬器會根據 `PV功率 - 負載功率 = 剩餘功率` 自動計算電網饋網或取電狀態，並同步模擬電池 SOC 的增減與功率變化。
3. **32位元支援**:
   所有 S32 (帶符號 32 位元) 標籤均正確處理負數補碼，可直觀顯示「買電/賣電」與「充電/放電」的狀態切換。

## 4. 快速開始

1. 安裝環境：`pip install pymodbus`
2. 執行腳本：`python main.py`
3. 使用 Modbus 工具連線至 `localhost:7002` 即可讀取與寫入以上所有標籤。