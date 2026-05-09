# EtherNet/IP（CIP Tag）Motor Simulator

本專案是一個以 Python + `cpppo` 實作的 **EtherNet/IP (CIP)** 模擬器，提供 Logix-like 的 **CIP Tag**（可被 HMI/SCADA/Client 讀寫）。  
此外內建與其他模擬器（`melsec_server` / `s7_server` / `fins_server`）一致的「馬達物理引擎」語意：用啟動命令與目標轉速驅動，持續更新轉速/電流/能量等監控資料。

## 1. 系統規格

- **通訊協定**：EtherNet/IP (CIP) – Tag Read/Write
- **TCP 埠號**：`6003`
- **更新頻率**：每 `0.1s` 更新一次（`main.py` background logic）

## 2. 安裝與本機啟動

在 `ethernet_ip_server/` 目錄下：

```bash
pip install -r requirements.txt
python main.py
```

啟動後 server 會依 `config.yaml` 監聽（預設 `0.0.0.0:6003`），並由 background logic 透過 client loop 讀/寫 tags 以更新狀態。

## 3. 設定檔（`config.yaml`）

你可以用 `config.yaml` 調整：

- `server.host` / `server.port`
- `simulator.init.motor_control`（啟動預設是否 ON）
- `simulator.init.target_speed`
- `simulator.physics.*`（加減速斜率、fault 門檻）
- `tags.*`（若你的上位系統想用不同 Tag 名稱）

## 4. Tag 映射（對齊其他 motor simulator 語意）

### 控制 / 回授（等同 MELSEC: Y0 / X0 / M10）

- **`Motor_Control` (BOOL)**：啟動/停止命令（等同 **Y0**）
- **`Motor_Run` (BOOL)**：運轉回授（等同 **X0**）
- **`Motor_Fault` (BOOL)**：故障位（等同 **M10**；目前規則：RPM > 1800 置位）

### 主要數值（對齊 `D10..D25` 語意）

- **`Target_Speed` (INT)**：目標 RPM（等同 D14）
- **`Current_Speed` (REAL)**：目前 RPM（float32；等同 D10..D11）
- **`Current_Amps` (REAL)**：目前電流（float32；等同 D12..D13）
- **`ErrScaled` (INT)**：\((Target\_Speed - Current\_Speed) \times 100\)（int16 語意；等同 D15）
- **`RuntimeTicks` (DINT)**：tick 計數（每 0.1s +1；等同 D16..D17）
- **`Encoder` (DINT)**：encoder 演示（等同 D18..D19）
- **`Energy_kWh` (LREAL)**：累積電能（float64；等同 D20..D23）
- **`BusV_x10` (INT)**：DC bus 電壓×10（uint16 語意；等同 D24）
- **`RPM_BCD` (INT)**：RPM 的 4 digits BCD（0..9999；uint16 語意；等同 D25）

### 其他演示 Tag

- **`Current_Temperature` (REAL)**：溫度演示值
- **`Name` (STRING)**：裝置名稱
- **`Mode` (SINT)**：保留欄位

## 5. 快速驗證（用 `test2.py` 當 client）

在另一個終端機：

```bash
python test2.py
```

`test2.py` 會：

- 先讀取一批 tags
- 嘗試寫入 `Motor_Control=1`、`Target_Speed=1500`（以及其他示範寫入）
- 再讀回確認

## 6. Docker / Compose

### A. Docker build/run

在 `ethernet_ip_server/` 目錄下：

```bash
docker build -t ethernet-ip-server:1.0 .
docker run --rm -p 6003:6003 ethernet-ip-server:1.0
```

### B. docker-compose

```bash
docker compose up -d --build
```

## 7. 實作說明（高層）

`main.py` 會啟動兩個 daemon thread：

- **Server thread**：用 `cpppo.server.enip.main` 建立 CIP Tag server
- **Logic thread**：用 `cpppo.server.enip.client` 連回本機 server，週期性讀取 `Motor_Control`/`Target_Speed`，並更新 `Current_Speed` 等衍生 tags

這樣的設計好處是：background logic 的讀寫行為與真實客戶端一致，且不需依賴 cpppo 內部資料結構。

