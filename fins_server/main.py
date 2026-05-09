import socket
import struct
import threading
import time, random
import os
import yaml

# --- OMRON FINS CONFIGURATION ---
_DEFAULT_CONFIG = {
    "network": {"host": "0.0.0.0", "port": 16004},
    "areas": {
        "D": {"word": 0x82, "bit": 0x02},
        "CIO": {"word": 0xB0, "bit": 0x30},
        "W": {"word": 0xB1, "bit": 0x31},
        "H": {"word": 0xB2, "bit": 0x32},
        "E0": {"word": 0xA0, "bit": 0x20},
    },
    "simulator": {
        "init": {"y0_start": 1, "target_rpm": 1200},
        "demo": {"d100_string": "HELLOWORLD", "d200_real": 123.456},
    },
}

def _parse_hex_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s, 10)
    raise TypeError(f"Unsupported numeric value: {type(v)}")

def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def load_config():
    cfg = dict(_DEFAULT_CONFIG)
    cfg["network"] = dict(_DEFAULT_CONFIG["network"])
    cfg["areas"] = {k: dict(v) for k, v in _DEFAULT_CONFIG["areas"].items()}
    cfg["simulator"] = {
        "init": dict(_DEFAULT_CONFIG["simulator"]["init"]),
        "demo": dict(_DEFAULT_CONFIG["simulator"]["demo"]),
    }

    path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, user_cfg)

    # Normalize hex strings in areas
    norm_areas = {}
    for name, a in cfg["areas"].items():
        norm_areas[name] = {
            "word": _parse_hex_int(a["word"]),
            "bit": _parse_hex_int(a["bit"]),
        }
    cfg["areas"] = norm_areas
    return cfg

CONFIG = load_config()
HOST, PORT = CONFIG["network"]["host"], int(CONFIG["network"]["port"])
AREAS = CONFIG["areas"]

# --- DATA MARSHALLER ---
class PLCValue:
    """Translates Python types to PLC-compatible binary formats."""
    # Format Map: (Struct Format, Word Count)
    FMTS = {
        'BOOL':  ('>?', 1),   'SINT':  ('>b', 1), 
        'USINT': ('>B', 1),   'INT':   ('>h', 1),
        'UINT':  ('>H', 1),   'DINT':  ('>i', 2),
        'UDINT': ('>I', 2),   'LINT':  ('>q', 4),
        'ULINT': ('>Q', 4),   'REAL':  ('>f', 2),
        'LREAL': ('>d', 4)
    }

    @staticmethod
    def encode(val, data_type):
        if data_type == 'STRING':
            b = str(val).encode('ascii')
            if len(b) % 2 != 0: b += b'\x00'
            return b
        fmt, _ = PLCValue.FMTS.get(data_type, ('>H', 1))
        return struct.pack(fmt, val)

    @staticmethod
    def decode(raw_bytes, data_type):
        if data_type == 'STRING':
            return raw_bytes.decode('ascii').strip('\x00')
        fmt, _ = PLCValue.FMTS.get(data_type, ('>H', 1))
        return struct.unpack(fmt, raw_bytes)[0]

