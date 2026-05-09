import math
import os
import threading
import time
from dataclasses import dataclass

import yaml
from cpppo.server.enip import client
from cpppo.server.enip.main import main as enip_main_function

_DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 6003},
    "simulator": {
        "tick_s": 0.1,
        "init": {"motor_control": 0, "target_speed": 1200},
        "physics": {"accel_per_tick": 50.5, "decel_per_tick": 30.2, "fault_rpm_threshold": 1800},
    },
    "tags": {
        "name": "Name",
        "mode": "Mode",
        "motor_control": "Motor_Control",
        "motor_run": "Motor_Run",
        "motor_fault": "Motor_Fault",
        "target_speed": "Target_Speed",
        "current_speed": "Current_Speed",
        "current_amps": "Current_Amps",
        "err_scaled": "ErrScaled",
        "runtime_ticks": "RuntimeTicks",
        "encoder": "Encoder",
        "energy_kwh": "Energy_kWh",
        "busv_x10": "BusV_x10",
        "rpm_bcd": "RPM_BCD",
        "current_temperature": "Current_Temperature",
    },
}


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def load_config() -> dict:
    cfg = {
        "server": dict(_DEFAULT_CONFIG["server"]),
        "simulator": {
            "tick_s": _DEFAULT_CONFIG["simulator"]["tick_s"],
            "init": dict(_DEFAULT_CONFIG["simulator"]["init"]),
            "physics": dict(_DEFAULT_CONFIG["simulator"]["physics"]),
        },
        "tags": dict(_DEFAULT_CONFIG["tags"]),
    }

    path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, user_cfg)
    return cfg


CONFIG = load_config()
HOST = str(CONFIG["server"]["host"])
PORT = int(CONFIG["server"]["port"])
SIM = CONFIG["simulator"]
TAG = CONFIG["tags"]

# 這裡用 CIP Tag 方式提供資料（Logix-like tags）
# 型別參考（cpppo/cpppo.enip）：BOOL/SINT/INT/DINT/LINT/REAL/LREAL/STRING
#
# 對齊其他 motor simulator 語意：
# - Motor_Control (BOOL)  : Y0（啟動/停止命令）
# - Motor_Run (BOOL)      : X0（運轉回授）
# - Motor_Fault (BOOL)    : M10（RPM > 1800 觸發）
# - Target_Speed (INT)    : 目標 RPM
# - Current_Speed (REAL)  : 目前 RPM（float32）
# - Current_Amps (REAL)   : 目前電流（float32）
# - ErrScaled (INT)       : (target - rpm) * 100（int16 語意，這裡用 INT）
# - RuntimeTicks (DINT)   : tick 計數（每 0.1s +1）
# - Encoder (DINT)        : encoder 演示（int32）
# - Energy_kWh (LREAL)    : 累積電能（float64）
# - BusV_x10 (INT)        : DC Bus 電壓×10（uint16 語意，這裡用 INT）
# - RPM_BCD (INT)         : 0..9999 packed BCD（uint16 語意，這裡用 INT）
TAGS = [
    f"{TAG['motor_control']}=BOOL:{int(SIM['init'].get('motor_control', 0))}",
    f"{TAG['motor_run']}=BOOL:0",
    f"{TAG['motor_fault']}=BOOL:0",
    f"{TAG['mode']}=SINT:0",
    f"{TAG['name']}=STRING:'EIP_MOTOR_SIM'",
    f"{TAG['target_speed']}=INT:{int(SIM['init'].get('target_speed', 1200))}",
    f"{TAG['current_speed']}=REAL:0.0",
    f"{TAG['current_amps']}=REAL:0.0",
    f"{TAG['err_scaled']}=INT:0",
    f"{TAG['runtime_ticks']}=DINT:0",
    f"{TAG['encoder']}=DINT:0",
    f"{TAG['energy_kwh']}=LREAL:0.0",
    f"{TAG['busv_x10']}=INT:3800",
    f"{TAG['rpm_bcd']}=INT:0",
    f"{TAG['current_temperature']}=REAL:25.0",
]


