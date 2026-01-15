# services/modem_scraper.py
"""
UHP Modem Web Scraper Service
Extracts telemetry data (C/N, etc.) from UHP modem web interface.
"""
from __future__ import annotations
import requests
import random
import time
from typing import Dict, Any, Optional

class ModemScraper:
    """Scraper for UHP modem web interface telemetry data."""
    
    def __init__(self, modem_url: str, timeout: float = 3.0):
        """
        Initialize modem scraper.
        
        Args:
            modem_url: Base URL of the modem (e.g., "http://192.168.0.3")
            timeout: Request timeout in seconds
        """
        self.modem_url = modem_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ACU_Dashboard_Client/1.0'
        })
    
    def get_telemetry(self) -> Dict[str, Any]:
        """
        Fetch and parse modem telemetry data.
        """
        import re
        data = {}
        
        # Fetch from UHP specific endpoint /ss54?dJ=1
        try:
            url = f"{self.modem_url}/ss54?dJ=1"
            # print(f"🔍 DEBUG: Fetching parsed data from {url}")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            text = response.text
            
            # Extract C/N
            # Pattern: "SCPC C/N 24.9 dB"
            cn_match = re.search(r'SCPC\s+C/N\s+(-?\d+\.?\d*)\s*dB', text)
            if cn_match:
                cn = float(cn_match.group(1))
                data["cn_ratio_modem"] = cn
                data["cn_ratio"] = cn
                # print(f"✅ DEBUG: Found C/N: {cn}")
            
            # Extract RF Level (Use as TX Level)
            # Pattern: "SCPC RF level -39.1 dBm"
            rf_match = re.search(r'SCPC\s+RF\s+level\s+(-?\d+\.?\d*)\s*dBm', text)
            if rf_match:
                rf = float(rf_match.group(1))
                data["tx_level"] = rf
                data["signal_strength"] = rf
                # print(f"✅ DEBUG: Found RF Level: {rf}")
                
        except Exception as e:
            print(f"❌ DEBUG: Scrape failed: {e}")
            
        # Set modem status
        data["modem_status"] = "Connected" if data else "No Data"
        
        return data

    # Helper methods removed as we are parsing directly in get_telemetry now
    def close(self):
        """Close the session."""
        self.session.close()
