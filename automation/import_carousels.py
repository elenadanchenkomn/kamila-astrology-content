"""Import dated PNG carousels from incoming/*.zip into images/2026/10/."""
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "incoming"
OUT = ROOT / "images" / "2026" / "10"
OUT.mkdir(parents=True, exist_ok=True)
MAX_SIZE = 15 * 1024 * 1024
MAX_IMAGES = 20

for archive in sorted(INCOMING.glob("*.zip")):
    match = re.search(r"(2026-10-\d{2})", archive.stem)
    if not match:
        print(f"Skipping {archive.name}: include YYYY-MM-DD in ZIP filename")
        continue
    date = match.group(1)
    with zipfile.ZipFile(archive) as z:
        images = [entry for entry in z.infolist() if not entry.is_dir() and entry.filename.lower().endswith(".png")]
        if not (1 <= len(images) <= MAX_IMAGES):
            raise ValueError(f"{archive.name}: expected 1-{MAX_IMAGES} PNGs")
        for i, entry in enumerate(sorted(images, key=lambda x: x.filename), 1):
            if entry.file_size > MAX_SIZE:
                raise ValueError(f"{entry.filename}: PNG too large")
            data = z.read(entry)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"{entry.filename}: invalid PNG signature")
            path = OUT / f"{date}-slide-{i:02d}.png"
            path.write_bytes(data)
            print(f"Imported {path.relative_to(ROOT)}")
