"""
OCR for the carat count on the career-complete results screen.

Unlike the timer (a presence check, handled by perceptual hashing in
detect.py), this needs the actual numeric value, so it genuinely needs
OCR. The result is always shown to the user to confirm/edit before it's
committed to the daily total -- OCR misreads on stylized digits are
common enough that this shouldn't be trusted blindly.
"""
from __future__ import annotations

import re
from typing import Optional

import pytesseract
from PIL import Image, ImageOps

_DIGIT_PATTERN = re.compile(r"\d[\d,]*")


def _preprocess(img: Image.Image, upscale: int = 3) -> Image.Image:
    """Grayscale + threshold + upscale -- makes stylized/anti-aliased
    game fonts far more reliable for tesseract than the raw crop."""
    gray = ImageOps.grayscale(img)
    # Simple fixed threshold; works well for high-contrast UI text.
    # If results are unreliable in practice, this is the first place to
    # tune (e.g. adaptive thresholding) once real captures are available.
    bw = gray.point(lambda p: 255 if p > 140 else 0)
    if upscale > 1:
        bw = bw.resize((bw.width * upscale, bw.height * upscale), Image.LANCZOS)
    return bw


def extract_carat_count(img: Image.Image) -> Optional[int]:
    """Returns the parsed integer carat count, or None if nothing
    digit-shaped was found in the region."""
    processed = _preprocess(img)
    # PSM 7 = treat the region as a single line of text, which fits a
    # tightly drag-selected carat-count crop.
    raw_text = pytesseract.image_to_string(
        processed, config="--psm 7 -c tessedit_char_whitelist=0123456789,"
    )
    match = _DIGIT_PATTERN.search(raw_text)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    try:
        return int(digits)
    except ValueError:
        return None
