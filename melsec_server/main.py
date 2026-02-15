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
            if key in ['D', 'W']:
                # Word devices: 2 bytes per point
                self.memory[cfg['code']] = bytearray(size * 2)
            else:
                # Bit devices: 1 byte per point (simplified)
                self.memory[cfg['code']] = [0] * size
        
        logger.info(f"Initialized memory for: {list(self.dev_cfg.keys())}")

    def start_randomizer(self):
        """Fills the ENTIRE memory range with test values."""
        def update_logic():
            d_code = self.dev_cfg['D']['code']
            # Calculate how many words we actually have in memory
            d_word_count = len(self.memory[d_code]) // 2
            
            logger.info(f"Randomizer filling D0 through D{d_word_count-1}")
            
            while self.running:
                # Create a value that changes over time so you see it move
                base_val = int(time.time()) % 100 
                
                for i in range(d_word_count):
                    # Value logic: (Address + base_val) 
                    # This ensures D700 will have value 700 + changing seconds
                    test_value = (i + base_val) % 65535
                    
                    start_idx = i * 2
                    end_idx = start_idx + 2
                    self.memory[d_code][start_idx:end_idx] = struct.pack('<H', test_value)
                
                # Slow down the loop to save CPU, but keep data fresh
                time.sleep(1)

        thread = threading.Thread(target=update_logic, daemon=True)
        thread.start()

    def make_response(self, payload, error=0x0000):
        """Builds a standard 3E Binary Frame Response."""
        # Subheader(D000) + Net(00) + PLC(FF) + IO(03FF) + Station(00)
        header = b'\xD0\x00\x00\xFF\xFF\x03\x00'
        # Data Length = Error Code (2 bytes) + Payload length
        length = struct.pack('<H', len(payload) + 2)
        return header + length + struct.pack('<H', error) + payload

    def handle_client(self, conn, addr):
        with conn:
            conn.settimeout(10.0) # Prevent hanging
            logger.info(f"New connection from {addr}")
            while self.running:
                try:
                    data = conn.recv(1024)
                    if not data: break
                    
                    # Log Raw Hex
                    hex_data = ' '.join(f'{b:02X}' for b in data)
                    logger.info(f"[{addr}] REQ: {hex_data}")

                    if len(data) < 21: continue

                    # Parse Command (Read=0401, Write=1401)
                    cmd = struct.unpack('<H', data[11:13])[0]
                    head_addr = struct.unpack('<I', data[15:18] + b'\x00')[0]
                    dev_code = data[18]
                    points = struct.unpack('<H', data[19:21])[0]

                    # --- READ LOGIC ---
                    if cmd == 0x0401:
                        if dev_code not in self.memory:
                            conn.sendall(self.make_response(b'', error=0xC051))
                            continue
                        
                        if dev_code in [0xA8, 0xB4]: # Word Devices
                            payload = self.memory[dev_code][head_addr*2 : (head_addr+points)*2]
                        else: # Bit Devices
                            payload = bytes(self.memory[dev_code][head_addr : head_addr+points])
                        
                        conn.sendall(self.make_response(payload))
                        logger.info(f"[{addr}] READ {points} points from {hex(dev_code)} Addr {head_addr}")

                    # --- WRITE LOGIC ---
                    elif cmd == 0x1401:
                        # Success ACK
                        conn.sendall(self.make_response(b''))
                        logger.info(f"[{addr}] WRITE processed for {hex(dev_code)} Addr {head_addr}")

                except socket.timeout:
                    break
                except Exception as e:
                    logger.error(f"Client handler error: {e}")
                    break
            logger.info(f"Connection closed for {addr}")

    def run(self):
        self.start_randomizer()
        
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server.bind((self.net['host'], self.net['port']))
            server.listen(5)
            logger.info(f"MELSEC SERVER ACTIVE: {self.net['host']}:{self.net['port']}")
            
            while True:
                conn, addr = server.accept()
                # Start a thread for each client to prevent blocking
                client_thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
                client_thread.start()
                
        except KeyboardInterrupt:
            self.running = False
            logger.info("Shutting down server...")
        finally:
            server.close()

if __name__ == "__main__":
    MelsecServer().run()