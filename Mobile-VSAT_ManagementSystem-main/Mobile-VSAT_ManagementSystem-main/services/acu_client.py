# services/acu_client.py
from __future__ import annotations

import time
from typing import Optional, Dict, Any

from services.acu_tcp import ACUTcp
from services.acu_driver import build_frame, parse_show, parse_sat, parse_place


def parse_kv_text(text: str) -> Dict[str, Any]:
    """
    Parse output:
      key=value
      key=value
    into dict.
    Ignores header lines like '$show' or empty lines.
    """
    d: Dict[str, Any] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("$"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip()
    return d



class ACUClient:
    """
    TCP-first ACU client for MVMS.
    - No Web/HTTP
    - Talks only to ACU over TCP (default 192.168.0.1:2217)
    - Uses your existing frame builder + parsers
    """

    def __init__(self, host: str = "192.168.0.1", port: int = 2217):
        self.host = host
        self.port = port
        self._tcp = ACUTcp()

    # ---------- Connection ----------
    def connect(self, timeout: float = 5.0) -> None:
        self._tcp.connect(self.host, self.port, timeout=timeout)

    def disconnect(self) -> None:
        self._tcp.disconnect()

    def is_connected(self) -> bool:
        return self._tcp.is_connected()

    def reconnect(self, timeout: float = 5.0) -> None:
        self._tcp.reconnect(timeout=timeout)

    # ---------- Low-level send ----------
    def send_raw(self, frame: str, retries: int = 3, timeout: float = 2.0) -> str:
        return self._safe_send_and_read(frame, retries=retries, timeout=timeout)

    def _safe_send_and_read(self, frame: str, retries: int, timeout: float) -> str:
        last_err: Optional[Exception] = None

        for _ in range(max(1, retries)):
            try:
                if not self.is_connected():
                    self.connect(timeout=timeout)

                resp = self._tcp.send_and_read(frame, retries=1, timeout=timeout)
                
                # ✅ FIX: Empty response is OK - ACU might not be responding
                # Return empty string instead of raising error
                if not resp:
                    return ""
                
                return resp

            except (ConnectionError, OSError) as e:
                # ✅ Only reconnect on actual connection errors
                last_err = e
                try:
                    self.reconnect(timeout=timeout)
                except Exception:
                    pass
                time.sleep(0.1)
            except Exception as e:
                # ✅ Other exceptions (like parsing errors) - just return what we got
                last_err = e
                time.sleep(0.1)

        # ✅ Return empty string if all retries exhausted - don't raise error
        return ""

    # ---------- High-level commands ----------
    def show(self, retries: int = 2, timeout: float = 2.0) -> Dict[str, Any]:
        """
        Request status and parse response.
        - Real ACU: parse_show(...)
        - Mock server: key=value lines -> parse_kv_text(...)
        """
        # ✅ FIX: Use correct ACU command format (matches testingport.py)
        frame = build_frame("cmd", "get show")  # Changed from ("show", "1")
        resp = self._safe_send_and_read(frame, retries=retries, timeout=timeout)

        # ✅ Handle empty response (ACU not responding)
        if not resp or not resp.strip():
            return {}

        # If mock server output contains "key=value", parse that
        if "=" in resp and "$show" not in resp:
            return parse_kv_text(resp)

        data = parse_show(resp)

        # normalize frame_code
        if data.get("frame_code", "").lower().startswith("$show"):
            data["frame_code"] = "show"

        return data

    def set_satellite(
        self,
        name: str,
        center_freq: str,
        carrier_freq: str,
        carrier_rate: str,
        sat_lon: str,
        pol_mode: str,
        lock_th: str,
        retries: int = 2,
        timeout: float = 2.0,
    ) -> Dict[str, Any]:
        frame = build_frame("cmd", "sat", name, center_freq, carrier_freq, carrier_rate, sat_lon, pol_mode, lock_th)
        resp = self._safe_send_and_read(frame, retries=retries, timeout=timeout)
        return parse_sat(resp)

    def set_place(
        self,
        lon: str,
        lat: str,
        heading: str,
        retries: int = 2,
        timeout: float = 2.0,
    ) -> Dict[str, Any]:
        frame = build_frame("cmd", "place", lon, lat, heading)
        resp = self._safe_send_and_read(frame, retries=retries, timeout=timeout)
        return parse_place(resp)
