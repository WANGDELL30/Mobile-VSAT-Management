# services/acu_scraper.py
import requests
import json
import re
import os
import time
import logging
from pprint import pprint
from dotenv import load_dotenv
from typing import Dict, Any, Optional

load_dotenv()

# NOTE: keeping your env key names as-is
ACU_URL = os.getenv("ACU_IP")
ACU_USER = os.getenv("ACU_USERNAME")
ACU_PASS = os.getenv("ACU_PASSWORD")
APP_MODE = os.getenv("APP_MODE")

LOGIN_ROUTE = "/login.cgi"
LOGIN_PAYLOAD = {
    "user": ACU_USER,
    "pword": ACU_PASS,
}

# ---- IMPORTANT FIX: never crash on import ----
# If env vars are missing, disable scraper mode gracefully.
# ---- IMPORTANT: TCP-only build ----
# Hard-disable the legacy HTTP scraper regardless of env vars.
SCRAPER_ENABLED = False
ACU_URL = ""
ACU_USER = ""
ACU_PASS = ""

print("[WARN] ACU scraper env vars missing (ACU_IP/ACU_USERNAME/ACU_PASSWORD). Scraper mode disabled.")


class ACUClient:
    """
    Web-scraper ACU client (HTTP). This is legacy if you are moving to TCP-only.
    It will be disabled if SCRAPER_ENABLED is False.
    """

    def __init__(self, base_url: str, username: str, password: str):
        if not SCRAPER_ENABLED:
            raise RuntimeError("ACU scraper is disabled (missing env vars).")

        self.base_url = base_url
        self._login_payload = {"user": username, "pword": password}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Origin": self.base_url
        })
        self._login()

    def _login(self):
        try:
            login_url = f"{self.base_url}/login.cgi"
            self.session.headers.update({"Referer": f"{self.base_url}/"})
            response = self.session.post(login_url, data=self._login_payload, timeout=5)
            response.raise_for_status()
            logging.info("Successfully logged into ACU.")
        except requests.exceptions.RequestException as e:
            logging.error(f"ACU login failed: {e}")
            raise

    def get_raw_data(self):
        try:
            redirect_url = f"{self.base_url}/home.html"
            self.session.get(redirect_url, timeout=5)
            time.sleep(1)

            data_url = f"{self.base_url}/home.js"
            headers = {
                "Referer": redirect_url,
                "ISAJAX": "yes"
            }
            data_response = self.session.post(data_url, headers=headers, timeout=5)
            data_response.raise_for_status()
            return self._parse_jsonp(data_response.text)
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error while fetching ACU data: {e}")
            return None

    @staticmethod
    def _parse_jsonp(jsonp_string):
        callback = "settingsCallback("
        if jsonp_string.startswith(callback):
            try:
                json_string = jsonp_string[len(callback):-2]
                json_string_cleaned = re.sub(r",\s*\]", "]", json_string)
                return json.loads(json_string_cleaned)
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSONP content: {e}")
                return None

        logging.warning("Received data is not in the expected JSONP format.")
        return None


def format_acu_data(raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not raw_data:
        return None

    status_map = {"0": "Searching", "1": "Error", "2": "Tracking", "3": "Stowed"}

    try:
        lat_val = int(raw_data.get("lat", 0)) / 1000000.0
        lng_val = int(raw_data.get("lng", 0)) / 1000000.0

        raw_status = raw_data.get("acustu")
        satellite_status_text = status_map.get(raw_status, f"{raw_status} : Unknown")

        # Keep your debug print if you want
        print(f"DEBUG from Formatter: Status is '{satellite_status_text}'")

        return {
            "current_azimuth": float(raw_data.get("taz", 0)) / 100.0,
            "current_elevation": float(raw_data.get("tel", 0)) / 100.0,
            "target_azimuth": float(raw_data.get("caz", 0)) / 100.0,
            "target_elevation": float(raw_data.get("cel", 0)) / 100.0,
            "cn_ratio": float(raw_data.get("msnr", 0)) / 10.0,
            "signal_power": int(raw_data.get("pow", 0)),
            "agc": int(raw_data.get("agc", 0)),
            "latitude": f"{abs(lat_val):.6f}° {'S' if lat_val < 0 else 'N'}",
            "longitude": f"{abs(lng_val):.6f}° {'E' if lng_val >= 0 else 'W'}",
            "satellite_status": satellite_status_text,
            "bdu_version": raw_data.get("bduver", "N/A"),
        }
    except (ValueError, TypeError) as e:
        logging.error(f"Error formatting raw data: {e}. Raw data: {raw_data}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    print("Attempting to fetch and format ACU data...")

    if not SCRAPER_ENABLED:
        print("Scraper disabled (missing env vars). Exiting.")
        raise SystemExit(0)

    try:
        client = ACUClient(base_url=ACU_URL, username=ACU_USER, password=ACU_PASS)
        raw_data = client.get_raw_data()

        if raw_data:
            live_data = format_acu_data(raw_data)
            if live_data:
                print("\n--- Formatted ACU Data ---")
                pprint(live_data)
            else:
                print("\n--- Failed to format data ---")
        else:
            print("\n--- Failed to retrieve data ---")

    except (RuntimeError, ValueError, requests.exceptions.RequestException) as e:
        print(f"\n--- A critical error occurred: {e} ---")
