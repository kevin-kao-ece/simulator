# FINS Server（OMRON FINS UDP）模擬器

本專案提供一個以 Python 實作的 **OMRON FINS (UDP)** 模擬器，支援基本的 **Memory Area Read (0101)** / **Memory Area Write (0102)**，並內建一個「類 MELSEC 馬達」背景邏輯，會持續更新 DM/CIO 等區域資料，方便 HMI/SCADA 或客戶端程式做整合測試。

## 1. 系統規格

- **通訊協定**：OMRON FINS / UDP
- **綁定位址 / 埠號**：由 `config.yaml` 控制（預設 `0.0.0.0:9600`）
- **支援區域（Word/Bit）**：`D`、`CIO`、`W`、`H`、`E0`（可在 `config.yaml` 調整 area code）
- **更新頻率**：背景邏輯每 `0.1s` 更新一次（見 `main.py`）

> 重要：`main.py` 會讀取同目錄的 `config.yaml` 覆寫預設值。  
> `docker-compose.yml` 對外映射是 **9600/udp**；請確保它與 `config.yaml` 的 `network.port` 一致。

## 2. 安裝與本機啟動

在專案根目錄或 `fins_server/` 目錄下執行皆可（以下以 `fins_server/` 為例）。

```bash
pip install -r requirements.txt
python main.py
```

啟動後會看到類似訊息：

- `OMRON FINS Simulator Ready on UDP <port>`
- `Supported: D, CIO, W, H, E (Bit & Word access)`

## 3. 設定檔（`config.yaml`）

`config.yaml` 主要分三塊：

- **network**
  - `host`：預設 `0.0.0.0`
  - `port`：預設 `9600`
- **areas**
  - 定義各區域的 word/bit area code（可用 `0x..` 或十進位字串）
- **simulator**
  - `init.y0_start`：啟動時預設 Y0（對應 CIO bit 0.0）
  - `init.target_rpm`：啟動時預設目標轉速（對應 D14）
  - `demo.*`：啟動時預寫 demo 值（對應 D100 字串、D200 REAL）

## 4. 快速驗證（使用 `client.py`）

`client.py` 提供最小可用的 FINS UDP 客戶端範例，會：

- 寫入 **D0 = 1** 作為 legacy start 命令（伺服器會同步 mirror 到 CIO bit 0.0）
- 週期性讀取 **D10..D25** 的資料區塊，解析成轉速/電流/能量等欄位

```bash
python client.py
```

若你的伺服器埠號不是 9600，請到 `client.py` 內調整 `OmronFinsClient(..., port=xxxx)`。

## 5. Docker / Compose

### A. Dockerfile

在 `fins_server/` 目錄下：

```bash
docker build -t fins-server:1.0 .
docker run --rm -p 9600:9600/udp fins-server:1.0
```

若你要改成其他埠號，請同步調整 `config.yaml` 與對外 port mapping（UDP）。

### B. docker-compose

`docker-compose.yml` 目前映射為 `9600:9600/udp`。請確認它與 `config.yaml` 的 `network.port` 一致，否則客戶端要連到對應的對外埠。

## 6. 內建馬達資料映射（對齊 `melsec_server` 語意）

背景邏輯會把一組馬達狀態寫進 FINS 的 DM/CIO 中（位址以 **Word**/Bit**邏輯**表示，實際封包仍遵循 FINS area code + addr/bit/count 的格式）。

### Bits（CIO bit area）

- **CIO 0.0**：Y0（Motor Start）
- **CIO 0.1**：X0（Running Feedback）
- **CIO 0.10**：M10（Fault；RPM > 1800）

同時保留 legacy/mirror 行為：

- **D0.0**（DM bit）會被視為 start/stop 命令，並 mirror 到 CIO 0.0
- **D3.0**（DM bit）會 mirror 運轉回授（等同 X0）

### Words（D area）

以下欄位用來對齊其他模擬器的 motor semantics：

- **D10..D11**：RPM（`float32`）
- **D12..D13**：Amps（`float32`）
- **D14**：Target RPM（`uint16`）
- **D15**：ErrScaled（`int16`，\((target - rpm) \times 100\)）
- **D16..D17**：Runtime ticks（`uint32`）
- **D18..D19**：Encoder（`int32`）
- **D20..D23**：Energy kWh（`float64`）
- **D24**：BusV × 10（`uint16`）
- **D25**：RPM BCD（`uint16`，0..9999）

> 注意：FINS 的位址欄位在封包中用 Big-Endian（`start_addr` 用 `>H` 解析）。  
> 但此模擬器為了對齊 `melsec_server` 的既有行為，部分多 word 的數值（例如 D10 的 float32）實際寫入時採用 **Little-Endian bytes**（見 `main.py` 的 `struct.pack('<f', ...)` 等用法）。  
> 若你的客戶端是「以 word 為單位」解碼，請務必用與本 README/`client.py` 相同的解析方式驗證。

## 7. 協定與區域代碼參考

- 更完整的 OMRON Memory Area / 型別整理請見 `readmem.md`（本目錄內）。
- 伺服器只實作最常用的 READ/WRITE；若你需要更多 MRC/SRC（例如多區塊讀、狀態指令等），可在 `main.py` 的封包解析/派送邏輯擴充。

