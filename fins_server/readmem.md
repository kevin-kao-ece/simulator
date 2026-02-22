## OMRON PLC Memory Areas & FINS Codes Reference

This table covers the memory areas for CS, CJ, and CP series PLCs. Note that bit-level and word-level access use distinct FINS area codes.

| Area Name | Prefix | Bit Code (Hex) | Word Code (Hex) | Description | Retentive |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CIO** (Core I/O) | `CIO` | `30` | `B0` | Physical I/O, Link Bits, and Internal relays. | No |
| **Work** Area | `W` | `31` | `B1` | Internal work bits for programming logic. | No |
| **Holding** Area | `H` | `32` | `B2` | Retentive bits; keeps status after power loss. | **Yes** |
| **Auxiliary** Area | `A` | `33` | `B3` | System status/control (Clock, Error flags). | Mixed |
| **Data Memory** | `D` | `02` | `82` | General data storage (Integers, Floats). | **Yes** |
| **Extended Memory** | `E` | `20-2F`* | `A0-AF`* | Extra data banks (Bank 0 to 15). | **Yes** |
| **Timer PV** | `T` | — | `89` | Timer Present Value (current elapsed time). | No |
| **Timer Flag** | `T` | `09` | — | Timer Completion Flag ("Done" bit). | No |
| **Counter PV** | `C` | — | `88` | Counter Present Value (current count). | **Yes**** |
| **Counter Flag** | `C` | `08` | — | Counter Completion Flag ("Done" bit). | **Yes**** |
| **Task Flags** | `TK` | `06` | `46` | Status flags for Cyclic Tasks. | No |
| **Index Register** | `IR` | — | `9C` | Pointer registers for indirect addressing. | No |
| **Data Register** | `DR` | — | `BC` | Offset data for Index Registers. | No |
| **Condition Flags**| `CF` | `03` | — | System arithmetic results (Greater than, etc.).| No |

*\* Extended Memory (EM) codes change based on the bank. Bit access for Bank 0 is 20, Bank 1 is 21, etc. Word access for Bank 0 is A0, Bank 1 is A1, up to AF.* *\*\* Counter values are retentive in most models unless specifically cleared.*

---

### Technical Usage Notes:
1. **Addressing Format:** * **Bit:** `<Area Code> <Word Address (2 bytes)> <Bit Address (1 byte)>`
   * **Word:** `<Area Code> <Word Address (2 bytes)> 00`
2. **NJ/NX Series:** While these newer controllers use a Tag-based system, they maintain a "Legacy" memory map (usually mapping tags to the D or E areas) to remain compatible with FINS-based HMIs and SCADA systems.
3. **DM Bit Access:** Some older models do not support bit-level access to the DM area directly via FINS (Code `02`). In those cases, you must read the whole word and mask the bits manually.

## OMRON PLC Supported Data Types

### 1. Boolean & Bit Strings
Used for logical operations and raw hex/bit manipulation.

| Data Type | Size | Range / Description | Series |
| :--- | :--- | :--- | :--- |
| **BOOL** | 1 Bit | `TRUE` (1) or `FALSE` (0). | All |
| **BYTE** | 8 Bits | 1-byte raw data (Hex: `00` to `FF`). | NJ/NX |
| **WORD** | 16 Bits | 1-word raw data (Hex: `0000` to `FFFF`). | All |
| **DWORD** | 32 Bits | 2-word raw data (Hex: `00000000` to `FFFFFFFF`). | All |
| **LWORD** | 64 Bits | 4-word raw data (Hex: `0000000000000000` to `FFFF...`). | NJ/NX |

---

### 2. Integers (Whole Numbers)
Note: CJ/CS series typically uses `INT` and `DINT` but handles unsigned values via specific instructions.

| Data Type | Size | Range (Signed) | Range (Unsigned) |
| :--- | :--- | :--- | :--- |
| **SINT / USINT**| 8 Bits | `-128` to `127` | `0` to `255` |
| **INT / UINT** | 16 Bits | `-32,768` to `32,767` | `0` to `65,535` |
| **DINT / UDINT**| 32 Bits | `-2,147,483,648` to `...` | `0` to `4,294,967,295` |
| **LINT / ULINT**| 64 Bits | `-9.22e18` to `9.22e18` | `0` to `1.84e19` |

---

### 3. Real Numbers (Floating Point)
Used for analog values and complex math.

| Data Type | Size | Description |
| :--- | :--- | :--- |
| **REAL** | 32 Bits | Single-precision floating point (approx. 7 decimal digits). |
| **LREAL** | 64 Bits | Double-precision floating point (approx. 15 decimal digits). |

---

### 4. Time & Date (NJ/NX Series Only)
Modern OMRON controllers have native types for scheduling and timestamps.

| Data Type | Description | Format Example |
| :--- | :--- | :--- |
| **TIME** | Duration | `T#10s`, `T#2h15m` |
| **DATE** | Calendar date | `D#2024-05-20` |
| **TIME_OF_DAY** | Time of clock | `TOD#14:30:05` |
| **DATE_AND_TIME**| Full timestamp | `DT#2024-05-20-14:30:05` |

---

### 5. Text & Complex Types
| Data Type | Description |
| :--- | :--- |
| **STRING** | ASCII text. (NJ/NX uses 1 byte per char + NULL terminator). |
| **ARRAY** | A collection of variables of the same type (e.g., `ARRAY[0..9] OF INT`). |
| **STRUCT** | A custom group of different data types (e.g., a "Motor" struct). |
| **UNION** | (NJ/NX) Allows the same memory to be accessed as different types. |


## OMRON Data Memory (DM) Capacity Reference

The address range for DM always starts at `D0`. The upper limit (End Address) varies by hardware.

| PLC Series | Model Example | Typical DM Range | Total Registers (Words) |
| :--- | :--- | :--- | :--- |
| **Micro** | CP1E / CP1L | `D0` to `D6143` | ~6,000 |
| **Micro (High-end)** | CP1H | `D0` to `D32767` | 32,768 |
| **Mid-Range** | CJ1M / CJ2M | `D0` to `D32767` | 32,768 |
| **High-End** | CJ2H / CS1H | `D0` to `D32767` | 32,768 |
| **Modern (IEC)** | NJ / NX Series | `D0` to `D32767`* | 32,768 |

*\*Note: In NJ/NX series, "D" is a legacy area used for FINS compatibility. Primary memory is stored in "Variable" memory, which can be several Megabytes in size.*