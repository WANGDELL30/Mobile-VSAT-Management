import serial
import serial.tools.list_ports
import threading
import time

CRLF = b"\r\n"

def xor_checksum(payload: str) -> str:
    """
    XOR of all ASCII chars between $ and * (excluding both)
    Return 2-hex UPPERCASE string (matching working code).
    """
    csum = 0
    for b in payload.encode("ascii"):
        csum ^= b
    return f"{csum:02X}"  # Uppercase to match working terminal code

def build_frame(frame_type: str, frame_code: str, *data_fields: str) -> str:
    """
    Build protocol frame:
      $cmd,xxx,ddd,...*HH\r\n
    ✅ FIXED: NO trailing comma before * (was causing ACU to reject commands)
    """
    parts = [f"${frame_type}", frame_code]
    parts.extend(data_fields)

    payload = ",".join(parts)  # NO trailing comma!
    csum = xor_checksum(payload[1:])  # exclude $
    return f"{payload}*{csum}\r\n"

class ACUSerial:
    mode = "serial"

    def __init__(self):
        self.ser = None
        self.lock = threading.Lock()

    @staticmethod
    def list_ports():
        return [{"device": p.device, "description": p.description}
                for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baudrate=38400, timeout=0.5):
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=timeout,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        time.sleep(0.1)

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def send_and_read(self, frame: str, retries=3, timeout=0.5):
        if not self.is_connected():
            raise RuntimeError("Serial not connected")

        raw = frame.encode("ascii")

        for _ in range(retries):
            with self.lock:
                self.ser.reset_input_buffer()
                self.ser.write(raw)
                self.ser.flush()

                start = time.time()
                while time.time() - start < timeout:
                    line = self.ser.readline()
                    if line:
                        return line.decode("ascii", errors="replace").strip()

            time.sleep(0.02)

        raise TimeoutError("No response after retries")


# ---------------- PARSERS ----------------

def parse_show(line: str) -> dict:
    """
    Parse $show response.
    """
    try:
        s = line.strip()
        if not s.lower().startswith("$show"):
            return {"raw": line}

        if "*" in s:
            s, checksum = s.split("*", 1)
            checksum = checksum.strip()
        else:
            checksum = None

        parts = [p.strip() for p in s.split(",")]
        data = parts[1:]

        def get(i, default=None):
            return data[i] if i < len(data) else default

        return {
           "frame_code": "show",
            "preset_azimuth": get(0),
            "preset_pitch": get(1),
            "preset_polarization": get(2),
            "current_azimuth": get(3),
            "current_pitch": get(4),
            "current_polarization": get(5),
            "antenna_status": get(6),
            "carrier_heading": get(7),
            "carrier_pitch": get(8),
            "carrier_roll": get(9),
            "longitude": get(10),
            "latitude": get(11),
            "gps_status": get(12),
            "limit_info": get(13),
            "alert_info": get(14),
            "agc_level": get(15),
            "az_pot": get(16),
            "pitch_pot": get(17),
            "time": ",".join(data[18:]).strip() if len(data) > 18 else get(18),
            "checksum": checksum,
            "raw": line,
        }
    except Exception:
        return {"raw": line}


def parse_sat(line: str) -> dict:
    """
    Parse satellite response:
    $cmd,sat,Name,CenterFreq,CarrierFreq,CarrierRate,SatLon,PolMode,LockTh,*hh
    """
    try:
        s = line.strip()
        if not s.lower().startswith("$cmd") or ",sat" not in s.lower():
            return {"raw": line}

        if "*" in s:
            s, checksum = s.split("*", 1)
            checksum = checksum.strip()
        else:
            checksum = None

        parts = [p.strip() for p in s.split(",")]
        data = parts[2:]  # after $cmd,sat

        def get(i, default=None):
            return data[i] if i < len(data) else default

        return {
            "frame_code": "sat",
            "sat_name": get(0),
            "center_freq": get(1),
            "carrier_freq": get(2),
            "carrier_rate": get(3),
            "sat_longitude": get(4),
            "pol_mode": get(5),
            "lock_threshold": get(6),
            "checksum": checksum,
            "raw": line
        }
    except Exception:
        return {"raw": line}


def parse_place(line: str) -> dict:
    """
    Parse place response:
    $cmd,place,lon,lat,heading,*hh
    """
    try:
        s = line.strip()
        if not s.lower().startswith("$cmd") or ",place" not in s.lower():
            return {"raw": line}

        if "*" in s:
            s, checksum = s.split("*", 1)
            checksum = checksum.strip()
        else:
            checksum = None

        parts = [p.strip() for p in s.split(",")]
        data = parts[2:]  # after $cmd,place

        def get(i, default=None):
            return data[i] if i < len(data) else default

        return {
            "frame_code": "place",
            "longitude": get(0),
            "latitude": get(1),
            "heading": get(2),
            "checksum": checksum,
            "raw": line
        }
    except Exception:
        return {"raw": line}


acu_serial = ACUSerial()
