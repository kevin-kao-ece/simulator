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
        raw = self.read_d_words(0, 12)
        if not raw: return None
        
        # Mapping based on our agreed Address Map
        res = {
            "Motor_Control": struct.unpack('>H', raw[0:2])[0],
            "Target_RPM": struct.unpack('>i', raw[2:6])[0],
            "Run_Status": struct.unpack('>H', raw[6:8])[0],
            "Current_RPM": struct.unpack('>i', raw[8:12])[0],
            "Temp": struct.unpack('>f', raw[12:16])[0],
            "Start_Timestamp": struct.unpack('>q', raw[16:24])[0]
        }
        return res

if __name__ == "__main__":
    client = OmronFinsClient('20.6.35.107')
    
    print("--- Sending Start Command (D0 = 1) ---")
    client.write_d_word(0, [1])
    data = client.read_all_data()
    
    try:
        for _ in range(20):
            data = client.read_all_data()
            if data:
                ts = data['Start_Timestamp']
                dt = datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts > 0 else "N/A"
                print(f"RPM: {data['Current_RPM']} | Temp: {data['Temp']:.1f} | Started: {dt}")
            time.sleep(1)
        
        print("--- Sending Start Command (D0 = 0) ---")
        client.write_d_word(0, [0])
        for _ in range(10):
            data = client.read_all_data()
            if data:
                ts = data['Start_Timestamp']
                dt = datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts > 0 else "N/A"
                print(f"RPM: {data['Current_RPM']} | Temp: {data['Temp']:.1f} | Started: {dt}")
            time.sleep(1)
    finally:
        print("--- Sending Stop Command (D0 = 0) ---")
        client.write_d_word(0, [0])