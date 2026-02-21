from __future__ import print_function
from cpppo.server.enip import client
from cpppo.server.enip.main import tags as registered_tags

# Configuration: IP of your simulator (localhost) and the tags you want to hit
HOST = '20.6.35.107'
PORT = 6003

def run_client():
    try:
        tags = ["Motor_Control","Motor_Run","Target_Speed"]
        # 1. Establish a connection using the connector context manager
        with client.connector(host=HOST, port=PORT) as conn:
            print(f"Connected to {HOST}\n" + "-"*30)

            # --- READ EXAMPLE ---
            # Read 'Temperature' and 'Motor_Control'
            # Returns a generator of (tag, value) tuples
            operations = client.parse_operations(tags)
            for index, descr, op, reply, status, value in conn.pipeline(operations):
                # 'descr' is the tag name/description
                # 'value' is the actual data
                print(f"READ: {descr:15} = {value}")

            # --- SINGLE WRITE EXAMPLE ---
            # Format: Tag=(Type)Value
            write_op = client.parse_operations(["Motor_Control=(BOOL)1"])
            for index, descr, op, reply, status, value in conn.pipeline(write_op):
                if status == 0:
                    print(f"SUCCESS: {descr} updated to {value}")
                else:
                    print(f"FAILURE: {descr} failed with status {status}")

            # --- PIPELINE (BULK) WRITE EXAMPLE ---
            # Updating multiple different types at once
            bulk_ops = client.parse_operations([
                "Motor_Control=(BOOL)1",
                "Motor_Run=(BOOL)1",
                "Target_Speed=(INT)1500"
            ])
            print("\nSending Bulk Update...")
            for index, descr, op, reply, status, value in conn.pipeline(bulk_ops):
                if status == 0:
                    print(f"SUCCESS: {descr} updated to {value}")
                else:
                    print(f"FAILURE: {descr} failed with status {status}")
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    run_client()