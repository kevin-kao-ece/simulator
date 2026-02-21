import socket
import struct
import threading
import time

# D0: Bool (1 Word) - Monot Control
# D1-D2: Int32 (2 Words) - Target RPM
# D3: Bool (1 Word) - Run Status
# D4-D5: Int32 (2 Words) - Current RPM
# D6-D7: Float (2 Words) - Temperature
# D8-D11 Long Int	Start Timestamp (UTC)	4 Words

# 配置
HOST = '0.0.0.0'
PORT = 9600

# 模擬記憶體 (初始化 1000 個 Word)
plc_memory = [0] * 1000

# --- 資料轉換輔助函數 (Big-Endian) ---
def set_float_to_mem(addr, val):
    # 將 float 轉為 2 個 16-bit Words (Big-Endian)
    b = struct.pack('>f', val)
    w1, w2 = struct.unpack('>HH', b)
    plc_memory[addr], plc_memory[addr+1] = w1, w2

def set_int32_to_mem(addr, val):
    # 將 int32 轉為 2 個 16-bit Words (Big-Endian)
    b = struct.pack('>i', int(val))
    w1, w2 = struct.unpack('>HH', b)
    plc_memory[addr], plc_memory[addr+1] = w1, w2

def set_long_to_mem(addr, val):
    """ 將 64-bit Long Integer 寫入 4 個 Words """
    b = struct.pack('>q', int(val)) # q 為 8-byte signed long
    words = struct.unpack('>HHHH', b)
    for i in range(4):
        plc_memory[addr + i] = words[i]

def get_bool(addr):
    return plc_memory[addr] == 1

def get_int32(addr):
    b = struct.pack('>HH', plc_memory[addr], plc_memory[addr+1])
    return struct.unpack('>i', b)[0]

def get_float(addr):
    b = struct.pack('>HH', plc_memory[addr], plc_memory[addr+1])
    return struct.unpack('>f', b)[0]

def get_long(addr):
    b = struct.pack('>HHHH', plc_memory[addr], plc_memory[addr+1], 
                    plc_memory[addr+2], plc_memory[addr+3])
    return struct.unpack('>q', b)[0]

# --- 初始化默認值 ---
plc_memory[0] = 0               # D0: Motor Control (OFF)
set_int32_to_mem(1, 1500)       # D1-D2: Target RPM
plc_memory[3] = 0               # D3: Run Status (STOP)
set_int32_to_mem(4, 0)          # D4-D5: Current RPM
set_float_to_mem(6, 25.0)       # D6-D7: Temp
set_long_to_mem(8, 0)           # D8-D11: Start Timestamp

# --- 物理邏輯模擬執行緒 ---
def plc_logic_loop():
    print("Logic Loop Running...")
    last_motor_state = False # 用於偵測上升邊緣
    
    while True:
        motor_on = get_bool(0)
        target_rpm = get_int32(1)
        current_rpm = get_int32(4)
        current_temp = get_float(6)

        # 偵測啟動瞬間 (D0 從 0 變 1)
        if motor_on and not last_motor_state:
            current_ts = int(time.time()) # UTC Timestamp
            set_long_to_mem(8, current_ts)
            print(f"Motor Started! Timestamp {current_ts} stored in D8-D11")
        
        # 偵測停止瞬間
        if not motor_on and last_motor_state:
            set_long_to_mem(8, 0) # 停止時歸零
            print("Motor Stopped! Timestamp reset.")

        if motor_on:
            plc_memory[3] = 1 # Run Status = True
            if current_rpm < target_rpm:
                set_int32_to_mem(4, min(current_rpm + 50, target_rpm))
            if current_temp < 50.0:
                set_float_to_mem(6, current_temp + 0.5)
        else:
            plc_memory[3] = 0 # Run Status = False
            if current_rpm > 0:
                set_int32_to_mem(4, max(current_rpm - 30, 0))
            if current_temp > 25.0:
                set_float_to_mem(6, max(current_temp - 0.2, 25.0))

        last_motor_state = motor_on
        time.sleep(0.5)

# --- FINS UDP Server --- (同前，省略重複細節但保留核心)
def start_server():
    threading.Thread(target=plc_logic_loop, daemon=True).start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, PORT))
        print(f"OMRON PLC Simulator (LINT Enabled) on UDP {PORT}")
        while True:
            data, addr = s.recvfrom(2048)
            if len(data) < 12: continue
            sa1, sid = data[7], data[9]
            mrc_src = data[10:12]
            print("Client arrived....")
            res_header = bytearray([0xC0, 0x00, 0x02, 0x00, sa1, 0x00, 0x00, 0x01, 0x00, sid])

            if mrc_src == b'\x01\x01': # READ
                start = int.from_bytes(data[13:15], 'big')
                count = int.from_bytes(data[16:18], 'big')
                payload = b''.join(plc_memory[start+i].to_bytes(2, 'big') for i in range(count))
                print(f"Client read start addr:  {start}, count: {count}")
                s.sendto(res_header + b'\x01\x01\x00\x00' + payload, addr)

            elif mrc_src == b'\x01\x02': # WRITE
                start = int.from_bytes(data[13:15], 'big')
                count = int.from_bytes(data[16:18], 'big')
                for i in range(count):
                    plc_memory[start + i] = int.from_bytes(data[18+i*2:20+i*2], 'big')
                print(f"Client write start addr: {start}, count: {count}")
                s.sendto(res_header + b'\x01\x02\x00\x00', addr)

if __name__ == "__main__":
    start_server()