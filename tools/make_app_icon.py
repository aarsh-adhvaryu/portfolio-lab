"""Draw the dashboard's icon (a rising chart line on blue) as src/pflab/app/static/pflab.ico (S54)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "pflab" / "app" / "static" / "pflab.ico"


def draw(size: int = 256) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 4, fill=(29, 78, 216, 255))
    s = size / 32
    w = max(2, int(2.8 * s))
    line = [(6 * s, 22 * s), (13 * s, 15 * s), (18 * s, 20 * s), (26 * s, 11 * s)]
    d.line(line, fill="white", width=w, joint="curve")
    d.line([(20 * s, 11 * s), (26 * s, 11 * s), (26 * s, 17 * s)], fill="white", width=w, joint="curve")
    for x, y in line[1:3]:
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill="white")
    return im


if __name__ == "__main__":
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(OUT)
