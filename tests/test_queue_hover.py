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


def test_format_song_tooltip_strips_newlines_from_metadata():
    """Newlines in title/artist/album/genre would otherwise add phantom
    lines to the tooltip and offset everything below — the tooltip
    is sized for exactly 7 sections. Today we sanitize them."""
    song = Song(
        id="x",
        title="Multi\nLine\nTitle",
        artist="Line1\nLine2",
        album="Album\nX",
        genre="Pop\nRock",
        year=2024,
    )
    text = _format_song_tooltip(song)
    plain = text.plain
    # Newlines must be collapsed to spaces
    assert "Multi Line Title" in plain
    assert "Line1 Line2" in plain
    assert "Album X" in plain
    assert "Pop Rock" in plain
    # No \nNewline jumps in the title (end-of-line is OK because the
    # tooltip itself uses \n to separate sections)
    assert "Line\nLine" not in plain  # would mean a phantom newline survived
    assert "Multi\nLine" not in plain
    assert "Album\nX" not in plain
    assert "Pop\nRock" not in plain


def test_format_song_tooltip_handles_tabs_and_multiple_whitespace():
    """Tabs and runs of whitespace should also collapse to single spaces."""
    song = Song(id="x", title="Foo\t\t  Bar   Baz")
    text = _format_song_tooltip(song)
    assert "Foo Bar Baz" in text.plain


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
    # The payload lives on the inner Static label (the Container carries the
    # border / padding, the label carries the rendered text).
    label_repr = str(queue._tooltip._label.render())
    assert "The Boy From Ipanema" in label_repr


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
    assert "Different Track" in str(queue._tooltip._label.render())


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


@pytest.mark.asyncio
async def test_song_tooltip_layout_does_not_crash_on_hover(hover_app):
    """Regression for the production crash: ``Static._content`` (or any
    `_content`-named attribute on the textual version installed) was being
    passed as the tooltip's payload, which made ``visualize`` raise
    ``VisualError: unable to display 'SongTooltip' type``.

    The fix was to stop subclassing ``Static`` for the tooltip. Instead
    the tooltip is a ``Container`` with a single ``Static`` child carrying
    the actual text. This test mounts the real layout pass twice (initial
    mount + a hover-triggered update) and asserts that neither raise.
    """
    pilot, _, queue = hover_app
    queue.set_songs([_full_song()])
    # Initial layout pass already happened during on_mount; surface it by
    # forcing the screen to refresh and then rendering the tooltip.
    await pilot.pause()
    queue._tooltip.render()  # would raise VisualError before the fix
    # Hover pass — this used to swap ``content`` for the widget itself
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    await pilot.pause()
    queue._tooltip.render()  # would raise VisualError on the second pass
    assert queue._tooltip.has_class("-visible")


def test_song_tooltip_does_not_shadow_static_content_attribute():
    """The production crash was caused by SongTooltip shadowing the
    parent ``Static`` class's ``_content`` attribute in textual versions
    where Static uses ``self._content`` (single underscore) instead of
    name-mangled ``__content``. We simulate that scenario here: a
    fake "Static-like" parent where ``self._content`` is the literal
    payload attribute. If SongTooltip's ``__init__`` writes
    ``self._content``, it would corrupt the parent's payload slot.

    The test asserts the invariant by checking that after init the
    tooltip has no attribute literally named ``_content`` (it stores
    the text on ``_label.update(...)`` instead). This catches the
    regression across textual versions.
    """
    from textual.containers import Container as _Container
    from textual.widgets import Static as _Static

    # Sanity: in the current textual version, Static uses __content.
    # The test still works if it switches to _content in the future:
    # we don't care about the parent, we care about the child class.
    tooltip = SongTooltip()
    # The literal attribute `_content` must NOT be set on the tooltip —
    # that's the invariant that crashed prod when the parent class
    # happened to use the same name.
    assert not hasattr(tooltip, "_content"), (
        "SongTooltip sets self._content, which shadows the parent "
        "Static's _content attribute in some textual versions and "
        "caused VisualError('unable to display SongTooltip type') "
        "in production. Store the rendered text on _label instead."
    )
    # And the type must be a Container (not a Static) so the parent
    # class's payload machinery is never reachable.
    assert isinstance(tooltip, _Container), (
        "SongTooltip must subclass Container, not Static, so the "
        "parent class's _content attribute is never read."
    )
    assert not isinstance(tooltip, _Static)


@pytest.mark.asyncio
async def test_song_tooltip_visualize_accepts_label_payload(hover_app):
    """End-to-end: the payload lives on the inner Static label, and
    ``visualize`` accepts it as a valid renderable type. We explicitly
    call ``visualize`` on the inner label's content — the same call
    path that crashed in production — to lock in the contract.
    """
    from textual.visual import VisualError, visualize

    pilot, _, queue = hover_app
    queue.set_songs([_full_song()])
    queue._mouse_hovering_over = 0
    queue._handle_hover(10, 10)
    await pilot.pause()

    label = queue._tooltip._label
    # The label is a Static; rendering it goes through the same
    # _content/visualize code path that the buggy SongTooltip used to
    # hit. Lift the visual out and round-trip it through visualize
    # to prove the payload survives the framework's validator.
    rendered = label.render()
    # rendered is a Visual; the safer check is on the Static's content
    # that produced it. Reach into the mangled/maybe-not-mangled slot.
    payload = getattr(label, "_Static__content", None) or getattr(label, "_content", None)
    assert payload is not None, "label has no resolvable content attribute"
    assert not isinstance(payload, SongTooltip), (
        "label content is the SongTooltip widget itself — the same "
        "corruption that crashed prod. The parent class resolved the "
        "renderable to the tooltip instance."
    )
    try:
        visualize(label, payload, markup=True)
    except VisualError as e:
        pytest.fail(f"visualize() rejected the label payload: {e}")
