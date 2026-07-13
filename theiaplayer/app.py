"""NaviTui — the app.

Songs-first: one sidebar of ways-to-list-tracks (views + playlists), one big
tracks pane, cover + queue on the right. No tabs, no album browsing — albums
and artists only exist inside search.

Cache-first everywhere: every pane renders from the last-known JSON cache
instantly, then a worker fetches fresh rows and swaps them in silently.
One 8fps heartbeat drives every animation (logo shimmer, visualizer,
progress pulse, marquee, spinners); each tick repaints only a few cells.
"""

from __future__ import annotations

import asyncio
import pathlib
import random
import subprocess

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from ricekit import KitApp, icons, palette
from ricekit.modals import HelpModal, PickerModal
from ricekit.storage import AppDirs
from ricekit.widgets import NavList, Splitter

import sys
from theiaplayer import anim, config as playerconfig, discord_rpc, player as playermod
if sys.platform == "darwin":
    from theiaplayer import nowplaying_mac as mprismod
else:
    from theiaplayer import mpris as mprismod
from theiaplayer.api import SubsonicClient, SubsonicError
from theiaplayer.art import CoverArt
from theiaplayer.models import Album, Artist, Playlist, Song
from theiaplayer.playqueue import PlayQueue
from theiaplayer.screens import InputModal, LyricsModal, OnboardingScreen, SearchModal
from theiaplayer.widgets import ClickList, Logo, NowPlaying, PAUSE_GLYPH, PLAY_GLYPH

VIEWS = [
    ("home", "home"),
    ("all-songs", "all tracks"),
    ("newest", "recently added"),
    ("recent", "recently played"),
    ("frequent", "most played"),
    ("starred", "starred"),
    ("shuffle-all", "shuffle everything"),
]
VIEW_LABELS = dict(VIEWS)

HELP_SECTIONS = [
    (
        "playback",
        [
            ("space", "play / pause"),
            ("enter / double-click", "play (track, view, playlist)"),
            ("n / b", "next / previous track"),
            ("← / →", "seek 5s   (shift: 30s)"),
            ("- / +", "volume down / up"),
            ("m", "mute"),
            ("s", "toggle shuffle"),
            ("r", "cycle repeat  off → all → one"),
        ],
    ),
    (
        "queue",
        [
            ("a", "add track to queue"),
            ("A", "play track next"),
            ("x", "remove track (in queue panel)"),
            ("X", "clear queue"),
            ("ctrl+↑ / ctrl+↓", "move track up / down in queue"),
            ("", "played tracks dim out — scroll up for history"),
        ],
    ),
    (
        "library",
        [
            ("j / k / g / G", "move in lists"),
            ("h / l", "previous / next panel"),
            ("/", "search  (enter play · a queue · A play next)"),
            ("p", "add track to a playlist"),
            ("f", "star / unstar track"),
            ("1-5", "rate track (0 = remove rating)"),
            ("v", "toggle track selection  (a/A/f apply to all selected)"),
            ("e / E", "go to album / artist of highlighted track"),
            ("L", "show / scroll lyrics of current track"),
            ("S", "create share link (copies to clipboard)"),
            ("R", "refresh from server"),
        ],
    ),
    (
        "app",
        [
            ("N", "toggle desktop notifications"),
            ("t", "cycle kit themes"),
            ("T", "theme picker (live preview)"),
            ("?", "this help"),
            ("q", "quit"),
        ],
    ),
]

APP_STARTED: bool = False

