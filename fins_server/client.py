import socket
import struct
import time
from datetime import datetime

class OmronFinsClient:
    def __init__(self, ip, port=9600):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind to port 0 to let OS pick a random available port (fixes Address in Use)
        self.sock.bind(('', 0))
        
        # FINS Header Constants
        self.ICF = 0x80  # Information Control Field (Request)
        self.RSV = 0x00  # Reserved
        self.GCT = 0x02  # Gateway Count
        self.DNA = 0x00  # Destination Network
        self.DA1 = 0x01  # Destination Node (PLC)
        self.DA2 = 0x00  # Destination Unit
        self.SNA = 0x00  # Source Network
        self.SA1 = 0x0A  # Source Node (PC - 10)
        self.SA2 = 0x00  # Source Unit
        self.SID = 0x00  # Service ID

    def _build_header(self):
        return struct.pack('BBBBBBBBBB', 
            self.ICF, self.RSV, self.GCT, self.DNA, self.DA1, 
            self.DA2, self.SNA, self.SA1, self.SA2, self.SID)

    def write_d_word(self, start_addr, data_words):
        """ data_words should be a list of 16-bit integers """
        header = self._build_header()
        command = b'\x01\x02'  # Memory Area Write
        # Area 0x82 (D), Address (2 bytes), Bit (00), Count (2 bytes)
        params = struct.pack('>BHBH', 0x82, start_addr, 0x00, len(data_words))
        
        payload = b''
        for w in data_words:
            payload += struct.pack('>H', w)
            
        packet = header + command + params + payload
        self.sock.sendto(packet, (self.ip, self.port))
        # Receive response (optional, to clear buffer)
        self.sock.recvfrom(1024)

    def read_d_words(self, start_addr, count):
        header = self._build_header()
        command = b'\x01\x01'  # Memory Area Read
        params = struct.pack('>BHBH', 0x82, start_addr, 0x00, count)
        
        packet = header + command + params
        self.sock.sendto(packet, (self.ip, self.port))
        
        data, _ = self.sock.recvfrom(2048)
        # FINS Response: Header(10) + Command(2) + EndCode(2) + Data...
        if len(data) >= 14:
            end_code = data[12:14]
            if end_code == b'\x00\x00':
                return data[14:]
        return None

    def read_all_data(self):
        # Read a block that covers D10..D25 (16 words)
        raw = self.read_d_words(10, 16)
        if not raw: return None
        
        # Mapping aligned with ../melsec_server motor simulator semantics
        res = {
            "D10_RPM_f32": struct.unpack('<f', raw[0:4])[0],             # D10..D11
            "D12_Amps_f32": struct.unpack('<f', raw[4:8])[0],            # D12..D13
            "D14_TargetRPM_u16": struct.unpack('<H', raw[8:10])[0],      # D14
            "D15_ErrScaled_i16": struct.unpack('<h', raw[10:12])[0],     # D15
            "D16_RuntimeTicks_u32": struct.unpack('<I', raw[12:16])[0],  # D16..D17
            "D18_Encoder_i32": struct.unpack('<i', raw[16:20])[0],       # D18..D19
            "D20_Energy_kWh_f64": struct.unpack('<d', raw[20:28])[0],    # D20..D23
            "D24_BusV_x10_u16": struct.unpack('<H', raw[28:30])[0],      # D24
            "D25_RPM_BCD_u16": struct.unpack('<H', raw[30:32])[0],       # D25
        }
        return res

if __name__ == "__main__":
    client = OmronFinsClient('127.0.0.1')
    
    print("--- Sending Start Command (legacy D0 = 1, mirrors to CIO Y0) ---")
    client.write_d_word(0, [1])
    data = client.read_all_data()
    
    try:
        for _ in range(20):
            data = client.read_all_data()
            if data:
                print(
                    f"RPM: {data['D10_RPM_f32']:.1f} | "
                    f"Amps: {data['D12_Amps_f32']:.2f} | "
                    f"Target: {data['D14_TargetRPM_u16']} | "
                    f"Err: {data['D15_ErrScaled_i16']} | "
                    f"Ticks: {data['D16_RuntimeTicks_u32']}"
                )
            time.sleep(1)
        
        print("--- Sending Start Command (D0 = 0) ---")
        client.write_d_word(0, [0])
        for _ in range(10):
            data = client.read_all_data()
            if data:
                print(
                    f"RPM: {data['D10_RPM_f32']:.1f} | "
                    f"Amps: {data['D12_Amps_f32']:.2f} | "
                    f"Target: {data['D14_TargetRPM_u16']} | "
                    f"Err: {data['D15_ErrScaled_i16']} | "
                    f"Ticks: {data['D16_RuntimeTicks_u32']}"
                )
            time.sleep(1)
    finally:
        print("--- Sending Stop Command (D0 = 0) ---")
        client.write_d_word(0, [0])