"""MPRIS2 MediaPlayer2.Player interface via dbus-python.


Runs in a background thread (dbus-python is synchronous/GLib-based, not
asyncio-friendly). The app calls `update()` from the UI thread; the thread
publishes the state on the D-Bus session bus.

If dbus-python isn't installed the module still imports cleanly — `create()`
returns a no-op MprisController and the caller treats MPRIS as optional.

Exposes: PlaybackStatus, Metadata (title/artist/album/art), CanPlay/Pause/etc.
Implements: Full transport control from external clients (play, pause, play-pause, next, previous)
via an asynchronous threadsafe event-loop bridge to the main Textual app.
"""

# pyright: reportMissingImports=false, reportUndefinedVariable=false, reportOptionalMemberAccess=false, reportOptionalIterable=false, reportOptionalOperand=false, reportTypedDictNotRequiredAccess=false, reportMissingTypeStubs=false, reportArgumentType=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportAttributeAccessIssue=false


from __future__ import annotations

import threading
from typing import TYPE_CHECKING

MPRIS_AVAILABLE = True
# Tracks whether ``dbus.mainloop.glib.threads_init()`` was actually called
# during the import below. Used by ``_assert_threads_inited`` to fail fast
# (instead of silently deadlocking) if a future refactor drops the call.
_THREADS_INITED = False
try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    # Habilitar soporte multihilo nativo en D-Bus/GLib de forma obligatoria
    dbus.mainloop.glib.threads_init()
    _THREADS_INITED = True
except Exception:
    MPRIS_AVAILABLE = False


def _assert_threads_inited() -> None:
    """Raise if dbus-python was imported but ``threads_init()`` wasn't called.

    dbus-python REQUIRES ``dbus.mainloop.glib.threads_init()`` in the main
    thread before any ``dbus.SessionBus()`` is instantiated from a secondary
    Python thread. Without it the GLib loop deadlocks on startup and the app
    hangs in black on launch. This guard turns that silent freeze into an
    actionable error if a future refactor drops the module-level call.
    """
    if MPRIS_AVAILABLE and not _THREADS_INITED:
        raise RuntimeError(
            "dbus.mainloop.glib.threads_init() was not called during theiaplayer.mpris import. "
            "Without it, the MPRIS background thread deadlocks on startup. "
            "This is a regression — see CLAUDE.md 'Hilos en dbus-python' gotcha."
        )

if TYPE_CHECKING:
    from theiaplayer.models import Song

BUS_NAME = "org.mpris.MediaPlayer2.theia-player"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
ROOT_IFACE = "org.mpris.MediaPlayer2"


