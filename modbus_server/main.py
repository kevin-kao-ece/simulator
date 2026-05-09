#!/usr/bin/env python3
"""Motor Modbus/TCP simulator.

Supports pymodbus 2.5.x (e.g. sync server under pymodbus.server.sync) and
pymodbus 3.8+ where ModbusSlaveContext was renamed ModbusDeviceContext and
ModbusServerContext uses ``devices=`` instead of ``slaves=``.
"""
import logging
import struct
import threading
import time


def _require_compatible_pymodbus():
    """pymodbus 3.13+ removes the classic datastore API this simulator uses (see ctx.store)."""
    try:
        import pymodbus
    except ImportError:
        return
    raw = getattr(pymodbus, "__version__", "0").split("+")[0]
    nums = []
    for tok in raw.split("."):
        if tok.isdigit():
            nums.append(int(tok))
        else:
            break
    major = nums[0] if nums else 0
    minor = nums[1] if len(nums) > 1 else 0
    if major > 3 or (major == 3 and minor >= 13):
        raise RuntimeError(
            "This motor simulator needs pymodbus>=3.8,<3.13 (or pymodbus 2.5.x). "
            "Version 3.13+ changed ModbusSequentialDataBlock / ModbusDeviceContext "
            "and is incompatible with this script. Pin e.g. pymodbus==3.12.4 in requirements.txt."
        )


from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

try:
    from pymodbus.datastore import ModbusSlaveContext
except ImportError:  # pymodbus >= 3.11
    from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext

try:
    from pymodbus.server.sync import StartTcpServer
except ImportError:
    from pymodbus.server import StartTcpServer


