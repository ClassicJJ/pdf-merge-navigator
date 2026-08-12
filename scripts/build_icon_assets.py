from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


ICON_SIZES = tuple(
    (size, size) for size in (16, 24, 32, 48, 64, 128, 256)
)
CANVAS_SIZE = 512
ICON_MARGIN = 22


def _content_box(image: Image.Image) -> tuple[int, int, int, int]:
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background).convert("L")
    mask = difference.point(lambda value: 255 if value > 8 else 0)
    box = mask.getbbox()
    if box is None:
        raise ValueError("The source image does not contain a visible icon.")
    return box


def build_icon_assets(
    source_path: Path,
    png_path: Path,
    ico_path: Path,
) -> None:
    with Image.open(source_path) as source:
        source_rgb = source.convert("RGB")
    icon_diameter = CANVAS_SIZE - 2 * ICON_MARGIN
    artwork = source_rgb.crop(_content_box(source_rgb)).resize(
        (icon_diameter, icon_diameter),
        Image.Resampling.LANCZOS,
    )

    scale = 4
    alpha_large = Image.new(
        "L",
        (icon_diameter * scale, icon_diameter * scale),
        0,
    )
    ImageDraw.Draw(alpha_large).ellipse(
        (0, 0, icon_diameter * scale - 1, icon_diameter * scale - 1),
        fill=255,
    )
    alpha = alpha_large.resize(
        (icon_diameter, icon_diameter),
        Image.Resampling.LANCZOS,
    )
    artwork.putalpha(alpha)

    icon = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    icon.alpha_composite(artwork, (ICON_MARGIN, ICON_MARGIN))
    png_path.parent.mkdir(parents=True, exist_ok=True)
    icon.save(png_path, format="PNG", optimize=True)
    icon.save(ico_path, format="ICO", sizes=ICON_SIZES)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("png", type=Path)
    parser.add_argument("ico", type=Path)
    arguments = parser.parse_args()
    build_icon_assets(arguments.source, arguments.png, arguments.ico)


if __name__ == "__main__":
    main()
