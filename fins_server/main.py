import socket
import struct
import threading
import time, random

# --- OMRON FINS CONFIGURATION ---
HOST, PORT = '172.25.48.76', 9600
AREAS = {
    'D':   {'word': 0x82, 'bit': 0x02}, # Data Memory
    'CIO': {'word': 0xB0, 'bit': 0x30}, # I/O Area
    'W':   {'word': 0xB1, 'bit': 0x31}, # Work Area
    'H':   {'word': 0xB2, 'bit': 0x32}, # Holding Area
    'E0':  {'word': 0xA0, 'bit': 0x20}, # Extended Memory Bank 0
}

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

    def access(self, area_code, start_addr, bit_offset, count, data=None):
        """Unified Read/Write access for Word and Bit areas."""
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

def background_logic():
    """Simulates a motor ramping up in the PLC memory."""
    print("⚙️  Logic simulation running...")
    while True:
        # Read D0 (Control) bit
        d0_word = struct.unpack_from('>H', plc.buffers[0x82], 0)[0]
        motor_on = bool(d0_word & 0x01)
        
        # 2. Read Current RPM (D4-D5, int32)
        current_rpm_bytes = plc.access(0x82, 4, 0, 2)
        rpm = struct.unpack('>i', current_rpm_bytes)[0]

        # 3. Read Target RPM (D1-D2, int32)
        target_rpm_bytes = plc.access(0x82, 1, 0, 2)
        target_rpm = struct.unpack('>i', target_rpm_bytes)[0]

        # 4. Handle Run Status (D3.0)
        d3_word = struct.unpack_from('>H', plc.buffers[0x82], 6)[0] # Offset 6 = D3
        run_status = bool(d3_word & 0x01)

        if motor_on:
            if not run_status:
                # Start the motor: Set D3.0 = 1 and Set Timestamp D8-D11
                plc.access(0x02, 3, 0, 1, data=b'\x01') # Use area 0x02 for bit write
                plc.access(0x82, 8, 0, 4, data=PLCValue.encode(int(time.time()), "LINT"))
                print("Motor Starting...")            

            if rpm < target_rpm:
                number = random.randint(rpm, target_rpm + 10)
                new_rpm = number
                plc.access(0x82, 4, 0, 2, data=struct.pack('>i', new_rpm))            
        else:
            if run_status:
                # Stop the motor: Set D3.0 = 0 and Clear Timestamp
                plc.access(0x02, 3, 0, 1, data=b'\x00')
                plc.access(0x82, 8, 0, 4, data=PLCValue.encode(0, "LINT")) # Fix: encode 0, not ""
                print("Motor Stopping...")

            if rpm > 0:
                number = random.randint(0, rpm)
                new_rpm = rpm - number
                plc.access(0x82, 4, 0, 2, data=struct.pack('>i', new_rpm))                
        
        temp_val = 25.0 + (rpm / 100.0) + random.uniform(0, 0.5)
        plc.access(0x82, 6, 0, 2, data=PLCValue.encode(temp_val, "REAL"))

        print(f"Status: {'ON' if motor_on else 'OFF'} | RPM: {rpm} | Target: {target_rpm}")
        time.sleep(0.5)

# --- FINS UDP SERVER ---
def start_server():
    # Start the logic thread
    threading.Thread(target=background_logic, daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, PORT))
        print(f"✅ OMRON FINS Simulator Ready on UDP {PORT}")
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
                print(f"⚠️ Error handling request: {e}")

if __name__ == "__main__":
    # Pre-load some data
    # Set D100 to "HELLOWORLD"
    plc.access(0x82, 100, 0, 5, data=PLCValue.encode("HELLOWORLD", "STRING"))
    # Set D200 to 123.456 (REAL)
    plc.access(0x82, 200, 0, 2, data=PLCValue.encode(123.456, "REAL"))
    
    start_server()