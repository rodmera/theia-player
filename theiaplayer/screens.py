"""Screens and modals: first-run onboarding and global search.

Onboarding follows the kit doctrine — never dump a new user into an empty
screen with an error toast. Credentials are validated live against the
server and only stored (chmod 600) once a ping succeeds.
"""

from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ricekit import icons, palette
from ricekit.widgets import NavList, pop_in

from theiaplayer import anim
from theiaplayer.api import SubsonicError, make_token, normalize_server
from theiaplayer.models import SearchResults
from theiaplayer.widgets import Logo, Visualizer


def settle_pop_in(screen, box_selector: str) -> None:
    """textual 8 sharp edge: `Widget.visual_style` caches the blended text
    background while an ancestor's opacity is still animating (the cache key
    ignores ancestor opacity), so text inside a pop_in'd box keeps a smudged
    background forever. Bust the cache once the fade has finished."""

    def bust() -> None:
        for widget in screen.query(f"{box_selector}, {box_selector} *"):
            widget._visual_style = None
            widget.refresh()

    screen.set_timer(0.25, bust)


class OnboardingScreen(Screen):
    """Server + credentials, validated live. Dismisses with the config dict."""

    BINDINGS = [Binding("escape", "quit_app", "quit", show=True)]

    DEFAULT_CSS = """
    OnboardingScreen { align: center middle; }
    OnboardingScreen #onboard-box {
        width: 58; height: auto;
        border: round $kit-border-focus;
        background: $kit-modal-bg;
        padding: 1 3;
    }
    OnboardingScreen #onboard-head { height: 1; margin-bottom: 1; }
    OnboardingScreen Visualizer { margin: 0 2 0 0; }
    OnboardingScreen Input {
        background: transparent;
        border: round $kit-border;
        margin-bottom: 0;
    }
    OnboardingScreen Input:focus { border: round $kit-border-focus; }
    OnboardingScreen #onboard-status { height: 2; padding: 0 1; }
    """

    def __init__(self, server: str = "", username: str = "") -> None:
        super().__init__()
        self._server = server
        self._username = username

    def compose(self) -> ComposeResult:
        with Vertical(id="onboard-box"):
            with Horizontal(id="onboard-head"):
                yield Visualizer(bars=4)
                yield Logo()
                yield Static(
                    Text("connect to your navidrome", style=palette.dim),
                )
            yield Input(
                value=self._server,
                placeholder="server · https://music.example.com",
                id="in-server",
            )
            yield Input(value=self._username, placeholder="username", id="in-user")
            yield Input(placeholder="password", password=True, id="in-pass")
            yield Static(self._hint(), id="onboard-status")

    def _hint(self) -> Text:
        t = Text()
        t.append("enter", style=palette.blue)
        t.append(" connect  ·  ", style=palette.vfaint)
        t.append("tab", style=palette.blue)
        t.append(" next field  ·  stored locally, chmod 600", style=palette.vfaint)
        return t

    def on_mount(self) -> None:
        pop_in(self.query_one("#onboard-box"))
        settle_pop_in(self, "#onboard-box")
        target = "#in-server" if not self._server else "#in-user"
        self.query_one(target, Input).focus()
        self.set_interval(1 / 8, self._tick)
        viz = self.query_one(Visualizer)
        viz.model.energy = 0.6

    def _tick(self) -> None:
        self.query_one(Logo).tick()
        self.query_one(Visualizer).tick()

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        order = ["in-server", "in-user", "in-pass"]
        values = {i: self.query_one(f"#{i}", Input).value.strip() for i in order}
        for field in order:
            if not values[field]:
                self.query_one(f"#{field}", Input).focus()
                return
        self._connect(values["in-server"], values["in-user"], values["in-pass"])

    def _status(self, text: Text) -> None:
        status = self.query_one("#onboard-status", Static)
        status.update(text)
        pop_in(status)

    @work(exclusive=True, group="onboard")
    async def _connect(self, server: str, username: str, password: str) -> None:
        import httpx

        from theiaplayer.api import SubsonicClient

        server = normalize_server(server)
        token, salt = make_token(password)
        spin = Text()
        spin.append(f"{anim.spinner(0)} ", style=palette.blue)
        spin.append(f"pinging {server} …", style=palette.sub)
        self._status(spin)
        client = SubsonicClient(server, username, token, salt, art_dir=self.app.dirs.cache_dir / "art")
        try:
            body = await client.ping()
        except SubsonicError as e:
            fail = Text()
            fail.append(f"{icons.CROSS_CIRCLE} ", style=palette.red)
            fail.append(str(e), style=palette.red)
            self._status(fail)
            self.query_one("#in-pass", Input).focus()
            return
        except (httpx.HTTPError, OSError) as e:
            fail = Text()
            fail.append(f"{icons.CROSS_CIRCLE} ", style=palette.red)
            fail.append(f"can't reach server: {e}", style=palette.red)
            self._status(fail)
            return
        finally:
            await client.close()

        okay = Text()
        okay.append(f"{icons.CHECK_CIRCLE} ", style=palette.green)
        server_kind = body.get("type", "subsonic")
        okay.append(f"connected — {server_kind} {body.get('serverVersion', '')}", style=palette.green)
        self._status(okay)
        self.dismiss({"server": server, "username": username, "token": token, "salt": salt})

    def action_quit_app(self) -> None:
        self.app.exit()


