"""MPRIS2 MediaPlayer2.Player interface via dbus-python.

Runs in a background thread (dbus-python is synchronous/GLib-based, not
asyncio-friendly). The app calls `update()` from the UI thread; the thread
publishes the state on the D-Bus session bus.

If dbus-python isn't installed the module still imports cleanly — `start()`
returns None and the caller treats MPRIS as optional.

Exposes: PlaybackStatus, Metadata (title/artist/album/art), CanPlay/Pause/etc.
Does NOT implement transport control from external clients (play/pause via media
key widget) — that requires an event loop bridge; deferred for a future HU.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

MPRIS_AVAILABLE = True
try:
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
except Exception:
    MPRIS_AVAILABLE = False

if TYPE_CHECKING:
    from navitui.models import Song

BUS_NAME = "org.mpris.MediaPlayer2.theia-player"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
ROOT_IFACE = "org.mpris.MediaPlayer2"


class _MprisService(dbus.service.Object):  # type: ignore[misc]
    def __init__(self, bus: "dbus.SessionBus") -> None:
        bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
        super().__init__(bus_name, OBJECT_PATH)
        self._status = "Stopped"
        self._meta: dict = self._empty_meta()
        self._props = dbus.service.PropertiesInterface(self)

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
                "CanQuit": dbus.Boolean(False),
                "CanRaise": dbus.Boolean(False),
                "HasTrackList": dbus.Boolean(False),
                "Identity": dbus.String("theia-player"),
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
                "Position": dbus.Int64(0),
                "MinimumRate": dbus.Double(1.0),
                "MaximumRate": dbus.Double(1.0),
                "CanGoNext": dbus.Boolean(True),
                "CanGoPrevious": dbus.Boolean(True),
                "CanPlay": dbus.Boolean(True),
                "CanPause": dbus.Boolean(True),
                "CanSeek": dbus.Boolean(False),
                "CanControl": dbus.Boolean(False),
            }
        return {}

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv")
    def Set(self, iface: str, prop: str, value) -> None:
        pass

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, iface: str, changed: dict, invalidated: list) -> None:
        pass

    # ── player interface (no-op stubs) ────────────────────────────────
    @dbus.service.method(PLAYER_IFACE)
    def Play(self) -> None:
        pass

    @dbus.service.method(PLAYER_IFACE)
    def Pause(self) -> None:
        pass

    @dbus.service.method(PLAYER_IFACE)
    def PlayPause(self) -> None:
        pass

    @dbus.service.method(PLAYER_IFACE)
    def Stop(self) -> None:
        pass

    @dbus.service.method(PLAYER_IFACE)
    def Next(self) -> None:
        pass

    @dbus.service.method(PLAYER_IFACE)
    def Previous(self) -> None:
        pass

    # ── state updates (called from app thread via GLib.idle_add) ─────
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

    def _set_song(self, song: "Song | None", art_url: str = "") -> None:
        if song is None:
            self._meta = self._empty_meta()
        else:
            self._meta = {
                "mpris:trackid": dbus.ObjectPath(f"/org/mpris/MediaPlayer2/track/{song.id}"),
                "xesam:title": dbus.String(song.title),
                "xesam:artist": dbus.Array([song.artist], signature="s"),
                "xesam:album": dbus.String(song.album),
                "mpris:length": dbus.Int64(song.duration * 1_000_000),
            }
            if art_url:
                self._meta["mpris:artUrl"] = dbus.String(art_url)
        self.PropertiesChanged(PLAYER_IFACE, {"Metadata": dbus.Dictionary(self._meta, signature="sv")}, [])


class MprisController:
    """Thread-safe façade the app uses to push state changes."""

    def __init__(self) -> None:
        self._svc: _MprisService | None = None
        self._loop: "GLib.MainLoop | None" = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not MPRIS_AVAILABLE:
            return
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        self._svc = _MprisService(bus)
        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._loop.run, daemon=True)
        self._thread.start()

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
        status = "Playing" if playing else "Paused"
        GLib.idle_add(self._svc._set_status, status)

    def set_stopped(self) -> None:
        if self._svc is None:
            return
        GLib.idle_add(self._svc._set_status, "Stopped")


def create() -> MprisController:
    ctrl = MprisController()
    if MPRIS_AVAILABLE:
        try:
            ctrl.start()
        except Exception:
            pass  # no D-Bus session (headless, Wayland without XDG_RUNTIME_DIR, etc.)
    return ctrl
