# services/test_acu_tcp.py
from services.acu_tcp import ACUTcp
from services.acu_driver import build_frame, parse_show

HOST = "192.168.0.1"
PORT = 2217

def main():
    tcp = ACUTcp()
    print(f"Connecting to {HOST}:{PORT} ...")
    tcp.connect(HOST, PORT, timeout=5.0)
    print("Connected:", tcp.is_connected())

    # Change this if your ACU expects a different $show format
    frame = build_frame("show", "1")
    print("Sending:", repr(frame))

    resp = tcp.send_and_read(frame, retries=2, timeout=2.0)
    print("Raw response:", resp)

    parsed = parse_show(resp)
    print("Parsed:")
    for k, v in parsed.items():
        print(f"  {k}: {v}")

    tcp.disconnect()
    print("Disconnected.")

if __name__ == "__main__":
    main()
