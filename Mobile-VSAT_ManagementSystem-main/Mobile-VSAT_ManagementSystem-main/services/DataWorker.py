import logging
from PySide6.QtCore import QObject, Signal

from services.acu_scraper import (
    ACUClient,
    format_acu_data,
    ACU_URL,
    ACU_USER,
    ACU_PASS,
    SCRAPER_ENABLED,
)

from services.uhp_scraper import UHPClient as UHPClientClass, UHP_URL


class DataWorker(QObject):
    data_ready = Signal(dict)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.acu_client = None
        self.uhp_client = None

    def run(self):
        try:
            # Create scraper client only if enabled
            if SCRAPER_ENABLED:
                if self.acu_client is None:
                    self.acu_client = ACUClient(
                        base_url=ACU_URL,
                        username=ACU_USER,
                        password=ACU_PASS
                    )

                raw_data = self.acu_client.get_raw_data()
                if not raw_data:
                    self.error.emit("Failed to retrieve raw data from ACU.")
                    return

                formatted_data = format_acu_data(raw_data)
                if not formatted_data:
                    self.error.emit("Failed to format raw data.")
                    return
            else:
                formatted_data = {}

            # UHP is optional
            if self.uhp_client is None and UHP_URL:
                self.uhp_client = UHPClientClass(base_url=UHP_URL)

            if self.uhp_client:
                uhp_cn_value = self.uhp_client.get_cn_ratio()
                if uhp_cn_value is not None:
                    logging.info(f"UHP C/N value retrieved: {uhp_cn_value}")
                    formatted_data["uhp_cn"] = uhp_cn_value
                else:
                    logging.warning("Failed to retrieve UHP C/N value.")

            self.data_ready.emit(formatted_data)

        except Exception as e:
            self.error.emit(f"A critical error occurred in DataWorker: {e}")
            self.acu_client = None
            self.uhp_client = None
