# components/MapView.py
import math
import io
import os
import time
import urllib.request
from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Signal, Slot

TILE_SIZE = 256


class MapWorker(QObject):
    """
    Offline-first tile renderer:
    - Tries to read tiles from disk: tile_path_template
    - If missing, downloads from OpenStreetMap and saves to the same path (cache)
    - Wraps X (world wrap) and clamps Y to valid range
    """

    finished = Signal(bytes)
    error = Signal(str)
    log = Signal(str, str)  # message, level for logging to Terminal Activity

    def __init__(self, tile_path_template: str, allow_online: bool = True):
        super().__init__()
        self.tile_path_template = tile_path_template
        self.allow_online = allow_online

        # Simple in-memory cooldown for failed downloads (avoid spamming network)
        self._fail_cache = {}  # (z,x,y) -> last_fail_time
        self._fail_cooldown_s = 30.0

        # OSM tile URL template (standard)
        self._osm_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

        # User-Agent is required by many servers
        self._ua = "MVMS/1.0 (PySide6 Tile Renderer)"

    @staticmethod
    def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[float, float]:
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = (lon_deg + 180.0) / 360.0 * n
        ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        return xtile, ytile

    @staticmethod
    def _wrap_and_clamp(zoom: int, x: int, y: int) -> tuple[int, int]:
        n = 2 ** zoom
        # Wrap X around the world
        x = x % n
        # Clamp Y (no wrap at poles)
        if y < 0:
            y = 0
        elif y >= n:
            y = n - 1
        return x, y

    def _tile_path(self, z: int, x: int, y: int) -> str:
        return self.tile_path_template.format(z=z, x=x, y=y)

    def _ensure_parent_dir(self, path: str):
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

    def _download_tile(self, z: int, x: int, y: int, save_path: str) -> bool:
        """
        Download a tile from OSM and cache to disk. Returns True if saved OK.
        """
        if not self.allow_online:
            return False

        key = (z, x, y)
        now = time.monotonic()
        last_fail = self._fail_cache.get(key, 0.0)
        if (now - last_fail) < self._fail_cooldown_s:
            return False

        url = self._osm_url.format(z=z, x=x, y=y)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self._ua})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = resp.read()

            # Save to cache
            self._ensure_parent_dir(save_path)
            with open(save_path, "wb") as f:
                f.write(data)
            return True

        except Exception:
            # remember fail time
            self._fail_cache[key] = now
            return False

    def _get_tile_image(self, z: int, x: int, y: int) -> Image.Image:
        """Get a tile image from disk or download. Returns placeholder if unavailable."""
        x, y = self._wrap_and_clamp(z, x, y)
        path = self._tile_path(z, x, y)

        # Try disk first
        try:
            if os.path.exists(path):
                img = Image.open(path).convert("RGB")
                return img
        except Exception as e:
            self.log.emit(f"Failed to load tile {z}/{x}/{y}: {e}", "warning")

        # If missing, try to download if online mode enabled
        if self.allow_online:
            if self._download_tile(z, x, y, path):
                try:
                    img = Image.open(path).convert("RGB")
                    self.log.emit(f"Downloaded tile {z}/{x}/{y}", "success")
                    return img
                except Exception as e:
                    self.log.emit(f"Failed to load downloaded tile {z}/{x}/{y}: {e}", "error")
        
        # Fallback: gray placeholder with tile coordinates
        placeholder = Image.new("RGB", (TILE_SIZE, TILE_SIZE), color="#E0E0E0")
        draw = ImageDraw.Draw(placeholder)
        # Draw border
        draw.rectangle([0, 0, TILE_SIZE-1, TILE_SIZE-1], outline="#999999", width=1)
        # Draw coordinates
        text = f"{z}/{x}/{y}\noffline"
        draw.text((TILE_SIZE//2, TILE_SIZE//2), text, fill="#666666", anchor="mm")
        return placeholder

    @Slot(float, float, int, dict)
    def run(self, lat: float, lon: float, zoom: int, pan_offset: dict):
        """
        Render a 3x3 tile canvas centered around (lat,lon) at given zoom,
        with pan_offset in tile units.
        """
        try:
            xtile, ytile = MapWorker.deg2num(lat, lon, zoom)

            center_x_tile = int(xtile) + int(pan_offset.get("x", 0))
            center_y_tile = int(ytile) + int(pan_offset.get("y", 0))

            canvas = Image.new("RGBA", (TILE_SIZE * 3, TILE_SIZE * 3))

            # Track tile loading statistics
            tiles_loaded = 0
            tiles_missing = 0

            # Paste 3x3 tiles
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    tile_x = center_x_tile + dx
                    tile_y = center_y_tile + dy

                    tile_img = self._get_tile_image(zoom, tile_x, tile_y)
                    
                    # Check if it's a placeholder (all one color)
                    colors = tile_img.getcolors(maxcolors=2)
                    if colors and len(colors) <= 2:  # likely placeholder
                        tiles_missing += 1
                    else:
                        tiles_loaded += 1

                    paste_x = (dx + 1) * TILE_SIZE
                    paste_y = (dy + 1) * TILE_SIZE
                    canvas.paste(tile_img, (paste_x, paste_y))

            # Log tile statistics
            if tiles_missing > 0:
                self.log.emit(f"Map rendered: {tiles_loaded} tiles loaded, {tiles_missing} missing (zoom {zoom})", "warning")
            
            # Draw red dot marker where the lat/lon lands inside the center tile
            draw = ImageDraw.Draw(canvas)

            x_offset = (xtile % 1) * TILE_SIZE
            y_offset = (ytile % 1) * TILE_SIZE

            dot_x = TILE_SIZE + x_offset - (pan_offset.get("x", 0) * TILE_SIZE)
            dot_y = TILE_SIZE + y_offset - (pan_offset.get("y", 0) * TILE_SIZE)

            r = 6
            # Draw marker with white outline for visibility
            draw.ellipse([dot_x - r - 1, dot_y - r - 1, dot_x + r + 1, dot_y + r + 1], fill="white")
            draw.ellipse([dot_x - r, dot_y - r, dot_x + r, dot_y + r], fill="red", outline="black", width=2)

            # Encode to PNG bytes
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG")
            self.finished.emit(buffer.getvalue())

        except Exception as e:
            error_msg = f"Map generation failed: {type(e).__name__}: {e}"
            self.error.emit(error_msg)
            self.log.emit(error_msg, "error")
