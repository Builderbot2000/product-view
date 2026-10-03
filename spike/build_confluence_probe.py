"""Build the Confluence HTML-import probe zip (milestone 1 spike).

Confluence Cloud's HTML import accepts only a .zip holding one folder of .html
files. The folder name becomes the space name, and a page's media sits in a
folder named after the page. This script writes the probe image into that media
folder and zips spike/confluence-probe/ into out/confluence-probe.zip.

    python spike/build_confluence_probe.py
"""

import struct
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "spike" / "confluence-probe"
SPACE_DIR = SOURCE / "Product View Probe"
OUT = ROOT / "out" / "confluence-probe.zip"


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A single-colour PNG, stdlib only, so the probe needs no image library."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width  # filter byte 0, then RGB pixels
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    media = SPACE_DIR / "ProbeDashboard"
    media.mkdir(exist_ok=True)
    (media / "probe-image.png").write_bytes(solid_png(120, 40, (9, 105, 218)))

    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SPACE_DIR.rglob("*")):
            if path.is_file():
                # Forward slashes and a single top-level folder, as the importer expects.
                zf.write(path, path.relative_to(SOURCE).as_posix())

    print(f"wrote {OUT}")
    with zipfile.ZipFile(OUT) as zf:
        for name in zf.namelist():
            print(f"  {name}")


if __name__ == "__main__":
    main()