class InputModal(ModalScreen):
    """One-line text prompt (e.g. a new playlist name). Dismisses with the
    entered string, or None on escape."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    DEFAULT_CSS = """
    InputModal { align: center middle; background: $kit-overlay; }
    InputModal #input-box {
        width: 52; height: auto;
        background: $kit-modal-bg; border: round $kit-border-focus; padding: 1 2;
    }
    InputModal Static { background: $kit-modal-bg; }
    InputModal Input { background: transparent; border: round $kit-border; }
    InputModal Input:focus { border: round $kit-border-focus; }
    """

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Static(Text(self._title, style=f"bold {palette.sub}"))
            yield Input(placeholder=self._placeholder, id="input-value")

    def on_mount(self) -> None:
        pop_in(self.query_one("#input-box"))
        settle_pop_in(self, "#input-box")
        self.query_one("#input-value", Input).focus()

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LyricsModal(ModalScreen):
    """Scrollable lyrics overlay. Dismiss with Escape or q."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("q", "cancel", show=False),
        Binding("j,down", "scroll_down", show=False),
        Binding("k,up", "scroll_up", show=False),
        Binding("space", "app_play_pause", show=False),
        Binding("n", "app_next_track", show=False),
        Binding("b", "app_prev_track", show=False),
        Binding("left", "app_seek_back", show=False),
        Binding("right", "app_seek_fwd", show=False),
        Binding("shift+left", "app_seek_back_big", show=False),
        Binding("shift+right", "app_seek_fwd_big", show=False),
    ]

    DEFAULT_CSS = """
    LyricsModal { align: center middle; background: $kit-overlay; }
    LyricsModal #lyrics-box {
        width: 72; height: 80%; max-height: 40;
        background: $kit-modal-bg; border: round $kit-border-focus; padding: 1 2;
    }
    LyricsModal #lyrics-title { margin-bottom: 1; }
    LyricsModal VerticalScroll { height: 1fr; }
    LyricsModal VerticalScroll Static { background: $kit-modal-bg; }
    LyricsModal .lyrics-line {
        height: auto;
        content-align: center middle;
        text-align: center;
        padding: 0 1;
        color: $text-disabled;
        transition: color 150ms;
    }
    LyricsModal .lyrics-line.active {
        color: #00ffcc;
        text-style: bold;
    }
    """

    def __init__(self, song_title: str, artist: str, lines: list[dict]) -> None:
        super().__init__()
        self._song_title = song_title
        self._artist = artist
        self._lines = lines
        self._is_synced = any(l.get("start") is not None for l in self._lines)
        self._line_widgets: list[Static] = []
        self._current_active_idx = -1

    def compose(self) -> ComposeResult:
        with Vertical(id="lyrics-box"):
            header = Text(no_wrap=True, overflow="ellipsis")
            header.append(self._song_title, style=f"bold {palette.sub}")
            header.append(f"  {self._artist}", style=palette.dim)
            yield Static(header, id="lyrics-title")
            with VerticalScroll(id="lyrics-scroll"):
                self._line_widgets = []
                for line in self._lines:
                    text = line.get("value", "")
                    widget = Static(text or " ", classes="lyrics-line")
                    self._line_widgets.append(widget)
                    yield widget

    def on_mount(self) -> None:
        pop_in(self.query_one("#lyrics-box"))
        settle_pop_in(self, "#lyrics-box")

    def update_time(self, time_sec: float) -> None:
        """Update synchronized lyrics scroll position based on player time (seconds)."""
        if not self._is_synced or not self._line_widgets:
            return
        
        time_ms = time_sec * 1000
        active_idx = -1
        for i, line in enumerate(self._lines):
            start = line.get("start")
            if start is not None and start <= time_ms:
                active_idx = i
            else:
                break
        
        if active_idx != self._current_active_idx and active_idx >= 0:
            # Desmarcar anterior
            if self._current_active_idx >= 0 and self._current_active_idx < len(self._line_widgets):
                self._line_widgets[self._current_active_idx].remove_class("active")
            
            # Destacar nuevo
            self._line_widgets[active_idx].add_class("active")
            self._current_active_idx = active_idx
            
            # Scroll suave para centrar
            try:
                scroll = self.query_one("#lyrics-scroll", VerticalScroll)
                scroll.scroll_to_widget(self._line_widgets[active_idx], animate=True)
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        self.query_one("#lyrics-scroll", VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one("#lyrics-scroll", VerticalScroll).scroll_up()

    def action_app_play_pause(self) -> None:
        self.app.action_play_pause()

    def action_app_next_track(self) -> None:
        self.app.action_next_track()

    def action_app_prev_track(self) -> None:
        self.app.action_prev_track()

    def action_app_seek_back(self) -> None:
        self.app.action_seek(-5)

    def action_app_seek_fwd(self) -> None:
        self.app.action_seek(5)

    def action_app_seek_back_big(self) -> None:
        self.app.action_seek(-30)

    def action_app_seek_fwd_big(self) -> None:
        self.app.action_seek(30)


class SearchModal(ModalScreen):
    """Global search over artists, albums and songs — debounced, grouped.

    Dismisses with ("song", songs, index) | ("song-queue", song, play_next)
    | ("album", album) | ("artist", artist) | None.
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down", "to_list", show=False),
        Binding("a", "queue_song(False)", show=False),
        Binding("A", "queue_song(True)", show=False),
    ]

    DEFAULT_CSS = """
    SearchModal { align: center middle; background: $kit-overlay; }
    SearchModal #search-box {
        width: 72; height: auto; max-height: 80%;
        background: $kit-modal-bg; border: round $kit-border-focus; padding: 1 1;
    }
    SearchModal Input { background: transparent; border: round $kit-border; }
    SearchModal Input:focus { border: round $kit-border-focus; }
    SearchModal #search-results {
        height: auto; max-height: 24;
        text-wrap: nowrap; text-overflow: ellipsis;
    }
    SearchModal #search-hint { padding: 1 1 0 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._results = SearchResults()

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Input(placeholder="search the library", id="search-input")
            yield NavList(id="search-results")
            yield Static(self._hint(), id="search-hint")

    def _hint(self) -> Text:
        t = Text()
        for key, desc in (("enter", "play"), ("a", "queue"), ("A", "play next"), ("esc", "close")):
            if key != "enter":
                t.append("  ·  ", style=palette.vfaint)
            t.append(key, style=palette.blue)
            t.append(f" {desc}", style=palette.dim)
        return t

    def _highlighted_song(self):
        """The Song under the results cursor, or None."""
        ol = self.query_one("#search-results", NavList)
        if ol.highlighted is None:
            return None
        option = ol.get_option_at_index(ol.highlighted)
        if option.id and option.id.startswith("song:"):
            return self._results.songs[int(option.id.split(":", 1)[1])]
        return None

    def action_queue_song(self, play_next: bool) -> None:
        song = self._highlighted_song()
        if song is not None:
            self.dismiss(("song-queue", song, play_next))

    def on_mount(self) -> None:
        pop_in(self.query_one("#search-box"))
        settle_pop_in(self, "#search-box")
        self.query_one("#search-input", Input).focus()

    @on(Input.Changed, "#search-input")
    def _changed(self, event: Input.Changed) -> None:
        query = event.value.strip()
        if len(query) >= 2:
            self._search(query)
        else:
            self.query_one("#search-results", NavList).clear_options()

    @work(exclusive=True, group="search")
    async def _search(self, query: str) -> None:
        try:
            self._results = await self.app.client.search(query)
        except Exception:
            return
        self._render_results()

    def _render_results(self) -> None:
        ol = self.query_one("#search-results", NavList)
        ol.clear_options()
        res = self._results
        opts: list[Option] = []

        def header(label: str) -> None:
            opts.append(Option(Text(f" {label}", style=f"bold {palette.dim}"), disabled=True))

        if res.songs:
            header("songs")
            for i, s in enumerate(res.songs):
                row = Text("  ", no_wrap=True, overflow="ellipsis")
                row.append(anim.NOTE_FRAMES[0] + " ", style=palette.blue)
                row.append(s.title, style=palette.text)
                row.append(f"  {s.artist}", style=palette.dim)
                opts.append(Option(row, id=f"song:{i}"))
        if res.albums:
            header("albums")
            for i, a in enumerate(res.albums):
                row = Text("  ", no_wrap=True, overflow="ellipsis")
                row.append("◉ ", style=palette.mauve)
                row.append(a.name, style=palette.text)
                row.append(f"  {a.artist}", style=palette.dim)
                if a.year:
                    row.append(f" · {a.year}", style=palette.faint)
                opts.append(Option(row, id=f"album:{i}"))
        if res.artists:
            header("artists")
            for i, a in enumerate(res.artists):
                row = Text("  ", no_wrap=True, overflow="ellipsis")
                row.append(f"{icons.USER} ", style=palette.peach)
                row.append(a.name, style=palette.text)
                row.append(f"  {a.album_count} albums", style=palette.dim)
                opts.append(Option(row, id=f"artist:{i}"))
        if not opts:
            opts.append(Option(Text("  no matches", style=palette.dim), disabled=True))
        ol.add_options(opts)
        first = next((i for i, o in enumerate(opts) if not o.disabled), None)
        if first is not None:
            ol.highlighted = first

    def action_to_list(self) -> None:
        ol = self.query_one("#search-results", NavList)
        if ol.option_count:
            ol.focus()

    @on(OptionList.OptionSelected, "#search-results")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id
        if not oid:
            return
        kind, _, idx = oid.partition(":")
        i = int(idx)
        if kind == "song":
            self.dismiss(("song", self._results.songs, i))
        elif kind == "album":
            self.dismiss(("album", self._results.albums[i]))
        elif kind == "artist":
            self.dismiss(("artist", self._results.artists[i]))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ServerSwitcherModal(ModalScreen):
    """Modal to switch between different server profiles."""

    DEFAULT_CSS = """
    ServerSwitcherModal { align: center middle; background: $kit-overlay; }
    ServerSwitcherModal #switcher-box {
        width: 48; height: auto; max-height: 15;
        background: $kit-modal-bg; border: round $kit-border-focus; padding: 1 2;
    }
    ServerSwitcherModal #switcher-title { margin-bottom: 1; }
    ServerSwitcherModal OptionList { height: auto; max-height: 8; border: none; }
    """

    def __init__(self, profiles: list[str], active_profile: str) -> None:
        super().__init__()
        self._profiles = profiles
        self._active_profile = active_profile

    def compose(self) -> ComposeResult:
        with Vertical(id="switcher-box"):
            yield Static(Text("Select Server Profile:", style=f"bold {palette.sub}"), id="switcher-title")
            options = []
            for p in self._profiles:
                label = f"● {p}" if p == self._active_profile else f"  {p}"
                options.append(Option(label, id=p))
            yield OptionList(*options, id="switcher-list")

    def on_mount(self) -> None:
        pop_in(self.query_one("#switcher-box"))
        settle_pop_in(self, "#switcher-box")
        ol = self.query_one("#switcher-list", OptionList)
        ol.focus()
        try:
            idx = self._profiles.index(self._active_profile)
            ol.highlighted = idx
        except ValueError:
            pass

    @on(OptionList.OptionSelected)
    def on_select(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("q", "cancel", show=False),
    ]


