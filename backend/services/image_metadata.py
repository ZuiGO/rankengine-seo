import struct
from pathlib import Path


def parse_image_metadata(file_path: str) -> dict:
    try:
        with open(file_path, "rb") as f:
            head = f.read(32)
    except OSError:
        return {}

    meta = {"format": Path(file_path).suffix.lstrip(".").upper() or None}

    if head[:8] == b"\x89PNG\r\n\x1a\n":
        meta["format"] = "PNG"
        w, h = struct.unpack(">II", head[16:24])
        meta["width"], meta["height"] = w, h
        return meta

    if head[:6] in (b"GIF87a", b"GIF89a"):
        meta["format"] = "GIF"
        w, h = struct.unpack("<HH", head[6:10])
        meta["width"], meta["height"] = w, h
        return meta

    if head[:2] == b"\xff\xd8":
        meta["format"] = "JPEG"
        dims = _jpeg_dimensions(file_path)
        if dims:
            meta["width"], meta["height"] = dims
        return meta

    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        meta["format"] = "WEBP"
        fmt = head[12:16]
        if fmt == b"VP8 ":
            w, h = struct.unpack("<HH", head[26:30])
            meta["width"], meta["height"] = w & 0x3FFF, h & 0x3FFF
        elif fmt == b"VP8L":
            b = head[21:25]
            bits = int.from_bytes(b, "little")
            meta["width"], meta["height"] = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif fmt == b"VP8X":
            w = int.from_bytes(head[24:27], "little") + 1
            h = int.from_bytes(head[27:30], "little") + 1
            meta["width"], meta["height"] = w, h
        return meta

    if head[:2] == b"BM":
        meta["format"] = "BMP"
        w, h = struct.unpack("<ii", head[18:26])
        meta["width"], meta["height"] = w, abs(h)
        return meta

    return meta


def _jpeg_dimensions(file_path: str):
    with open(file_path, "rb") as f:
        data = f.read(4096)
    pos = 2
    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        pos += 2
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            break
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if pos + 5 < len(data):
                h, w = struct.unpack(">HH", data[pos + 3:pos + 7])
                return w, h
        pos += length
    return None