def _define_service(callbacks: dict | None = None):
    """Define _MprisService only when dbus is available — avoids NameError at class parse time."""

    class _MprisService(dbus.service.Object):  # type: ignore[misc]
        def __init__(self, bus) -> None:
            bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
            super().__init__(bus_name, OBJECT_PATH)
            self._status = "Stopped"
            self._position = 0
            self._meta: dict = self._empty_meta()
            self._callbacks = callbacks or {}

        # ── root interface ────────────────────────────────────────────────
        @dbus.service.method(ROOT_IFACE)
        def Raise(self) -> None:
            pass

        @dbus.service.method(ROOT_IFACE)
        def Quit(self) -> None:
            pass

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
        def Get(self, iface: str, prop: str):
            return self.GetAll(iface)[prop]

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface: str) -> dict:
            if iface == ROOT_IFACE:
                return {
                    "CanQuit": dbus.Boolean(True),
                    "CanRaise": dbus.Boolean(False),
                    "HasTrackList": dbus.Boolean(False),
                    "Identity": dbus.String("TheIA Player"),
                    "DesktopEntry": dbus.String("theia-player"),
                    "SupportedUriSchemes": dbus.Array([], signature="s"),
                    "SupportedMimeTypes": dbus.Array([], signature="s"),
                }
            if iface == PLAYER_IFACE:
                return {
                    "PlaybackStatus": dbus.String(self._status),
                    "LoopStatus": dbus.String("None"),
                    "Rate": dbus.Double(1.0),
                    "Shuffle": dbus.Boolean(False),
                    "Metadata": dbus.Dictionary(self._meta, signature="sv"),
                    "Volume": dbus.Double(1.0),
                    "Position": dbus.Int64(self._position),
                    "MinimumRate": dbus.Double(1.0),
                    "MaximumRate": dbus.Double(1.0),
                    "CanGoNext": dbus.Boolean(True),
                    "CanGoPrevious": dbus.Boolean(True),
                    "CanPlay": dbus.Boolean(True),
                    "CanPause": dbus.Boolean(True),
                    "CanSeek": dbus.Boolean(False),
                    "CanControl": dbus.Boolean(True),
                }
            return {}

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv")
        def Set(self, iface: str, prop: str, value) -> None:
            pass

        @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
        def PropertiesChanged(self, iface: str, changed: dict, invalidated: list) -> None:
            pass

        # ── player interface (callbacks implemented) ──────────────────────
        @dbus.service.method(PLAYER_IFACE)
        def Play(self) -> None:
            if "play" in self._callbacks:
                self._callbacks["play"]()

        @dbus.service.method(PLAYER_IFACE)
        def Pause(self) -> None:
            if "pause" in self._callbacks:
                self._callbacks["pause"]()

        @dbus.service.method(PLAYER_IFACE)
        def PlayPause(self) -> None:
            if "play_pause" in self._callbacks:
                self._callbacks["play_pause"]()

        @dbus.service.method(PLAYER_IFACE)
        def Stop(self) -> None:
            if "stop" in self._callbacks:
                self._callbacks["stop"]()

        @dbus.service.method(PLAYER_IFACE)
        def Next(self) -> None:
            if "next" in self._callbacks:
                self._callbacks["next"]()

        @dbus.service.method(PLAYER_IFACE)
        def Previous(self) -> None:
            if "prev" in self._callbacks:
                self._callbacks["prev"]()

        # ── state updates (called via GLib.idle_add) ──────────────────────
        def _empty_meta(self) -> dict:
            return {
                "mpris:trackid": dbus.ObjectPath("/org/mpris/MediaPlayer2/TrackList/NoTrack"),
                "xesam:title": dbus.String(""),
                "xesam:artist": dbus.Array([], signature="s"),
                "xesam:album": dbus.String(""),
            }

        def _set_status(self, status: str) -> None:
            self._status = status
            self.PropertiesChanged(PLAYER_IFACE, {"PlaybackStatus": dbus.String(status)}, [])

        def _set_position(self, microsec: int) -> None:
            self._position = microsec
            self.PropertiesChanged(PLAYER_IFACE, {"Position": dbus.Int64(microsec)}, [])

        def _set_song(self, song: "Song | None", art_url: str = "") -> None:
            if song is None:
                self._meta = self._empty_meta()
            else:
                self._meta = {
                    "mpris:trackid": dbus.ObjectPath(f"/org/mpris/MediaPlayer2/track/{song.id}"),
                    "xesam:title": dbus.String(song.title),
                    "xesam:artist": dbus.Array([song.artist], signature="s"),
                    "xesam:album": dbus.String(song.album),
                    "xesam:albumArtist": dbus.Array([song.artist], signature="s"),
                    "mpris:length": dbus.Int64(song.duration * 1_000_000),
                    "xesam:userRating": dbus.Double(float(song.rating or 0) / 5.0),
                }
                if art_url:
                    self._meta["mpris:artUrl"] = dbus.String(art_url)
            self.PropertiesChanged(PLAYER_IFACE, {"Metadata": dbus.Dictionary(self._meta, signature="sv")}, [])

    return _MprisService


class MprisController:
    """Thread-safe façade the app uses to push state changes.

    All public methods are safe to call whether or not dbus is available —
    they silently no-op when MPRIS_AVAILABLE is False.
    """

    def __init__(self, callbacks: dict | None = None) -> None:
        self._svc = None
        self._loop = None
        self._thread: threading.Thread | None = None
        self._callbacks = callbacks or {}

    def start(self) -> None:
        if not MPRIS_AVAILABLE:
            return
        # Lanzar la inicialización y el loop de D-Bus de forma asíncrona en un hilo de fondo
        # Esto independiza por completo el arranque del hilo principal de Textual, eliminando todo riesgo de congelamientos.
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        try:
            _assert_threads_inited()
            DBusGMainLoop(set_as_default=True)
            bus = dbus.SessionBus()
            MprisService = _define_service(self._callbacks)
            self._svc = MprisService(bus)
            self._loop = GLib.MainLoop()
            self._loop.run()
        except Exception:
            self._svc = None
            self._loop = None

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()

    def set_song(self, song: "Song | None", art_path: str = "") -> None:
        if self._svc is None:
            return
        art_url = f"file://{art_path}" if art_path else ""
        GLib.idle_add(self._svc._set_song, song, art_url)

    def set_playing(self, playing: bool) -> None:
        if self._svc is None:
            return
        GLib.idle_add(self._svc._set_status, "Playing" if playing else "Paused")

    def set_stopped(self) -> None:
        if self._svc is None:
            return
        GLib.idle_add(self._svc._set_status, "Stopped")

    def set_position(self, seconds: float) -> None:
        if self._svc is None:
            return
        microsec = int(seconds * 1_000_000)
        GLib.idle_add(self._svc._set_position, microsec)


def create(callbacks: dict | None = None) -> MprisController:
    ctrl = MprisController(callbacks)
    if MPRIS_AVAILABLE:
        try:
            ctrl.start()
        except Exception:
            pass  # no D-Bus session (headless, Wayland without XDG_RUNTIME_DIR, etc.)
    return ctrl
