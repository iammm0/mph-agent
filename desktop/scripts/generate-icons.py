#!/usr/bin/env python3
"""从 public/brand/icon.png 生成 Tauri / Windows 任务栏与安装包所需图标。"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow：pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "public" / "brand" / "icon.png"
OUT = ROOT / "src-tauri" / "icons"


def square_canvas(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    w, h = rgba.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
    return canvas


def rgba_to_bmp_dib(im: Image.Image) -> bytes:
    w, h = im.size
    pixels = list(im.getdata())
    row_xor = ((w * 32 + 31) // 32) * 4
    row_and = ((w + 31) // 32) * 4
    xor = bytearray()
    andm = bytearray()
    for y in range(h - 1, -1, -1):
        row = bytearray()
        mask_row = bytearray()
        bit = 0
        mask_byte = 0
        for x in range(w):
            r, g, b, a = pixels[y * w + x]
            row += bytes((b, g, r, a))
            if a < 128:
                mask_byte |= 1 << (7 - bit)
            bit += 1
            if bit == 8:
                mask_row.append(mask_byte)
                bit = 0
                mask_byte = 0
        if bit:
            mask_row.append(mask_byte)
        if len(row) < row_xor:
            row += b"\x00" * (row_xor - len(row))
        if len(mask_row) < row_and:
            mask_row += b"\x00" * (row_and - len(mask_row))
        xor += row
        andm += mask_row
    header = struct.pack(
        "<IIIHHIIIIII",
        40,
        w,
        h * 2,
        1,
        32,
        0,
        len(xor) + len(andm),
        0,
        0,
        0,
        0,
    )
    return header + bytes(xor) + bytes(andm)


def write_ico(canvas: Image.Image, path: Path, sizes: list[int]) -> None:
    entries: list[tuple[int, bytes]] = []
    for s in sizes:
        im = canvas.resize((s, s), Image.Resampling.LANCZOS)
        entries.append((s, rgba_to_bmp_dib(im)))

    num = len(entries)
    header = struct.pack("<HHH", 0, 1, num)
    offset = 6 + 16 * num
    dirs = b""
    payload = b""
    for s, data in entries:
        bw = 0 if s >= 256 else s
        bh = 0 if s >= 256 else s
        dirs += struct.pack("<BBBBHHII", bw, bh, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    path.write_bytes(header + dirs + payload)


def main() -> None:
    if not SRC.is_file():
        print(f"缺少品牌源图：{SRC}", file=sys.stderr)
        raise SystemExit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    canvas = square_canvas(Image.open(SRC))
    canvas.save(OUT / "icon.png", optimize=True)
    for size, name in [(32, "32x32.png"), (128, "128x128.png"), (256, "128x128@2x.png")]:
        canvas.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name, optimize=True)
    write_ico(canvas, OUT / "icon.ico", [16, 24, 32, 48, 64, 128, 256])
    print(f"已写入 {OUT}（icon.ico / png 多尺寸）")


if __name__ == "__main__":
    main()
