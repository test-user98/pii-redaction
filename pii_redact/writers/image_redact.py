"""Paint surrogate text over word boxes in an image (used for OCR'd PII)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont


def redact_image(png_bytes: bytes, boxes: list[tuple[tuple[float, float, float, float], str]]) -> bytes:
    """boxes: [((x0, y0, x1, y1) in image px, surrogate_text)] -> PNG bytes, same size."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for (x0, y0, x1, y1), text in boxes:
        draw.rectangle((x0, y0, x1, y1), fill="white")
        if not text:
            continue
        size = max(6, int((y1 - y0) * 0.8))
        font = ImageFont.load_default(size=size)
        while size > 6 and draw.textlength(text, font=font) > (x1 - x0):
            size -= 1
            font = ImageFont.load_default(size=size)
        draw.text((x0, y0), text, fill="black", font=font)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
