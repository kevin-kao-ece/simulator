import snap7
import time
import math
import threading
import ctypes
from snap7.util import set_real, set_int, set_bool

def start_s7_server():
    server = snap7.server.Server()
    
    # 1. Prepare memory buffer
    size = 1024
    db1_data = (ctypes.c_ubyte * size)()
    
    # 2. THE ULTIMATE FIX FOR 'Unknown Area code'
    # We try to get the library's internal definition of srvAreaDB
    try:
        # In many versions, this is an object that contains the correct .value
        from snap7.types import srvAreaDB
        area_to_register = srvAreaDB
    except:
        # If the import fails, we use the integer 0 wrapped as a c_int
        # 0 is the internal index for srvAreaDB in the Snap7 C source code
        area_to_register = ctypes.c_int(0)

    try:
        # Register Data Block 1
        server.register_area(area_to_register, 1, db1_data)
        print(f"✅ Registered DB1 successfully.")
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        # Final desperate attempt: raw integer 0
        server.register_area(0, 1, db1_data)

    # 3. Start the server
    try:
        server.start_to('0.0.0.0', 6002)
    except:
        server.start() # Defaults to 102 (needs sudo)

    print("🚀 S7 Simulator is LIVE on Port 6002")

    def simulate_data():
        angle = 0.0
        while True:
            try:
                set_real(db1_data, 0, math.sin(angle) * 100)
                set_int(db1_data, 4, int(time.time()) % 32767)
                set_bool(db1_data, 6, 0, (int(time.time()) % 2 == 0))
                angle += 0.1
                time.sleep(1)
            except: break

    threading.Thread(target=simulate_data, daemon=True).start()

    try:
        while True:
            event = server.pick_event()
            if event:
                print(f"[{time.strftime('%H:%M:%S')}] {server.event_text(event)}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.stop()
        server.destroy()

if __name__ == "__main__":
    start_s7_server()