"""Playback engine — a thin, thread-aware wrapper around libmpv.

mpv does the heavy lifting (HTTP streaming, every codec, seeking, volume);
we observe `time-pos`/`duration` and the `end-file` event. mpv fires those
callbacks on its own event thread, so the app schedules UI work with
`loop.call_soon_threadsafe` (never a blocking call — that deadlocks against
`terminate()`); this module never touches the UI.

If libmpv isn't installed the app still runs (browse, search, queue); it
just tells you how to get sound on your OS.
"""

from __future__ import annotations

from typing import Callable

MPV_AVAILABLE = True
MPV_ERROR = ""
try:
    import mpv as _mpv
except (ImportError, OSError, AttributeError) as e:  # missing libmpv shows as OSError
    MPV_AVAILABLE = False
    MPV_ERROR = str(e)

INSTALL_HINTS = (
    "libmpv not found — install mpv for playback:\n"
    "  arch:    sudo pacman -S mpv\n"
    "  debian:  sudo apt install libmpv2\n"
    "  macos:   brew install mpv\n"
    "  windows: place libmpv-2.dll on PATH (mpv.io/installation)"
)

class Player:
    """One mpv instance for the life of the app.

    Callbacks (all fired from mpv's event thread):
      on_position(pos_seconds, duration_seconds)
      on_track_end(failed: bool)   natural EOF or a stream error
    """

    def __init__(
        self,
        on_position: Callable[[float, float], None],
        on_track_end: Callable[[bool], None],
        ao: str | None = None,
        replaygain: str = "album",
        gapless: str = "yes",
        replaygain_preamp: float = 0.0,
        replaygain_fallback: float = -6.0,
        audio_exclusive: bool = False,
    ) -> None:
        self._on_position = on_position
        self._on_track_end = on_track_end
        self.position = 0.0
        self.duration = 0.0
        self._want_playing = False
        self._closing = False
        self._last_forwarded = -1.0

        opts: dict = dict(
            video=False,
            terminal=False,
            idle=True,
            audio_client_name="theia-player",
            replaygain=replaygain,
            gapless_audio=gapless,
            replaygain_preamp=replaygain_preamp,
            replaygain_fallback=replaygain_fallback,
            audio_exclusive=audio_exclusive,
            pipewire_buffer=150,
        )
        if ao:
            opts["ao"] = ao
        self._m = _mpv.MPV(**opts)

        @self._m.property_observer("time-pos")
        def _time(_name, value) -> None:
            if value is None or self._closing:
                return
            self.position = float(value)
            # mpv fires this many times a second; only cross into the UI
            # thread on ~quarter-second boundaries
            if abs(self.position - self._last_forwarded) >= 0.25:
                self._last_forwarded = self.position
                self._on_position(self.position, self.duration)

        @self._m.property_observer("duration")
        def _dur(_name, value) -> None:
            if value is not None and not self._closing:
                self.duration = float(value)

        @self._m.event_callback("end-file")
        def _end(event) -> None:
            data = getattr(event, "data", None)
            reason = getattr(data, "reason", None)
            if not self._want_playing or self._closing:
                return  # we stopped/replaced it ourselves
            if reason == _mpv.MpvEventEndFile.EOF:
                self._want_playing = False
                self._on_track_end(False)
            elif reason == _mpv.MpvEventEndFile.ERROR:
                self._want_playing = False
                self._on_track_end(True)

    # ── transport ─────────────────────────────────────────────────────
    def play(self, url: str, start: float = 0.0) -> None:
        self._want_playing = False  # swallow the end-file of whatever was on
        self.position = start
        self.duration = 0.0
        self._last_forwarded = -1.0
        if start > 0:
            self._m.loadfile(url, start=str(start))
        else:
            self._m.loadfile(url)
        self._m.pause = False
        self._want_playing = True

    def stop(self) -> None:
        self._want_playing = False
        self._m.command("stop")
        self.position = 0.0
        self.duration = 0.0

    @property
    def paused(self) -> bool:
        return bool(self._m.pause)

    def set_paused(self, paused: bool) -> None:
        self._m.pause = paused

    def toggle_pause(self) -> None:
        self._m.pause = not self._m.pause

    @property
    def active(self) -> bool:
        """A track is loaded (playing or paused)."""
        return self._want_playing

    def seek(self, seconds: float) -> None:
        if not self._want_playing:
            return
        try:
            self._m.seek(seconds, reference="relative")
        except SystemError:
            pass  # seeking before the stream is ready

    def seek_to(self, fraction: float) -> None:
        if not self._want_playing or self.duration <= 0:
            return
        try:
            self._m.seek(max(0.0, min(fraction, 0.99)) * self.duration, reference="absolute")
        except SystemError:
            pass

    # ── volume ────────────────────────────────────────────────────────
    @property
    def volume(self) -> int:
        try:
            return int(self._m.volume or 0)
        except Exception:
            return 0

    def set_volume(self, value: int) -> int:
        value = max(0, min(130, value))
        self._m.volume = value
        return value

    @property
    def muted(self) -> bool:
        return bool(self._m.mute)

    def toggle_mute(self) -> bool:
        self._m.mute = not self._m.mute
        return bool(self._m.mute)

    def get_audio_devices(self) -> list[dict]:
        try:
            raw_devices = self._m.audio_device_list or []
            filtered = []
            seen_descs = set()
            for d in raw_devices:
                name = d.get("name", "")
                desc = d.get("description", "")
                if name.startswith("alsa/") and not any(name.startswith(p) for p in ["alsa/hw:", "alsa/plughw:"]):
                    continue
                if any(name.startswith(p) for p in ["auto", "pipewire", "pulse", "coreaudio", "wasapi", "alsa"]):
                    if desc not in seen_descs:
                        seen_descs.add(desc)
                        filtered.append(d)
            return filtered if filtered else raw_devices
        except Exception:
            return []

    def set_audio_device(self, name: str) -> None:
        try:
            # Smart-normalize the device prefix to match the active Audio Output (ao) driver.
            # e.g., if we are running on 'pulse' but the device name is 'pipewire/bluez_output...',
            # we translate it to 'pulse/bluez_output...' so mpv can resolve it.
            ao = self._m.ao
            if isinstance(ao, list) and ao:
                ao = ao[0].get("name")
            if not isinstance(ao, str):
                ao = "pulse"
            if "/" in name:
                current_prefix, device_id = name.split("/", 1)
                if current_prefix != ao and ao in ("pulse", "pipewire", "alsa"):
                    name = f"{ao}/{device_id}"
            self._m.audio_device = name
        except Exception:
            pass

    def get_current_audio_device(self) -> str:
        try:
            return self._m.audio_device or "auto"
        except Exception:
            return "auto"

    def set_equalizer(self, gains: list[float]) -> None:
        """gains is a list of 10 float values for the 10 EQ bands (31Hz to 16kHz)."""
        if not gains or all(g == 0.0 for g in gains):
            try:
                self._m.af = ""
            except Exception:
                pass
            return
        
        freqs = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        filters = []
        for i, g in enumerate(gains[:10]):
            f = freqs[i]
            # equalizer=f=<freq>:t=q:w=1.0:g=<gain>
            filters.append(f"equalizer=f={f}:t=q:w=1.0:g={g}")
        
        af_string = f"lavfi=[{','.join(filters)}]"
        try:
            self._m.af = af_string
        except Exception:
            pass

    def terminate(self) -> None:
        self._closing = True  # observers go quiet before the core dies
        self._want_playing = False
        try:
            self._m.terminate()
        except Exception:
            pass

