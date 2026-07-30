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


def upright(im: Image.Image, card: dict) -> Image.Image:
    """Rotate a landscape Location card upright before descriptors.

    Lorcana Locations are printed LANDSCAPE (~7:5), but Lorcast serves their art
    rotated 90° CCW into the same 488x681 portrait frame every other card uses.
    Nothing normalised that, so every Location's reference vector described a
    sideways card while the client's query vector comes from a correctly
    landscape-rectified frame (scanner-worker.js swaps the rectify output dims
    for landscape quads). The descriptors squash to 12x12 / 9x8, so aspect
    cancels out and only ORIENTATION matters — which made Locations not merely
    weak but ANTI-correlated: querying with a Location's own art rotated upright
    ranked the true card 1035-3048 of 3198 (a portrait control ranks 1). That
    killed every colour-dependent stage for all 106 Locations, which is why a
    field tester reported "it cannot recognize locations".
    """
    if "Location" not in (card.get("card_type") or ""):
        return im
    if im.width >= im.height:
        return im   # already landscape (a future feed change) — leave it alone
    return im.transpose(Image.ROTATE_270)   # 90° CW undoes Lorcast's CCW framing


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
    n_loc = [0]
    for i, c in enumerate(cards):
        im = upright(Image.open(IMGDIR / f"{c['id']}.avif").convert("RGB"), c)
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
        if "Location" in (c.get("card_type") or ""):
            n_loc[0] += 1
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

    print(f"rotated {n_loc[0]} Location cards upright before descriptors")
    if not n_loc[0]:
        print("  WARNING: zero Locations seen — is card_type in cards.json? "
              "(re-run fetch_cards.py) Location colour matching will stay broken.")
    cb = (OUT / "color.bin").stat().st_size
    jb = (OUT / "index.json").stat().st_size
    print(f"wrote scanner/color.bin ({cb/1e6:.2f} MB), scanner/dhash.bin "
          f"({n*8/1e3:.0f} KB), scanner/index.json ({jb/1e6:.2f} MB)")
    print(f"total raw ~{(cb + n*8 + jb)/1e6:.2f} MB (gzips ~50-60%)")


if __name__ == "__main__":
    main()
