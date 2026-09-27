"""Build the README's project images from the portfolio repo.

Each project gets a gallery tile (600x375, cropped or padded to 16:10) and a
write-up image (560 px wide, natural aspect). Animated GIFs are re-encoded
with ffmpeg; PDFs are rendered from page 1 with PyMuPDF.

To feature a different picture, change its entry in PROJECTS and re-run:

    python scripts/make_thumbnails.py [path/to/OWongit.github.io/projects]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "assets" / "projects"
DEFAULT_SRC = REPO.parent / "OWongit.github.io" / "projects"

TILE_W, TILE_H = 600, 375
DETAIL_W = 560
BG = (20, 21, 23)  # --ui-bg from the portfolio
JPEG_QUALITY = 86
GIF_MAX_BYTES = 3_000_000

# tile / detail: source file relative to the portfolio's projects/ folder
# mode:     "fill" crops to 16:10, "fit" letterboxes onto the page background
# focus:    (x, y) in 0-1, where the fill crop centres on
# box:      (left, top, right, bottom) in 0-1, pre-crop applied before anything else
#           (detail_box does the same for the write-up image)
# start/duration: seconds of an animated GIF to keep; fps/colors trade GIF smoothness for size
PROJECTS = [
    dict(slug="daq-hardware", tile="DAQ_Rev2/DAQ_3D_VIEW_FRONT.png", detail="DAQ_Rev2/LAYOUT.png"),
    # left-anchored so the live thrust plot stays whole; the settings modal opens at ~4 s
    dict(slug="daq-software", tile="DAQ_GUI/GUI.gif", detail="DAQ_GUI/Command_Central.png",
         focus=(0, 0.5), start=0, duration=8),
    dict(slug="rocket-engine", tile="SARP_LabVIEW/ENGINE.png", detail="SARP_LabVIEW/GUI.png",
         focus=(0.2, 0.5)),
    dict(slug="hv-capacitor", tile="Zap_MTS/Bank Q.png", detail="Zap_MTS/LabVIEW_GUI.png"),
    dict(slug="antenna-capstone",
         tile="Blue Origin/Blue-Origin-EVALUATION-OF-HIGH-FREQUENCY-SUBSTRATES-1.pdf",
         detail="Blue Origin/Blue-Origin-EVALUATION-OF-HIGH-FREQUENCY-SUBSTRATES-1.pdf",
         focus=(0.5, 0)),
    # box drops the letterbox; the centre crop keeps the seam between the two feeds and the
    # motion-highlight border that appears on the front door camera
    dict(slug="unifi-cams", tile="House_Cams/cams_vid.gif", detail="House_Cams/MONITOR.png",
         box=(0, 0.25, 1, 0.75), start=1, duration=6, fps=10, colors=48),
    # both crops leave out the phone number printed on the card
    dict(slug="nfc-business-card", tile="Business_Card/FRONT.png", detail="Business_Card/NFC.png",
         box=(0, 0.12, 1, 0.72), detail_box=(0.31, 0, 1, 1)),
    dict(slug="relay-switch", tile="Relay_Switch/BACK_PIC.png", detail="Relay_Switch/LAYOUT.png"),
    dict(slug="daq-enclosure", tile="DAQ_Enclosure/internals.png", detail="DAQ_Enclosure/connectors.png"),
    dict(slug="debugstream", tile="DebugStream/V4.png", detail="DebugStream/DebugStream_GUI.png"),
    dict(slug="polybot", tile="PolyBot/BUY_LIST.png", detail="PolyBot/SHEET.png"),
]


def load(path: Path) -> Image.Image:
    """Open an image or the first page of a PDF as flat RGB."""
    if path.suffix.lower() == ".pdf":
        import pymupdf  # only needed for PDF sources

        page = pymupdf.open(path)[0]
        zoom = 3000 / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    im = Image.open(path)
    im.seek(0)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, BG)
        flat.paste(im, mask=im.getchannel("A"))
        return flat
    return im.convert("RGB")


def precrop(im: Image.Image, box) -> Image.Image:
    if not box:
        return im
    w, h = im.size
    left, top, right, bottom = box
    return im.crop((round(left * w), round(top * h), round(right * w), round(bottom * h)))


def fill(im: Image.Image, w: int, h: int, focus=(0.5, 0.5)) -> Image.Image:
    scale = max(w / im.width, h / im.height)
    sw, sh = round(im.width * scale), round(im.height * scale)
    im = im.resize((sw, sh), Image.LANCZOS, reducing_gap=3.0)
    x = round((sw - w) * focus[0])
    y = round((sh - h) * focus[1])
    return im.crop((x, y, x + w, y + h))


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    scale = min(w / im.width, h / im.height)
    sw, sh = round(im.width * scale), round(im.height * scale)
    im = im.resize((sw, sh), Image.LANCZOS, reducing_gap=3.0)
    canvas = Image.new("RGB", (w, h), BG)
    canvas.paste(im, ((w - sw) // 2, (h - sh) // 2))
    return canvas


def to_width(im: Image.Image, w: int) -> Image.Image:
    if im.width <= w:
        return im
    return im.resize((w, round(im.height * w / im.width)), Image.LANCZOS, reducing_gap=3.0)


def save_jpeg(im: Image.Image, dst: Path) -> None:
    im.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)


def make_gif(src: Path, dst: Path, spec: dict) -> None:
    fx, fy = spec.get("focus", (0.5, 0.5))
    pre = ""
    if spec.get("box"):
        left, top, right, bottom = spec["box"]
        pre = f"crop=iw*{right - left}:ih*{bottom - top}:iw*{left}:ih*{top},"
    crop = f"crop={TILE_W}:{TILE_H}:(iw-{TILE_W})*{fx}:(ih-{TILE_H})*{fy}"
    graph = (
        f"fps={spec.get('fps', 12)},{pre}scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=increase:flags=lanczos,{crop},"
        f"split[a][b];[a]palettegen=max_colors={spec.get('colors', 128)}:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    )
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-ss", str(spec.get("start", 0)), "-t", str(spec.get("duration", 6)),
           "-i", str(src), "-filter_complex", graph, "-loop", "0", str(dst)]
    subprocess.run(cmd, check=True)
    if dst.stat().st_size > GIF_MAX_BYTES:
        print(f"  ! {dst.name} is over {GIF_MAX_BYTES / 1e6:.0f} MB; shorten its duration")


def build(spec: dict, src_root: Path) -> list[Path]:
    slug = spec["slug"]
    tile_src = src_root / spec["tile"]
    detail_src = src_root / spec["detail"]

    if tile_src.suffix.lower() == ".gif":
        tile_dst = OUT / f"{slug}.gif"
        make_gif(tile_src, tile_dst, spec)
    else:
        tile_dst = OUT / f"{slug}.jpg"
        im = precrop(load(tile_src), spec.get("box"))
        if spec.get("mode") == "fit":
            im = fit(im, TILE_W, TILE_H)
        else:
            im = fill(im, TILE_W, TILE_H, spec.get("focus", (0.5, 0.5)))
        save_jpeg(im, tile_dst)

    detail_dst = OUT / f"{slug}-detail.jpg"
    save_jpeg(to_width(precrop(load(detail_src), spec.get("detail_box")), DETAIL_W), detail_dst)
    return [tile_dst, detail_dst]


def main() -> None:
    src_root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src_root.is_dir():
        sys.exit(f"Portfolio projects folder not found: {src_root}")
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg is required for the animated tiles")

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for spec in PROJECTS:
        for path in build(spec, src_root):
            size = path.stat().st_size
            total += size
            with Image.open(path) as im:
                print(f"{path.name:32s} {im.width}x{im.height:<5d} {size / 1024:8.0f} KB")
    print(f"{'total':32s} {'':9s} {total / 1024:8.0f} KB")


if __name__ == "__main__":
    main()
