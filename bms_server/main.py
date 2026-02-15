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
HR_NOMINAL_AH        = 1440
HR_STORED_AH         = 1441
HR_ACTUAL_CURRENT   = 1442
HR_PACK_VOLTAGE     = 1443
HR_MAX_CELL_VOLT    = 1444
HR_MIN_CELL_VOLT    = 1445
HR_MAX_CELL_TEMP    = 1446
HR_MIN_CELL_TEMP    = 1447
HR_SOH              = 1450
HR_WORKING_STATUS   = 1451
HR_ALARM_STATUS     = 1452

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
        return 3.0 + soc * 1.2  # 3.0V ~ 4.2V

    def step(self, dt=1.0):
        # -------- Current --------
        self.current = random.uniform(-30, 30)

        # -------- A-Hr --------
        delta_ah = self.current * dt / 3600.0
        self.stored_ah = max(
            0.0, min(self.nominal_ah, self.stored_ah - delta_ah)
        )

        # -------- Voltage --------
        soc = self._soc()
        ocv_cell = self._ocv(soc)
        self.pack_voltage = (
            ocv_cell * self.cell_count
            - self.current * self.internal_resistance
        )

        cell_voltages = [
            ocv_cell + random.uniform(-0.03, 0.03)
            for _ in range(self.cell_count)
        ]

        # -------- Temperature --------
        temp_rise = abs(self.current) * 0.02
        cell_temps = [
            self.temperature_base + temp_rise + random.uniform(-1.5, 1.5)
            for _ in range(self.cell_count)
        ]

        max_v, min_v = max(cell_voltages), min(cell_voltages)
        max_t, min_t = max(cell_temps), min(cell_temps)

        # -------- Alarm Status --------
        alarm = 0
        if max_v > 4.20: alarm |= 1 << 0
        if min_v < 3.00: alarm |= 1 << 1
        if max_t > 60: alarm |= 1 << 2
        if self.current > 50: alarm |= 1 << 3
        if min_t < 0: alarm |= 1 << 4
        if (max_v - min_v) > 0.08: alarm |= 1 << 5
        if self.current < -40: alarm |= 1 << 6

        # -------- Working Status --------
        status = 0
        if self.permanent_lock:
            status |= 1 << 7
        elif alarm:
            status |= 1 << 6
        else:
            status |= 1 << 1  # Power On
            if abs(self.current) < 1:
                status |= 1 << 3
            elif self.current > 0:
                status |= 1 << 4
            else:
                status |= 1 << 5

        if max_v > 4.35 or max_t > 80:
            self.permanent_lock = True

        # -------- SOH --------
        self.cycle_ah += abs(delta_ah)
        if self.cycle_ah >= self.nominal_ah:
            self.cycle_ah = 0
            self.soh = max(70.0, self.soh - 0.05)

        return {
            "nom_ah": self.nominal_ah,
            "sto_ah": self.stored_ah,
            "cur": self.current,
            "pack_v": self.pack_voltage,
            "max_v": max_v,
            "min_v": min_v,
            "max_t": max_t,
            "min_t": min_t,
            "soh": self.soh,
            "status": status,
            "alarm": alarm,
        }

# =========================================================
# Modbus Register Update Task (One-by-One)
# =========================================================
async def update_holding_registers(device_ctx):
    sim = BatterySimulator()

    while True:
        data = sim.step(1.0)

        device_ctx.setValues(3, HR_NOMINAL_AH,      [int(data["nom_ah"] * 10)])
        device_ctx.setValues(3, HR_STORED_AH,       [int(data["sto_ah"] * 10)])
        device_ctx.setValues(3, HR_ACTUAL_CURRENT, [int(data["cur"] * 10) & 0xFFFF])
        device_ctx.setValues(3, HR_PACK_VOLTAGE,   [int(data["pack_v"] * 100)])
        device_ctx.setValues(3, HR_MAX_CELL_VOLT,  [int(data["max_v"] * 1000)])
        device_ctx.setValues(3, HR_MIN_CELL_VOLT,  [int(data["min_v"] * 1000)])
        device_ctx.setValues(3, HR_MAX_CELL_TEMP,  [int(data["max_t"] * 10)])
        device_ctx.setValues(3, HR_MIN_CELL_TEMP,  [int(data["min_t"] * 10)])
        device_ctx.setValues(3, HR_SOH,             [int(data["soh"] * 100)])
        device_ctx.setValues(3, HR_WORKING_STATUS, [data["status"]])
        device_ctx.setValues(3, HR_ALARM_STATUS,   [data["alarm"]])

        logger.info(
            "I=%.1fA V=%.1fV SOC=%.1f%% Status=0x%04X Alarm=0x%04X",
            data["cur"], data["pack_v"],
            (data["sto_ah"] / data["nom_ah"]) * 100,
            data["status"], data["alarm"]
        )

        await asyncio.sleep(3)

# =========================================================
# Main
# =========================================================
async def main():
    HR_SIZE = 65535

    device = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(0, [0] * HR_SIZE)
    )

    context = ModbusServerContext(
        devices=device,
        single=True
    )

    asyncio.create_task(update_holding_registers(device))

    logger.info("Starting Modbus TCP BMS Server on port 502")
    await StartAsyncTcpServer(
        context=context,
        address=("0.0.0.0", 7001),
    )

if __name__ == "__main__":
    asyncio.run(main())
