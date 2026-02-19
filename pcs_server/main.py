#!/usr/bin/env python3
import asyncio
import random
import logging
import struct
import time
from datetime import datetime

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusDeviceContext,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PCS-Ultimate-Sim")

class LoggingDataBlock(ModbusSequentialDataBlock):
    def __init__(self, address, values):
        super().__init__(address, values)
        self.internal_update = False

    def setValues(self, address, values):
        if not self.internal_update:
            print(f"EXTERNAL WRITE | Address: {address} | Data: {values}")
        super().setValues(address, values)

# =========================================================
# Data Type Helpers
# =========================================================
def set_data(context, addr, value, data_type="U16"):
    slave_id = 0x00
    if data_type == "U16":
        vals = [int(value) & 0xFFFF]
    elif data_type == "S16":
        packed = struct.pack('>h', int(value))
        vals = list(struct.unpack('>H', packed))
    elif data_type == "U32":
        val = int(value) & 0xFFFFFFFF
        vals = [(val >> 16) & 0xFFFF, val & 0xFFFF]
    elif data_type == "S32":
        packed = struct.pack('>i', int(value))
        vals = list(struct.unpack('>HH', packed))
    
    block = context[slave_id].store['h'] # Get the holding register block
    block.internal_update = True         # Set flag
    context[slave_id].setValues(3, addr, vals)
    block.internal_update = False        # Reset flag    

# =========================================================
# Simulator Logic Class
# =========================================================
class PCSExtendedLogic:
    def __init__(self):
        self.acc_load_e = 1000000 
        self.soc = 85.0 
        self.baudrate = 9600
        
    def get_time_registers(self):
        """處理時間封裝: High byte/Low byte"""
        now = datetime.now()
        year = now.year
        month_day = (now.month << 8) | now.day
        hour_minute = (now.hour << 8) | now.minute
        second_zero = (now.second << 8) | 0
        return year, month_day, hour_minute, second_zero

    def step(self):
        v_base = 230.0 + random.uniform(-1, 1)
        pv_w = 5000 + random.randint(-200, 200)
        load_w_total = 2400 + random.randint(-100, 300)
        
        # 簡單三相分配
        l_load = [load_w_total // 3 + random.randint(-20, 20) for _ in range(3)]
        
        # 電力平衡: Grid = PV - Load (正值賣電, 負值買電)
        grid_w = pv_w - load_w_total
        
        # 電池功率模擬 (正充負放)
        batt_w = grid_w * 0.8 # 假設 80% 剩餘電力進電池
        self.soc += (batt_w * 3 / 360000)
        self.soc = max(10, min(100, self.soc))
        
        return {
            "v": v_base, "pv": pv_w, "load_total": load_w_total,
            "l_load": l_load, "batt_w": batt_w, "soc": self.soc,
            "grid_w": grid_w, "freq": 60.0 + random.uniform(-0.01, 0.01)
        }

# =========================================================
# Update Task
# =========================================================
async def update_registers(context, logic):
    while True:
        try:
            d = logic.step()
            
            # --- 1. 基礎量測 (4097-4111) ---
            set_data(context, 4097, d["v"] * 10) # L1 V
            set_data(context, 4101, d["freq"] * 100) # L1 Freq

            # --- 2. Grid數據 (4890-4897, 5024-5028) ---
            set_data(context, 4890, d["v"] * 10)
            set_data(context, 4893, (d["grid_w"]/d["v"])*10, "S32") # Grid Current
            set_data(context, 5024, d["grid_w"] // 3, "S32") # L1 Grid Sum
            set_data(context, 5026, d["grid_w"] // 3, "S32") # L2
            set_data(context, 5028, d["grid_w"] // 3, "S32") # L3

            # --- 3. Load數據 (5030-5040) ---
            set_data(context, 5030, d["l_load"][0], "S32")
            set_data(context, 5032, d["l_load"][1], "S32")
            set_data(context, 5034, d["l_load"][2], "S32")
            set_data(context, 5036, 150, "U32")      # Daily
            set_data(context, 5040, logic.acc_load_e, "U32") # Acc
            logic.acc_load_e += (d["load_total"] * 3 / 36000)

            # --- 4. Backup數據 (4944-4960, 5044-5058) ---
            set_data(context, 4944, d["v"] * 10)
            set_data(context, 5044, d["l_load"][0], "S32")
            set_data(context, 5050, d["l_load"][0] + 30, "U32") # Apparent

            # --- 5. PV & Battery (5080-5094, 8192-8222) ---
            set_data(context, 5084, d["pv"], "U32")
            set_data(context, 5086, d["batt_w"], "S32")
            set_data(context, 8192, d["soc"] * 10)
            set_data(context, 8199, (d["batt_w"]/52)*10, "S32")
            set_data(context, 8201, d["batt_w"], "S32")
            set_data(context, 8215, 3352) # Max Cell
            set_data(context, 8219, 26, "S16") # Avg Temp

            # --- 6. 寫入標籤初始化與時間同步 (12288-20481) ---
            yr, md, hm, sc = logic.get_time_registers()
            set_data(context, 12288, yr)
            set_data(context, 12289, md)
            set_data(context, 12290, hm)
            set_data(context, 12291, sc)

            # 保持一些預設設定值
            # 這些值通常由外部寫入，這裡做為初始化
            # set_data(context, 12364, 9600) 
            # set_data(context, 12466, 1) # Power flow direction

            #logger.info(f"Update Success | PV: {d['pv']}W | SOC: {d['soc']:.1f}% | Grid: {int(d['grid_w'])}W")

        except Exception as e:
            logger.error(f"Update loop error: {e}")
        await asyncio.sleep(3)

async def main():
    # 建立涵蓋所有位址的資料區塊
    block = LoggingDataBlock(0, [0] * 65535)
    context = ModbusServerContext(devices=ModbusDeviceContext(hr=block), single=True)
    
    logic = PCSExtendedLogic()
    
    # --- 初始設定 Writable Tags ---
    set_data(context, 12364, 9600)     # Baudrate
    set_data(context, 12293, 100)      # Power derating 100%
    set_data(context, 12473, 5000, "U32") # Max fed-in
    set_data(context, 20480, 60)       # First connect time

    asyncio.create_task(update_registers(context, logic))
    
    logger.info("PCS Full Simulator (Read/Write) running on port 7002")
    await StartAsyncTcpServer(context=context, address=("0.0.0.0", 7002))

if __name__ == "__main__":
    asyncio.run(main())