# --- CORE MEMORY ENGINE ---
class PLCMemory:
    def __init__(self):
        # Initialize 10,000 words (20,000 bytes) per physical area
        self.buffers = {area['word']: bytearray(20000) for area in AREAS.values()}
        self._lock = threading.RLock()

    def access(self, area_code, start_addr, bit_offset, count, data=None):
        """Unified Read/Write access for Word and Bit areas."""
        with self._lock:
            is_bit_mode = any(area_code == a['bit'] for a in AREAS.values())
            # Find the Word-based buffer associated with this area code
            base_word_area = next((a['word'] for a in AREAS.values() if area_code in a.values()), 0x82)
            buf = self.buffers[base_word_area]

            if data is None: # --- READ ---
                if is_bit_mode:
                    res = bytearray()
                    for i in range(count):
                        curr_bit = bit_offset + i
                        idx = (start_addr + (curr_bit // 16)) * 2
                        bit_pos = curr_bit % 16
                        word_val = struct.unpack_from('>H', buf, idx)[0]
                        res.append(1 if (word_val & (1 << bit_pos)) else 0)
                    return res
                else:
                    return buf[start_addr * 2 : (start_addr + count) * 2]

            else: # --- WRITE ---
                if is_bit_mode:
                    for i in range(count):
                        curr_bit = bit_offset + i
                        idx = (start_addr + (curr_bit // 16)) * 2
                        bit_pos = curr_bit % 16
                        word_val = struct.unpack_from('>H', buf, idx)[0]
                        if data[i]: word_val |= (1 << bit_pos)
                        else: word_val &= ~(1 << bit_pos)
                        struct.pack_into('>H', buf, idx, word_val)
                else:
                    buf[start_addr * 2 : start_addr * 2 + len(data)] = data
                return None

# --- SIMULATOR INSTANCE & LOGIC ---
plc = PLCMemory()

def _bcd_pack_u16_u9999(value):
    v = max(0, min(9999, int(value)))
    d = [(v // 1000) % 10, (v // 100) % 10, (v // 10) % 10, v % 10]
    w = 0
    for n in d:
        w = (w << 4) | (n & 0xF)
    return w

def background_logic():
    """Simulates MELSEC-like motor physics using FINS DM/CIO memory map."""
    print("Logic simulation running (MELSEC-compatible map)...")

    # --- MELSEC-compatible map (implemented on OMRON areas) ---
    # Bits (simulated on CIO bit area):
    # - Y0  (Motor Start)    -> CIO bit 0.0（亦可由 D0.0 legacy 鏡像啟動；OR 合併，不會僅因 D0=0 清除對 CIO 的寫入）
    # - X0  (Running FB)     -> CIO bit 0.1
    # - M10 (Fault bit)      -> CIO bit 0.10
    CIO_BIT = AREAS['CIO']['bit']   # 0x30
    D_WORD = AREAS['D']['word']     # 0x82

    # Words in D area (big-endian encoding in this simulator):
    # - D10..D11: current_rpm (float32)
    # - D12..D13: current_amps(float32)
    # - D14     : target_rpm  (uint16)
    # - D15     : err_scaled  (int16)  ( (target - rpm) * 100 )
    # - D16..D17: runtime_ticks (uint32)
    # - D18..D19: encoder_i32   (int32)
    # - D20..D23: energy_kwh    (float64)
    # - D24     : bus_v_x10     (uint16)
    # - D25     : rpm_bcd       (uint16) packed 0..9999

    # Internal physics variables
    current_rpm = 0.0
    runtime_ticks = 0
    encoder_i32 = 0
    energy_kwh = 0.0

    while True:
        # --- Read target RPM (D14, u16) ---
        raw_target = plc.access(D_WORD, 14, 0, 1)
        target_rpm = struct.unpack('<H', raw_target)[0]

        # --- Start command: CIO 0.00 (Y0) OR legacy mirror D0.00 ---
        # 舊版 bug：僅依 D0.0 決定 Y0，D0=0 時每拍把 CIO Y0 清 0，會抹掉 Northbound 對 CIO 的位元寫入，
        # OPC UA 輪詢讀回永遠對不上剛寫入的 True → Northbound write confirm timeout。
        y0_cio = plc.access(CIO_BIT, 0, 0, 1)[0] & 1
        d0_word = struct.unpack_from('>H', plc.buffers[D_WORD], 0)[0]
        legacy_start = 1 if (d0_word & 0x01) else 0
        y0 = 1 if (y0_cio or legacy_start) else 0
        plc.access(CIO_BIT, 0, 0, 1, data=bytes([y0]))

        # --- Physics: Ramp Speed Up/Down ---
        if y0 == 1:
            if current_rpm < target_rpm:
                current_rpm += 50.5
            plc.access(CIO_BIT, 0, 1, 1, data=b'\x01')  # X0 = 1 (running feedback)
        else:
            if current_rpm > 0:
                current_rpm -= 30.2
            if current_rpm <= 0:
                current_rpm = 0.0
                plc.access(CIO_BIT, 0, 1, 1, data=b'\x00')  # X0 = 0

        # --- Write RPM to D10 (float32, little-endian like melsec_server) ---
        plc.access(D_WORD, 10, 0, 2, data=struct.pack('<f', float(current_rpm)))

        # --- Simulate current (Amps) to D12 (float32) ---
        if current_rpm > 0:
            current_amps = (current_rpm / 150.0) + (int(time.time()) % 3)
        else:
            current_amps = 0.0
        plc.access(D_WORD, 12, 0, 2, data=struct.pack('<f', float(current_amps)))

        # --- Extra MELSEC-oriented types (same semantics as melsec_server) ---
        err_scaled = int(round((target_rpm - current_rpm) * 100))
        err_scaled = max(-32768, min(32767, err_scaled))
        runtime_ticks = (runtime_ticks + 1) & 0xFFFFFFFF
        encoder_i32 += int(round(current_rpm * 16.7))
        encoder_i32 = max(-2147483648, min(2147483647, encoder_i32))
        energy_kwh += abs(current_rpm) * abs(current_amps) * (0.1 / 3.6e9)
        bus_v_x10 = int(round(3800 + (current_rpm / 1200.0) * 15 + (runtime_ticks % 7)))
        bus_v_x10 = max(0, min(65535, bus_v_x10))

        plc.access(D_WORD, 15, 0, 1, data=struct.pack('<h', err_scaled))                 # D15
        plc.access(D_WORD, 16, 0, 2, data=struct.pack('<I', runtime_ticks))              # D16..D17
        plc.access(D_WORD, 18, 0, 2, data=struct.pack('<i', encoder_i32))                # D18..D19
        plc.access(D_WORD, 20, 0, 4, data=struct.pack('<d', float(energy_kwh)))          # D20..D23
        plc.access(D_WORD, 24, 0, 1, data=struct.pack('<H', bus_v_x10))                  # D24
        plc.access(D_WORD, 25, 0, 1, data=struct.pack('<H', _bcd_pack_u16_u9999(current_rpm)))  # D25

        # --- Fault logic: if RPM > 1800 then M10 = 1 ---
        m10 = 1 if current_rpm > 1800 else 0
        plc.access(CIO_BIT, 0, 10, 1, data=bytes([m10]))

        # Backward-compat mirror: D3.0 run status and a non-overlapping timestamp
        x0 = plc.access(CIO_BIT, 0, 1, 1)[0]
        plc.access(AREAS['D']['bit'], 3, 0, 1, data=bytes([1 if x0 else 0]))
        if x0:
            # NOTE: Legacy timestamp previously used D8..D11 which overlaps D10..D11 (RPM float).
            # Store it at D40..D43 instead.
            plc.access(D_WORD, 40, 0, 4, data=PLCValue.encode(int(time.time()), "LINT"))
        else:
            plc.access(D_WORD, 40, 0, 4, data=PLCValue.encode(0, "LINT"))

        time.sleep(0.1)

# --- FINS UDP SERVER ---
def start_server():
    # Start the logic thread
    threading.Thread(target=background_logic, daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, PORT))
        print(f"OMRON FINS Simulator Ready on UDP {PORT}")
        print("Supported: D, CIO, W, H, E (Bit & Word access)")

        while True:
            data, addr = s.recvfrom(2048)
            if len(data) < 12: continue

            # Extract FINS Header info
            sa1, sid = data[7], data[9]
            mrc_src = data[10:12]
            res_header = bytearray([0xC0, 0x00, 0x02, 0x00, sa1, 0x00, 0x00, 0x01, 0x00, sid])

            # Address parsing
            area = data[12]
            start_addr = struct.unpack('>H', data[13:15])[0]
            bit_offset = data[15]
            count = struct.unpack('>H', data[16:18])[0]

            try:
                if mrc_src == b'\x01\x01': # READ COMMAND
                    payload = plc.access(area, start_addr, bit_offset, count)
                    s.sendto(res_header + b'\x01\x01\x00\x00' + payload, addr)

                elif mrc_src == b'\x01\x02': # WRITE COMMAND
                    write_payload = data[18:]
                    plc.access(area, start_addr, bit_offset, count, data=write_payload)
                    s.sendto(res_header + b'\x01\x02\x00\x00', addr)
            except Exception as e:
                print(f"Error handling request: {e}")

if __name__ == "__main__":
    # Pre-load some data
    # MELSEC-compatible init
    init_cfg = (CONFIG.get("simulator") or {}).get("init") or {}
    demo_cfg = (CONFIG.get("simulator") or {}).get("demo") or {}

    plc.access(AREAS["CIO"]["bit"], 0, 0, 1, data=bytes([1 if int(init_cfg.get("y0_start", 1)) else 0]))
    plc.access(AREAS["D"]["word"], 14, 0, 1, data=struct.pack("<H", int(init_cfg.get("target_rpm", 1200))))

    # Keep previous demo values
    plc.access(AREAS["D"]["word"], 100, 0, 5, data=PLCValue.encode(demo_cfg.get("d100_string", "HELLOWORLD"), "STRING"))
    plc.access(AREAS["D"]["word"], 200, 0, 2, data=PLCValue.encode(float(demo_cfg.get("d200_real", 123.456)), "REAL"))
    
    start_server()