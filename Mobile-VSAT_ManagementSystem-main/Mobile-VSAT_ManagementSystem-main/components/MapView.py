import math
import io
from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Signal, Slot, QByteArray, QBuffer, QIODevice

TILE_SIZE = 256

class MapWorker(QObject):
    finished = Signal(bytes)
    error = Signal(str)

    @staticmethod
    def deg2num(lat_deg: float, lon_deg: float, zoom) -> tuple[float, float]:
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = (lon_deg + 180.0) / 360.0 * n
        ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        return xtile, ytile

    def _get_tile_image(self, zoom, x, y) -> Image:
        path = self.tile_path_template.format(z=zoom, x=x, y=y)
        try: 
            return Image.open(path).convert('RGB')
        except:
            return Image.new('RGB', (TILE_SIZE, TILE_SIZE), color="#e0e0e0")

    def __init__(self, tile_path_template: str):
        super().__init__()
        self.tile_path_template = tile_path_template

    @Slot(float, float, int, dict)
    def run(self, lat: float, lon: float, zoom: int, pan_offset: dict):
        try:
            xtile, ytile = MapWorker.deg2num(lat, lon, zoom)

            center_x_tile = int(xtile)
            center_y_tile = int(ytile)

            center_x_tile += pan_offset.get('x', 0)
            center_y_tile += pan_offset.get('y', 0)

            canvas = Image.new('RGBA', (TILE_SIZE * 3, TILE_SIZE * 3))

            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    tile_x = center_x_tile + dx
                    tile_y = center_y_tile + dy
                    tile_image = self._get_tile_image(zoom, tile_x, tile_y)

                    paste_x = (dx + 1) * TILE_SIZE
                    paste_y = (dy + 1) * TILE_SIZE

                    canvas.paste(tile_image, (paste_x, paste_y))

            draw = ImageDraw.Draw(canvas)

            x_offset = (xtile % 1) * TILE_SIZE
            y_offset = (ytile % 1) * TILE_SIZE

            dot_x = TILE_SIZE + x_offset - (pan_offset.get('x', 0) * TILE_SIZE)
            dot_y = TILE_SIZE + y_offset - (pan_offset.get('y', 0) * TILE_SIZE)
            dot_radius = 5

            dot_box = [
                dot_x - dot_radius,
                dot_y - dot_radius,
                dot_x + dot_radius,
                dot_y + dot_radius
            ]

            draw.ellipse(dot_box, fill='red', outline='black', width=1)

            buffer = io.BytesIO()
            canvas.save(buffer, format='PNG')
            
            self.finished.emit(buffer.getvalue())

        except Exception as e:
            self.error.emit(f"Map generation Failed: {e}")