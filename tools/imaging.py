"""Image helpers: resize, WebP encode, dominant colour, perceptual hash."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 200_000_000


def open_upright(path_or_bytes) -> Image.Image:
    """Opens an image and applies its EXIF orientation; returns RGB."""
    img = Image.open(path_or_bytes if not isinstance(path_or_bytes, bytes) else io.BytesIO(path_or_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    return img


def fit_long_side(img: Image.Image, long_side: int) -> Image.Image:
    """Scales down (never up, never crops) so the long side is <= long_side."""
    w, h = img.size
    scale = long_side / max(w, h)
    if scale >= 1:
        return img
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def encode_webp(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=5)
    return buf.getvalue()


def dominant_color(img: Image.Image) -> str:
    """Most common colour of a 5-colour quantisation, as #rrggbb.

    Used by the app as the placeholder colour while a thumbnail loads.
    """
    small = img.copy()
    small.thumbnail((96, 96))
    q = small.quantize(colors=5, method=Image.Quantize.FASTOCTREE)
    palette = q.getpalette()
    counts = sorted(q.getcolors(), reverse=True)
    idx = counts[0][1]
    r, g, b = palette[idx * 3: idx * 3 + 3]
    return f"#{r:02x}{g:02x}{b:02x}"


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    m[0] *= 1 / np.sqrt(2)
    return m * np.sqrt(2 / n)


_DCT32 = _dct_matrix(32)


def phash(img: Image.Image) -> str:
    """64-bit DCT perceptual hash (same idea as imagehash.phash), hex."""
    g = np.asarray(img.convert("L").resize((32, 32), Image.LANCZOS), dtype=np.float64)
    d = _DCT32 @ g @ _DCT32.T
    low = d[:8, :8].flatten()
    med = np.median(low[1:])
    bits = low > med
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def trim_flat_border(img: Image.Image, max_fraction: float = 0.08, tolerance: float = 6.0) -> Image.Image:
    """Removes flat, uniform bands along the edges (scanner borders, black
    bars, canvas edges of museum scans). At most [max_fraction] of each side
    is removed, and only rows/columns whose pixels are nearly constant
    (std-dev < [tolerance]) — real image content is never cut."""
    a = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = a.shape

    def run(lines) -> int:
        n = 0
        for line in lines:
            if line.std() >= tolerance:
                break
            n += 1
        return n

    lim_h, lim_w = int(h * max_fraction), int(w * max_fraction)
    top = min(run(a[i] for i in range(h)), lim_h)
    bottom = min(run(a[h - 1 - i] for i in range(h)), lim_h)
    left = min(run(a[:, j] for j in range(w)), lim_w)
    right = min(run(a[:, w - 1 - j] for j in range(w)), lim_w)
    if top + bottom + left + right == 0:
        return img
    return img.crop((left, top, w - right, h - bottom))
