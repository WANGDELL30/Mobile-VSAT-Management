import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 2217

# Simple fake state
STATE = {
    "current_azimuth": 123.45,
    "current_elevation": 32.10,
    "current_polarization": 10.00,
    "target_azimuth": 125.00,
    "target_elevation": 33.00,
    "target_polarization": 10.50,
    "antenna_status": "2",  # tracking
    "agc": "78",
    "gps_status": "OK",
    "latitude": "-6.250000",
    "longitude": "107.150000",
}


def handle_client(conn: socket.socket, addr):
    print("Client connected:", addr)
    conn.settimeout(1.0)
    buf = b""
    try:
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
            except socket.timeout:
                continue

            # process lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode(errors="ignore").strip()
                print("RX:", cmd)

                # Update fake state a bit to look alive
                STATE["current_azimuth"] = round(STATE["current_azimuth"] + 0.1, 2)
                STATE["agc"] = str(int(STATE["agc"]) % 100)

                # Very simple protocol:
                # if "get show" -> return key=value lines
                # MVMS sends "$show,1,*.." so treat "$show" as "get show"
                if cmd.startswith("$show") or "get show" in cmd or cmd.startswith("show"):
                    resp = "\n".join([f"{k}={v}" for k, v in STATE.items()]) + "\n"
                else:
                 resp = "OK\n"


                conn.sendall(resp.encode())
                print("TX:", resp[:120].replace("\n", "\\n"))
    except Exception as e:
        print("Client error:", e)
    finally:
        conn.close()
        print("Client disconnected:", addr)


def main():
    print(f"Mock ACU listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(5)
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
