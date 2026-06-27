"""
Compact visual descriptors for card matching. Deliberately simple so the exact
same math is portable to in-browser JS on a 2D canvas:

  - dhash64 : 9x8 grayscale horizontal-gradient hash (64 bits)
  - phash64 : 32x32 grayscale DCT low-freq hash (64 bits)
  - color_sig : GxG RGB grid, per-channel mean-centred + L2-normalised (robust to
                global brightness / white-balance shift)
  - gray_sig : NxN grayscale grid, mean-centred + L2-normalised

Matching combines hamming distance on the hashes with cosine distance on the
signatures (see match.py). All inputs are PIL RGB images of any size.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

COLOR_GRID = 12   # color_sig = 12*12*3 = 432 dims
GRAY_GRID = 16    # gray_sig = 16*16 = 256 dims

# Precompute the DCT-II basis for 32x32 (orthonormal).
_N = 32
_k = np.arange(_N)
_DCT = np.cos(np.pi * (2 * _k[:, None] + 1) * _k[None, :] / (2 * _N))
_DCT[0, :] *= 1 / np.sqrt(2)
_DCT *= np.sqrt(2 / _N)


def _gray(img: Image.Image, w: int, h: int) -> np.ndarray:
    g = img.convert("L").resize((w, h), Image.BILINEAR)
    return np.asarray(g, dtype=np.float32)


def dhash64(img: Image.Image) -> int:
    a = _gray(img, 9, 8)
    bits = a[:, 1:] > a[:, :-1]            # 8x8 -> 64 bools
    out = 0
    for b in bits.flatten():
        out = (out << 1) | int(b)
    return out


def phash64(img: Image.Image) -> int:
    a = _gray(img, _N, _N)
    d = _DCT @ a @ _DCT.T                  # 2D DCT
    low = d[:8, :8].copy()
    med = np.median(low[1:].flatten())     # exclude DC term from threshold
    bits = (low > med).flatten()
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def color_sig(img: Image.Image) -> np.ndarray:
    a = np.asarray(
        img.convert("RGB").resize((COLOR_GRID, COLOR_GRID), Image.BILINEAR),
        dtype=np.float32,
    )                                      # 12x12x3
    # gray-world white balance: cancel a global colour cast (warm indoor light /
    # phone auto-WB) by scaling each channel to a common mean. Applied to BOTH the
    # reference art and the camera query, so they live in the same cast-invariant
    # space. Without this, a warm-tinted phone photo matches yellow/amber art
    # regardless of the real card (verified: real scans were 2% -> 30% top-1).
    m = a.reshape(-1, 3).mean(0)
    a = a * (m.mean() / np.clip(m, 1e-3, None))
    a = a.reshape(-1)                      # 432
    a -= a.mean()
    n = np.linalg.norm(a)
    return a / n if n > 1e-6 else a


def gray_sig(img: Image.Image) -> np.ndarray:
    a = _gray(img, GRAY_GRID, GRAY_GRID).reshape(-1)  # 256
    a -= a.mean()
    n = np.linalg.norm(a)
    return a / n if n > 1e-6 else a


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def describe(img: Image.Image) -> dict:
    return {
        "dhash": dhash64(img),
        "phash": phash64(img),
        "color": color_sig(img),
        "gray": gray_sig(img),
    }
