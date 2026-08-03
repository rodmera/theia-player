"""Tests for theiaplayer.anim — pure animation primitives.

These are the renderer the heartbeat calls every tick. A bug here
gets burned into every frame in the app, so the suite covers every
public function plus the ANSI-vs-truecolor branch on shaders that
degrade gracefully on the `system` theme.
"""

from __future__ import annotations

import pytest

from theiaplayer import anim
from ricekit import palette


# ── color math ─────────────────────────────────────────────────────────


def test_blend_returns_c1_under_ansi_palette():
    """On the `system` theme there are no RGB values to blend; the
    function must return c1 untouched so the UI doesn't crash."""
    palette.set_ansi(True)
    try:
        assert anim.blend("#ff0000", "#00ff00", 0.5) == "#ff0000"
        assert anim.blend("anything", "anything", 0.0) == "anything"
    finally:
        palette.set_ansi(False)


def test_blend_mixes_truecolor_at_half():
    palette.set_ansi(False)
    out = anim.blend("#000000", "#ffffff", 0.5)
    # Python's round() uses banker's rounding: round(127.5) == 128
    assert out == "#808080"


def test_blend_mixes_truecolor_at_quarter():
    palette.set_ansi(False)
    out = anim.blend("#000000", "#ffffff", 0.25)
    # 0 + (255-0)*0.25 = 63.75 → round → 64 → 0x40
    assert out == "#404040"


def test_blend_clamps_t_to_zero_and_one():
    palette.set_ansi(False)
    a = anim.blend("#000000", "#ffffff", -0.5)
    b = anim.blend("#000000", "#ffffff", 1.5)
    assert a == "#000000"
    assert b == "#ffffff"


def test_blend_returns_c1_on_unparseable_color():
    palette.set_ansi(False)
    assert anim.blend("not-a-color", "#ffffff", 0.5) == "not-a-color"


def test_can_blend_is_false_under_ansi():
    palette.set_ansi(True)
    try:
        assert anim.can_blend() is False
    finally:
        palette.set_ansi(False)
    assert anim.can_blend() is True


# ── shimmer ─────────────────────────────────────────────────────────────


def test_shimmer_under_ansi_returns_flat_styled_text():
    palette.set_ansi(True)
    try:
        out = anim.shimmer("hello", phase=5.0, base="red", glow="white")
        assert out.plain == "hello"
    finally:
        palette.set_ansi(False)


def test_shimmer_truecolor_phase_loops_without_errors():
    palette.set_ansi(False)
    text = "theia-player"
    for phase in (0.0, 3.0, 10.0, 50.0, 100.0):
        out = anim.shimmer(text, phase=phase, base="#000000", glow="#ffffff")
        assert out.plain == text
        assert len(out) == len(text)


def test_shimmer_empty_string_returns_empty():
    palette.set_ansi(False)
    out = anim.shimmer("", phase=0.0, base="#000000", glow="#ffffff")
    assert out.plain == ""


# ── smooth_bar ─────────────────────────────────────────────────────────


def test_smooth_bar_clamps_fraction_outside_zero_one():
    """Negative fraction → clamp to 0 (empty); >1 → clamp to 1 (full)."""
    empty = anim.smooth_bar(-0.5, width=10).plain
    full = anim.smooth_bar(1.5, width=10).plain
    assert empty == "─" * 10
    # full = "━━━━━━━━━●"  (9 fills + 1 head = width 10)
    assert full == "━━━━━━━━━●"
    assert len(full) == 10


def test_smooth_bar_zero_fraction_is_all_empty():
    bar = anim.smooth_bar(0.0, width=5)
    assert bar.plain == "─────"


def test_smooth_bar_full_fraction_is_all_filled():
    bar = anim.smooth_bar(1.0, width=5)
    assert bar.plain == "━━━━●"


def test_smooth_bar_half_fraction_renders_slider():
    bar = anim.smooth_bar(0.5, width=4)
    # 0.5 * 4 = 2, so 2 cells filled minus 1 = 1 line + 1 head
    assert bar.plain == "━●──"


def test_smooth_bar_single_char_width():
    bar = anim.smooth_bar(0.0, width=1)
    assert bar.plain == "─"
    bar = anim.smooth_bar(1.0, width=1)
    assert bar.plain == "●"


# ── mini_gauge ─────────────────────────────────────────────────────────


def test_mini_gauge_zero_is_all_empty():
    assert anim.mini_gauge(0.0, width=4).plain == "▯▯▯▯"


def test_mini_gauge_full_is_all_lit():
    assert anim.mini_gauge(1.0, width=4).plain == "▮▮▮▮"


def test_mini_gauge_clamps_fraction():
    assert anim.mini_gauge(-1.0, width=4).plain == anim.mini_gauge(0.0, width=4).plain
    assert anim.mini_gauge(2.0, width=4).plain == anim.mini_gauge(1.0, width=4).plain


def test_mini_gauge_default_width_is_six():
    # round(0.5 * 6) = 3 lit, 3 empty
    assert anim.mini_gauge(0.5).plain == "▮▮▮▯▯▯"


# ── marquee ────────────────────────────────────────────────────────────


def test_marquee_short_text_returned_unchanged():
    assert anim.marquee("hi", width=10, tick=0) == "hi"


