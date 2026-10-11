"""Assemble real browser captures into a captioned README walkthrough.

Capture the synthetic public demo through the browser, then run this script.
Screenshots are preserved; the caption area is added above each original frame.
Requires Pillow (included in the desktop development dependencies).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "docs" / "images" / "web"
SLIDES = (
    ("data.png", "01 / INSPECT", "Start with deliberately imperfect data.", 3500),
    ("rules.png", "02 / UNDERSTAND", "Read the SQL behind every check.", 4500),
    ("report-dirty.png", "03 / INVESTIGATE", "8 failed checks. Each one has evidence.", 4500),
    ("report-clean.png", "04 / VERIFY", "Repair, rerun: 48 checks pass. History stays.", 5000),
)


def font(size, bold=False):
    candidates = (
        Path("C:/Windows/Fonts") / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    )
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def main():
    images = [Image.open(DIRECTORY / name).convert("RGB") for name, *_ in SLIDES]
    if len({im.size for im in images}) != 1:
        raise ValueError("Capture all slides at the same browser size.")
    width, height = images[0].size
    frames = []
    for index, (source, (_, label, caption, _)) in enumerate(zip(images, SLIDES)):
        canvas = Image.new("RGB", (width, height + 104), "#12243a")
        canvas.paste(source, (0, 104))
        draw = ImageDraw.Draw(canvas)
        draw.text((26, 16), label, font=font(16, True), fill="#77ddd4")
        draw.text((26, 43), caption, font=font(23, True), fill="#ffffff")
        for step in range(len(SLIDES)):
            x = 26 + step * ((width - 52) // len(SLIDES))
            draw.rounded_rectangle((x, 86, x + (width - 68) // len(SLIDES), 90), radius=2,
                                   fill="#77ddd4" if step <= index else "#365066")
        frames.append(canvas.quantize(colors=192, method=Image.Quantize.MEDIANCUT))
    destination = DIRECTORY / "workflow.gif"
    frames[0].save(destination, save_all=True, append_images=frames[1:],
                   duration=[slide[3] for slide in SLIDES], loop=0, optimize=True, disposal=2)
    print(f"{destination.name}: {len(frames)} frames, {destination.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
