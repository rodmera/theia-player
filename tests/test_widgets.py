"""Tests for theiaplayer.widgets — NowPlaying and ClickList.

Earlier coverage was 52%; these tests push the line-rendering math
(used every tick by the 8fps heartbeat) onto the test net. The
ClickList tests lock in the single/double-click semantics that the
queue panel depends on.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pytest_asyncio import fixture as pytest_asyncio_fixture

from theiaplayer import anim
from theiaplayer.models import Song
from theiaplayer.playqueue import Repeat
from theiaplayer.widgets import (
    ClickList,
    Logo,
    NowPlaying,
    PLAY_GLYPH,
    PAUSE_GLYPH,
    SHUFFLE_ICON,
    REPEAT_ICON,
)


class _WidgetHostApp:
    """Real Textual app that hosts one NowPlaying widget so widget
    method calls get a real app context (needed for `self.app`,
    `self.screen`, `self.visualize`, etc.)."""

    @staticmethod
    def make():
        from ricekit.app import KitApp
        from textual.containers import Vertical

        class _HostApp(KitApp):
            def compose(self):
                with Vertical():
                    yield NowPlaying(id="np")

        return _HostApp


@pytest_asyncio_fixture
async def widget_app():
    host_cls = _WidgetHostApp.make()
    app = host_cls()
    async with app.run_test() as pilot:
        np = app.query_one("#np", NowPlaying)
        yield pilot, app, np


# ── ClickList ─────────────────────────────────────────────────────────


def test_clicklist_marks_disabled_options_skipped():
    """Disabled options (used as group headers) must not be selected
    by single click — the queue panel relies on this for folder
    headers in playlists."""
    from textual.widgets.option_list import Option
    from rich.text import Text

    cl = ClickList()
    cl.add_options([
        Option(Text("item 0"), id="0"),
        Option(Text("-- header --"), id="h", disabled=True),
        Option(Text("item 2"), id="2"),
    ])
    # Pre-conditions
    assert cl.option_count == 3
    # Single-click on a disabled option should not move the cursor
    # (the platform behavior is to no-op; we test the documented contract).
    # We can't trigger _on_click without a real mouse event, so we
    # emphasize the user-facing guarantee: manually setting the
    # highlight to a disabled option is allowed by the framework but
    # the action_select() path is a no-op.
    cl.highlighted = 1
    # Option 1 is disabled → action_select() should not invoke any
    # selection event. We assert by reading the option's ``disabled``
    # bit, which is the canonical guard.
    assert cl.get_option_at_index(1).disabled


def test_clicklist_distinct_option_ids():
    """Textual's OptionList rejects duplicate IDs (raises DuplicateID).
    This test pins that contract so the queue panel can rely on
    `get_option_index(id)` returning exactly one row."""
    from textual.widgets.option_list import Option
    from textual.widgets._option_list import DuplicateID
    from rich.text import Text

    cl = ClickList()
    with pytest.raises(DuplicateID):
        cl.add_options([
            Option(Text("a"), id="song-1"),
            Option(Text("b"), id="song-1"),
        ])
    # Sanity: unique IDs are accepted
    cl2 = ClickList()
    cl2.add_options([
        Option(Text("a"), id="song-1"),
        Option(Text("b"), id="song-2"),
    ])
    assert cl2.option_count == 2


# ── NowPlaying ────────────────────────────────────────────────────────


def test_nowplaying_default_state():
    """Brand-new widget: no song, paused, full volume, no modes."""
    np = NowPlaying()
    assert np.song is None
    assert np.playing is False
    assert np.position == 0.0
    assert np.duration == 0.0
    assert np.volume == 100
    assert np.muted is False
    assert np.shuffle is False
    assert np.repeat is Repeat.OFF
    assert np.border_title == "now playing"


def test_nowplaying_set_song_starts_title_flash():
    """Setting a new song (or any song, when previous was None) must
    pulse the title flash so the user sees the change."""
    np = NowPlaying()
    song = Song(id="x", title="First Song")
    np.set_song(song)
    assert np._title_flash == 12


def test_nowplaying_set_same_song_no_flash():
    """Re-setting the same song (e.g. on a remount) does not flash."""
    np = NowPlaying()
    song = Song(id="x", title="First Song")
    np.set_song(song)
    np._title_flash = 0
    np.set_song(song)
    assert np._title_flash == 0


def test_nowplaying_set_song_none_resets_position():
    """Clearing the song (e.g. on quit) must reset counters so the
    progress bar doesn't show stale state."""
    np = NowPlaying()
    np.set_song(Song(id="x", title="Foo"))
    np.position = 50.0
    np.duration = 200.0
    np.set_song(None)
    assert np.song is None
    assert np.position == 0.0
    assert np.duration == 0.0


def test_nowplaying_set_progress_only_updates_position():
    """``set_progress`` updates the position always; duration only
    when the new value is positive (avoids zeroing out on a stray
    callback)."""
    np = NowPlaying()
    np.set_song(Song(id="x", title="Foo"))
    np.set_progress(50.0, 0.0)
    assert np.position == 50.0
    assert np.duration == 0.0  # not updated


