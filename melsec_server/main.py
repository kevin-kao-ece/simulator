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
        self.mem_lock = threading.RLock()

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
        y_base = int(self.dev_cfg['Y']['range'][0])
        with self.mem_lock:
            self.memory[y_code][0 - y_base] = 0x01  # Set Y0 to ON immediately (range-aware)
        logger.info(f"Initialized memory. Y0 is set to 1 (Motor Start).")
        d_code = self.dev_cfg['D']['code']
        d_base = int(self.dev_cfg['D']['range'][0])
        # NOTE: Avoid overlapping floats:
        # - Motor speed  (float) uses D10..D11
        # - Motor current(float) uses D12..D13
        # - Target RPM   (u16)   uses D14
        d14_off = (14 - d_base) * 2
        with self.mem_lock:
            # 1200 decimal = 0x04B0 -> Packed as [0xB0, 0x04] (Little Endian)
            self.memory[d_code][d14_off : d14_off + 2] = struct.pack('<H', 1200)
        logger.info("D14 (Target RPM) initialized to 1200.")

    def _get_dev_base(self, dev_code: int) -> int:
        for _name, cfg in self.dev_cfg.items():
            if cfg.get('code') == dev_code:
                return int(cfg['range'][0])
        return 0

    @staticmethod
    def _frame_total_length(data_length: int) -> int:
        # 3E frame: 7-byte header + 2-byte data length + data_length bytes payload
        return 9 + data_length

    def start_simulation_logic(self):
        """Background thread to simulate a Motor State & Physics."""
        def update_loop():
            # Device Codes from Config
            d_code = self.dev_cfg['D']['code']
            x_code = self.dev_cfg['X']['code']
            y_code = self.dev_cfg['Y']['code']
            m_code = self.dev_cfg['M']['code']

            d_base = int(self.dev_cfg['D']['range'][0])
            x_base = int(self.dev_cfg['X']['range'][0])
            y_base = int(self.dev_cfg['Y']['range'][0])
            m_base = int(self.dev_cfg['M']['range'][0])

            d10_off = (10 - d_base) * 2
            d12_off = (12 - d_base) * 2
            d14_off = (14 - d_base) * 2
            x0_idx = 0 - x_base
            y0_idx = 0 - y_base
            m10_idx = 10 - m_base

            # Internal physics variables
            current_rpm = 0.0

            while self.running:
                with self.mem_lock:
                    raw_target = self.memory[d_code][d14_off : d14_off + 2]  # D14
                    motor_target_rpm = struct.unpack('<H', raw_target)[0]

                    # 1. READ COMMAND: Check if Start Output (Y0) is ON
                    motor_switch = self.memory[y_code][y0_idx]  # Y0

                # 2. PHYSICS: Ramp Speed Up/Down
                if motor_switch == 0x01:                            # Y0 == 1
                    if current_rpm < motor_target_rpm:
                        current_rpm += 50.5  # Acceleration
                    with self.mem_lock:
                        self.memory[x_code][x0_idx] = 0x01  # Feedback X0 = Running
                else:                                           # Y0 == 0
                    if current_rpm > 0:
                        current_rpm -= 30.2  # Deceleration
                    if current_rpm <= 0:
                        current_rpm = 0
                        with self.mem_lock:
                            self.memory[x_code][x0_idx] = 0x00  # Feedback X0 = Stopped

                # 3. WRITE RPM TO D10 (float: 2xWord)
                with self.mem_lock:
                    self.memory[d_code][d10_off : d10_off + 4] = struct.pack('<f', float(current_rpm))

                # 4. SIMULATE CURRENT (Amps) TO D12 (float: 2xWord)
                # Formula: (RPM / 100) + random noise
                if current_rpm > 0:
                    current_amps = (current_rpm / 150) + (int(time.time()) % 3)
                else:
                    current_amps = 0.0
                with self.mem_lock:
                    self.memory[d_code][d12_off : d12_off + 4] = struct.pack('<f', float(current_amps))

                # 5. FAULT LOGIC: If RPM > 1800 (Overload), trip M10
                with self.mem_lock:
                    if current_rpm > 1800:
                        self.memory[m_code][m10_idx] = 0x01 # Fault bit M10
                    else:
                        self.memory[m_code][m10_idx] = 0x00

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

    def _process_request_frame(self, conn, addr, frame: bytes):
        if len(frame) < 21:
            return

        # --- Request Parsing ---
        # Frame header layout (3E Binary):
        #  0..6   : fixed header (7 bytes)
        #  7..8   : data length (2 bytes, little-endian) = bytes from timer..end
        #  9..10  : monitoring timer (2 bytes)
        # 11..12  : command (2 bytes)
        # 13..14  : subcommand (2 bytes)
        # 15..17  : head device number (3 bytes, little-endian)
        # 18      : device code (1 byte)
        # 19..20  : points (2 bytes)

        cmd = struct.unpack('<H', frame[11:13])[0]
        head_addr = struct.unpack('<I', frame[15:18] + b'\x00')[0]
        dev_code = frame[18]
        points = struct.unpack('<H', frame[19:21])[0]

        if dev_code not in self.memory:
            logger.warning(f"Invalid device code requested: {hex(dev_code)}")
            conn.sendall(self.make_response(b'', error=0xC051))
            return

        base = self._get_dev_base(dev_code)
        rel_addr = head_addr - base
        if rel_addr < 0:
            conn.sendall(self.make_response(b'', error=0xC050))
            return

        # --- READ LOGIC (0401) ---
        if cmd == 0x0401:
            if dev_code in WORD_DEVICE_CODES:
                start, end = rel_addr * 2, (rel_addr + points) * 2
                with self.mem_lock:
                    if end > len(self.memory[dev_code]):
                        conn.sendall(self.make_response(b'', error=0xC050))
                        return
                    payload = bytes(self.memory[dev_code][start:end])
            else:
                with self.mem_lock:
                    if rel_addr + points > len(self.memory[dev_code]):
                        conn.sendall(self.make_response(b'', error=0xC050))
                        return
                    raw_bits = self.memory[dev_code][rel_addr : rel_addr + points]

                packed_payload = []
                for i in range(0, len(raw_bits), 2):
                    b1 = (raw_bits[i] & 0x01) << 4  # Bit 0 to High Nibble
                    b2 = 0
                    if i + 1 < len(raw_bits):
                        b2 = (raw_bits[i+1] & 0x01) # Bit 1 to Low Nibble
                    packed_payload.append(b1 | b2)

                payload = bytes(packed_payload)

            conn.sendall(self.make_response(bytes(payload)))
            logger.debug(f"READ {points} pts from {hex(dev_code)} at {head_addr}")
            return

        # --- WRITE LOGIC (1401) ---
        if cmd == 0x1401:
            write_data = frame[21:]

            if dev_code in WORD_DEVICE_CODES:
                start, end = rel_addr * 2, (rel_addr + points) * 2
                needed_len = points * 2
                with self.mem_lock:
                    if end > len(self.memory[dev_code]):
                        conn.sendall(self.make_response(b'', error=0xC050))
                        return
                    self.memory[dev_code][start:end] = write_data[:needed_len]
                conn.sendall(self.make_response(b''))
                return

            num_bytes_received = (points + 1) // 2
            payload = write_data[:num_bytes_received]

            if rel_addr + points > len(self.memory[dev_code]):
                conn.sendall(self.make_response(b'', error=0xC050))
                return

            unpacked_bits = []
            for b in payload:
                unpacked_bits.append((b >> 4) & 0x01)
                if len(unpacked_bits) < points:
                    unpacked_bits.append(b & 0x01)

            with self.mem_lock:
                for i, bit_val in enumerate(unpacked_bits):
                    self.memory[dev_code][rel_addr + i] = bit_val

            conn.sendall(self.make_response(b''))
            logger.info(f"WRITE BIT {points} pts to {hex(dev_code)} at {head_addr}: {unpacked_bits}")
            return

        conn.sendall(self.make_response(b'', error=0xC052))

    def handle_client(self, conn, addr):
        with conn:
            conn.settimeout(15.0)
            logger.info(f"Connected by {addr}")
            buf = bytearray()
            while self.running:
                try:
                    chunk = conn.recv(4096) # Large buffer for ZR/R block transfers
                    if not chunk:
                        break
                    buf.extend(chunk)

                    # Parse 0..N frames out of TCP stream using header data length
                    while True:
                        if len(buf) < 9:
                            break
                        data_len = struct.unpack('<H', buf[7:9])[0]
                        total_len = self._frame_total_length(data_len)
                        if total_len < 21:
                            # Invalid length; drop buffer to resync
                            logger.warning(f"Invalid frame length from {addr}: {total_len}")
                            buf.clear()
                            break
                        if len(buf) < total_len:
                            break
                        frame = bytes(buf[:total_len])
                        del buf[:total_len]
                        self._process_request_frame(conn, addr, frame)
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
