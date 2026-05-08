import snap7
import time
import yaml
import threading
import ctypes
import logging
from snap7.util import set_real, set_int, set_bool
from snap7.types import srvAreaPE, srvAreaPA, srvAreaMK, srvAreaDB
import struct

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("S7Simulator")

def _bcd_pack_u16_u9999(value: float) -> int:
    """Pack 0..9999 into one word as 4 decimal digits (one nibble per digit)."""
    v = max(0, min(9999, int(value)))
    d = [(v // 1000) % 10, (v // 100) % 10, (v // 10) % 10, v % 10]
    w = 0
    for n in d:
        w = (w << 4) | (n & 0xF)
    return w

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
        self._init_defaults()

    def _init_defaults(self):
        """Initialize default values to mirror melsec_server motor simulator."""
        pa = self.memory.get('PA')
        db1 = self.memory.get('DB1')
        if pa:
            # Default Y0=1  -> Q0.0 ON
            pa[0] |= 0x01
        if db1:
            # Default target rpm (D14) = 1200 -> DBW28 (byte offset 28)
            set_int(db1, 28, 1200)

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
            # Offsets mirror melsec_server's D mapping (byte offsets in DB1)
            # D10..D11 -> float32 at byte 20
            # D12..D13 -> float32 at byte 24
            # D14      -> uint16 (stored as int16 here) at byte 28
            # D15      -> int16 at byte 30
            # D16..D17 -> uint32 at byte 32
            # D18..D19 -> int32 at byte 36
            # D20..D23 -> float64 at byte 40
            # D24      -> uint16 at byte 48
            # D25      -> BCD word at byte 50
            d10_off = 20
            d12_off = 24
            d14_off = 28
            d15_off = 30
            d16_off = 32
            d18_off = 36
            d20_off = 40
            d24_off = 48
            d25_off = 50

            current_rpm = 0.0
            runtime_ticks = 0
            encoder_i32 = 0
            energy_kwh = 0.0

            angle = 0.0
            db1 = self.memory.get('DB1')
            pa_area = self.memory.get('PA')
            pe_area = self.memory.get('PE')
            mk_area = self.memory.get('MK')

            while self.running:
                # 1) Read target rpm from DB1.DBW28
                motor_target_rpm = 0
                if db1:
                    motor_target_rpm = int.from_bytes(bytes(db1[d14_off:d14_off + 2]), byteorder='big', signed=False)

                # 2) Read command: Y0 -> Q0.0
                motor_switch = bool(pa_area[0] & 0x01) if pa_area else False

                # 3) Physics: ramp
                if motor_switch:
                    if current_rpm < motor_target_rpm:
                        current_rpm += 50.5
                    if pe_area:
                        pe_area[0] |= 0x01  # X0 -> I0.0 feedback running
                else:
                    if current_rpm > 0:
                        current_rpm -= 30.2
                    if current_rpm <= 0:
                        current_rpm = 0.0
                        if pe_area:
                            pe_area[0] &= 0xFE  # X0 -> I0.0 feedback stopped

                # 4) Write RPM float32 to D10 (DBD20)
                if db1:
                    db1[d10_off:d10_off + 4] = struct.pack('>f', float(current_rpm))

                # 5) Simulate current (Amps) float32 to D12 (DBD24)
                if current_rpm > 0:
                    current_amps = (current_rpm / 150.0) + (int(time.time()) % 3)
                else:
                    current_amps = 0.0
                if db1:
                    db1[d12_off:d12_off + 4] = struct.pack('>f', float(current_amps))

                # 6) Extra demo registers (same logic as melsec_server)
                err_scaled = int(round((motor_target_rpm - current_rpm) * 100))
                err_scaled = max(-32768, min(32767, err_scaled))
                runtime_ticks = (runtime_ticks + 1) & 0xFFFFFFFF
                encoder_i32 += int(round(current_rpm * 16.7))
                encoder_i32 = max(-2147483648, min(2147483647, encoder_i32))
                energy_kwh += abs(current_rpm) * abs(current_amps) * (0.1 / 3.6e9)
                bus_v_x10 = int(round(3800 + (current_rpm / 1200.0) * 15 + (runtime_ticks % 7)))
                bus_v_x10 = max(0, min(65535, bus_v_x10))
                bcd_rpm = _bcd_pack_u16_u9999(current_rpm)

                if db1:
                    db1[d15_off:d15_off + 2] = struct.pack('>h', err_scaled)
                    db1[d16_off:d16_off + 4] = struct.pack('>I', runtime_ticks)
                    db1[d18_off:d18_off + 4] = struct.pack('>i', encoder_i32)
                    db1[d20_off:d20_off + 8] = struct.pack('>d', energy_kwh)
                    db1[d24_off:d24_off + 2] = struct.pack('>H', bus_v_x10)
                    db1[d25_off:d25_off + 2] = struct.pack('>H', bcd_rpm)

                    # Mirror "W100" as DBW200 (byte 200) for HMI testing
                    db1[200:202] = struct.pack('>H', motor_target_rpm & 0xFFFF)
                    # "TN0" as DBW300
                    db1[300:302] = struct.pack('>H', runtime_ticks & 0xFFFF)
                    # "CN0" as DBW302 (pulse count)
                    pulse_inc = max(0, int(current_rpm / 120.0))
                    cur_cn = struct.unpack('>H', bytes(db1[302:304]))[0]
                    cur_cn = (cur_cn + pulse_inc) & 0xFFFF
                    db1[302:304] = struct.pack('>H', cur_cn)

                # 7) Fault logic: if RPM > 1800, trip M10 (MK byte10 bit0)
                if mk_area:
                    if current_rpm > 1800:
                        mk_area[10] |= 0x01
                    else:
                        mk_area[10] &= 0xFE

                # 8) Blink TS0 as M0.0 (optional)
                if mk_area:
                    if (runtime_ticks % 100) >= 50:
                        mk_area[0] |= 0x01
                    else:
                        mk_area[0] &= 0xFE

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