import time
import threading
from cpppo.server.enip.main import main as enip_main_function
from cpppo.server.enip.get_attribute import proxy

# Ethernet/IP (CIP) Data Type Map:
# BOOL  = 1-bit (True/False)
# SINT  = 8-bit Signed Integer (-128 to 127)
# INT   = 16-bit Signed Integer (-32768 to 32767)
# DINT  = 32-bit Signed Integer (Standard PLC register)
# LINT  = 64-bit Signed Integer (Large register)
# REAL  = 32-bit Floating Point (Decimal)
# LREAL = 64-bit Floating Point (Double precision)
# STRING = Character data

tags = [
    "control=BOOL:0",          # Boolean
    "running=BOOL:0",          # Boolean
    "speed=INT:1500",            # 16-bit Integer
    "currentSpeed=INT:0",           # 16-bit Integer
    "Temperature=REAL:25.0",          # 32-bit Integer
    "Machine_Name=STRING:'A01'",     # String data
    "Year=INT:2026",                 # 16-bit Integer
    "Month=SINT:1",                  # 8-bit Integer
    "Day=SINT:1",                    # 8-bit Integer    
    "Time=SINT[3]:0,0,0"             # Array of hh:mm:ss Integers
]

def start_adapter():
    print("--- EtherNet/IP Simulator Starting ---")
    
    enip_main_function(host='0.0.0.0', port=44818, tags=tags)

if __name__ == "__main__":
    try:
        start_adapter()
    except KeyboardInterrupt:
        print("\nServer Offline.")