class TheIAPlayerApp(KitApp):
    TITLE = "theia-player"

    BINDINGS = [
        Binding("space", "play_pause", "play/pause"),
        Binding("n", "next_track", "next"),
        Binding("b", "prev_track", show=False),
        Binding("slash", "search", "search"),
        Binding("s", "toggle_shuffle", "shuffle"),
        Binding("r", "cycle_repeat", "repeat"),
        Binding("left", "seek(-5)", show=False),
        Binding("right", "seek(5)", show=False),
        Binding("shift+left", "seek(-30)", show=False),
        Binding("shift+right", "seek(30)", show=False),
        Binding("minus", "volume(-5)", show=False),
        Binding("plus,equals_sign", "volume(5)", show=False),
        Binding("m", "mute", show=False),
        Binding("a", "enqueue(False)", show=False),
        Binding("A", "enqueue(True)", show=False),
        Binding("x", "queue_remove", show=False),
        Binding("X", "queue_clear", show=False),
        Binding("f", "star", show=False),
        Binding("p", "playlist_add", show=False),
        Binding("h", "focus_panel(-1)", show=False),
        Binding("l", "focus_panel(1)", show=False),
        Binding("R", "refresh", show=False),
        Binding("t", "cycle_kit_theme", "theme"),
        Binding("T", "change_theme", show=False),
        Binding("question_mark", "help", "help"),
        Binding("N", "toggle_notifications", "silent", show=True),
        Binding("P", "toggle_private_mode", "private", show=True),
        Binding("L", "show_lyrics", "lyrics", show=True),
        Binding("ctrl+g", "switch_server", "switch server", show=True),
        Binding("ctrl+d", "switch_audio_device", "audio device", show=True),
        Binding("alt+a", "filter_albums", "albums", show=False),
        Binding("alt+s", "filter_singles", "singles/EPs", show=False),
        Binding("alt+o", "filter_all", "all releases", show=False),
        Binding("q", "quit", "quit"),
    ]

    CSS = """
    #topbar { height: 1; padding: 0 1; }
    #topbar #status { width: 1fr; text-align: right; }

    #main { height: 1fr; }
    NavList { text-wrap: nowrap; text-overflow: ellipsis; }
    .panel { border: round $kit-border; }
    .panel:focus-within { border: round $kit-border-focus; }
    .panel NavList { height: 1fr; }
    #sidebar-panel { width: 26; }
    #tracks-panel { width: 1fr; }
    #side { width: 36; }
    #art-panel { height: 40%; min-height: 12; border: round $kit-border; }
    #queue-panel { height: 1fr; border: round $kit-border; }

    NowPlaying.playing { border: round $kit-border-alt; }
    #sidebar-list {
        scrollbar-size: 1 1;
        scrollbar-color: $kit-border;
        scrollbar-color-hover: $kit-border-focus;
        scrollbar-color-active: $kit-border-focus;
    }
    """

    def __init__(self, client: SubsonicClient | None = None, ao: str | None = None) -> None:
        # Load config BEFORE super().__init__() so we can patch class BINDINGS
        self.dirs = AppDirs("theia-player")
        self._audio_cache_dir = self.dirs.cache_dir / "audio"
        self._audio_cache_dir.mkdir(parents=True, exist_ok=True)
        self._active_downloads: set[str] = set()
        _pcfg = playerconfig.load(self.dirs.config_file.parent)
        playerconfig.write_default(self.dirs.config_file.parent)
        TheIAPlayerApp.BINDINGS = playerconfig.build_bindings(_pcfg.get("keybinds", {}))

        super().__init__()
        self._pcfg = _pcfg
        self.client: SubsonicClient | None = client
        self._ao = ao
        self.queue = PlayQueue()
        self.player = None
        self.mpris: mprismod.MprisController | None = None
        self.discord: discord_rpc.DiscordController | None = None
        self._notify_on: bool = bool(_pcfg.get("desktop_notifications", True))
        self._selection: set[str] = set()  # selected song IDs
        self.view: str = "all-songs"  # sidebar view id (or "pl:<id>", or "artist:<id>")
        self._songs: list[Song] = []  # what the tracks pane shows
        self._playlists: list[Playlist] = []
        # playback bookkeeping
        self._scrobbled = False
        self._end_failures = 0
        self._resume_position = 0.0
        self._mutations = 0
        self._last_persist = 0.0
        self._queue_scrolled_to = -2

        # new features bookkeeping
        self.private_mode: bool = False
        self.autoplay_enabled: bool = bool(_pcfg.get("autoplay", True))
        self._autoplay_loading: bool = False
        self.artist_release_filter: str = "all"
        self._current_artist_albums: list[Album] = []
        self._current_artist_songs: list[Song] = []
        self._current_artist_name: str = ""

    # ── layout ────────────────────────────────────────────────────────
    def compose(self):
        with Horizontal(id="topbar"):
            yield Logo(id="logo")
            yield Static(id="status")
        with Horizontal(id="main"):
            with Vertical(id="sidebar-panel", classes="panel"):
                yield ClickList(id="sidebar-list")
            yield Splitter("#sidebar-panel", on_resized=self._persist_width, id="split1")
            with Vertical(id="tracks-panel", classes="panel"):
                yield ClickList(id="tracks-list")
            yield Splitter("#side", invert=True, on_resized=self._persist_width, id="split2")
            with Vertical(id="side"):
                yield CoverArt(id="art-panel")
                with Vertical(id="queue-panel", classes="panel"):
                    yield ClickList(id="queue-list")
        yield NowPlaying(id="now")
        yield Footer()

    def on_mount(self) -> None:
        self._loop = asyncio.get_running_loop()  # for mpv-thread callbacks
        state = self.dirs.load_state()
        self._notify_on = state.get("desktop_notifications", self._notify_on)
        self.init_kit(theme=state.get("theme"))

        for selector, width in (state.get("widths") or {}).items():
            try:
                self.query_one(selector).styles.width = width
            except Exception:
                pass

        self.query_one("#sidebar-panel").border_title = "tracks"
        self.query_one("#tracks-panel").border_title = "tracks"
        self.query_one("#art-panel", CoverArt).border_title = "cover"
        self.query_one("#queue-panel").border_title = "queue"
        saved_view = state.get("view", "all-songs")
        if saved_view in VIEW_LABELS or saved_view.startswith(("pl:", "artist:", "album:")):
            self.view = saved_view

        pcfg = self._pcfg
        self.player = playermod.create_player(
            self._mpv_position,
            self._mpv_track_end,
            ao=self._ao,
            replaygain=pcfg["replaygain"],
            gapless=pcfg["gapless"],
            replaygain_preamp=float(pcfg.get("replaygain_preamp", 0)),
            replaygain_fallback=float(pcfg.get("replaygain_fallback", -6)),
            audio_exclusive=bool(pcfg.get("audio_exclusive", False)),
        )
        default_vol = pcfg["default_volume"]
        saved_vol = int(state.get("volume", default_vol if default_vol >= 0 else 80))
        self.player.set_volume(saved_vol)
        
        # Apply equalizer on startup if enabled
        eq_cfg = pcfg.get("equalizer", {})
        if eq_cfg.get("enabled", False):
            self.player.set_equalizer(eq_cfg.get("bands", []))

        mpris_callbacks = {
            "play": lambda: self._loop.call_soon_threadsafe(self.action_play),
            "pause": lambda: self._loop.call_soon_threadsafe(self.action_pause),
            "play_pause": lambda: self._loop.call_soon_threadsafe(self.action_play_pause),
            "next": lambda: self._loop.call_soon_threadsafe(self.action_next_track),
            "prev": lambda: self._loop.call_soon_threadsafe(self.action_prev_track),
        }
        self.mpris = mprismod.create(mpris_callbacks)
        self.discord = discord_rpc.create(
            pcfg.get("discord_app_id", ""),
            enabled=bool(pcfg.get("discord_rich_presence", False)),
        )
        now = self.query_one("#now", NowPlaying)
        now.volume = self.player.volume

        # restore the queue exactly as it was left
        cached_queue = self.dirs.read_cache("queue")
        if cached_queue:
            self.queue = PlayQueue.from_dict(cached_queue)
            self._resume_position = float(cached_queue.get("position", 0.0))
            now.set_song(self.queue.current)
            now.set_progress(self._resume_position, self.queue.current.duration if self.queue.current else 0)
            now._title_flash = 0
        now.shuffle = self.queue.shuffle
        now.repeat = self.queue.repeat
        self._render_queue()

        self.set_interval(1 / 8, self._heartbeat)
        self.set_interval(180, self._maybe_auto_refresh)

        if not playermod.MPV_AVAILABLE:
            self.notify(playermod.INSTALL_HINTS, severity="warning", timeout=15)

        if self.client is None:
            config = self.dirs.load_config()
            if all(config.get(k) for k in ("server", "username", "token", "salt")):
                self.client = SubsonicClient(
                    config["server"], config["username"], config["token"], config["salt"],
                    art_dir=self.dirs.cache_dir / "art",
                )
            else:
                self.push_screen(
                    OnboardingScreen(config.get("server", ""), config.get("username", "")),
                    self._onboarded,
                )
                return
        self._start()
        
        # Indicar al watchdog que la app inicio correctamente
        global APP_STARTED
        APP_STARTED = True

    def _onboarded(self, config: dict | None) -> None:
        if not config:
            return
        self._save_secrets(config)
        self.client = SubsonicClient(
            config["server"], config["username"], config["token"], config["salt"],
            art_dir=self.dirs.cache_dir / "art",
        )
        self.notify("welcome to theia-player ♪", timeout=4)
        self._start()

    def _save_secrets(self, config: dict) -> None:
        path = self.dirs.config_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f'{k} = "{v}"\n' for k, v in config.items()))
        path.chmod(0o600)

    def _start(self) -> None:
        # Restore saved audio device if available
        saved_device = self.dirs.load_state().get("audio_device")
        if saved_device and self.player is not None:
            self.player.set_audio_device(saved_device)
        self._render_status()
        cached = self.dirs.read_cache("playlists")
        if cached:
            self._playlists = [Playlist.from_dict(p) for p in cached.get("playlists", [])]
        self._render_sidebar()
        sidebar = self.query_one("#sidebar-list", ClickList)
        sidebar.focus()
        self._highlight_view(self.view)
        self._load_playlists()
        
        # Load the cover art of the restored song on startup (now that client is ready)
        if self.queue.current and self.queue.current.cover_art:
            self._load_art(self.queue.current.cover_art, f"song-{self.queue.current.id}")

    def _render_status(self) -> None:
        if self.client is None:
            return
        host = self.client.server.split("://", 1)[-1]
        text = Text()
        if getattr(self, "private_mode", False):
            text.append("[Private] ", style="bold #ff007f")
        text.append(f"{self.client.username}@{host}", style=palette.dim)
        from theiaplayer import __version__
        text.append(f" · v{__version__}", style=palette.dim)
        self.query_one("#status", Static).update(text)

    # ── the heartbeat (all constant animation) ────────────────────────
    def _heartbeat(self) -> None:
        try:
            self.query_one("#logo", Logo).tick()
            now = self.query_one("#now", NowPlaying)
            if self.player is not None:
                now.set_playing(self.player.active and not self.player.paused)
                now.set_class(self.player.active, "playing")
                from theiaplayer.screens import LyricsModal
                if isinstance(self.screen, LyricsModal):
                    self.screen.update_time(self.player.position)
            now.tick()
            busy = any(
                not w.is_finished
                for w in self.workers
                if w.group in ("lib", "songs")
            )
            panel = self.query_one("#tracks-panel")
            if busy:
                panel.border_subtitle = f"{anim.spinner(int(now._tick))} refreshing"
            elif panel.border_subtitle and "refreshing" in panel.border_subtitle:
                count = self.query_one("#tracks-list", NavList).option_count
                panel.border_subtitle = str(count) if count else None
        except Exception:
            return  # shutdown race: the timer can fire while widgets unmount

    # ── sidebar ───────────────────────────────────────────────────────
    def _render_sidebar(self) -> None:
        ol = self.query_one("#sidebar-list", ClickList)
        highlighted_id = None
        if ol.highlighted is not None:
            highlighted_id = ol.get_option_at_index(ol.highlighted).id
        options: list[Option] = []
        for view_id, label in VIEWS:
            row = Text(no_wrap=True, overflow="ellipsis")
            glyph, color = ("◍", palette.mauve)
            if view_id == "home":
                glyph, color = "🏠", palette.peach
            elif view_id == "starred":
                glyph, color = icons.STAR, palette.yellow
            elif view_id == "shuffle-all":
                glyph, color = "◍", palette.peach
            row.append(f"{glyph} ", style=color)
            row.append(label, style=palette.text)
            options.append(Option(row, id=view_id))
        options.append(Option(Text(" "), disabled=True))
        options.append(Option(Text(" playlists", style=f"bold {palette.dim}"), disabled=True))
        current_folder = None
        for p in self._playlists:
            row = Text(no_wrap=True, overflow="ellipsis")
            if "/" in p.name:
                folder, name = p.name.split("/", 1)
                if folder != current_folder:
                    current_folder = folder
                    folder_row = Text(no_wrap=True, overflow="ellipsis")
                    folder_row.append(f" 📂 {folder}", style=f"bold {palette.peach}")
                    options.append(Option(folder_row, disabled=True))
                row.append("   ", style=palette.vfaint)
                row.append(f"{icons.LIST} ", style=palette.lav)
                row.append(name, style=palette.text)
                row.append(f" {p.song_count}♪", style=palette.vfaint)
            else:
                current_folder = None
                row.append(f"{icons.LIST} ", style=palette.lav)
                row.append(p.name, style=palette.text)
                row.append(f" {p.song_count}♪", style=palette.vfaint)
            options.append(Option(row, id=f"pl:{p.id}"))
        new_row = Text(no_wrap=True)
        new_row.append(f"{icons.PLUS} ", style=palette.green)
        new_row.append("new playlist", style=palette.sub)
        options.append(Option(new_row, id="pl-new"))

        had_focus = ol.has_focus
        ol.clear_options()
        ol.add_options(options)
        self._highlight_view(highlighted_id or self.view)
        if had_focus:
            ol.focus()

    def _highlight_view(self, view_id: str | None) -> None:
        if not view_id:
            return
        ol = self.query_one("#sidebar-list", ClickList)
        for i in range(ol.option_count):
            if ol.get_option_at_index(i).id == view_id:
                ol.highlighted = i
                return

    @on(OptionList.OptionHighlighted, "#sidebar-list")
    def _sidebar_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        oid = event.option.id
        if not oid or oid == "pl-new":
            return
        self.view = oid
        self.dirs.save_state({"view": oid})
        self._load_view(oid)

    @on(OptionList.OptionSelected, "#sidebar-list")
    def _sidebar_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id
        if not oid:
            return
        if oid == "pl-new":
            self.push_screen(
                InputModal("new playlist", placeholder="name"), self._playlist_created_name
            )
        elif oid == "shuffle-all":
            self._shuffle_everything()
        elif self._songs:
            # enter on a view or playlist just plays it from the top
            self._play_songs(self._songs, 0)

    # ── loading songs into the tracks pane ────────────────────────────
    def _tracks_title(self, view_id: str) -> str:
        if view_id.startswith("pl:"):
            pid = view_id.split(":", 1)[1]
            playlist = next((p for p in self._playlists if p.id == pid), None)
            return playlist.name if playlist else "playlist"
        return VIEW_LABELS.get(view_id, "tracks")

    def _apply_filters(self, songs: list[Song]) -> list[Song]:
        f = self._pcfg.get("filters", playerconfig.DEFAULT_FILTERS)
        exclude_titles = [t.lower() for t in f.get("exclude_titles", [])]
        exclude_artists = [a.lower() for a in f.get("exclude_artists", [])]
        exclude_genres = [g.lower() for g in f.get("exclude_genres", [])]
        min_dur = int(f.get("min_duration", 0))
        max_dur = int(f.get("max_duration", 0))
        min_plays = int(f.get("min_play_count", 0))

        def keep(s: Song) -> bool:
            if exclude_titles and any(t in s.title.lower() for t in exclude_titles):
                return False
            if exclude_artists and s.artist.lower() in exclude_artists:
                return False
            if exclude_genres and s.genre.lower() in exclude_genres:
                return False
            if min_dur and s.duration <= min_dur:
                return False
            if max_dur and s.duration >= max_dur:
                return False
            if min_plays and s.play_count < min_plays:
                return False
            return True

        return [s for s in songs if keep(s)]

    def _show_songs(self, songs: list[Song], title: str) -> None:
        self._songs = self._apply_filters(songs)
        panel = self.query_one("#tracks-panel")
        panel.border_title = title
        self._fill("#tracks-list", [self._song_row(s) for s in self._songs], "#tracks-panel")

    @work(exclusive=True, group="songs")
    async def _load_view(self, view_id: str) -> None:
        await asyncio.sleep(0.12)  # superseded while the cursor is moving
        title = self._tracks_title(view_id)

        if view_id == "home":
            cache_key = "home-mix"

            async def fetch():
                try:
                    res = await asyncio.gather(
                        self.client.get_random_songs(size=10),
                        self.client.get_songs_by_albums("newest"),
                        self.client.get_songs_by_albums("frequent"),
                        return_exceptions=True
                    )
                    randoms = res[0] if isinstance(res[0], list) else []
                    newest = res[1] if isinstance(res[1], list) else []
                    frequent = res[2] if isinstance(res[2], list) else []
                    newest = newest[:10]
                    frequent = frequent[:10]
                    seen_ids = set()
                    mixed_songs = []
                    for song in randoms + frequent + newest:
                        if song.id not in seen_ids:
                            seen_ids.add(song.id)
                            mixed_songs.append(song)
                    return mixed_songs
                except Exception:
                    return []
        elif view_id in ("all-songs", "shuffle-all"):
            cache_key, fetch = "all-songs", self.client.get_all_songs
        elif view_id in ("newest", "recent", "frequent"):
            cache_key = f"songview-{view_id}"

            async def fetch(v=view_id):
                return await self.client.get_songs_by_albums(v)
        elif view_id == "starred":
            cache_key = "starred-songs"

            async def fetch():
                return (await self.client.get_starred()).songs
        elif view_id.startswith("pl:"):
            pid = view_id.split(":", 1)[1]
            cache_key = f"playlist-songs-{pid}"

            async def fetch(p=pid):
                return await self.client.get_playlist_songs(p)
        else:
            return

        cached = self.dirs.read_cache(cache_key)
        if cached:
            self._show_songs([Song.from_dict(s) for s in cached.get("songs", [])], title)
        try:
            songs = await fetch()
        except Exception as e:
            self._connection_trouble(e)
            return
        self.dirs.write_cache(cache_key, {"songs": [s.to_dict() for s in songs]})
        if self.view == view_id:
            self._show_songs(songs, title)

    @work(exclusive=True, group="songs")
    async def _load_artist_songs(self, artist: Artist) -> None:
        """Ad-hoc view from search: every song by an artist, flattened."""
        title = f"artist · {artist.name}"
        self.view = f"artist:{artist.id}"
        self._highlight_view(None)
        self.artist_release_filter = "all"
        self._current_artist_name = artist.name
        self._current_artist_albums = []
        self._current_artist_songs = []
        cache_key = f"artist-songs-{artist.id}"
        cached = self.dirs.read_cache(cache_key)
        if cached:
            self._current_artist_songs = [Song.from_dict(s) for s in cached.get("songs", [])]
            self._current_artist_albums = [Album.from_dict(a) for a in cached.get("albums", [])]
            self._filter_and_show_artist_songs()
        try:
            albums = await self.client.get_artist_albums(artist.id)
            results = await asyncio.gather(
                *(self.client.get_album_songs(a.id) for a in albums),
                return_exceptions=True,
            )
        except Exception as e:
            self._connection_trouble(e)
            return
        songs: list[Song] = []
        for r in results:
            if isinstance(r, list):
                songs.extend(r)
        self._current_artist_albums = albums
        self._current_artist_songs = songs
        self.dirs.write_cache(cache_key, {
            "songs": [s.to_dict() for s in songs],
            "albums": [a.to_dict() for a in albums]
        })
        self._filter_and_show_artist_songs()
        self.query_one("#tracks-list", ClickList).focus()

    @work(exclusive=True, group="lib")
    async def _load_playlists(self) -> None:
        try:
            playlists = await self.client.get_playlists()
        except Exception as e:
            self._connection_trouble(e)
            return
        self.dirs.write_cache("playlists", {"playlists": [p.to_dict() for p in playlists]})
        self._playlists = playlists
        self._render_sidebar()

    # ── row rendering ─────────────────────────────────────────────────
    def _song_row(self, s: Song) -> Option:
        current = self.queue.current
        is_current = current is not None and s.id == current.id
        is_selected = s.id in self._selection
        cols = self._pcfg.get("columns", playerconfig.DEFAULT_COLUMNS)
        row = Text(no_wrap=True, overflow="ellipsis")

        # selection marker or play marker
        if is_selected:
            row.append(" ● ", style=palette.peach)
        else:
            marker = anim.NOTE_FRAMES[0] if is_current else "·"
            row.append(f" {marker} ", style=palette.blue if is_current else palette.vfaint)

        if cols.get("track_number") and s.track:
            row.append(f"{s.track:>2d} ", style=palette.vfaint)

        row.append(s.title, style=f"bold {palette.blue}" if is_current else palette.text)

        if s.starred:
            row.append(f" {icons.STAR}", style=palette.yellow)

        if s.rating and cols.get("rating"):
            row.append(f" {'★' * s.rating}", style=palette.yellow)

        if cols.get("artist", True):
            row.append(f"  {s.artist}", style=palette.dim)

        if cols.get("album") and s.album:
            row.append(f" · {s.album}", style=palette.faint)

        if cols.get("year") and s.year:
            row.append(f" · {s.year}", style=palette.vfaint)

        if cols.get("genre") and s.genre:
            row.append(f" · {s.genre}", style=palette.vfaint)

        if cols.get("bit_rate") and s.bit_rate:
            row.append(f" · {s.bit_rate}k", style=palette.vfaint)

        if cols.get("play_count") and s.play_count:
            row.append(f" · {s.play_count}×", style=palette.vfaint)

        if cols.get("duration", True):
            row.append(f" · {anim.fmt_time(s.duration)}", style=palette.vfaint)

        return Option(row, id=s.id)

    def _fill(self, selector: str, options: list[Option], subtitle_of: str | None = None) -> None:
        ol = self.query_one(selector, NavList)
        had_focus = ol.has_focus
        highlighted = ol.highlighted
        ol.clear_options()
        ol.add_options(options)
        if options:
            keep = highlighted if highlighted is not None and highlighted < len(options) else 0
            ol.highlighted = keep
        if subtitle_of:
            panel = self.query_one(subtitle_of)
            panel.border_subtitle = str(len(options)) if options else None
        if had_focus:
            ol.focus()

    # ── tracks pane ───────────────────────────────────────────────────
    @on(OptionList.OptionHighlighted, "#tracks-list")
    def _track_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self.player is not None and self.player.active:
            return  # while playing, the cover belongs to the current song
        # Only change cover art on highlight if the tracks list actually has focus
        if not self.query_one("#tracks-list").has_focus:
            return
        song = next((s for s in self._songs if s.id == event.option.id), None)
        if song is not None and song.cover_art:
            self._load_art(song.cover_art, f"song-{song.id}")

    @on(OptionList.OptionSelected, "#tracks-list")
    def _track_selected(self, event: OptionList.OptionSelected) -> None:
        idx = next((i for i, s in enumerate(self._songs) if s.id == event.option.id), None)
        if idx is not None:
            self._play_songs(self._songs, idx)

    @on(OptionList.OptionSelected, "#queue-list")
    def _queue_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.highlighted is not None:
            self.queue.jump(event.option_list.highlighted)
            self._play_current()

    # ── playback ──────────────────────────────────────────────────────
    def _shuffle_everything(self) -> None:
        if not self._songs:
            self.notify("still fetching the library — try again in a second", timeout=3)
            return
        if not self.queue.shuffle:
            self.queue.shuffle = True
            self.query_one("#now", NowPlaying).shuffle = True
            self.dirs.save_state({"shuffle": True})
        self._play_songs(self._songs, random.randrange(len(self._songs)))
        self.notify(f"shuffling all {len(self._songs)} tracks", timeout=3)

    def _play_songs(self, songs: list[Song], start: int) -> None:
        self.queue.set_songs(songs, start)
        self._play_current()

    def _play_current(self, resume_at: float = 0.0) -> None:
        song = self.queue.current
        now = self.query_one("#now", NowPlaying)
        if song is None:
            self.player.stop()
            now.set_song(None)
            self._render_queue()
            if self.mpris is not None:
                self.mpris.set_stopped()
            return

        # Close and pro-actively reload lyrics if currently viewing them
        from theiaplayer.screens import LyricsModal
        if isinstance(self.screen, LyricsModal):
            self.pop_screen()
            self.action_show_lyrics()
        
        # Audio cache implementation
        audio_path = self._get_cached_audio_path(song)
        if audio_path and audio_path.exists():
            self.player.play(str(audio_path), start=resume_at)
        else:
            self.player.play(self.client.stream_url(song.id), start=resume_at)
            self._cache_audio_async(song)
            
        now.set_song(song)
        now.set_progress(resume_at, song.duration)
        self._scrobbled = False
        self._scrobble(song.id, False)
        if song.cover_art:
            self._load_art(song.cover_art, f"song-{song.id}")
        self._render_queue()
        self._refresh_song_markers()
        self._persist_queue()
        if self.mpris is not None:
            art_path = self.client.cached_art(song.cover_art) if (self.client and song.cover_art) else None
            self.mpris.set_song(song, str(art_path) if art_path else "")
            self.mpris.set_playing(True)
        self._send_notification(song)
        self._update_discord(song)
        self._check_autoplay()

    def _refresh_song_markers(self) -> None:
        """Re-render the tracks pane so the ♪ marker follows the player."""
        self._fill("#tracks-list", [self._song_row(s) for s in self._songs])

    def action_play_pause(self) -> None:
        if self.player.active:
            self.player.toggle_pause()
            if self.mpris is not None:
                self.mpris.set_playing(not self.player.paused)
        elif self.queue.current is not None:
            # resume a restored queue exactly where it left off
            self._play_current(resume_at=self._resume_position)
            self._resume_position = 0.0

    def action_play(self) -> None:
        if self.player.active:
            if self.player.paused:
                self.player.set_paused(False)
                if self.mpris is not None:
                    self.mpris.set_playing(True)
        elif self.queue.current is not None:
            self._play_current(resume_at=self._resume_position)
            self._resume_position = 0.0

    def action_pause(self) -> None:
        if self.player.active:
            if not self.player.paused:
                self.player.set_paused(True)
                if self.mpris is not None:
                    self.mpris.set_playing(False)

    def action_next_track(self) -> None:
        song = self.queue.advance(natural=False)
        if song is not None:
            self._play_current()

    def action_prev_track(self) -> None:
        if self.player.position > 4:
            self.player.seek_to(0.0)
            return
        song = self.queue.prev()
        if song is not None:
            self._play_current()

    def action_seek(self, seconds: int) -> None:
        self.player.seek(seconds)

    def seek_fraction(self, fraction: float) -> None:
        self.player.seek_to(fraction)

    def action_volume(self, delta: int) -> None:
        volume = self.player.set_volume(self.player.volume + delta)
        now = self.query_one("#now", NowPlaying)
        now.volume = volume
        now.flash_volume()
        self.dirs.save_state({"volume": volume})

    def set_volume_fraction(self, fraction: float) -> None:
        self.action_volume(round(fraction * 100) - self.player.volume)

    def action_mute(self) -> None:
        now = self.query_one("#now", NowPlaying)
        now.muted = self.player.toggle_mute()
        now.flash_volume()

    def action_toggle_shuffle(self) -> None:
        on_now = self.queue.toggle_shuffle()
        self.query_one("#now", NowPlaying).shuffle = on_now
        self._render_queue()
        self.dirs.save_state({"shuffle": on_now})
        self.notify(f"shuffle {'on' if on_now else 'off'}", timeout=1.5)

    def action_cycle_repeat(self) -> None:
        mode = self.queue.cycle_repeat()
        self.query_one("#now", NowPlaying).repeat = mode
        self.dirs.save_state({"repeat": mode.value})
        self.notify(f"repeat {mode.value}", timeout=1.5)

    # ── notifications ─────────────────────────────────────────────────
    def _send_notification(self, song: Song | None) -> None:
        if not self._notify_on or song is None:
            return
        try:
            args = ["notify-send", "-t", "5000", song.title, f"{song.artist} — {song.album}"]
            art = self.client.cached_art(song.cover_art) if (self.client and song.cover_art) else None
            if art:
                args += ["-i", str(art)]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass  # notify-send not installed

    def action_toggle_notifications(self) -> None:
        self._notify_on = not self._notify_on
        self.dirs.save_state({"desktop_notifications": self._notify_on})
        self.notify(f"notifications {'on' if self._notify_on else 'off'}", timeout=2)

    def action_toggle_private_mode(self) -> None:
        self.private_mode = not self.private_mode
        self._render_status()
        self.notify(f"private mode {'on' if self.private_mode else 'off'}", timeout=2)

    def action_switch_server(self) -> None:
        config = self.dirs.load_config()
        profiles = config.get("profiles", {})
        if not profiles:
            self.notify("No alternative server profiles found in config.toml", severity="warning", timeout=4)
            return
        active_profile = self.dirs.load_state().get("active_profile", "default")
        from theiaplayer.screens import ServerSwitcherModal
        self.push_screen(
            ServerSwitcherModal(list(profiles.keys()), active_profile),
            self._on_server_selected
        )

    def _on_server_selected(self, selected: str | None) -> None:
        if selected:
            config = self.dirs.load_config()
            profiles = config.get("profiles", {})
            if selected in profiles:
                self.dirs.save_state({"active_profile": selected})
                self.notify(f"Switching to profile: {selected}...", timeout=2)
                self._reconnect_client(profiles[selected])

    def _reconnect_client(self, creds: dict) -> None:
        try:
            from theiaplayer.api import SubsonicClient
            self.client = SubsonicClient(
                creds["server"], creds["username"], creds["token"], creds["salt"],
                art_dir=self.dirs.cache_dir / "art",
            )
            self._render_status()
            self.queue.clear()
            self._load_playlists()
            self._load_view("home")
            self.notify("Server connected successfully!", timeout=2)
        except Exception as e:
            self.notify(f"Connection failed: {e}", severity="error", timeout=4)

    def action_switch_audio_device(self) -> None:
        if self.player is None:
            return
        devices = self.player.get_audio_devices()
        if not devices:
            self.notify("No audio output devices detected", severity="warning", timeout=4)
            return
        active_device = self.player.get_current_audio_device()
        from theiaplayer.screens import AudioDeviceSwitcherModal
        self.push_screen(
            AudioDeviceSwitcherModal(devices, active_device),
            self._on_audio_device_selected
        )

    def _on_audio_device_selected(self, selected: str | None) -> None:
        if selected and self.player is not None:
            self.player.set_audio_device(selected)
            self.dirs.save_state({"audio_device": selected})
            devices = self.player.get_audio_devices()
            desc = next((d.get("description", selected) for d in devices if d.get("name") == selected), selected)
            self.notify(f"Audio output: {desc}", timeout=3)

    def _check_autoplay(self) -> None:
        if not getattr(self, "autoplay_enabled", True):
            return
        if self.client is None:
            return
        remaining = len(self.queue.songs) - (self.queue.index + 1)
        if remaining <= 1:
            if getattr(self, "_autoplay_loading", False):
                return
            self._autoplay_loading = True
            self._fetch_autoplay_songs()

    @work(exclusive=True, group="autodj")
    async def _fetch_autoplay_songs(self) -> None:
        try:
            seed = self.queue.current
            if seed is not None:
                songs = await self.client.get_similar_songs(seed.id, size=15)
            else:
                songs = await self.client.get_random_songs(size=15)
            f = self._pcfg.get("filters", playerconfig.DEFAULT_FILTERS)
            songs = playerconfig.apply_filters(songs, f)
            if songs:
                self.queue.add(songs)
                self._render_queue()
                self._persist_queue()
                self.notify(f"Auto DJ: {len(songs)} similar songs enqueued", timeout=3)
        except Exception:
            pass
        finally:
            self._autoplay_loading = False

    def _filter_and_show_artist_songs(self) -> None:
        if not self.view.startswith("artist:"):
            return
        filtr = getattr(self, "artist_release_filter", "all")
        if filtr == "album":
            allowed_albums = {a.id for a in self._current_artist_albums if a.release_type == "album"}
            title_suffix = " · albums"
        elif filtr == "single":
            allowed_albums = {a.id for a in self._current_artist_albums if a.release_type in ["single", "ep"]}
            title_suffix = " · singles & EPs"
        elif filtr == "compilation":
            allowed_albums = {a.id for a in self._current_artist_albums if a.release_type == "compilation"}
            title_suffix = " · compilations"
        else:
            allowed_albums = {a.id for a in self._current_artist_albums}
            title_suffix = " · all releases"
        filtered_songs = [s for s in self._current_artist_songs if s.album_id in allowed_albums]
        title = f"artist · {self._current_artist_name}{title_suffix}"
        self._show_songs(filtered_songs, title)

    def action_filter_albums(self) -> None:
        if self.view.startswith("artist:"):
            self.artist_release_filter = "album"
            self._filter_and_show_artist_songs()
            self.notify("Filter: Albums", timeout=1.5)

    def action_filter_singles(self) -> None:
        if self.view.startswith("artist:"):
            self.artist_release_filter = "single"
            self._filter_and_show_artist_songs()
            self.notify("Filter: Singles & EPs", timeout=1.5)

    def action_filter_all(self) -> None:
        if self.view.startswith("artist:"):
            self.artist_release_filter = "all"
            self._filter_and_show_artist_songs()
            self.notify("Filter: All Releases", timeout=1.5)

    # ── discord ───────────────────────────────────────────────────────
    def _update_discord(self, song: Song | None) -> None:
        if self.discord is None:
            return
        if song is None:
            self.discord.clear()
            return
        art_path = self.client.cached_art(song.cover_art) if (self.client and song.cover_art) else None
        self.discord.update(
            title=song.title,
            artist=song.artist,
            album=song.album,
            art_url=f"file://{art_path}" if art_path else "",
            position=self.player.position if self.player else 0.0,
            duration=float(song.duration),
        )

    # ── queue reorder ─────────────────────────────────────────────────
    def action_queue_move(self, direction: int) -> None:
        focused = self.focused
        if focused is None or focused.id != "queue-list":
            return
        ol = self.query_one("#queue-list")
        if ol.highlighted is None:
            return
        i = ol.highlighted
        moved = self.queue.move_up(i) if direction < 0 else self.queue.move_down(i)
        if moved:
            new_i = i - 1 if direction < 0 else i + 1
            self._render_queue()
            self.query_one("#queue-list").highlighted = new_i
            self._persist_queue()

    # ── share ─────────────────────────────────────────────────────────
    @work(group="mutate")
    async def action_share(self) -> None:
        if self.client is None:
            return
        song = self._highlighted_song() or self.queue.current
        if song is None:
            self.notify("highlight a track first", timeout=3)
            return
        try:
            url = await self.client.create_share(song.id)
        except Exception as e:
            self.notify(f"share failed: {e}", severity="error", timeout=5)
            return
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"]):
            try:
                subprocess.run(cmd, input=url.encode(), check=True, timeout=3,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.notify(f"link copied: {url}", timeout=8)
                return
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        self.notify(f"share: {url}", timeout=12)

    # ── rating ────────────────────────────────────────────────────────
    def action_rate(self, n: int) -> None:
        song = self._highlighted_song()
        if song is None:
            return
        song.rating = n
        self._do_rate(song.id, n)
        self._refresh_song_markers()
        label = ("★" * n + "☆" * (5 - n)) if n > 0 else "rating removed"
        self.notify(f"{label}  {song.title}", timeout=2)

    @work(group="mutate")
    async def _do_rate(self, song_id: str, rating: int) -> None:
        self._mutations += 1
        try:
            await self.client.set_rating(song_id, rating)
        except Exception as e:
            self.notify(f"rating failed: {e}", severity="warning")
        finally:
            self._mutations -= 1

    # ── lyrics ────────────────────────────────────────────────────────
    @work(exclusive=True, group="lyrics")
    async def action_show_lyrics(self) -> None:
        if self.client is None:
            return
        song = self.queue.current
        if song is None:
            self.notify("nothing playing", timeout=3)
            return
        self.notify("fetching lyrics…", timeout=2)
        lines = await self.client.get_lyrics(song.id, artist=song.artist, title=song.title)
        if not lines:
            self.notify("no lyrics found", timeout=3)
            return
        self.push_screen(LyricsModal(song.title, song.artist, lines))

    # ── equalizer ─────────────────────────────────────────────────────
    def action_show_equalizer(self) -> None:
        if self.player is None:
            return
        eq_cfg = self._pcfg.get("equalizer", {
            "enabled": False,
            "preset": "flat",
            "bands": [0.0] * 10
        })
        from theiaplayer.screens import EqualizerModal
        self.push_screen(
            EqualizerModal(
                enabled=bool(eq_cfg.get("enabled", False)),
                preset=str(eq_cfg.get("preset", "flat")),
                gains=eq_cfg.get("bands", [0.0] * 10)
            ),
            self._equalizer_done
        )

    def _equalizer_done(self, result: dict | None) -> None:
        if not result:
            return
        self._pcfg["equalizer"] = result
        self._save_equalizer_settings(result)

    def _save_equalizer_settings(self, result: dict) -> None:
        path = self.dirs.config_dir / "player.toml"
        if not path.exists():
            return
        try:
            import tomlkit
            doc = tomlkit.parse(path.read_text())
            if "equalizer" not in doc:
                doc["equalizer"] = tomlkit.table()
            
            doc["equalizer"]["enabled"] = result["enabled"]
            doc["equalizer"]["preset"] = result["preset"]
            
            # Format bands array beautifully as a single line
            bands_array = tomlkit.array()
            for b in result["bands"]:
                bands_array.append(float(b))
            doc["equalizer"]["bands"] = bands_array
            
            path.write_text(tomlkit.dumps(doc))
        except Exception:
            pass

    # ── go to album / artist ──────────────────────────────────────────
    def action_go_to_album(self) -> None:
        song = self._highlighted_song() or self.queue.current
        if song is None or song.album_id is None:
            return
        self._load_album(song.album_id, song.album)

    def action_go_to_artist(self) -> None:
        song = self._highlighted_song() or self.queue.current
        if song is None or song.artist_id is None:
            return
        self._load_artist_songs(Artist(id=song.artist_id, name=song.artist))

    @work(exclusive=True, group="songs")
    async def _load_album(self, album_id: str, album_name: str) -> None:
        title = f"album · {album_name}"
        self.view = f"album:{album_id}"
        self._highlight_view(None)
        try:
            songs = await self.client.get_album_songs(album_id)
        except Exception as e:
            self._connection_trouble(e)
            return
        self._show_songs(songs, title)
        self.query_one("#tracks-list", ClickList).focus()

    # ── selection ─────────────────────────────────────────────────────
    def action_toggle_selection(self) -> None:
        focused = self.focused
        if focused is None or focused.id != "tracks-list":
            return
        ol = self.query_one("#tracks-list")
        if ol.highlighted is None or ol.highlighted >= len(self._songs):
            return
        song = self._songs[ol.highlighted]
        if song.id in self._selection:
            self._selection.discard(song.id)
        else:
            self._selection.add(song.id)
        self._refresh_song_markers()

    def _clear_selection(self) -> None:
        if self._selection:
            self._selection.clear()
            self._refresh_song_markers()

    # ── mpv thread callbacks ──────────────────────────────────────────
    # These arrive on mpv's event thread and must NEVER block: a blocking
    # call_from_thread here deadlocks against player.terminate() on quit
    # (the UI thread joins the event thread while the event thread waits
    # for the UI thread). call_soon_threadsafe just enqueues and returns.
    def _mpv_position(self, position: float, duration: float) -> None:
        try:
            self._loop.call_soon_threadsafe(self._on_position, position, duration)
        except Exception:
            pass  # loop gone — app shutting down

    def _mpv_track_end(self, failed: bool) -> None:
        try:
            self._loop.call_soon_threadsafe(self._on_track_end, failed)
        except Exception:
            pass

    def _on_position(self, position: float, duration: float) -> None:
        if not self.is_running:
            return
        now = self.query_one("#now", NowPlaying)
        now.set_progress(position, duration)
        if self.mpris is not None:
            self.mpris.set_position(position)
        if position > 3:
            self._end_failures = 0
        song = self.queue.current
        if song and not self._scrobbled and duration > 0:
            if position >= min(duration / 2, 240):
                self._scrobbled = True
                self._scrobble(song.id, True)
        # crash-safe resume point, at most every 10s
        if position - self._last_persist >= 10 or position < self._last_persist:
            self._last_persist = position
            self._persist_queue(position)

    def _on_track_end(self, failed: bool) -> None:
        if not self.is_running:
            return
        if failed:
            self._end_failures += 1
            song = self.queue.current
            self.notify(
                f"stream failed: {song.title if song else '?'}",
                severity="warning",
                timeout=4,
            )
            if self._end_failures >= 3:
                self.notify("three failures in a row — stopping", severity="error")
                self.player.stop()
                self.query_one("#now", NowPlaying).set_playing(False)
                return
        song = self.queue.advance(natural=not failed)
        if song is not None:
            self._play_current()
        else:
            self.player.stop()
            now = self.query_one("#now", NowPlaying)
            now.set_playing(False)
            now.set_progress(0.0, 0.0)
            self._render_queue()
            if self.mpris is not None:
                self.mpris.set_stopped()

    # ── queue ─────────────────────────────────────────────────────────
    def _render_queue(self) -> None:
        panel = self.query_one("#queue-panel")
        options = []
        for i, song in enumerate(self.queue.songs):
            row = Text(no_wrap=True, overflow="ellipsis")
            if i < self.queue.index:
                # already played: dim it way down, scroll up to revisit
                row.append(f"{i + 1:>2d} ", style=palette.vfaint)
                row.append(song.title, style=palette.faint)
                row.append(f"  {song.artist}", style=palette.vfaint)
            elif i == self.queue.index:
                glyph = PLAY_GLYPH if (self.player and self.player.active and not self.player.paused) else PAUSE_GLYPH
                row.append(f"{glyph} ", style=palette.green)
                row.append(song.title, style=f"bold {palette.blue}")
                row.append(f"  {song.artist}", style=palette.dim)
            else:
                row.append(f"{i + 1:>2d} ", style=palette.vfaint)
                row.append(song.title, style=palette.text)
                row.append(f"  {song.artist}", style=palette.dim)
            options.append(Option(row, id=f"q{i}"))
        self._fill("#queue-list", options)
        ol = self.query_one("#queue-list", NavList)
        if options and 0 <= self.queue.index < len(options):
            ol.highlighted = self.queue.index
            # pin the current track to the top so the panel reads "up next";
            # only when the track changes, so manual scrollback isn't fought
            if self.queue.index != self._queue_scrolled_to:
                self._queue_scrolled_to = self.queue.index
                index = self.queue.index
                self.call_after_refresh(
                    lambda: ol.scroll_to(y=index, animate=False)
                )
        upcoming = self.queue.songs[self.queue.index + 1 :] if self.queue.index >= 0 else self.queue.songs
        remaining = sum(s.duration for s in upcoming)
        panel.border_subtitle = (
            f"{len(upcoming)}♪ up next · {anim.fmt_time(remaining)}" if self.queue.songs else None
        )

    def action_enqueue(self, play_next: bool) -> None:
        focused = self.focused
        if focused is None or focused.id != "tracks-list":
            return
        ol = self.query_one("#tracks-list", NavList)
        if ol.highlighted is None or ol.highlighted >= len(self._songs):
            return
        if self._selection:
            songs = [s for s in self._songs if s.id in self._selection]
            if play_next:
                self.queue.add_next(songs)
            else:
                self.queue.add(songs)
            self._render_queue()
            self._persist_queue()
            self.notify(f"queued {'next: ' if play_next else ''}{len(songs)} tracks", timeout=2)
            self._clear_selection()
        else:
            song = self._songs[ol.highlighted]
            if play_next:
                self.queue.add_next([song])
            else:
                self.queue.add([song])
            self._render_queue()
            self._persist_queue()
            self.notify(f"queued {'next: ' if play_next else ''}{song.title}", timeout=2)

    def action_queue_remove(self) -> None:
        focused = self.focused
        if focused is None or focused.id != "queue-list":
            return
        ol = self.query_one("#queue-list", NavList)
        if ol.highlighted is None:
            return
        was_current = ol.highlighted == self.queue.index
        self.queue.remove(ol.highlighted)
        if was_current:
            self._play_current()
        else:
            self._render_queue()
        self._persist_queue()

    def action_queue_clear(self) -> None:
        self.queue.clear()
        self.player.stop()
        now = self.query_one("#now", NowPlaying)
        now.set_song(None)
        now.set_playing(False)
        self._render_queue()
        self._persist_queue()
        self.notify("queue cleared", timeout=2)
        if self.mpris is not None:
            self.mpris.set_stopped()

    def _persist_queue(self, position: float | None = None) -> None:
        data = self.queue.to_dict()
        data["position"] = position if position is not None else (self.player.position if self.player else 0.0)
        self.dirs.write_cache("queue", data)

    # ── playlists ─────────────────────────────────────────────────────
    def _highlighted_song(self) -> Song | None:
        focused = self.focused
        if focused is not None and focused.id == "tracks-list":
            ol = self.query_one("#tracks-list", NavList)
            if ol.highlighted is not None and ol.highlighted < len(self._songs):
                return self._songs[ol.highlighted]
        elif focused is not None and focused.id == "queue-list":
            ol = self.query_one("#queue-list", NavList)
            if ol.highlighted is not None and ol.highlighted < len(self.queue.songs):
                return self.queue.songs[ol.highlighted]
        return None

    def action_playlist_add(self) -> None:
        song = self._highlighted_song()
        if song is None:
            self.notify("highlight a track first (tracks or queue panel)", timeout=3)
            return
        options = [
            Option(Text(f" {icons.LIST} {p.name}", style=palette.text), id=f"pl:{p.id}")
            for p in self._playlists
        ]
        options.append(Option(Text(f" {icons.PLUS} new playlist…", style=palette.sub), id="pl-new"))

        def picked(choice: str | None) -> None:
            if not choice:
                return
            if choice == "pl-new":
                self.push_screen(
                    InputModal("new playlist", placeholder="name"),
                    lambda name: self._playlist_create(name, song) if name else None,
                )
            else:
                pid = choice.split(":", 1)[1]
                self._playlist_append(pid, song)

        self.push_screen(PickerModal(f"add “{song.title}” to…", options), picked)

    def _playlist_created_name(self, name: str | None) -> None:
        if name:
            self._playlist_create(name, None)

    @work(group="mutate")
    async def _playlist_create(self, name: str, song: Song | None) -> None:
        self._mutations += 1
        try:
            await self.client.create_playlist(name, [song.id] if song else [])
        except Exception as e:
            self.notify(f"couldn't create playlist: {e}", severity="error", timeout=5)
            return
        finally:
            self._mutations -= 1
        self.notify(
            f"created “{name}”" + (f" with {song.title}" if song else ""), timeout=3
        )
        self._load_playlists()

    @work(group="mutate")
    async def _playlist_append(self, playlist_id: str, song: Song) -> None:
        self._mutations += 1
        try:
            await self.client.add_to_playlist(playlist_id, [song.id])
        except Exception as e:
            self.notify(f"couldn't add to playlist: {e}", severity="error", timeout=5)
            return
        finally:
            self._mutations -= 1
        playlist = next((p for p in self._playlists if p.id == playlist_id), None)
        self.notify(f"added to “{playlist.name if playlist else 'playlist'}”", timeout=3)
        # the playlist's cached songs are stale now
        try:
            (self.dirs.cache_dir / f"playlist-songs-{playlist_id}.json").unlink()
        except OSError:
            pass
        self._load_playlists()

    # ── starring ──────────────────────────────────────────────────────
    def action_star(self) -> None:
        if self._selection:
            songs = [s for s in self._songs if s.id in self._selection]
            for s in songs:
                s.starred = not s.starred
                self._star(s.id, "song", s.starred)
            self._refresh_song_markers()
            self._render_queue()
            self._clear_selection()
            return
        song = self._highlighted_song()
        if song is None:
            return
        song.starred = not song.starred  # optimistic — the cache IS the truth
        self._star(song.id, "song", song.starred)
        self._refresh_song_markers()
        self._render_queue()
        current = self.queue.current
        if current is not None and song.id == current.id:
            current.starred = song.starred
            self.query_one("#now", NowPlaying).song = current

    @work(group="mutate")
    async def _star(self, item_id: str, kind: str, star: bool) -> None:
        self._mutations += 1
        try:
            await self.client.set_star(item_id, kind, star)
        except Exception as e:
            self.notify(f"couldn't {'star' if star else 'unstar'}: {e}", severity="warning")
        finally:
            self._mutations -= 1

    @work(group="mutate")
    async def _scrobble(self, song_id: str, submission: bool) -> None:
        if getattr(self, "private_mode", False):
            return
        try:
            await self.client.scrobble(song_id, submission)
        except Exception:
            pass  # scrobbling is best-effort

    # ── art ───────────────────────────────────────────────────────────
    @work(exclusive=True, group="art")
    async def _load_art(self, cover_id: str, key: str) -> None:
        panel = self.query_one("#art-panel", CoverArt)
        try:
            path = await self.client.cover_art(cover_id)
        except Exception:
            panel.placeholder()
            return
        panel.show(path, key)
        # Actualizar en caliente MPRIS una vez que la carátula se ha descargado en disco
        if self.mpris is not None and self.queue.current is not None:
            self.mpris.set_song(self.queue.current, str(path))

    # ── search ────────────────────────────────────────────────────────
    def action_search(self) -> None:
        if self.client is None:
            return
        self.push_screen(SearchModal(), self._search_done)

    def _search_done(self, result) -> None:
        if not result:
            return
        kind = result[0]
        if kind == "song":
            _, songs, index = result
            self._play_songs(songs, index)
        elif kind == "song-queue":
            _, song, play_next = result
            if play_next:
                self.queue.add_next([song])
            else:
                self.queue.add([song])
            self._render_queue()
            self._persist_queue()
            self.notify(f"queued {'next: ' if play_next else ''}{song.title}", timeout=2)
        elif kind == "album":
            self._enqueue_album(result[1])
        elif kind == "artist":
            self._load_artist_songs(result[1])

    @work(group="mutate")
    async def _enqueue_album(self, album: Album) -> None:
        try:
            songs = await self.client.get_album_songs(album.id)
        except Exception as e:
            self._connection_trouble(e)
            return
        self.queue.add(songs)
        self._render_queue()
        self._persist_queue()
        self.notify(f"queued album: {album.name}", timeout=3)

    # ── misc actions ──────────────────────────────────────────────────
    def action_focus_panel(self, direction: int) -> None:
        lists = [
            self.query_one("#sidebar-list", NavList),
            self.query_one("#tracks-list", NavList),
            self.query_one("#queue-list", NavList),
        ]
        focused = self.focused
        try:
            i = lists.index(focused)
        except ValueError:
            i = 0 if direction > 0 else 1
            direction = 0 if direction > 0 else -1
        lists[(i + direction) % len(lists)].focus()

    def action_refresh(self) -> None:
        self._load_playlists()
        if self.view.startswith(("artist:", "album:")):
            pass  # ad-hoc view; nothing to re-trigger
        else:
            self._load_view(self.view)
        self.notify("refreshing", timeout=1.5)

    def _maybe_auto_refresh(self) -> None:
        if self.client is None or self._mutations > 0:
            return
        if self.screen is not self.screen_stack[0]:
            return  # modal open — don't yank state around underneath it
        self._load_playlists()
        if not self.view.startswith(("artist:", "album:")):
            self._load_view(self.view)

    def action_help(self) -> None:
        self.push_screen(HelpModal(HELP_SECTIONS, title="theia-player · keys"))

    def on_kit_theme_changed(self) -> None:
        if not self.kit_theme_previewing:
            self.dirs.save_state({"theme": self.theme})
        self._render_status()
        if self.client is not None:
            self._render_sidebar()
            self._refresh_song_markers()
            self._render_queue()

    def _persist_width(self, selector: str, width: int | None) -> None:
        widths = self.dirs.load_state().get("widths", {})
        if width is None:
            widths.pop(selector, None)
        else:
            widths[selector] = width
        self.dirs.save_state({"widths": widths})

    def _connection_trouble(self, error: Exception) -> None:
        if isinstance(error, SubsonicError):
            self.notify(f"server error: {error}", severity="error", timeout=6)
        else:
            self.notify("offline — showing cached library", severity="warning", timeout=4)

    def on_key(self, event) -> None:
        """Handle keys that can't be expressed as parameterised Binding actions."""
        if event.key in ("1", "2", "3", "4", "5", "0"):
            focused = self.focused
            if focused is not None and focused.id == "tracks-list":
                self.action_rate(int(event.key))
                event.stop()

    async def action_quit(self) -> None:
        if self.mpris is not None:
            self.mpris.stop()
        if self.discord is not None:
            self.discord.stop()
        if self.player is not None:
            self._persist_queue()
            self.player.terminate()
        if self.client is not None:
            try:
                await self.client.close()
            except Exception:
                pass
        self.exit()

    def _get_cached_audio_path(self, song: Song) -> pathlib.Path:
        import pathlib
        return self._audio_cache_dir / f"{song.id}.{song.suffix or 'mp3'}"

    def _cache_audio_async(self, song: Song) -> None:
        url = self.client.stream_url(song.id) if self.client else ""
        if url:
            self._download_song_to_cache(song, url)

    @work(group="cache_download")
    async def _download_song_to_cache(self, song: Song, url: str) -> None:
        if not hasattr(self, "_active_downloads"):
            self._active_downloads = set()
        if song.id in self._active_downloads:
            return
        self._active_downloads.add(song.id)
        try:
            dest = self._get_cached_audio_path(song)
            if dest.exists():
                return
            import httpx
            tmp_dest = dest.with_suffix(".tmp")
            self._rotate_audio_cache_if_needed()
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", url) as response:
                    if response.status_code == 200:
                        with open(tmp_dest, "wb") as f:
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)
                        if tmp_dest.exists():
                            tmp_dest.rename(dest)
        except Exception:
            pass
        finally:
            self._active_downloads.discard(song.id)

    def _rotate_audio_cache_if_needed(self) -> None:
        try:
            limit = float(self._pcfg.get("cache_size_gb", 2.0)) * 1024 * 1024 * 1024
            dir_path = self._audio_cache_dir
            if not dir_path.exists():
                return
            files = [
                (f, f.stat())
                for f in dir_path.iterdir()
                if f.is_file() and not f.name.endswith(".tmp")
            ]
            total_size = sum(stat.st_size for _, stat in files)
            if total_size <= limit:
                return
            files.sort(key=lambda x: x[1].st_atime)
            target_size = limit * 0.8
            for f, stat in files:
                try:
                    f.unlink()
                    total_size -= stat.st_size
                    if total_size <= target_size:
                        break
                except Exception:
                    pass
        except Exception:
            pass


