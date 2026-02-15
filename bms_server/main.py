#!/usr/bin/env python3
import asyncio
import random
import logging

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusDeviceContext,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer

# =========================================================
# Logging
# =========================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BMS-Modbus")

# =========================================================
# Modbus Holding Register Map
# =========================================================
# Read Only (Status)
HR_NOMINAL_AH       = 1440
HR_STORED_AH        = 1441
HR_ACTUAL_CURRENT   = 1442
HR_PACK_VOLTAGE     = 1443
HR_MAX_CELL_VOLT    = 1444
HR_MIN_CELL_VOLT    = 1445
HR_MAX_CELL_TEMP    = 1446
HR_MIN_CELL_TEMP    = 1447
HR_CELL_POS_LOW     = 1448  # Cell position Max/Min (Low Byte)
HR_VMS_ID_TEMP      = 1449  # VMS ID of Max/Min Temp
HR_SOH              = 1450
HR_WORKING_STATUS   = 1451
HR_ALARM_STATUS     = 1452
HR_CELL_POS_HIGH    = 1453  # Cell position Max/Min (High Byte)

# Writable (Commands) - Initialized to 0
CMD_BALANCE_MODE    = 1596  # cmd04
CMD_05              = 1598  # cmd05
CMD_COMPENSATION    = 1599  # cmd07 (0x25)
CMD_FORCE_PRECHG    = 1642  # cmd06
CMD_FORCE_PWR_OFF   = 6452  # cmd03
CMD_RELEASE_PWR_OFF = 10077 # cmd02
CMD_DECODE          = 15115 # cmd01

# =========================================================
# Battery Simulator
# =========================================================
class BatterySimulator:
    def __init__(self):
        self.nominal_ah = 100.0
        self.stored_ah = 80.0
        self.cell_count = 12
        self.internal_resistance = 0.02
        self.temperature_base = 25.0
        self.current = 0.0
        self.pack_voltage = 0.0
        self.soh = 100.0
        self.cycle_ah = 0.0
        self.permanent_lock = False

    def _soc(self):
        return max(0.0, min(1.0, self.stored_ah / self.nominal_ah))

    def _ocv(self, soc):
        return 3.0 + soc * 1.2

    def step(self, dt=1.0):
        self.current = random.uniform(-30, 30)
        delta_ah = self.current * dt / 3600.0
        self.stored_ah = max(0.0, min(self.nominal_ah, self.stored_ah - delta_ah))

        soc = self._soc()
        ocv_cell = self._ocv(soc)
        self.pack_voltage = (ocv_cell * self.cell_count - self.current * self.internal_resistance)

        # Voltages and Indices
        cell_voltages = [ocv_cell + random.uniform(-0.03, 0.03) for _ in range(self.cell_count)]
        max_v, min_v = max(cell_voltages), min(cell_voltages)
        idx_max_v, idx_min_v = cell_voltages.index(max_v) + 1, cell_voltages.index(min_v) + 1

        # Temperatures and VMS IDs
        temp_rise = abs(self.current) * 0.02
        cell_temps = [self.temperature_base + temp_rise + random.uniform(-1.5, 1.5) for _ in range(self.cell_count)]
        max_t, min_t = max(cell_temps), min(cell_temps)
        
        # Logic for Packed Bytes (Position)
        # Low Byte (1448): High=MaxIdx, Low=MinIdx
        pos_low = (idx_max_v << 8) | (idx_min_v & 0xFF)
        # High Byte (1453): Using similar logic or as a placeholder for extension
        pos_high = (idx_max_v << 8) | (idx_min_v & 0xFF)

        # Alarm/Status Logic
        alarm = 0
        if max_v > 4.20: alarm |= 1 << 0
        if min_v < 3.00: alarm |= 1 << 1
        if max_t > 60: alarm |= 1 << 2
        
        status = 0x0002 if not alarm else 0x0040 # Simplified status for brevity

        return {
            "nom_ah": self.nominal_ah, "sto_ah": self.stored_ah, "cur": self.current,
            "pack_v": self.pack_voltage, "max_v": max_v, "min_v": min_v,
            "max_t": max_t, "min_t": min_t, "soh": self.soh, "status": status, "alarm": alarm,
            "pos_low": pos_low, "pos_high": pos_high, "vms_id": 1 # Hardcoded VMS ID
        }

# =========================================================
# Modbus Register Update Task
# =========================================================
async def update_holding_registers(device_ctx):
    sim = BatterySimulator()

    while True:
        data = sim.step(1.0)
        
        # Update Read-Only Status Registers
        updates = {
            HR_NOMINAL_AH:     int(data["nom_ah"] * 10),
            HR_STORED_AH:      int(data["sto_ah"] * 10),
            HR_ACTUAL_CURRENT: int(data["cur"] * 10) & 0xFFFF,
            HR_PACK_VOLTAGE:   int(data["pack_v"] * 100),
            HR_MAX_CELL_VOLT:  int(data["max_v"] * 1000),
            HR_MIN_CELL_VOLT:  int(data["min_v"] * 1000),
            HR_MAX_CELL_TEMP:  int(data["max_t"] * 10),
            HR_MIN_CELL_TEMP:  int(data["min_t"] * 10),
            HR_CELL_POS_LOW:   data["pos_low"],
            HR_VMS_ID_TEMP:    data["vms_id"],
            HR_SOH:            int(data["soh"] * 100),
            HR_WORKING_STATUS: data["status"],
            HR_ALARM_STATUS:   data["alarm"],
            HR_CELL_POS_HIGH:  data["pos_high"],
        }

        for addr, value in updates.items():
            device_ctx.setValues(3, addr, [value])

        logger.info("BMS Heartbeat: V=%.2fV I=%.1fA SOC=%.1f%%", 
                    data["pack_v"], data["cur"], (data["sto_ah"]/data["nom_ah"])*100)
        await asyncio.sleep(3)

# =========================================================
# Main
# =========================================================
async def main():
    # Use a sparse dictionary-based block if you don't want to allocate 65k zeros, 
    # but for a simulator, a large list is fine.
    HR_SIZE = 20000 
    
    # Initialize all registers (including Writable ones) to 0
    device = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(0, [0] * HR_SIZE)
    )

    context = ModbusServerContext(devices=device, single=True)
    asyncio.create_task(update_holding_registers(device))

    logger.info("Starting Modbus TCP BMS Server on port 7001")
    await StartAsyncTcpServer(context=context, address=("0.0.0.0", 7001))

if __name__ == "__main__":
    asyncio.run(main())