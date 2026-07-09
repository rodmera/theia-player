"""Animation primitives — pure functions the widgets call every tick.

Everything here degrades gracefully under the `system` theme: ANSI palette
colors can't be blended (there are no RGB values to blend), so gradients and
shimmers collapse to flat styled text instead of crashing or banding.
"""

from __future__ import annotations

import math

from rich.color import Color
from rich.text import Text

from ricekit import palette

# ── color math ─────────────────────────────────────────────────────────


def _rgb(color: str) -> tuple[int, int, int] | None:
    try:
        triplet = Color.parse(color).get_truecolor()
    except Exception:
        return None
    return (triplet.red, triplet.green, triplet.blue)


def blend(c1: str, c2: str, t: float) -> str:
    """Mix two colors. Under the ANSI palette there's nothing honest to
    blend (the terminal owns the real values), so return c1 untouched."""
    if palette.is_ansi:
        return c1
    a, b = _rgb(c1), _rgb(c2)
    if a is None or b is None:
        return c1
    t = max(0.0, min(1.0, t))
    return "#{:02x}{:02x}{:02x}".format(
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def can_blend() -> bool:
    return not palette.is_ansi


# ── the shimmer (the constant logo animation) ──────────────────────────

SHIMMER_TAIL = 10  # phase cells past the end so the glow slides fully off


def shimmer(text: str, phase: float, base: str, glow: str, window: float = 4.0) -> Text:
    """A soft highlight that sweeps across `text`. `phase` loops over
    len(text) + SHIMMER_TAIL. Flat text under ANSI palettes."""
    out = Text()
    if not can_blend():
        out.append(text, style=f"bold {base}")
        return out
    center = (phase % (len(text) + SHIMMER_TAIL)) - SHIMMER_TAIL / 2
    for i, ch in enumerate(text):
        d = abs(i - center)
        intensity = max(0.0, 1.0 - d / window) ** 2
        style = blend(base, glow, intensity)
        out.append(ch, style=f"bold {style}" if intensity > 0.55 else style)
    return out


# ── smooth progress bar (sub-cell precision) ───────────────────────────

_EIGHTHS = "▏▎▍▌▋▊▉█"


def smooth_bar(fraction: float, width: int, head_pulse: float = 0.0) -> Text:
    """A minimal, elegant progress slider.

    Replaces blocky full-cell blocks with a slim horizontal line and a circular
    slider head, delivering a premium, minimalist web-like aesthetic.
    """
    fraction = max(0.0, min(1.0, fraction))
    filled_width = round(fraction * width)
    
    fill_color = blend(palette.blue, palette.lav, 0.3)
    head_color = blend(fill_color, palette.text, 0.55 * head_pulse)
    
    bar = Text()
    if filled_width > 0:
        if filled_width > 1:
            # Parte llena de la línea (línea horizontal de grosor medio)
            bar.append("━" * (filled_width - 1), style=fill_color)
        # Cabeza deslizante en forma de círculo nítido
        bar.append("●", style=head_color)
        
    empty_width = width - filled_width
    if empty_width > 0:
        # Parte vacía de la línea (línea horizontal delgada simple)
        bar.append("─" * empty_width, style=palette.vfaint)
        
    return bar


def mini_gauge(fraction: float, width: int = 6) -> Text:
    """Small blocky gauge for volume."""
    fraction = max(0.0, min(1.0, fraction))
    lit = round(fraction * width)
    t = Text()
    t.append("▮" * lit, style=palette.lav)
    t.append("▯" * (width - lit), style=palette.vfaint)
    return t


# ── marquee ────────────────────────────────────────────────────────────

_MARQUEE_GAP = "   ·   "
_MARQUEE_DWELL = 10  # ticks to rest at the start of each loop


def marquee(text: str, width: int, tick: int) -> str:
    """Slide text that doesn't fit; text that fits is returned untouched."""
    if len(text) <= width:
        return text
    loop = text + _MARQUEE_GAP
    span = len(loop)
    pos = tick % (span + _MARQUEE_DWELL)
    offset = 0 if pos < _MARQUEE_DWELL else pos - _MARQUEE_DWELL
    doubled = loop + loop
    return doubled[offset : offset + width]


# ── time ───────────────────────────────────────────────────────────────


def fmt_time(seconds: float | int | None) -> str:
    if not seconds or seconds < 0:
        return "0:00"
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


# ── the visualizer model (widget-free so it's testable) ────────────────

_BLOCKS = " ▁▂▃▄▅▆▇█"


class VizModel:
    """Fake-but-lively EQ bars: each bar eases toward a random target that
    re-rolls near arrival. Energy 1.0 = playing, 0.0 = silent; pausing
    lets the bars fall to the floor instead of freezing mid-air."""

    def __init__(self, bars: int = 5, seed: int = 0) -> None:
        self.n = bars
        self.heights = [0.0] * bars
        self.targets = [0.0] * bars
        self.energy = 0.0
        self._t = seed

    def tick(self) -> None:
        self._t += 1
        for i in range(self.n):
            if self.energy > 0.05:
                if abs(self.heights[i] - self.targets[i]) < 0.08:
                    # deterministic-ish wobble: cheap hash of bar + time
                    r = math.sin(self._t * 12.9898 + i * 78.233) * 43758.5453
                    self.targets[i] = (r - math.floor(r)) * self.energy
            else:
                self.targets[i] = 0.0
            self.heights[i] += (self.targets[i] - self.heights[i]) * 0.45

    def render(self) -> Text:
        t = Text()
        blendable = can_blend()
        for i, h in enumerate(self.heights):
            ch = _BLOCKS[min(len(_BLOCKS) - 1, round(h * (len(_BLOCKS) - 1)))]
            if blendable:
                color = blend(palette.blue, palette.mauve, i / max(1, self.n - 1))
                color = blend(palette.faint, color, 0.35 + 0.65 * h)
            else:
                color = palette.blue
            t.append(ch, style=color)
        return t


# ── glyph cycles ───────────────────────────────────────────────────────

NOTE_FRAMES = ["♪", "♫", "♪", "♬"]
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner(tick: int) -> str:
    return SPINNER[tick % len(SPINNER)]


def note(tick: int) -> str:
    return NOTE_FRAMES[(tick // 3) % len(NOTE_FRAMES)]
