import snap7
import time
import yaml
import threading
import ctypes
import logging
from snap7.util import set_real, set_int, set_bool

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("S7Simulator")

class S7FullSimulator:
    def __init__(self, config_path='config.yaml'):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.server = snap7.server.Server()
        self.memory = {}
        self.running = True

        # S7 Area Constants (Snap7 內部代碼)
        # srvAreaPE=0x81, srvAreaPA=0x82, srvAreaMK=0x83, srvAreaDB=0x84
        self.AREA_MAP = {
            'PE': 0x81,
            'PA': 0x82,
            'MK': 0x83,
            'DB': 0x84
        }

        self._setup_areas()

    def _setup_areas(self):
        """根據 Config 註冊所有區域"""
        for name, cfg in self.config['areas'].items():
            size = cfg['size']
            buffer = (ctypes.c_ubyte * size)()
            
            try:
                if name.startswith('DB'):
                    db_number = int(name.replace('DB', ''))
                    area_code = self.AREA_MAP['DB']
                    self.server.register_area(area_code, db_number, buffer)
                    self.memory[name] = buffer
                    logger.info(f"Registered {name} (Size: {size})")
                elif name in self.AREA_MAP:
                    area_code = self.AREA_MAP[name]
                    # PE, PA, MK 在 Snap7 中編號通常填 0
                    self.server.register_area(area_code, 0, buffer)
                    self.memory[name] = buffer
                    logger.info(f"Registered Area {name} (Size: {size})")
            except Exception as e:
                logger.error(f"Failed to register {name}: {e}")

    def start_physics_logic(self):
        """模擬馬達、感測器以及故障安全邏輯"""
        def update_loop():
            angle = 0.0
            db1 = self.memory.get('DB1')
            pa_area = self.memory.get('PA') # Output Q
            mk_area = self.memory.get('MK') # Merker M
            
            # 從 Config 讀取設定
            fault_addr = self.config['logic']['fault_bit_address']
            fault_code_offset = self.config['logic']['fault_code_db_offset']

            while self.running:
                # --- 1. 故障偵測 (監控 M100.0) ---
                is_fault = False
                if mk_area:
                    # 檢查 M[fault_addr].0 位元
                    is_fault = bool(mk_area[fault_addr] & 0x01)

                # --- 2. 安全連鎖處理 ---
                if is_fault:
                    # 如果有故障，強制將所有輸出 (Q 區) 清零
                    if pa_area:
                        for i in range(len(pa_area)):
                            pa_area[i] = 0
                    
                    # 在 DB1 寫入故障代碼 999
                    if db1:
                        set_int(db1, fault_code_offset, 999)
                        set_bool(db1, 6, 0, False) # 強制馬達狀態為停止
                else:
                    # 無故障時的正常邏輯
                    if db1:
                        # 清除故障代碼
                        set_int(db1, fault_code_offset, 0)
                        
                        # 模擬溫度 (REAL)
                        temp = 25.0 + (angle % 10)
                        set_real(db1, 0, temp)
                        
                        # 正常運行回授：若 Q0.0 開啟，則 DB1.DBX6.0 為 True
                        if pa_area:
                            motor_running = bool(pa_area[0] & 0x01)
                            set_bool(db1, 6, 0, motor_running)

                angle += 0.2
                time.sleep(0.1) # 提高邏輯掃描頻率到 100ms

        threading.Thread(target=update_loop, daemon=True).start()

    def run(self):
        self.start_physics_logic()
        
        net = self.config['network']
        try:
            self.server.start_to(net['host'], net['port'])
            logger.info(f"S7 Simulator LIVE on {net['host']}:{net['port']}")
        except:
            logger.warning("Could not start on custom port, trying default 102...")
            self.server.start()

        try:
            while True:
                event = self.server.pick_event()
                if event:
                    logger.info(f"EVENT: {self.server.event_text(event)}")
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.running = False
            self.server.stop()
            self.server.destroy()
            logger.info("Server Shutdown.")

if __name__ == "__main__":
    S7FullSimulator().run()