import socket
import struct
import yaml
import logging
import threading
import time

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("MelsecSimulator")

# Professional Device Classifications based on MC Protocol Specs
# Word Devices: 2 bytes per address
WORD_DEVICE_CODES = {0xA8, 0xB4, 0xAF, 0xB0, 0xC2, 0xC5} # D, W, R, ZR, TN, CN
# Bit Devices: 1 byte per address (simulated as bytearray for alignment)
BIT_DEVICE_CODES  = {0x90, 0x9C, 0x9D, 0xA0, 0xC1, 0xC0, 0xC4, 0xC3} # M, X, Y, B, TS, TC, CS, CC

class MelsecServer:
    def __init__(self, config_path='config.yaml'):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.net = self.config['network']
        self.dev_cfg = self.config['devices']
        self.running = True
        self.memory = {}

        # Initialize Memory Buffers
        for key, cfg in self.dev_cfg.items():
            size = cfg['range'][1] - cfg['range'][0] + 1
            code = cfg['code']
            
            if code in WORD_DEVICE_CODES:
                # Word devices: 2 bytes per point
                self.memory[code] = bytearray(size * 2)
            else:
                # Bit devices: 1 byte per point (0x00 or 0x01)
                self.memory[code] = bytearray(size)
        
        logger.info(f"Initialized memory for codes: {[hex(c) for c in self.memory.keys()]}")

        # --- NEW: Set Y0 Initial Value to 1 ---
        y_code = self.dev_cfg['Y']['code']
        self.memory[y_code][0] = 0x01  # Set Y0 to ON immediately
        
        logger.info(f"Initialized memory. Y0 is set to 1 (Motor Start).")

    def start_simulation_logic(self):
        """Background thread to simulate a Motor State & Physics."""
        def update_loop():
            # Device Codes from Config
            d_code = self.dev_cfg['D']['code']
            x_code = self.dev_cfg['X']['code']
            y_code = self.dev_cfg['Y']['code']
            m_code = self.dev_cfg['M']['code']
            
            # Internal physics variables
            current_rpm = 0.0
            motor_target_rpm = 1500.0
            
            while self.running:
                # 1. READ COMMAND: Check if Start Output (Y0) is ON
                motor_switch = self.memory[y_code][0] 
                
                # 2. PHYSICS: Ramp Speed Up/Down
                if motor_switch == 0x01:
                    if current_rpm < motor_target_rpm:
                        current_rpm += 50.5  # Acceleration
                    self.memory[x_code][0] = 0x01  # Feedback X0 = Running
                else:
                    if current_rpm > 0:
                        current_rpm -= 30.2  # Deceleration
                    if current_rpm <= 0:
                        current_rpm = 0
                        self.memory[x_code][0] = 0x00  # Feedback X0 = Stopped

                # 3. WRITE RPM TO D10 (Word)
                self.memory[d_code][20:22] = struct.pack('<H', int(current_rpm*10))

                # 4. SIMULATE CURRENT (Amps) TO D11
                # Formula: (RPM / 100) + random noise
                if current_rpm > 0:
                    current_amps = (current_rpm / 150) + (int(time.time()) % 3)
                else:
                    current_amps = 0
                self.memory[d_code][22:24] = struct.pack('<H', int(current_amps*100))

                # 5. FAULT LOGIC: If RPM > 1800 (Overload), trip M10
                if current_rpm > 1800:
                    self.memory[m_code][10] = 0x01 # Fault bit M10
                else:
                    self.memory[m_code][10] = 0x00

                #logger.info(f"Current RPM: {current_rpm}, AMPS: {current_amps}, Target RPM: {motor_target_rpm}")
                time.sleep(0.1) # 100ms update for smooth ramping

        threading.Thread(target=update_loop, daemon=True).start()

    def make_response(self, payload, error=0x0000):
        """Builds a standard 3E Binary Frame Response."""
        # Header: Subheader(D000) + Network(00) + PLC(FF) + IO(03FF) + Station(00)
        header = b'\xD0\x00\x00\xFF\xFF\x03\x00'
        # Data Length = Error Code (2 bytes) + Payload length
        length = struct.pack('<H', len(payload) + 2)
        return header + length + struct.pack('<H', error) + payload

    def handle_client(self, conn, addr):
        with conn:
            conn.settimeout(15.0)
            logger.info(f"Connected by {addr}")
            while self.running:
                try:
                    data = conn.recv(4096) # Large buffer for ZR/R block transfers
                    if not data: break
                    
                    if len(data) < 21: continue # Minimum 3E frame size

                    # --- Request Parsing ---
                    # Command: Read(0401) or Write(1401)
                    cmd = struct.unpack('<H', data[11:13])[0]
                    # Start Address: 3 bytes (Little Endian)
                    head_addr = struct.unpack('<I', data[15:18] + b'\x00')[0]
                    dev_code = data[18]
                    points = struct.unpack('<H', data[19:21])[0]

                    if dev_code not in self.memory:
                        logger.warning(f"Invalid device code requested: {hex(dev_code)}")
                        conn.sendall(self.make_response(b'', error=0xC051))
                        continue

                    # --- READ LOGIC (0401) ---
                    if cmd == 0x0401:
                        if dev_code in WORD_DEVICE_CODES:
                            start, end = head_addr * 2, (head_addr + points) * 2
                            payload = bytes(self.memory[dev_code][start:end])
                        else:
                            # --- BIT DEVICE FIX ---
                            raw_bits = self.memory[dev_code][head_addr : head_addr + points]
                            packed_payload = []
                            
                            # MC Protocol packs 2 bits per byte (4 bits each)
                            # Even-indexed bit (0, 2, 4...) -> High Nibble
                            # Odd-indexed bit (1, 3, 5...)  -> Low Nibble
                            for i in range(0, len(raw_bits), 2):
                                b1 = (raw_bits[i] & 0x01) << 4  # Bit 0 to High Nibble
                                b2 = 0
                                if i + 1 < len(raw_bits):
                                    b2 = (raw_bits[i+1] & 0x01) # Bit 1 to Low Nibble
                                packed_payload.append(b1 | b2)
                            
                            payload = bytes(packed_payload)
                        conn.sendall(self.make_response(bytes(payload)))
                        logger.debug(f"READ {points} pts from {hex(dev_code)} at {head_addr}")

                    # --- WRITE LOGIC (1401) ---
                    elif cmd == 0x1401:
                        write_data = data[21:]  # Payload start

                        if dev_code in WORD_DEVICE_CODES:
                            start, end = head_addr * 2, (head_addr + points) * 2
                            needed_len = points * 2
                            if end <= len(self.memory[dev_code]):
                                self.memory[dev_code][start:end] = write_data[:needed_len]
                                conn.sendall(self.make_response(b''))
                        else:
                            # --- BIT DEVICE UNPACKING FIX ---
                            # Number of bytes sent by client is (points + 1) // 2
                            num_bytes_received = (points + 1) // 2
                            payload = write_data[:num_bytes_received]
                            
                            if head_addr + points <= len(self.memory[dev_code]):
                                unpacked_bits = []
                                for b in payload:
                                    # Extract High Nibble (First bit)
                                    unpacked_bits.append((b >> 4) & 0x01)
                                    # Extract Low Nibble (Second bit)
                                    if len(unpacked_bits) < points:
                                        unpacked_bits.append(b & 0x01)
                                
                                # Store as clean 0x00 or 0x01 in memory
                                for i, bit_val in enumerate(unpacked_bits):
                                    self.memory[dev_code][head_addr + i] = bit_val
                                    
                                conn.sendall(self.make_response(b''))
                                logger.info(f"WRITE BIT {points} pts to {hex(dev_code)} at {head_addr}: {unpacked_bits}")
                            else:
                                conn.sendall(self.make_response(b'', error=0xC050))
                except Exception as e:
                    logger.error(f"Error handling client {addr}: {e}")
                    break
            logger.info(f"Disconnected from {addr}")

    def run(self):
        self.start_simulation_logic()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server.bind((self.net['host'], self.net['port']))
            server.listen(5)
            logger.info(f"MELSEC 3E SIMULATOR START: {self.net['host']}:{self.net['port']}")
            
            while True:
                conn, addr = server.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            self.running = False
            logger.info("Shutting down...")
        finally:
            server.close()

if __name__ == "__main__":
    MelsecServer().run()