"""NaviTui's animated widgets.

One shared 8fps heartbeat in the app calls `.tick()` on each of these; every
widget only repaints its own few cells, so the constant motion costs almost
nothing. Colors are read from `ricekit.palette` at render time so a theme
switch restyles every animation live.
"""

from __future__ import annotations

import math

from rich.text import Text
from textual.containers import Container
from textual.geometry import Offset
from textual.widgets import Static

from ricekit import icons, palette
from ricekit.widgets import NavList

from theiaplayer import anim
from theiaplayer.models import Song
from theiaplayer.playqueue import Repeat

SHUFFLE_ICON = "\uf074"  # nf-fa-random
REPEAT_ICON = "\uf01e"  # nf-fa-repeat
PLAY_GLYPH = "\uf04b"  # nf-fa-play
PAUSE_GLYPH = "\uf04c"  # nf-fa-pause

class ClickList(NavList):
    """Single click highlights (previews), double click selects (acts).
    Keyboard enter still selects instantly — only the mouse path changes."""

    async def _on_click(self, event) -> None:
        clicked = event.style.meta.get("option")
        if clicked is not None and not self._options[clicked].disabled:
            event.stop()
            event.prevent_default()
            self.highlighted = clicked
            if getattr(event, "chain", 1) >= 2:
                self.action_select()


