from __future__ import annotations

from pathlib import Path
from PIL import Image


def convert_png_to_webp(png_path: Path, destination_dir: Path, quality: int = 80) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{png_path.stem}.webp"
    with Image.open(png_path) as image:
        image.save(destination, "WEBP", quality=quality)
    return destination


def convert_all_png_to_webp(source_dir: Path, destination_dir: Path, quality: int = 80) -> int:
    destination_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for png_path in sorted(source_dir.glob("*.png")):
        try:
            destination = convert_png_to_webp(png_path, destination_dir, quality)
            print(f"[IMAGE] WebP保存: {destination}")
            count += 1
        except Exception as exc:
            print(f"[IMAGE] WebP変換失敗: {png_path.name}: {exc}")
    return count
