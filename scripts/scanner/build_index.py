"""
Build the SHIPPABLE scanner index from cached Lorcast images.

Writes three files into the repo-root `scanner/` dir (served by dev_server +
Netlify, fetched once by the PWA and cached):

  scanner/index.json  — { version, dims, grid, count, scale, cards:[{id,name,
                          version,set_id,rarity,art_key,ink,collector_number}] }
  scanner/color.bin   — Int8  [count * 432]  L2-normalised colour sigs * scale
  scanner/dhash.bin   — Uint8 [count * 8]    64-bit dHash, little-endian

The client computes the same colour sig on a camera frame, L2-normalises, and
ranks by dot product (== cosine since refs are unit-norm). dHash hamming is a
light tiebreaker.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IMGDIR = DATA / "img"
REPO = HERE.parent.parent
OUT = REPO / "scanner"
sys.path.insert(0, str(HERE))
import descriptors as D  # noqa: E402

INDEX_VERSION = 2   # v2 = gray-world white-balanced colour sig (cast-invariant)
SCALE = 127.0 / 0.25   # quantization: |components| rarely exceed ~0.25


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cards = json.loads((DATA / "cards.json").read_text(encoding="utf-8"))
    cards = [c for c in cards if (IMGDIR / f"{c['id']}.avif").exists()]
    n = len(cards)
    dims = D.COLOR_GRID * D.COLOR_GRID * 3
    print(f"building index for {n} cards ({dims}-dim colour sig) ...")

    color = np.zeros((n, dims), dtype=np.int8)
    dhash = np.zeros(n, dtype=np.uint64)
    meta = []
    for i, c in enumerate(cards):
        im = Image.open(IMGDIR / f"{c['id']}.avif").convert("RGB")
        cs = D.color_sig(im)
        color[i] = np.clip(np.round(cs * SCALE), -127, 127).astype(np.int8)
        dhash[i] = D.dhash64(im)
        meta.append({
            "id": c["id"],
            "name": c.get("name"),
            "version": c.get("version"),
            "set_id": c.get("set_id"),
            "rarity": c.get("rarity"),
            "art_key": c.get("art_key"),
        })
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{n}")

    (OUT / "color.bin").write_bytes(color.tobytes())
    # dHash little-endian uint64 -> 8 bytes each
    (OUT / "dhash.bin").write_bytes(b"".join(struct.pack("<Q", int(h)) for h in dhash))
    manifest = {
        "version": INDEX_VERSION,
        "dims": dims,
        "grid": D.COLOR_GRID,
        "count": n,
        "scale": SCALE,
        "cards": meta,
    }
    (OUT / "index.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")

    cb = (OUT / "color.bin").stat().st_size
    jb = (OUT / "index.json").stat().st_size
    print(f"wrote scanner/color.bin ({cb/1e6:.2f} MB), scanner/dhash.bin "
          f"({n*8/1e3:.0f} KB), scanner/index.json ({jb/1e6:.2f} MB)")
    print(f"total raw ~{(cb + n*8 + jb)/1e6:.2f} MB (gzips ~50-60%)")


if __name__ == "__main__":
    main()