def _bcd_pack_u16_u9999(value: float) -> int:
    v = int(max(0, min(9999, round(value))))
    d0 = (v // 1000) % 10
    d1 = (v // 100) % 10
    d2 = (v // 10) % 10
    d3 = v % 10
    return ((d0 & 0xF) << 12) | ((d1 & 0xF) << 8) | ((d2 & 0xF) << 4) | (d3 & 0xF)


@dataclass
class MotorState:
    rpm: float = 0.0
    ticks: int = 0
    encoder: int = 0
    energy_kwh: float = 0.0


def _read_tags(conn, names: list[str]) -> dict[str, object]:
    ops = client.parse_operations(names)
    out: dict[str, object] = {}
    for _, descr, _, _, status, value in conn.pipeline(ops):
        if status == 0:
            out[str(descr)] = value
    return out


def _write_tags(conn, operations: list[str]) -> None:
    ops = client.parse_operations(operations)
    for _ in conn.pipeline(ops):
        pass


def motor_loop(server_host: str, server_port: int, stop_event: threading.Event) -> None:
    """
    透過 EtherNet/IP client 迴圈讀/寫 tags，讓數值隨 Motor_Control/Target_Speed 更新。
    這樣可以避免直接碰 cpppo server 內部資料結構，並且跟真實客戶端行為一致。
    """
    st = MotorState()

    # 等 server 起來（簡單延遲，避免首次連線失敗）
    time.sleep(0.5)

    while not stop_event.is_set():
        try:
            with client.connector(host=server_host, port=server_port, timeout=1.0) as conn:
                while not stop_event.is_set():
                    r = _read_tags(conn, [TAG["motor_control"], TAG["target_speed"]])
                    motor_control = bool(r.get(TAG["motor_control"], 0))
                    target = int(r.get(TAG["target_speed"], 0))

                    # 物理：每 0.1s tick
                    if motor_control:
                        if st.rpm < target:
                            st.rpm += float(SIM["physics"].get("accel_per_tick", 50.5))
                        motor_run = 1
                    else:
                        if st.rpm > 0:
                            st.rpm -= float(SIM["physics"].get("decel_per_tick", 30.2))
                        if st.rpm <= 0:
                            st.rpm = 0.0
                            motor_run = 0
                        else:
                            motor_run = 1

                    # 限幅
                    st.rpm = float(max(0.0, min(30000.0, st.rpm)))

                    # 電流（演示）：轉速越高電流越大，加上些微波動
                    if st.rpm > 0:
                        amps = (st.rpm / 150.0) + (int(time.time()) % 3)
                    else:
                        amps = 0.0

                    # 其他衍生量（對齊 melsec/fins 語意）
                    err_scaled = int(round((target - st.rpm) * 100))
                    err_scaled = max(-32768, min(32767, err_scaled))
                    st.ticks = (st.ticks + 1) & 0xFFFFFFFF
                    st.encoder = int(max(-2147483648, min(2147483647, st.encoder + int(round(st.rpm * 16.7)))))
                    st.energy_kwh += abs(st.rpm) * abs(amps) * (0.1 / 3.6e9)
                    bus_v_x10 = int(round(3800 + (st.rpm / 1200.0) * 15 + (st.ticks % 7)))
                    bus_v_x10 = max(0, min(65535, bus_v_x10))
                    rpm_bcd = _bcd_pack_u16_u9999(st.rpm)
                    fault_threshold = float(SIM["physics"].get("fault_rpm_threshold", 1800))
                    fault = 1 if st.rpm > fault_threshold else 0

                    # 溫度（演示）：隨電流上升，並緩慢回復
                    temp_base = 25.0 + min(60.0, abs(amps) * 0.3)
                    temp_wave = math.sin(time.time() / 5.0) * 0.3
                    temperature = float(temp_base + temp_wave)

                    _write_tags(
                        conn,
                        [
                            f"{TAG['motor_run']}=(BOOL){motor_run}",
                            f"{TAG['motor_fault']}=(BOOL){fault}",
                            f"{TAG['current_speed']}=(REAL){st.rpm}",
                            f"{TAG['current_amps']}=(REAL){float(amps)}",
                            f"{TAG['err_scaled']}=(INT){err_scaled}",
                            f"{TAG['runtime_ticks']}=(DINT){st.ticks}",
                            f"{TAG['encoder']}=(DINT){st.encoder}",
                            f"{TAG['energy_kwh']}=(LREAL){float(st.energy_kwh)}",
                            f"{TAG['busv_x10']}=(INT){bus_v_x10}",
                            f"{TAG['rpm_bcd']}=(INT){rpm_bcd}",
                            f"{TAG['current_temperature']}=(REAL){temperature}",
                        ],
                    )

                    time.sleep(float(SIM.get("tick_s", 0.1)))
        except Exception:
            # 連線失敗/重連：稍等再試
            time.sleep(0.5)


def start_server() -> None:
    print("--- EtherNet/IP (CIP Tag) Motor Simulator Starting ---")
    print(f"Listening on {HOST}:{PORT}")
    enip_main_function(host=HOST, port=PORT, tags=TAGS)


if __name__ == "__main__":
    stop_event = threading.Event()
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    logic_thread = threading.Thread(target=motor_loop, args=("127.0.0.1", PORT, stop_event), daemon=True)
    logic_thread.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        stop_event.set()
        print("\nServer Offline.")