"""
Autorun-timer presence detection via perceptual hashing.

Deliberately NOT OCR. The timer container has static elements (border,
icon, "AUTO" label, panel background) that don't change frame to frame,
even though the digits inside it do. We hash the whole region including
those static elements; a countdown ticking by changes only a small part
of the pixels, so the hash stays within a small distance of the reference
the entire time the box is on screen. Comparing hashes is far cheaper
than OCR's classification pipeline and is exactly what we need for a
presence check rather than reading a value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import imagehash
from PIL import Image


# Fallback if calibration only had one sample to work with.
FALLBACK_MAX_DISTANCE = 10
# Safety margin added on top of the largest distance observed between
# same-timer-different-tick samples during calibration.
CALIBRATION_MARGIN = 4


@dataclass(frozen=True)
class ReferenceHash:
    hash_str: str
    max_distance: int = FALLBACK_MAX_DISTANCE

    @classmethod
    def from_image(cls, img: Image.Image, max_distance: int = FALLBACK_MAX_DISTANCE) -> "ReferenceHash":
        h = imagehash.phash(img)
        return cls(hash_str=str(h), max_distance=max_distance)

    @classmethod
    def calibrate(cls, samples: List[Image.Image]) -> "ReferenceHash":
        """Build a reference from multiple frames captured ~1s apart while
        the timer box is visible (so the digits differ between samples but
        the surrounding chrome doesn't). The threshold is derived from how
        much the hash naturally moves just from the digits ticking, rather
        than a fixed guess -- this is what keeps a per-second-changing
        countdown from being misread as "the box disappeared"."""
        if not samples:
            raise ValueError("calibrate() needs at least one sample image")
        hashes = [imagehash.phash(img) for img in samples]
        reference_hash = hashes[0]
        if len(hashes) == 1:
            max_distance = FALLBACK_MAX_DISTANCE
        else:
            max_distance = int(max(reference_hash - h for h in hashes[1:])) + CALIBRATION_MARGIN
        return cls(hash_str=str(reference_hash), max_distance=max_distance)

    def to_hash(self) -> imagehash.ImageHash:
        return imagehash.hex_to_hash(self.hash_str)


def is_timer_present(current: Image.Image, reference: ReferenceHash) -> bool:
    """True if `current` is close enough to the reference to count as
    'the timer box is showing'."""
    current_hash = imagehash.phash(current)
    distance = int(current_hash - reference.to_hash())
    return bool(distance <= reference.max_distance)
