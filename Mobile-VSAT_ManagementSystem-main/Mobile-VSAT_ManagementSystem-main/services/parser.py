def parse_show(line: str) -> dict:
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
            "frame_code": parts[0],
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
    except:
        return {"raw": line}