class SongTooltip(Container):
    """Floating overlay that surfaces the full song metadata on hover.

    Mounted once by ``QueueList`` on the screen; shown/hidden by mouse
    events. Lives on its own layer so it floats above every panel and is
    not clipped by the queue's narrow column.

    Implemented as a ``Container`` with a single ``Static`` child (the
    ``_label``) rather than subclassing ``Static`` directly, so the
    per-version ``_content`` attribute on the parent class never shadows
    the rendered payload. Updating the Static child via ``update()``
    triggers a layout pass that resizes the floating tooltip correctly.
    """

    DEFAULT_CSS = """
    SongTooltip {
        layer: _theia_tooltips;
        background: $panel;
        border: round $kit-border;
        padding: 0 2;
        width: auto;
        height: auto;
        max-width: 60;
        display: none;
    }
    SongTooltip.-visible { display: block; }
    SongTooltip > Static {
        width: auto;
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "track info"
        self._label: Static | None = None

    def compose(self):
        yield Static("")

    def on_mount(self) -> None:
        self._label = self.query_one(Static)

    def show_song(self, song: "Song", *, playing: bool = False) -> None:
        """Render and display the tooltip for ``song``.

        The Static's size is recomputed from the new content so subsequent
        ``position_near`` calls clamp against the real bounding box.
        """
        if self._label is None:
            return
        self._label.update(_format_song_tooltip(song, playing=playing))
        self.add_class("-visible")

    def hide(self) -> None:
        self.remove_class("-visible")

    def position_near(self, mouse_x: int, mouse_y: int) -> None:
        """Pin the tooltip to the cursor, clamped inside the screen."""
        if not self.has_class("-visible"):
            return
        try:
            screen_w, screen_h = self.screen.size.width, self.screen.size.height
        except Exception:
            return
        tip_w = self.outer_size.width or 40
        tip_h = self.outer_size.height or 6
        x = mouse_x + 2
        y = mouse_y + 1
        if x + tip_w > screen_w:
            x = mouse_x - tip_w - 2
        if y + tip_h > screen_h:
            y = mouse_y - tip_h - 1
        self.absolute_offset = Offset(max(0, x), max(0, y))


def _format_song_tooltip(song: "Song", *, playing: bool = False) -> Text:
    """Build the multi-line Rich Text shown inside ``SongTooltip``.

    Pure function so unit tests can verify content without spinning up a
    Textual app. Sections are joined with blank lines so the tooltip reads
    cleanly even at 60 cols wide.
    """
    text = Text()

    # 1) Title + state badge
    title = Text()
    if playing:
        title.append(PLAY_GLYPH + " ", style=palette.green)
    title.append(song.title or "—", style=f"bold {palette.text}")
    text.append_text(title)

    # 2) Artist (prominent, dim)
    if song.artist:
        text.append("\n")
        text.append(song.artist, style=palette.dim)

    # 3) Album · year
    if song.album or song.year:
        text.append("\n")
        album_line = Text()
        if song.album:
            album_line.append(song.album, style=palette.sub)
        if song.year:
            album_line.append("  ·  ", style=palette.vfaint)
            album_line.append(str(song.year), style=palette.vfaint)
        text.append_text(album_line)

    # 4) Genre
    if song.genre:
        text.append("\n")
        text.append(song.genre, style=palette.dim)

    # 5) Duration · format · bitrate
    tech_bits: list[str] = []
    if song.duration:
        tech_bits.append(anim.fmt_time(song.duration))
    if song.suffix:
        tech_bits.append(song.suffix.upper())
    if song.bit_rate:
        tech_bits.append(f"{song.bit_rate} kbps")
    if tech_bits:
        text.append("\n")
        tech = Text()
        tech.append(tech_bits[0], style=f"bold {palette.peach}")
        for piece in tech_bits[1:]:
            tech.append("  ·  ", style=palette.vfaint)
            tech.append(piece, style=palette.dim)
        text.append_text(tech)

    # 6) Track · disc
    track_bits: list[str] = []
    if song.track:
        track_bits.append(f"Track {song.track}")
    if song.disc:
        track_bits.append(f"Disc {song.disc}")
    if track_bits:
        text.append("\n")
        text.append("  ·  ".join(track_bits), style=palette.vfaint)

    # 7) Rating · play count · starred
    tail_bits: list[tuple[str, str]] = []
    if song.rating:
        stars = "★" * song.rating + "☆" * (5 - song.rating)
        tail_bits.append((stars, palette.yellow))
    if song.play_count:
        tail_bits.append((f"{song.play_count} plays", palette.dim))
    if song.starred:
        tail_bits.append((f"{icons.STAR} starred", palette.yellow))
    if tail_bits:
        text.append("\n")
        tail = Text()
        for i, (piece, style) in enumerate(tail_bits):
            if i:
                tail.append("  ·  ", style=palette.vfaint)
            tail.append(piece, style=style)
        text.append_text(tail)

    return text


class QueueList(ClickList):
    """The queue column — a ``ClickList`` that shows a hover tooltip.

    The right-hand column is narrow on purpose, so titles and artist
    names get ellipsized. This widget keeps the existing single/double
    click behavior and adds: when the mouse rests on a row, a floating
    ``SongTooltip`` with the full metadata (title, artist, album, year,
    genre, duration, format, bitrate, track, disc, rating, plays, starred)
    appears next to the cursor and updates live as it moves between rows.
    """

    BINDINGS = ClickList.BINDINGS  # preserve j/k/g/G navigation

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._songs: list[Song] = []
        self._tooltip: SongTooltip | None = None
        self._last_hover_idx: int | None = None

    # ── song list management (called by the app on every queue render) ──

    def set_songs(self, songs: list[Song], *, current_index: int = -1) -> None:
        """Bind the queue's songs so ``_mouse_hovering_over`` resolves to
        a real ``Song`` when computing the tooltip."""
        self._songs = list(songs)
        self._current_index = current_index
        if self._last_hover_idx is None or self._last_hover_idx >= len(self._songs):
            # The hovered row no longer exists (queue cleared, row removed)
            self._last_hover_idx = None
            if self._tooltip is not None:
                self._tooltip.hide()
            return
        # Song at the same index may have changed (re-render with new order)
        self._show_for_idx(self._last_hover_idx)

    # ── lifecycle ───────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # Mount the overlay tooltip on the screen so it floats above the
        # queue and is not clipped by the panel's narrow column.
        self._tooltip = SongTooltip()
        self.screen.mount(self._tooltip)

    def on_unmount(self) -> None:
        if self._tooltip is not None:
            try:
                self._tooltip.remove()
            except Exception:
                pass
            self._tooltip = None

    # ── mouse routing ───────────────────────────────────────────────────

    def _on_mouse_move(self, event) -> None:
        super()._on_mouse_move(event)
        self._handle_hover(event.screen_x, event.screen_y)

    def _on_leave(self, _) -> None:
        super()._on_leave(_)
        self._last_hover_idx = None
        if self._tooltip is not None:
            self._tooltip.hide()

    # ── tooltip plumbing ────────────────────────────────────────────────

    def _handle_hover(self, screen_x: int, screen_y: int) -> None:
        idx = getattr(self, "_mouse_hovering_over", None)
        if idx is None or idx < 0 or idx >= len(self._songs):
            self._last_hover_idx = None
            if self._tooltip is not None:
                self._tooltip.hide()
            return
        if idx == self._last_hover_idx and self._tooltip is not None and self._tooltip.has_class("-visible"):
            # Same row, but the cursor moved inside it — keep it pinned to the cursor.
            self._tooltip.position_near(screen_x, screen_y)
            return
        self._last_hover_idx = idx
        self._show_for_idx(idx, screen_x, screen_y)

    def _show_for_idx(self, idx: int, screen_x: int | None = None, screen_y: int | None = None) -> None:
        if self._tooltip is None or idx < 0 or idx >= len(self._songs):
            return
        playing = idx == getattr(self, "_current_index", -1)
        self._tooltip.show_song(self._songs[idx], playing=playing)
        if screen_x is not None and screen_y is not None:
            # The size just changed with the new content; wait a tick so
            # ``outer_size`` reflects the rendered tooltip before clamping.
            self.call_after_refresh(
                lambda x=screen_x, y=screen_y: self._tooltip.position_near(x, y)
            )


class Logo(Static):
    """The NaviTui wordmark with a constant shimmer sweeping across it."""

    DEFAULT_CSS = """
    Logo { width: auto; height: 1; padding: 0 1; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._phase = 0.0

    def tick(self) -> None:
        self._phase += 0.55
        self.update(self.logo_text())

    def logo_text(self) -> Text:
        t = Text()
        t.append(anim.note(int(self._phase)) + " ", style=palette.mauve)
        t.append_text(anim.shimmer("theia-player", self._phase, palette.mauve, palette.text))
        return t

class Visualizer(Static):
    """Standalone EQ bars (used in the onboarding screen for flair)."""

    DEFAULT_CSS = """
    Visualizer { width: auto; height: 1; }
    """

    def __init__(self, bars: int = 5, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = anim.VizModel(bars)

    def tick(self) -> None:
        self.model.tick()
        self.update(self.model.render())

class NowPlaying(Static):
    """The two-line transport: viz + title marquee + star on top, smooth
    progress bar with times, volume gauge and mode toggles below.

    Click the bar to seek, click the gauge to set volume, click the
    shuffle/repeat glyphs to toggle them (they route through app actions).
    """

    DEFAULT_CSS = """
    NowPlaying {
        height: 4;
        border: round $kit-border;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.song: Song | None = None
        self.playing = False
        self.position = 0.0
        self.duration = 0.0
        self.volume = 100
        self.muted = False
        self.shuffle = False
        self.repeat = Repeat.OFF
        self.viz = anim.VizModel(5, seed=7)
        self._tick = 0
        self._title_flash = 0  # ticks of brightness after a track change
        self._vol_flash = 0
        self._bar_span: tuple[int, int] = (0, 0)  # x range of the seek bar
        self._gauge_span: tuple[int, int] = (0, 0)
        self._mode_spans: dict[str, tuple[int, int]] = {}
        self.border_title = "now playing"

    # ── state from the app ────────────────────────────────────────────
    def set_song(self, song: Song | None) -> None:
        if song is not None and (self.song is None or song.id != self.song.id):
            self._title_flash = 12
        self.song = song
        if song is None:
            self.position = 0.0
            self.duration = 0.0

    def set_progress(self, position: float, duration: float) -> None:
        self.position = position
        if duration > 0:
            self.duration = duration

    def set_playing(self, playing: bool) -> None:
        self.playing = playing

    def flash_volume(self) -> None:
        self._vol_flash = 10

    def tick(self) -> None:
        self._tick += 1
        self.viz.energy = 1.0 if self.playing else 0.0
        self.viz.tick()
        if self._title_flash > 0:
            self._title_flash -= 1
        if self._vol_flash > 0:
            self._vol_flash -= 1
        self.update(self._render_lines())

    # ── drawing ───────────────────────────────────────────────────────
    def _render_lines(self) -> Text:
        width = max(20, self.content_size.width)
        return Text("\n").join([self._line_top(width), self._line_bottom(width)])

    def _line_top(self, width: int) -> Text:
        line = Text()
        line.append_text(self.viz.render())
        line.append("  ")
        if self.song is None:
            line.append("nothing playing", style=palette.dim)
            line.append("  ·  press ", style=palette.vfaint)
            line.append("enter", style=palette.dim)
            line.append(" on a track", style=palette.vfaint)
            return line
        star = f" {icons.STAR}" if self.song.starred else ""
        state = PLAY_GLYPH if self.playing else PAUSE_GLYPH
        line.append(f"{state} ", style=palette.green if self.playing else palette.peach)
        # brighten the title briefly on track change, then settle
        flash = self._title_flash / 12
        title_color = anim.blend(palette.text, "#ffffff", 0.7 * flash)
        room = width - line.cell_len - len(star) - 1
        body = f"{self.song.title}  —  {self.song.artist} · {self.song.album}"
        line.append(anim.marquee(body, max(8, room), self._tick // 2), style=f"bold {title_color}")
        if star:
            line.append(star, style=palette.yellow)
        return line

    def _line_bottom(self, width: int) -> Text:
        elapsed = anim.fmt_time(self.position)
        total = anim.fmt_time(self.duration or (self.song.duration if self.song else 0))

        # Aprovechar el espacio muerto de la sangría bajo las barras de intensidad para colocar
        # el tiempo transcurrido actual en un bloque de ancho exacto de 7 caracteres.
        left_time = f"{elapsed:>5s}  "
        right_time = f"  {total} "

        # right side: volume + modes
        right = Text("  ")
        gauge_start = None
        vol_frac = 0.0 if self.muted else self.volume / 100
        right.append("vol ", style=palette.vfaint)
        gauge_start = right.cell_len
        gauge = anim.mini_gauge(vol_frac, 6)
        if self._vol_flash > 0 and anim.can_blend():
            gauge.stylize(anim.blend(palette.lav, "#ffffff", self._vol_flash / 14))
        right.append_text(gauge)
        gauge_end = right.cell_len
        vol_label = "mut" if self.muted else f"{self.volume:>3d}"
        right.append(f" {vol_label}", style=palette.red if self.muted else palette.dim)
        right.append("  ")
        shuf_start = right.cell_len
        right.append(
            f"{SHUFFLE_ICON} ",
            style=palette.peach if self.shuffle else palette.vfaint,
        )
        shuf_end = right.cell_len
        rep_start = right.cell_len
        rep_style = palette.peach if self.repeat is not Repeat.OFF else palette.vfaint
        right.append(REPEAT_ICON, style=rep_style)
        if self.repeat is Repeat.ONE:
            right.append("¹", style=palette.peach)
        rep_end = right.cell_len

        # Conditionally show the [Silent] indicator if notifications are muted
        if not getattr(self.app, "_notify_on", True):
            right.append("  [Silent]", style="bold " + palette.peach)

        if self.song is not None:
            s = self.song
            suffix = (s.suffix or "").lower()
            br = s.bit_rate or 0
            if suffix == "flac" or br >= 1000:
                if br >= 2000:
                    right.append("  [FLAC 24/96]", style=f"bold {palette.green}")
                else:
                    right.append("  [FLAC Lossless]", style=f"bold {palette.green}")
            elif br > 0:
                right.append(f"  [{br}k]", style=palette.dim)
            elif suffix:
                right.append(f"  [{suffix.upper()}]", style=palette.dim)

        bar_width = max(4, width - len(left_time) - len(right_time) - right.cell_len)
        frac = self.position / self.duration if self.duration > 0 else 0.0
        pulse = (math.sin(self._tick * 0.55) + 1) / 2 if self.playing else 0.0
        line = Text()
        line.append(left_time, style=palette.dim)
        line.append_text(anim.smooth_bar(frac, bar_width, head_pulse=pulse))
        line.append(right_time, style=palette.dim)
        base = line.cell_len
        line.append_text(right)

        # remember hit-boxes for the mouse (content coordinates, line y=1)
        self._bar_span = (len(left_time), len(left_time) + bar_width)
        self._gauge_span = (base + gauge_start, base + gauge_end)
        self._mode_spans = {
            "shuffle": (base + shuf_start, base + shuf_end),
            "repeat": (base + rep_start, base + rep_end),
        }
        return line

    # ── mouse ─────────────────────────────────────────────────────────
    def on_click(self, event) -> None:
        content = event.get_content_offset(self)
        if content is None:
            return
        x, y = content
        if y != 1:
            return
        b0, b1 = self._bar_span
        if b0 <= x < b1 and b1 > b0:
            self.app.seek_fraction((x - b0 + 0.5) / (b1 - b0))
            return
        g0, g1 = self._gauge_span
        if g0 <= x < g1:
            self.app.set_volume_fraction((x - g0 + 0.5) / (g1 - g0))
            return
        for name, (m0, m1) in self._mode_spans.items():
            if m0 <= x < m1:
                if name == "shuffle":
                    self.app.action_toggle_shuffle()
                else:
                    self.app.action_cycle_repeat()
                return
