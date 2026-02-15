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
# New Writeable Tag
rs485BaudRate        = 12364  # Uint16, writable, no random generation

# Original Tags
l1Voltage            = 4097
l1Current            = 4098
l1Power              = 4099
l1Frequency          = 4101
l2Voltage            = 4102
l2Current            = 4103
l2Power              = 4104
l2Frequency          = 4106
l3Voltage            = 4107
l3Current            = 4108
l3Power              = 4109
l3Frequency          = 4111
mppt1Voltage         = 4112
mppt1Current         = 4113
mppt1Power           = 4114
mppt2Voltage         = 4116
mppt2Current         = 4117
mppt2Power           = 4118
mppt3Voltage         = 4120
mppt3Current         = 4121
mppt3Power           = 4122
innerTemp            = 4124
invertMode           = 4125
errorCode1           = 4126
errorCode2           = 4127
errorCode3           = 4128
totalEnergy          = 4129
todayEnergy          = 4135
gridTotalActivePower = 4151
gridTodayReactivePower = 4153
pvTodayPeakPower     = 4155
powerFactor          = 4157
mppt4Voltage         = 4158
mppt4Current         = 4159
mppt4Power           = 4160
pvTotalInputPower    = 4168
systemWorkStatus     = 4170
mppt5Voltage         = 4224
mppt5Current         = 4225
mppt5Power           = 4226
mppt6Voltage         = 4228
mppt6Current         = 4229
mppt6Power           = 4230
string1EnergyTotal   = 4272
string1EnergyToday   = 4274
string2EnergyTotal   = 4276
string2EnergyToday   = 4278
string3EnergyTotal   = 4280
string3EnergyToday   = 4282
string4EnergyTotal   = 4284
string4EnergyToday   = 4286
string5EnergyTotal   = 4288
string5EnergyToday   = 4290
string6EnergyTotal   = 4292
string6EnergyToday   = 4294
l1WattOfGrid         = 4864
l2WattOfGrid         = 4866
l3WattOfGrid         = 4868
accuEnergyOfImport   = 4870
accuEnergyOfExport   = 4872
l1WattOfLoad         = 4874

# =========================================================
# Helpers
# =========================================================
def to_m(val, multiplier=1):
    return [int(val * multiplier)]

def bin_to_int(bin_input):
    if isinstance(bin_input, bytes):
        bin_input = bin_input.decode()
    return [int(bin_input, 2)]

# =========================================================
# Register Update Task
# =========================================================
async def update_holding_registers(context):
    slave_id = 0x00 
    
    # Initialize the Baud Rate once (e.g., 9600)
    context[slave_id].setValues(3, rs485BaudRate, [9600])
    
    while True:
        try:
            # Update only the "dynamic" registers
            context[slave_id].setValues(3, l1Voltage, to_m(random.uniform(220, 240), 10))
            context[slave_id].setValues(3, l1Current, to_m(random.uniform(4, 6), 10))
            context[slave_id].setValues(3, l1Power,   to_m(random.uniform(1000, 3000)))
            
            # Monitoring the writable tag in logs to see if a client changed it
            current_baud = context[slave_id].getValues(3, rs485BaudRate, 1)[0]
            
            logger.info(f"System Active | BaudRate: {current_baud} | L1: {context[slave_id].getValues(3, l1Voltage, 1)[0]/10}V")

        except Exception as e:
            logger.error(f"Update Loop Error: {e}")

        await asyncio.sleep(3)

# =========================================================
# Main
# =========================================================
async def main():
    # HR_SIZE 65535 covers the entire register space
    block = ModbusSequentialDataBlock(0, [0] * 65535)
    device = ModbusDeviceContext(hr=block)
    context = ModbusServerContext(devices=device, single=True)

    asyncio.create_task(update_holding_registers(context))

    logger.info("Starting Modbus TCP Server on 0.0.0.0:7002")
    # This server will now accept Function Code 06 (Write Single) 
    # and 16 (Write Multiple) from your client.
    await StartAsyncTcpServer(
        context=context,
        address=("0.0.0.0", 7002),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")