"""Compose the README hero: network screenshots stacked as cards, DI.FM on top.

    uv run python tools/readme_hero.py

Reads the screenshots listed in CARDS from docs/assets, trims the terminal
padding around each one and writes docs/assets/hero-networks.png with a
transparent background so it works with GitHub's light and dark themes.
Cards are scaled by width, so capture every screenshot at the same terminal
size and font (the current set is about 122x30 cells) or the text sizes in
the stack won't match.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
OUTPUT = ASSETS / "hero-networks.png"
CARDS = [  # front to back; neighbors alternate so title bars stay distinct
    "screenshot-channels.png",
    "jazz-radio.png",
    "classical-radio.png",
    "rock-radio.png",
    "radio-tunes.png",
    "zen-radio.png",
]
SHRINK = 0.04  # per card behind the front one
PEEK = 64  # px of each card's title bar left visible above the next one
DIM = 0.1  # per card behind the front one
RADIUS = 22
MARGIN = 70


def trim_padding(image: Image.Image, tolerance: int = 10) -> Image.Image:
    """Crop the terminal's padding, sampled from the bottom edge."""
    image = image.convert("RGB")
    padding = image.getpixel((image.width // 2, image.height - 1))
    diff = ImageChops.difference(image, Image.new("RGB", image.size, padding))
    mask = diff.convert("L").point(lambda v: 255 if v > tolerance else 0)
    return image.crop(mask.getbbox())


def rounded_card(image: Image.Image, dim: float) -> Image.Image:
    box = (0, 0, image.width - 1, image.height - 1)
    card = image.convert("RGBA")
    if dim:
        shade = Image.new("RGBA", card.size, (0, 0, 0, round(255 * dim)))
        card = Image.alpha_composite(card, shade)
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, RADIUS, fill=255)
    card.putalpha(mask)
    # A faint rim keeps the edges visible on GitHub's dark background.
    rim = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        box, RADIUS, outline=(255, 255, 255, 40), width=2
    )
    return Image.alpha_composite(card, rim)


def drop_shadow(size: tuple[int, int], blur: int = 22) -> tuple[Image.Image, int]:
    pad = blur * 3
    shadow = Image.new("RGBA", (size[0] + 2 * pad, size[1] + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad, pad + size[0], pad + size[1]), RADIUS, fill=(0, 0, 0, 150)
    )
    return shadow.filter(ImageFilter.GaussianBlur(blur)), pad


def main() -> None:
    shots = [trim_padding(Image.open(ASSETS / name)) for name in CARDS]
    front_width = shots[0].width
    cards = []
    for depth, shot in enumerate(shots):
        width = round(front_width * (1 - SHRINK * depth))
        if width != shot.width:
            height = round(shot.height * width / shot.width)
            shot = shot.resize((width, height), Image.LANCZOS)
        x = MARGIN + (front_width - width) // 2
        y = MARGIN + PEEK * (len(shots) - 1 - depth)
        cards.append((rounded_card(shot, DIM * depth), x, y))

    front, _, front_y = cards[0]
    canvas = Image.new(
        "RGBA",
        (front_width + 2 * MARGIN, front_y + front.height + MARGIN),
        (0, 0, 0, 0),
    )
    for card, x, y in reversed(cards):
        shadow, pad = drop_shadow(card.size)
        canvas.alpha_composite(shadow, (x - pad, y - pad + 14))
        canvas.alpha_composite(card, (x, y))
    canvas.save(OUTPUT, optimize=True)
    print(f"{OUTPUT.relative_to(ROOT)} {canvas.width}x{canvas.height}")


if __name__ == "__main__":
    main()
