"""Tests for theiaplayer.art.cmyk_to_rgb_safe().

Verifies the CMYK normalization that prevents ``textual-image`` from
crashing on CMYK-sourced JPEG cover art with
``OSError: cannot write mode CMYK as PNG``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from theiaplayer.art import cmyk_to_rgb_safe


def _cmyk_jpeg(path: Path, color=(0, 100, 100, 0), size=(10, 10)) -> None:
    Image.new("CMYK", size, color).save(path, "JPEG")


def _rgb_jpeg(path: Path, color=(120, 80, 200), size=(10, 10)) -> None:
    Image.new("RGB", size, color).save(path, "JPEG")


def test_cmyk_to_rgb_converts_cmyk_to_rgb_in_place():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cover.jpg"
        _cmyk_jpeg(path)
        assert Image.open(path).mode == "CMYK"
        converted = cmyk_to_rgb_safe(path)
        assert converted is True
        assert Image.open(path).mode == "RGB"


def test_cmyk_to_rgb_no_op_for_already_rgb():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cover.jpg"
        _rgb_jpeg(path)
        assert Image.open(path).mode == "RGB"
        converted = cmyk_to_rgb_safe(path)
        assert converted is False
        # File untouched.
        assert Image.open(path).mode == "RGB"


def test_cmyk_to_rgb_returns_false_for_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "does_not_exist.jpg"
        assert cmyk_to_rgb_safe(path) is False


def test_cmyk_to_rgb_returns_false_for_corrupt_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "garbage.jpg"
        path.write_bytes(b"not a real jpeg")
        # Must not raise — broken cover art must never crash the player.
        assert cmyk_to_rgb_safe(path) is False


def test_cmyk_to_rgb_preserves_pixels():
    """A plain CMYK swatch converts to the same visible RGB color."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cover.jpg"
        # Use a neutral CMYK so the RGB conversion is predictable.
        Image.new("CMYK", (4, 4), (0, 0, 0, 0)).save(path, "JPEG")
        cmyk_to_rgb_safe(path)
        # PIL converts (0,0,0,0) CMYK to white (255,255,255) by default.
        # Sample 4 corners (always non-empty) and assert each is near-white.
        # ``getpixel`` on a real RGB image returns ``tuple[int, int, int]``;
        # pyright's PIL stubs widen it to ``float | None | tuple[...]``, so
        # we narrow with an explicit cast.
        with Image.open(path).convert("RGB") as rgb:
            assert rgb.mode == "RGB"
            for x, y in [(0, 0), (3, 0), (0, 3), (3, 3)]:
                r, g, b = rgb.getpixel((x, y))  # type: ignore[misc]
                assert r >= 250 and g >= 250 and b >= 250, (
                    f"expected near-white at ({x},{y}), got ({r},{g},{b})"
                )