class AudioDeviceSwitcherModal(ModalScreen):
    """Modal to switch between different audio output devices."""

    DEFAULT_CSS = """
    AudioDeviceSwitcherModal { align: center middle; background: $kit-overlay; }
    AudioDeviceSwitcherModal #device-box {
        width: 52; height: auto; max-height: 18;
        background: $kit-modal-bg; border: round $kit-border-focus; padding: 1 2;
    }
    AudioDeviceSwitcherModal #device-title { margin-bottom: 1; }
    AudioDeviceSwitcherModal OptionList { height: auto; max-height: 10; border: none; }
    """

    def __init__(self, devices: list[dict], active_device: str) -> None:
        super().__init__()
        self._devices = devices
        self._active_device = active_device

    def compose(self) -> ComposeResult:
        with Vertical(id="device-box"):
            yield Static(Text("Select Audio Output Device:", style=f"bold {palette.sub}"), id="device-title")
            options = []
            for d in self._devices:
                name = d.get("name", "auto")
                desc = d.get("description", name)
                label = f"● {desc}" if name == self._active_device else f"  {desc}"
                options.append(Option(label, id=name))
            yield OptionList(*options, id="device-list")

    def on_mount(self) -> None:
        pop_in(self.query_one("#device-box"))
        settle_pop_in(self, "#device-box")
        ol = self.query_one("#device-list", OptionList)
        ol.focus()
        try:
            idx = next((i for i, d in enumerate(self._devices) if d.get("name") == self._active_device), 0)
            ol.highlighted = idx
        except Exception:
            pass

    @on(OptionList.OptionSelected)
    def on_select(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("q", "cancel", show=False),
    ]


