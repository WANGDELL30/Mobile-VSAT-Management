import socket
import threading
import time

class ACUTcp:
    mode = "tcp"

    def __init__(self):
        self.sock = None
        self.lock = threading.Lock()
        self.host = None
        self.port = None

    def connect(self, host: str, port: int, timeout=5.0):
        self.host = host
        self.port = port

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.settimeout(timeout)
        s.connect((host, port))

        self.sock = s

    def reconnect(self, timeout=5.0):
        if self.host and self.port:
            self.disconnect()
            time.sleep(0.5)
            self.connect(self.host, self.port, timeout=timeout)

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def is_connected(self):
        return self.sock is not None

    def send_and_read(self, frame, retries=3, timeout=5.0):
        if not self.is_connected():
            raise RuntimeError("TCP not connected")

        raw = frame if isinstance(frame, (bytes, bytearray)) else frame.encode("ascii")

        for attempt in range(retries):
            with self.lock:
                try:
                    # Drain input buffer to avoid reading stale streaming data
                    self.sock.settimeout(0.01)
                    try:
                        while True:
                            if not self.sock.recv(4096):
                                break
                    except socket.timeout:
                        pass
                    except Exception:
                        pass

                    # Send
                    self.sock.settimeout(timeout)
                    self.sock.sendall(raw)

                    # Read FULL response (multi-line), not just the first line
                    buff = b""
                    start = time.time()

                    # We will keep reading until:
                    # - overall timeout reached, OR
                    # - we already got at least one newline AND the socket goes idle briefly
                    idle_timeout = 0.5
                    last_rx = None

                    while time.time() - start < timeout:
                        # use short recv timeout so we can detect "idle"
                        self.sock.settimeout(idle_timeout)
                        try:
                            chunk = self.sock.recv(4096)
                        except socket.timeout:
                            # if we already received something and it includes a newline, treat idle as end of message
                            if buff and (b"\n" in buff or b"\r\n" in buff):
                                break
                            continue

                        if not chunk:
                            raise ConnectionError("TCP Closed by peer")

                        buff += chunk
                        last_rx = time.time()

                    text = buff.decode("ascii", errors="replace").strip()
                    if text:
                        return text

                except socket.timeout:
                    pass
                except Exception:
                    # try reconnect once
                    try:
                        self.reconnect(timeout=timeout)
                    except Exception:
                        pass

            time.sleep(0.2)

        raise TimeoutError("No TCP response after retries")
