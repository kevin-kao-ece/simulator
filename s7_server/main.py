import snap7
import time
import yaml
import threading
import ctypes
import logging
from snap7.util import set_real, set_int, set_bool
from snap7.types import srvAreaPE, srvAreaPA, srvAreaMK, srvAreaDB

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
        """Register areas using official Snap7 Server Enums"""        
        
        # Map our config strings to the library's Enum objects
        area_enums = {
            'PE': srvAreaPE,
            'PA': srvAreaPA,
            'MK': srvAreaMK,
            'DB': srvAreaDB
        }

        for name, cfg in self.config['areas'].items():
            size = cfg['size']
            buffer = (ctypes.c_ubyte * size)()
            
            try:
                if name.startswith('DB'):
                    db_nr = int(name.replace('DB', ''))
                    # Pass the Enum srvAreaDB instead of 0x84
                    self.server.register_area(srvAreaDB, db_nr, buffer)
                    self.memory[name] = buffer
                    logger.info(f"Registered {name} (Size: {size})")
                
                elif name in area_enums:
                    # Pass srvAreaPA, srvAreaPE, or srvAreaMK Enum objects
                    self.server.register_area(area_enums[name], 0, buffer)
                    self.memory[name] = buffer
                    logger.info(f"Registered Area {name} (Size: {size})")
                    
            except Exception as e:
                logger.error(f"Failed to register {name}: {e}")

    def start_physics_logic(self):
        def update_loop():
            angle = 0.0
            rpm = 0.0  # 初始化轉速
            db1 = self.memory.get('DB1')
            pa_area = self.memory.get('PA')
            mk_area = self.memory.get('MK')
            
            fault_addr = self.config['logic']['fault_bit_address']
            fault_code_offset = self.config['logic']['fault_code_db_offset']

            while self.running:
                is_fault = bool(mk_area[fault_addr] & 0x01) if mk_area else False

                if is_fault:
                    rpm = 0.0 # 故障時轉速歸零
                    if db1:
                        set_int(db1, fault_code_offset, 999)
                        set_bool(db1, 6, 0, False)
                else:
                    if db1:
                        set_int(db1, fault_code_offset, 0)
                        
                        # --- 轉速模擬邏輯 ---
                        # 檢查 Q0.0 是否開啟 (馬達啟動指令)
                        motor_command = bool(pa_area[0] & 0x01) if pa_area else False
                        
                        if motor_command:
                            # 馬達啟動：轉速逐漸上升到 1500 RPM
                            if rpm < 1500: rpm += 50.0 
                        else:
                            # 馬達停止：轉速逐漸下降
                            if rpm > 0: rpm -= 30.0
                            if rpm < 0: rpm = 0
                        
                        # 將轉速寫入 DB1.DBW2 (偏移量 2，INT)
                        set_int(db1, 4, int(rpm))
                        
                        # 模擬溫度 (隨轉速略微波動)
                        temp = 25.0 + (rpm / 100.0) + (angle % 2)
                        set_real(db1, 0, temp)
                        
                        # 運行狀態回授
                        set_bool(db1, 6, 0, motor_command)

                angle += 0.2
                time.sleep(0.1)

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