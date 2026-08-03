"""Tests for the queue hover tooltip.

Covers three contracts:

1. ``_format_song_tooltip`` is a pure function that surfaces every
   relevant piece of metadata from a ``Song`` (title, artist, album,
   year, genre, duration, format, bitrate, track, disc, rating, plays,
   starred) in a multi-line ``Text`` — so even a song with only a title
   renders without exploding.

2. ``QueueList`` is a drop-in replacement for ``ClickList`` (same vim
   bindings, same single/double click behavior) plus the new hover
   contract: when ``_mouse_hovering_over`` points at a valid index, the
   tooltip becomes visible; when it leaves the widget or the index
   becomes out of range, the tooltip hides.

3. ``set_songs`` is the bridge between the app and the widget. It binds
   the live queue list so the index under the cursor resolves to a real
   ``Song``. A re-render that drops the currently-hovered index must
   hide the tooltip instead of leaving it showing the wrong song.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pytest_asyncio import fixture as pytest_asyncio_fixture

from theiaplayer.models import Song
from theiaplayer.widgets import (
    PLAY_GLYPH,
    QueueList,
    SongTooltip,
    _format_song_tooltip,
)


# ── pure formatter ───────────────────────────────────────────────────────


def _full_song() -> Song:
    return Song(
        id="s1",
        title="The Boy From Ipanema",
        artist="Astrud Gilberto",
        album="Getz/Gilberto #2",
        year=1964,
        genre="Bossa Nova",
        duration=192,
        suffix="flac",
        bit_rate=1411,
        track=5,
        disc=1,
        rating=4,
        play_count=12,
        starred=True,
    )


def test_format_song_tooltip_surfaces_every_field():
    text = _format_song_tooltip(_full_song())
    plain = text.plain
    for needle in [
        "The Boy From Ipanema",
        "Astrud Gilberto",
        "Getz/Gilberto #2",
        "1964",
        "Bossa Nova",
        "3:12",  # 192s formatted
        "FLAC",
        "1411",
        "Track 5",
        "Disc 1",
        "★★★★☆",
        "12 plays",
        "starred",
    ]:
        assert needle in plain, f"missing {needle!r} in tooltip:\n{plain}"


def test_format_song_tooltip_minimal_song_does_not_explode():
    """A Song with only the required fields must still render cleanly."""
    text = _format_song_tooltip(Song(id="x", title="Solo"))
    assert "Solo" in text.plain
    # No empty/decorative fragments should leak
    after = text.plain.split("Solo", 1)[1]
    assert "  ·  " not in after


def test_format_song_tooltip_playing_badge():
    """``playing=True`` prepends the play glyph to the title line."""
    text = _format_song_tooltip(_full_song(), playing=True)
    assert text.plain.startswith(PLAY_GLYPH + " ")
    text_idle = _format_song_tooltip(_full_song(), playing=False)
    assert not text_idle.plain.startswith(PLAY_GLYPH + " ")


def test_format_song_tooltip_omits_blank_sections():
    """Sections with no source data must not produce dangling separators."""
    text = _format_song_tooltip(Song(id="x", title="Only Title", artist="A"))
    plain = text.plain
    assert "Track" not in plain
    assert "Disc" not in plain
    assert "plays" not in plain
    assert "starred" not in plain
    assert "  ·  " not in plain


# ── QueueList hover wiring (Textual app context) ─────────────────────────


class _HoverHostApp:
    """Lightweight harness: a real App that mounts one QueueList and
    exposes the widget + the auto-mounted SongTooltip.

    We avoid importing TheIAPlayerApp here because that would pull in
    the Subsonic client, MPV, and the entire app stack — way too much
    surface area for a tooltip unit test. KitApp is required though:
    NavList's DEFAULT_CSS references ``$kit-cursor`` / ``$kit-border``
    which only KitApp registers.
    """

    @staticmethod
    def make():
        from ricekit.app import KitApp
        from textual.containers import Vertical

        class _HostApp(KitApp):
            def compose(self):
                with Vertical():
                    yield QueueList(id="q")

        return _HostApp


@pytest_asyncio_fixture
async def hover_app():
    from textual.app import App

    host_cls = _HoverHostApp.make()
    app = host_cls()
    async with app.run_test() as pilot:
        queue: QueueList = app.query_one("#q", QueueList)
        # on_mount has fired, so _tooltip is live
        assert queue._tooltip is not None
        yield pilot, app, queue


@pytest.mark.asyncio
async def test_queue_list_mounts_song_tooltip_on_screen(hover_app):
    _, _, queue = hover_app
    # The SongTooltip is mounted on the screen (not inside the queue),
    # so it lives alongside the host in the same Screen.
    tooltip = queue._tooltip
    assert tooltip is not None
    assert isinstance(tooltip, SongTooltip)
    # Not visible until something is hovered
    assert not tooltip.has_class("-visible")


@pytest.mark.asyncio
async def test_queue_list_shows_tooltip_when_hover_index_in_range(hover_app):
    _, _, queue = hover_app
    queue.set_songs([_full_song(), Song(id="s2", title="Second")])
    # Simulate the OptionList state where the mouse is on row 0
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    assert queue._tooltip.has_class("-visible")
    text_repr = str(queue._tooltip.render())
    assert "The Boy From Ipanema" in text_repr


@pytest.mark.asyncio
async def test_queue_list_hides_tooltip_when_index_out_of_range(hover_app):
    _, _, queue = hover_app
    queue.set_songs([_full_song()])
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    assert queue._tooltip.has_class("-visible")

    # Now the queue shrinks: index 0 is gone
    queue.set_songs([])
    assert not queue._tooltip.has_class("-visible")
    assert queue._last_hover_idx is None


@pytest.mark.asyncio
async def test_queue_list_set_songs_preserves_hover_when_in_range(hover_app):
    """A re-render that keeps the same length must not hide the tooltip —
    the cursor is still on the same row, even if the song at that row
    changed (shuffle, reorder)."""
    _, _, queue = hover_app
    queue.set_songs([_full_song()])
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    assert queue._tooltip.has_class("-visible")

    replacement = Song(id="s2", title="Different Track", artist="Other")
    queue.set_songs([replacement])
    assert queue._tooltip.has_class("-visible")
    assert "Different Track" in str(queue._tooltip.render())


@pytest.mark.asyncio
async def test_queue_list_handle_hover_hides_on_invalid_index(hover_app):
    """If the queue is cleared while the cursor is on a row, the next
    mouse move (with no valid index) must hide the tooltip."""
    _, _, queue = hover_app
    queue.set_songs([_full_song()])
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    assert queue._tooltip.has_class("-visible")

    # Simulate OptionList clearing the hover state on clear_options
    queue._mouse_hovering_over = None
    queue._handle_hover(11, 11)
    assert not queue._tooltip.has_class("-visible")


@pytest.mark.asyncio
async def test_queue_list_on_leave_hides_tooltip(hover_app):
    from textual.events import Leave

    _, _, queue = hover_app
    queue.set_songs([_full_song()])
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    assert queue._tooltip.has_class("-visible")

    # Dispatch a synthetic leave event
    queue.post_message(Leave(queue))
    await hover_app[0].pause()
    assert not queue._tooltip.has_class("-visible")
    assert queue._last_hover_idx is None


def test_queue_list_preserves_clicklist_bindings():
    """QueueList must keep j/k/g/G vim navigation from ClickList."""
    keys = set()
    for b in QueueList.BINDINGS:
        for k in b.key.split(","):
            keys.add(k.strip())
    assert {"j", "k", "g", "G"}.issubset(keys), (
        f"QueueList lost vim navigation bindings: {keys}"
    )
