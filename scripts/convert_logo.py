"""One-shot: render Logos/PacksInk.pdf to PNGs for the site.

Produces:
    Logos/packs-ink-logo.png   - top-bar wordmark (1200x wide)
    Logos/logo transparent.png - same, alias kept for back-compat
    icon-192.png               - PWA icon (192x192 square, padded)
    icon-512.png               - PWA icon (512x512 square, padded)
    apple-touch-icon.png       - iOS install icon (180x180 square, padded)
    favicon-32.png, favicon-16.png - browser favicon (square, padded)
"""
import fitz
from pathlib import Path

PDF_PATH = Path("Logos/PacksInk.pdf")
OUT_DIR  = Path("Logos")
ROOT     = Path(".")

def render_to_pixmap(pdf, page_idx, target_w):
    page = pdf[page_idx]
    src_w = page.rect.width or 1
    zoom = target_w / src_w
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)

def save_square(pdf, size, out_path):
    """Render the logo and center it on a transparent square of given size."""
    # First render at full quality, then resize to fit within the square.
    pix = render_to_pixmap(pdf, 0, size * 2)  # 2x for better downsample later
    # Use PIL for the square padding + resize since fitz doesn't do that.
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
    # Fit within (size, size) preserving aspect ratio.
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    canvas.paste(img, (x, y), img)
    canvas.save(str(out_path))
    print(f"  {out_path}  ({size}x{size})")

def save_natural(pdf, target_w, out_path):
    pix = render_to_pixmap(pdf, 0, target_w)
    pix.save(str(out_path))
    print(f"  {out_path}  ({pix.width}x{pix.height})")

def main():
    if not PDF_PATH.exists():
        raise SystemExit(f"Not found: {PDF_PATH}")
    pdf = fitz.open(str(PDF_PATH))
    print(f"PDF has {len(pdf)} page(s).")
    # Wordmark/badge images (natural aspect ratio)
    save_natural(pdf, 1200, OUT_DIR / "packs-ink-logo.png")
    save_natural(pdf, 1200, OUT_DIR / "logo transparent.png")
    # PWA icons (square, padded)
    save_square(pdf, 192, ROOT / "icon-192.png")
    save_square(pdf, 512, ROOT / "icon-512.png")
    save_square(pdf, 180, ROOT / "apple-touch-icon.png")
    save_square(pdf, 32,  ROOT / "favicon-32.png")
    save_square(pdf, 16,  ROOT / "favicon-16.png")
    pdf.close()
    print("Done.")

if __name__ == "__main__":
    main()