# ── Equalizer ─────────────────────────────────────────────────────────────────

PRESETS: dict[str, list[float]] = {
    "flat":       [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "bass":       [6.0, 5.0, 4.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "rock":       [4.0, 3.0, -1.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0],
    "pop":        [-2.0, -1.0, 0.0, 2.0, 4.0, 4.0, 2.0, 0.0, -1.0, -2.0],
    "vocal":      [-4.0, -3.0, -2.0, 0.0, 3.0, 4.0, 3.0, 1.0, -1.0, -3.0],
    "electronic": [5.0, 4.0, 1.0, 0.0, -1.0, 2.0, 1.0, 3.0, 4.0, 5.0],
    "classical":  [4.0, 3.0, 2.0, 2.0, -1.0, -1.0, 0.0, 2.0, 3.0, 4.0],
}


class EqualizerBand(Static):
    """A vertical column representing a single frequency band in the EQ."""
    def __init__(self, freq_label: str, gain: float = 0.0) -> None:
        super().__init__(classes="eq-band")
        self.freq_label = freq_label
        self.gain = gain  # -12.0 to +12.0 dB
        self.selected = False

    def render(self) -> Text:
        t = Text()
        # Render a vertical bar from +12dB (top) to -12dB (bottom)
        # Height of the bar: 13 lines (steps of 2dB)
        for step in range(12, -13, -2):
            is_active = False
            if self.gain >= 0:
                is_active = (0 <= step <= self.gain)
            else:
                is_active = (self.gain <= step <= 0)
                
            char = "█" if is_active else "░"
            color = "#00ffcc" if is_active else "#333333"
            if step == 0 and not is_active:
                char = "─"  # center line
                color = "#555555"
                
            t.append(f" {char} \n", style=color)
            
        t.append(f"\n{self.freq_label}\n", style="bold" if self.selected else "dim")
        t.append(f"{self.gain:+.1f}dB", style="#00ffcc" if self.selected else "dim")
        return t

    def on_click(self, event) -> None:
        # Calculate gain based on click's Y coordinate (0 to 12)
        y = event.y
        if 0 <= y <= 12:
            step = 12 - (y * 2)
            self.gain = max(-12.0, min(12.0, float(step)))
            self.refresh()
            self.screen.on_band_changed(self)


class EqualizerModal(ModalScreen):
    """An interactive 10-band software parametric equalizer modal."""

    BINDINGS = [
        Binding("escape", "save_close", show=False),
        Binding("q", "save_close", show=False),
        Binding("h,left", "select_prev", show=False),
        Binding("l,right", "select_next", show=False),
        Binding("k,up", "gain_up", show=False),
        Binding("j,down", "gain_down", show=False),
        Binding("p,P", "cycle_preset", "presets"),
        Binding("space", "toggle_eq", "toggle"),
    ]

    DEFAULT_CSS = """
    EqualizerModal { align: center middle; background: $kit-overlay; }
    EqualizerModal #eq-box {
        width: 78; height: 21;
        background: $kit-modal-bg; border: round $kit-border-focus; padding: 1 2;
    }
    EqualizerModal #eq-title { margin-bottom: 1; content-align: center middle; text-align: center; }
    EqualizerModal #eq-bands {
        height: 15;
        align: center middle;
    }
    EqualizerModal .eq-band {
        width: 7;
        height: 15;
        content-align: center middle;
        text-align: center;
        background: $kit-modal-bg;
    }
    EqualizerModal .eq-band.selected {
        background: #112211;
    }
    EqualizerModal #eq-footer {
        margin-top: 1;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, enabled: bool, preset: str, gains: list[float]) -> None:
        super().__init__()
        self._enabled = enabled
        self._preset = preset
        self._gains = list(gains) if gains else [0.0] * 10
        self._selected_idx = 0
        self._bands: list[EqualizerBand] = []
        self._freqs = ["31Hz", "62Hz", "125Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "8kHz", "16kHz"]

    def compose(self) -> ComposeResult:
        with Vertical(id="eq-box"):
            yield Static("♪  Equalizer", id="eq-title")
            with Horizontal(id="eq-bands"):
                for i, freq in enumerate(self._freqs):
                    band = EqualizerBand(freq, self._gains[i])
                    if i == self._selected_idx:
                        band.selected = True
                        band.add_class("selected")
                    yield band
            yield Static(self._footer_text(), id="eq-footer")

    def on_mount(self) -> None:
        pop_in(self.query_one("#eq-box"))
        settle_pop_in(self, "#eq-box")
        self._bands = list(self.query(".eq-band"))

    def _footer_text(self) -> str:
        state = "[ON]" if self._enabled else "[OFF]"
        preset_name = self._preset.upper()
        return f"Status: {state}  ·  Preset: {preset_name}  ·  [Space]: Toggle  ·  [P]: Presets"

    def _get_gains(self) -> list[float]:
        return [b.gain for b in self._bands]

    def on_band_changed(self, band: EqualizerBand) -> None:
        idx = self._bands.index(band)
        self._gains[idx] = band.gain
        self._preset = "custom"
        self.query_one("#eq-footer", Static).update(self._footer_text())
        if self._enabled:
            self.app.player.set_equalizer(self._get_gains())

    def action_select_next(self) -> None:
        self._bands[self._selected_idx].selected = False
        self._bands[self._selected_idx].remove_class("selected")
        self._bands[self._selected_idx].refresh()
        
        self._selected_idx = (self._selected_idx + 1) % len(self._bands)
        
        self._bands[self._selected_idx].selected = True
        self._bands[self._selected_idx].add_class("selected")
        self._bands[self._selected_idx].refresh()

    def action_select_prev(self) -> None:
        self._bands[self._selected_idx].selected = False
        self._bands[self._selected_idx].remove_class("selected")
        self._bands[self._selected_idx].refresh()
        
        self._selected_idx = (self._selected_idx - 1) % len(self._bands)
        
        self._bands[self._selected_idx].selected = True
        self._bands[self._selected_idx].add_class("selected")
        self._bands[self._selected_idx].refresh()

    def action_gain_up(self) -> None:
        band = self._bands[self._selected_idx]
        band.gain = min(12.0, band.gain + 1.0)
        band.refresh()
        self.on_band_changed(band)

    def action_gain_down(self) -> None:
        band = self._bands[self._selected_idx]
        band.gain = max(-12.0, band.gain - 1.0)
        band.refresh()
        self.on_band_changed(band)

    def action_toggle_eq(self) -> None:
        self._enabled = not self._enabled
        self.query_one("#eq-footer", Static).update(self._footer_text())
        if self._enabled:
            self.app.player.set_equalizer(self._get_gains())
        else:
            self.app.player.set_equalizer([])

    def action_cycle_preset(self) -> None:
        presets_list = ["flat", "bass", "rock", "pop", "vocal", "electronic", "classical"]
        try:
            cur_idx = presets_list.index(self._preset)
        except ValueError:
            cur_idx = -1
        next_preset = presets_list[(cur_idx + 1) % len(presets_list)]
        self._preset = next_preset
        
        gains = PRESETS[next_preset]
        for i, band in enumerate(self._bands):
            band.gain = gains[i]
            band.refresh()
            
        self.query_one("#eq-footer", Static).update(self._footer_text())
        if self._enabled:
            self.app.player.set_equalizer(gains)

    def action_save_close(self) -> None:
        self.dismiss({
            "enabled": self._enabled,
            "preset": self._preset,
            "bands": self._get_gains()
        })
