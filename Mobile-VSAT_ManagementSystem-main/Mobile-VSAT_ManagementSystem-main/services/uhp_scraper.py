# services/uhp_scraper.py
import requests
import os
import time
import logging
import random
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

UHP_URL = os.getenv("UHP_IP")
APP_MODE = os.getenv("APP_MODE", "production")

# ---- IMPORTANT FIX: never crash on import ----
SCRAPER_ENABLED = bool(UHP_URL)
if not SCRAPER_ENABLED:
    UHP_URL = UHP_URL or ""
    print("[WARN] UHP scraper env var missing (UHP_IP). Modem scraper disabled.")


class UHPClient:
    def __init__(self, base_url: str, max_retries: int = 3):
        if not SCRAPER_ENABLED:
            raise RuntimeError("UHP scraper is disabled (missing UHP_IP).")

        self.base_url = base_url
        # base_url is expected to be IP/host only (no scheme)
        self.data_url = f"http://{self.base_url}/ss54?dJ=1"
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ACU_Dashboard_Client/1.0"})

    def get_cn_ratio(self) -> Optional[float]:
        """
        Fetches the C/N ratio with retries for network resilience.
        """

        if APP_MODE == "development":
            logging.info("[DEV MODE] UHPClient returning mock C/N data.")
            return 15.0

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(self.data_url, timeout=5)
                response.raise_for_status()
                return float(response.text.strip())

            except requests.exceptions.RequestException as e:
                logging.error(f"UHP fetch attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logging.info(f"Retrying UHP fetch in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                else:
                    logging.error("All UHP retry attempts failed.")
                    return None

            except (ValueError, TypeError) as e:
                logging.error(f"Error parsing UHP C/N value: {e}")
                return None

        return None