def _make_server_context(device: ModbusSlaveContext) -> ModbusServerContext:
    try:
        return ModbusServerContext(slaves=device, single=True)
    except TypeError:
        return ModbusServerContext(devices=device, single=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Motor-Modbus")

# =========================================================
# Modbus Map（對齊其他 motor simulator 語意）
# =========================================================
# Bits:
# - Coil 0        : Y0 (Motor_Control) 啟動/停止
# - Discrete 0    : X0 (Motor_Run)     運轉回授
# - Discrete 10   : M10 (Fault)        RPM > 1800 置位
#
# Holding Registers（0-based address）:
# - HR 0          : legacy start mirror（bit0==1 視為啟動；與 Coil 0 為 OR，不會單靠 HR0=0 清掉外部寫線圈）
# - HR 10..11     : D10..D11 current_rpm  (float32, little-endian bytes)
# - HR 12..13     : D12..D13 current_amps (float32, little-endian bytes)
# - HR 14         : D14 target_rpm        (uint16)
# - HR 15         : D15 err_scaled        (int16) (target-rpm)*100
# - HR 16..17     : D16..D17 runtime_ticks(uint32)
# - HR 18..19     : D18..D19 encoder_i32  (int32)
# - HR 20..23     : D20..D23 energy_kwh   (float64)
# - HR 24         : D24 bus_v_x10         (uint16)
# - HR 25         : D25 rpm_bcd           (uint16, 0..9999 packed)


class LoggingDataBlock(ModbusSequentialDataBlock):
    def __init__(self, address, values):
        super().__init__(address, values)
        self.internal_update = False

    def setValues(self, address, values):
        if not self.internal_update:
            logger.info("EXTERNAL WRITE | Address=%s | Data=%s", address, values)
        super().setValues(address, values)


def _set_values_internal(ctx: ModbusSlaveContext, fx: int, addr: int, vals: list[int]) -> None:
    store_key = {1: "c", 2: "d", 3: "h", 4: "i"}[fx]
    block = ctx.store[store_key]
    if hasattr(block, "internal_update"):
        block.internal_update = True
    ctx.setValues(fx, addr, vals)
    if hasattr(block, "internal_update"):
        block.internal_update = False


def _u16(v: int) -> int:
    return int(v) & 0xFFFF


def _i16(v: int) -> int:
    return struct.unpack(">H", struct.pack(">h", int(v)))[0]


def _pack_le_f32_to_u16s(value: float) -> list[int]:
    b = struct.pack("<f", float(value))  # 4 bytes, little-endian
    return [struct.unpack(">H", b[0:2])[0], struct.unpack(">H", b[2:4])[0]]


def _pack_le_u32_to_u16s(value: int) -> list[int]:
    b = struct.pack("<I", int(value) & 0xFFFFFFFF)
    return [struct.unpack(">H", b[0:2])[0], struct.unpack(">H", b[2:4])[0]]


def _pack_le_i32_to_u16s(value: int) -> list[int]:
    b = struct.pack("<i", int(value))
    return [struct.unpack(">H", b[0:2])[0], struct.unpack(">H", b[2:4])[0]]


def _pack_le_f64_to_u16s(value: float) -> list[int]:
    b = struct.pack("<d", float(value))
    return [
        struct.unpack(">H", b[0:2])[0],
        struct.unpack(">H", b[2:4])[0],
        struct.unpack(">H", b[4:6])[0],
        struct.unpack(">H", b[6:8])[0],
    ]


def _bcd_pack_u16_u9999(value: float) -> int:
    v = max(0, min(9999, int(round(value))))
    d = [(v // 1000) % 10, (v // 100) % 10, (v // 10) % 10, v % 10]
    w = 0
    for n in d:
        w = (w << 4) | (n & 0xF)
    return w


def motor_update_loop(device: ModbusSlaveContext, stop_event: threading.Event):
    current_rpm = 0.0
    runtime_ticks = 0
    encoder_i32 = 0
    energy_kwh = 0.0

    # init defaults (align others)
    _set_values_internal(device, 3, 14, [_u16(1200)])  # Target RPM
    _set_values_internal(device, 1, 0, [1])  # Coil 0 == Y0 default ON

    while not stop_event.is_set():
        # --- Read control ---
        # 外部 FC5/FC15 寫入的 Coil 0（Y0），以及 HR0 bit0 傳統鏡像，兩者任一為真即視為「啟動命令」。
        # 舊版 bug：HR0 bit0==0 時每拍強制把 Coil 清 0，會立刻抹掉 Northbound 對 Coil 的寫入，馬達永遠不起來，
        # OPC UA 輪詢讀回也與剛寫入的值不一致 → ERR_TIMEOUT / Northbound write confirm timeout。
        coil_direct = int(device.getValues(1, 0, count=1)[0]) & 1
        legacy_word0 = int(device.getValues(3, 0, count=1)[0]) & 0xFFFF
        legacy_start = 1 if (legacy_word0 & 0x0001) else 0
        coil_y0 = 1 if (coil_direct or legacy_start) else 0
        _set_values_internal(device, 1, 0, [coil_y0])

        target_rpm = int(device.getValues(3, 14, count=1)[0]) & 0xFFFF

        # --- Physics (tick 0.1s) ---
        if coil_y0 == 1:
            if current_rpm < target_rpm:
                current_rpm += 50.5
            motor_run = 1
        else:
            if current_rpm > 0:
                current_rpm -= 30.2
            if current_rpm <= 0:
                current_rpm = 0.0
                motor_run = 0
            else:
                motor_run = 1

        current_rpm = float(max(0.0, min(30000.0, current_rpm)))

        if current_rpm > 0:
            current_amps = (current_rpm / 150.0) + (int(time.time()) % 3)
        else:
            current_amps = 0.0

        err_scaled = int(round((target_rpm - current_rpm) * 100))
        err_scaled = max(-32768, min(32767, err_scaled))
        runtime_ticks = (runtime_ticks + 1) & 0xFFFFFFFF
        encoder_i32 += int(round(current_rpm * 16.7))
        encoder_i32 = max(-2147483648, min(2147483647, encoder_i32))
        energy_kwh += abs(current_rpm) * abs(current_amps) * (0.1 / 3.6e9)
        bus_v_x10 = int(round(3800 + (current_rpm / 1200.0) * 15 + (runtime_ticks % 7)))
        bus_v_x10 = max(0, min(65535, bus_v_x10))
        rpm_bcd = _bcd_pack_u16_u9999(current_rpm)

        fault = 1 if current_rpm > 1800 else 0

        # --- Publish status ---
        _set_values_internal(device, 2, 0, [motor_run])   # Discrete 0 == X0
        _set_values_internal(device, 2, 10, [fault])      # Discrete 10 == M10

        _set_values_internal(device, 3, 10, _pack_le_f32_to_u16s(current_rpm))       # D10..11
        _set_values_internal(device, 3, 12, _pack_le_f32_to_u16s(current_amps))      # D12..13
        _set_values_internal(device, 3, 15, [_i16(err_scaled)])                       # D15
        _set_values_internal(device, 3, 16, _pack_le_u32_to_u16s(runtime_ticks))     # D16..17
        _set_values_internal(device, 3, 18, _pack_le_i32_to_u16s(encoder_i32))       # D18..19
        _set_values_internal(device, 3, 20, _pack_le_f64_to_u16s(energy_kwh))        # D20..23
        _set_values_internal(device, 3, 24, [_u16(bus_v_x10)])                        # D24
        _set_values_internal(device, 3, 25, [_u16(rpm_bcd)])                           # D25

        time.sleep(0.1)

# =========================================================
# Main
# =========================================================
def main():
    _require_compatible_pymodbus()
    # 建立涵蓋常用範圍的資料區塊；模擬器用途，直接給足夠大即可
    size = 2000
    device = ModbusSlaveContext(
        co=LoggingDataBlock(0, [0] * size),  # coils
        di=LoggingDataBlock(0, [0] * size),  # discrete inputs
        hr=LoggingDataBlock(0, [0] * size),  # holding registers
        ir=LoggingDataBlock(0, [0] * size),  # input registers (未用，先保留)
    )

    context = _make_server_context(device)
    stop_event = threading.Event()
    t = threading.Thread(target=motor_update_loop, args=(device, stop_event), daemon=True)
    t.start()

    logger.info("Starting Modbus TCP Motor Simulator on port 16001")
    try:
        StartTcpServer(context=context, address=("0.0.0.0", 16001))
    finally:
        stop_event.set()

if __name__ == "__main__":
    main()