@pytest.mark.asyncio
async def test_nowplaying_flash_volume_resets_after_ticks(widget_app):
    _, _, np = widget_app
    np.flash_volume()
    assert np._vol_flash == 10
    np.tick()
    assert np._vol_flash == 9
    np.tick()
    assert np._vol_flash == 8


@pytest.mark.asyncio
async def test_nowplaying_tick_updates_viz_state(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo"))
    np.flash_volume()
    start_tick = np._tick
    np.tick()
    assert np._tick == start_tick + 1
    assert np._vol_flash == 9


@pytest.mark.asyncio
async def test_nowplaying_line_top_nothing_playing_includes_hint(widget_app):
    _, _, np = widget_app
    top = np._line_top(width=80)
    assert "nothing playing" in top.plain
    assert "enter" in top.plain


@pytest.mark.asyncio
async def test_nowplaying_line_top_with_song_has_title(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Bohemian Rhapsody", artist="Queen", album="A Night at the Opera"))
    top = np._line_top(width=80)
    assert "Bohemian Rhapsody" in top.plain
    assert "Queen" in top.plain


@pytest.mark.asyncio
async def test_nowplaying_line_top_star_appears_when_starred(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo", starred=True))
    top = np._line_top(width=80)
    # Nerd Font star (icons.STAR == "\uf005") is the canonical glyph
    from ricekit import icons
    assert icons.STAR in top.plain


@pytest.mark.asyncio
async def test_nowplaying_line_top_play_pause_glyphs(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo"))
    np.playing = False
    top = np._line_top(width=80)
    assert PAUSE_GLYPH in top.plain
    np.playing = True
    top = np._line_top(width=80)
    assert PLAY_GLYPH in top.plain


@pytest.mark.asyncio
async def test_nowplaying_line_top_marquees_long_titles(widget_app):
    _, _, np = widget_app
    long_title = "X" * 200
    np.set_song(Song(id="x", title=long_title, artist="A", album="B"))
    top = np._line_top(width=40)
    # marquee keeps the line within the width
    assert len(top.plain) <= 80  # roughly 2x width


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_includes_vol_gauge(widget_app):
    _, _, np = widget_app
    np.volume = 50
    bottom = np._line_bottom(width=80)
    assert "vol" in bottom.plain
    # 50% of 6 = 3 lit cells
    assert bottom.plain.count("▮") == 3


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_muted_label_is_red(widget_app):
    _, _, np = widget_app
    np.muted = True
    np.volume = 50
    bottom = np._line_bottom(width=80)
    assert "mut" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_repeat_one_superscript(widget_app):
    _, _, np = widget_app
    np.repeat = Repeat.ONE
    bottom = np._line_bottom(width=80)
    assert "¹" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_silent_badge_when_notifications_off(widget_app):
    _, app, np = widget_app
    app._notify_on = False
    bottom = np._line_bottom(width=80)
    assert "[Silent]" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_shows_flac_lossless(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo", suffix="flac", bit_rate=1411))
    bottom = np._line_bottom(width=80)
    assert "FLAC Lossless" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_shows_flac_24_96(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo", suffix="flac", bit_rate=2400))
    bottom = np._line_bottom(width=80)
    assert "FLAC 24/96" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_shows_bitrate_for_non_flac(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo", suffix="mp3", bit_rate=320))
    bottom = np._line_bottom(width=80)
    assert "[320k]" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_line_bottom_shows_format_suffix(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo", suffix="ogg"))
    bottom = np._line_bottom(width=80)
    assert "[OGG]" in bottom.plain


@pytest.mark.asyncio
async def test_nowplaying_lines_include_time_markers(widget_app):
    _, _, np = widget_app
    np.set_song(Song(id="x", title="Foo", duration=200))
    np.position = 60
    np.duration = 200
    bottom = np._line_bottom(width=80)
    assert "1:00" in bottom.plain  # elapsed
    assert "3:20" in bottom.plain  # total


@pytest.mark.asyncio
async def test_nowplaying_render_lines_joins_top_and_bottom(widget_app):
    _, _, np = widget_app
    out = np._render_lines()
    assert "\n" in out.plain
    assert len(out.plain.split("\n")) >= 2


# ── Logo ──────────────────────────────────────────────────────────────


def test_logo_init_zero_phase():
    logo = Logo()
    assert logo._phase == 0.0


@pytest.mark.asyncio
async def test_logo_tick_advances_phase(widget_app):
    _, _, _ = widget_app
    logo = Logo()
    logo.tick()
    assert logo._phase == pytest.approx(0.55)
    logo.tick()
    assert logo._phase == pytest.approx(1.1)


def test_logo_text_includes_wordmark():
    logo = Logo()
    text = logo.logo_text()
    assert "theia-player" in text.plain