def test_marquee_text_exactly_width_returned_unchanged():
    """``len(text) <= width`` short-circuits to the original text."""
    assert anim.marquee("0123456789", width=10, tick=0) == "0123456789"


def test_marquee_long_text_scrolls_with_tick():
    """The marquee must produce different output at different ticks when
    the text is longer than the viewport."""
    text = "abcdefghij" * 3  # 30 chars
    width = 5
    snapshots = {anim.marquee(text, width, tick=t) for t in range(40)}
    # The marquee loops, so we expect dozens of distinct windows
    assert len(snapshots) > 5


def test_marquee_resets_to_zero_at_each_loop():
    """A long text with a tick matching the loop span should hit the
    start-of-text window (after the dwell)."""
    text = "abcdefghij"
    width = 5
    snap = anim.marquee(text, width, tick=0)
    assert snap == "abcde"  # first 5 chars
    # After span + dwell, the window starts at offset 0 again
    span = len(text + "   ·   ")  # marquee gap is appended
    snap = anim.marquee(text, width, tick=span + anim._MARQUEE_DWELL)
    assert snap == "abcde"


# ── fmt_time ───────────────────────────────────────────────────────────


def test_fmt_time_zero_returns_zero_zero():
    assert anim.fmt_time(0) == "0:00"


def test_fmt_time_none_returns_zero_zero():
    assert anim.fmt_time(None) == "0:00"


def test_fmt_time_negative_returns_zero_zero():
    assert anim.fmt_time(-5) == "0:00"


def test_fmt_time_under_an_hour():
    assert anim.fmt_time(45) == "0:45"
    assert anim.fmt_time(60) == "1:00"
    assert anim.fmt_time(125) == "2:05"
    assert anim.fmt_time(360) == "6:00"


def test_fmt_time_over_an_hour_uses_h_m_s():
    assert anim.fmt_time(3600) == "1:00:00"
    assert anim.fmt_time(3661) == "1:01:01"
    assert anim.fmt_time(7325) == "2:02:05"


def test_fmt_time_truncates_fractional_seconds():
    assert anim.fmt_time(125.7) == "2:05"


def test_fmt_time_float_under_one_second():
    assert anim.fmt_time(0.4) == "0:00"


# ── VizModel ───────────────────────────────────────────────────────────


def test_viz_model_init_zero_heights():
    m = anim.VizModel(bars=5, seed=0)
    assert m.n == 5
    assert m.heights == [0.0] * 5
    assert m.energy == 0.0


def test_viz_model_silent_tick_collapses_to_zero():
    """With energy=0 (paused), all bars must decay to 0 (asymptotically)."""
    m = anim.VizModel(bars=3, seed=1)
    m.energy = 0.0
    # Prime bars to nonzero state
    m.heights = [0.5, 0.7, 0.9]
    for _ in range(50):
        m.tick()
    # Asymptotic decay: 50 ticks of 0.45 damping leaves essentially zero
    assert all(h < 1e-6 for h in m.heights)


def test_viz_model_silent_tick_targets_are_zero():
    """Targets reset to zero when energy falls below the threshold."""
    m = anim.VizModel(bars=3, seed=2)
    m.energy = 0.0
    for _ in range(5):
        m.tick()
    assert m.targets == [0.0, 0.0, 0.0]


def test_viz_model_playing_tick_stays_bounded():
    m = anim.VizModel(bars=5, seed=42)
    m.energy = 1.0
    for _ in range(50):
        m.tick()
        for h in m.heights:
            assert 0.0 <= h <= 1.0


def test_viz_model_render_emits_one_block_per_bar():
    m = anim.VizModel(bars=4, seed=7)
    m.energy = 1.0
    for _ in range(5):
        m.tick()
    out = m.render()
    # each bar is one block character
    assert len(out) == 4


def test_viz_model_render_ansi_branch_does_not_crash():
    palette.set_ansi(True)
    try:
        m = anim.VizModel(bars=3, seed=1)
        m.energy = 90.0  # push beyond clamp target
        for _ in range(5):
            m.tick()
        out = m.render()
        assert len(out) == 3
    finally:
        palette.set_ansi(False)


# ── glyph cycles ───────────────────────────────────────────────────────


def test_note_cycles_through_frames():
    """NOTE_FRAMES = ["♪", "♫", "♪", "♬"] — note ♪ appears twice, so
    we expect 3 distinct glyphs across a long tick sweep."""
    seen = {anim.note(t) for t in range(60)}
    assert seen == set(anim.NOTE_FRAMES)


def test_note_chunks_every_three_ticks():
    """``tick // 3`` means notes advance once per 3 ticks; any two ticks
    within the same chunk produce the same glyph."""
    assert anim.note(0) == anim.note(1) == anim.note(2)
    assert anim.note(3) == anim.note(4) == anim.note(5)


def test_spinner_cycles_through_frames():
    seen = {anim.spinner(t) for t in range(20)}
    assert len(seen) > 1  # 10-frame cycle, all unique


def test_note_and_spinner_unicode_only():
    for t in range(50):
        assert isinstance(anim.note(t), str)
        assert isinstance(anim.spinner(t), str)