def watchdog_thread() -> None:
    import time
    import os
    import sys
    import traceback
    
    # Esperar 5 segundos
    time.sleep(5.0)
    
    # Si la aplicacion no ha indicado que se inicio correctamente en el hilo de la UI,
    # recopilamos las trazas de todos los hilos activos del proceso, las guardamos en /tmp/theia-player.log
    # y abortamos el proceso inmediatamente para liberar la terminal del usuario.
    global APP_STARTED
    if not APP_STARTED:
        log_path = "/tmp/theia-player.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n🚨 WATCHDOG TIMEOUT: El reproductor se quedo congelado en el arranque (>5.0s).\n")
                f.write("=== COLA DE LLAMADAS DE HILOS (STACK TRACES) ===\n")
                for thread_id, frame in sys._current_frames().items():
                    f.write(f"\n--- Thread {thread_id} ---\n")
                    traceback.print_stack(frame, file=f)
        except Exception:
            pass
        os._exit(1)


def main() -> None:
    import os
    import sys
    import threading
    import traceback
    
    # Silenciar warnings menores de PipeWire
    os.environ["PIPEWIRE_DEBUG"] = "0"
    
    # Si corre en Ghostty o Kitty, forzar de forma nativa el Kitty Graphics Protocol (tgp) para portadas de alta resolucion real.
    # Nota de sistemas: El uso de enlaces simbolicos directos de TTY (sin wrappers de Bash intermedias) es mandatorio
    # para que la negociacion de capacidades ANSI de textual-image fluya de forma asincrona y estable en caliente.
    term = os.environ.get("TERM_PROGRAM", "").lower()
    is_kitty_compatible = (term in ("ghostty", "kitty") or os.environ.get("TERM") == "xterm-kitty")
    if is_kitty_compatible and "NAVITUI_ART" not in os.environ:
        os.environ["NAVITUI_ART"] = "tgp"
        
    log_path = "/tmp/theia-player.log"
    try:
        # Intentar limpiar el archivo de log viejo para partir de cero
        if os.path.exists(log_path):
            os.remove(log_path)
    except Exception:
        pass
        
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write("=== INICIANDO THEIA-PLAYER INTERACTIVO ===\n")
            
        # Lanzar el hilo de watchdog daemonizado de fondo para liberar de inmediato la terminal ante cualquier bloqueo
        t = threading.Thread(target=watchdog_thread, daemon=True)
        t.start()
        
        # Ejecutar la aplicacion
        TheIAPlayerApp().run()
        
    except Exception as e:
        # CAPTURAR CUALQUIER EXCEPCIÓN DEL ARRANQUE Y GUARDARLA AL LOG
        try:
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"\n🚨 CRASH CRÍTICO EN EL ARRANQUE:\n")
                traceback.print_exc(file=log_file)
        except Exception:
            pass
        # Tambien imprimirlo a stderr real por si la Alternate Screen se cierra para que el usuario tenga el traceback en consola
        sys.stderr.write(f"\n🚨 CRASH CRÍTICO EN EL ARRANQUE:\n")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