class NullPlayer:
    """Stands in when libmpv is missing so the rest of the app still works."""

    position = 0.0
    duration = 0.0
    paused = True
    active = False
    volume = 100
    muted = False

    def __init__(self, *a, **kw) -> None:
        pass

    def play(self, url: str, start: float = 0.0) -> None:
        pass

    def stop(self) -> None:
        pass

    def set_paused(self, paused: bool) -> None:
        pass

    def toggle_pause(self) -> None:
        pass

    def seek(self, seconds: float) -> None:
        pass

    def seek_to(self, fraction: float) -> None:
        pass

    def set_volume(self, value: int) -> int:
        return value

    def toggle_mute(self) -> bool:
        return False

    def get_audio_devices(self) -> list[dict]:
        return []

    def set_audio_device(self, name: str) -> None:
        pass

    def set_equalizer(self, gains: list[float]) -> None:
        pass

    def get_current_audio_device(self) -> str:
        return "auto"

    def terminate(self) -> None:
        pass

def create_player(
    on_position,
    on_track_end,
    ao: str | None = None,
    replaygain: str = "album",
    gapless: str = "yes",
    replaygain_preamp: float = 0.0,
    replaygain_fallback: float = -6.0,
    audio_exclusive: bool = False,
):
    if not MPV_AVAILABLE:
        return NullPlayer()
        
    ao = choose_audio_driver(ao)

    return Player(
        on_position,
        on_track_end,
        ao=ao,
        replaygain=replaygain,
        gapless=gapless,
        replaygain_preamp=replaygain_preamp,
        replaygain_fallback=replaygain_fallback,
        audio_exclusive=audio_exclusive,
    )

def choose_audio_driver(ao: str | None, platform: str | None = None) -> str | None:
    """Pick the mpv ``--ao`` driver to use, given an explicit override.

    On Linux, defaults to ``"pipewire"`` — the native pipewire driver
    supports direct device targeting (so ``ctrl+d`` can address a specific
    sink) and runs Bluetooth streams reliably with the 150ms buffer set in
    :class:`Player`. Was previously ``"pulse"`` (see commit ``0a12bbd`` for
    the revert); kept as a named function so flipping the default is a
    one-line change and is unit-testable.

    On macOS, leaves the value ``None`` so mpv falls back to its native
    CoreAudio backend. An explicit ``ao`` value always wins.
    """
    if ao is not None:
        return ao
    if platform is None:
        import sys
        platform = sys.platform
    if platform == "darwin":
        return None
    return "pipewire"
