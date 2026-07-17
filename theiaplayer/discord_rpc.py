"""Discord Rich Presence integration via pypresence.

Graceful no-op when pypresence isn't installed or Discord isn't running.
The controller is meant to be called from the main (UI) thread — each call
is a quick local IPC write to Discord's named pipe, well under 1ms.

To enable:
  1. Create an application at discord.com/developers/applications
  2. Set discord_rich_presence = true and discord_app_id = "<your id>"
     in ~/.config/theia-player/player.toml
"""

from __future__ import annotations

import time

DISCORD_AVAILABLE = True
try:
    from pypresence import Presence  # type: ignore[import-untyped]
except ImportError:
    DISCORD_AVAILABLE = False

class DiscordController:
    def __init__(self, app_id: str) -> None:
        self._app_id = app_id
        self._rpc = None
        self._connected = False
        self._last_update = 0.0

    def start(self) -> None:
        if not DISCORD_AVAILABLE or not self._app_id:
            return
        try:
            self._rpc = Presence(self._app_id)
            self._rpc.connect()
            self._connected = True
        except Exception:
            self._rpc = None
            self._connected = False

    def update(
        self,
        title: str,
        artist: str,
        album: str,
        art_url: str = "",
        position: float = 0.0,
        duration: float = 0.0,
    ) -> None:
        if not self._connected or self._rpc is None:
            return
        # Discord rate-limits to ~5 updates/15 s; enforce 3s minimum
        now = time.monotonic()
        if now - self._last_update < 3.0:
            return
        self._last_update = now
        try:
            state = f"{artist} — {album}" if artist and album else (artist or album)
            kwargs: dict = {
                "details": (title or "Unknown")[:128],
                "state": (state or "")[:128] or None,
                "large_image": art_url or "music",
                "large_text": (album or "")[:128] or None,
                "activity_type": 2,  # Listening
            }
            if duration > 0:
                start_ts = int(time.time() - position)
                kwargs["start"] = start_ts
                kwargs["end"] = start_ts + int(duration)
            self._rpc.update(**kwargs)
        except Exception:
            self._connected = False

    def clear(self) -> None:
        if not self._connected or self._rpc is None:
            return
        try:
            self._rpc.clear()
        except Exception:
            pass

    def stop(self) -> None:
        self.clear()
        if self._rpc is not None:
            try:
                self._rpc.close()
            except Exception:
                pass
        self._rpc = None
        self._connected = False

def create(app_id: str, enabled: bool = True) -> DiscordController:
    ctrl = DiscordController(app_id)
    if enabled and DISCORD_AVAILABLE and app_id:
        try:
            ctrl.start()
        except Exception:
            pass
    return ctrl
