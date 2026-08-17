"""Unix Domain Socket IPC server & client for remote CLI control of theia-player."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from theiaplayer.app import TheIAPlayerApp

SOCKET_PATH = Path(f"/tmp/theia-player-{os.getuid()}.sock")


def send_ipc_command(cmd: str, *args: str) -> dict | None:
    """Send a command to a running theia-player instance via Unix socket.
    Returns response dict on success, or None if no instance is listening.
    """
    if not SOCKET_PATH.exists():
        return None

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1.5)
        client.connect(str(SOCKET_PATH))
        payload = json.dumps({"command": cmd, "args": list(args)})
        client.sendall(payload.encode("utf-8") + b"\n")

        data = b""
        while True:
            chunk = client.recv(4096)
            if not chunk or b"\n" in chunk:
                data += chunk
                break
            data += chunk

        client.close()
        if data:
            return json.loads(data.decode("utf-8").strip())
        return {"status": "ok"}
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
        try:
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    except Exception:
        return None


class IpcServer:
    """Asyncio Unix Domain Socket server embedded into TheIAPlayerApp."""

    def __init__(self, app: "TheIAPlayerApp") -> None:
        self.app = app
        self._server: asyncio.Server | None = None
        self._running = False

    async def start(self) -> None:
        try:
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink(missing_ok=True)
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                path=str(SOCKET_PATH),
            )
            self._running = True
        except Exception:
            self._server = None

    async def stop(self) -> None:
        self._running = False
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        try:
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if not line:
                writer.close()
                return

            req = json.loads(line.decode("utf-8").strip())
            cmd = req.get("command", "").lower().strip()
            args = req.get("args", [])

            resp = await self._dispatch_command(cmd, args)
            writer.write(json.dumps(resp).encode("utf-8") + b"\n")
            await writer.drain()
        except Exception as e:
            try:
                writer.write(json.dumps({"status": "error", "error": str(e)}).encode("utf-8") + b"\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch_command(self, cmd: str, args: list) -> dict:
        app = self.app
        if cmd in ("play", "resume"):
            app.action_play()
            return {"status": "ok", "action": "play"}
        elif cmd == "pause":
            app.action_pause()
            return {"status": "ok", "action": "pause"}
        elif cmd in ("play-pause", "playpause", "toggle"):
            app.action_play_pause()
            return {"status": "ok", "action": "play_pause"}
        elif cmd in ("next", "skip"):
            app.action_next_track()
            return {"status": "ok", "action": "next"}
        elif cmd in ("prev", "previous", "back"):
            app.action_prev_track()
            return {"status": "ok", "action": "prev"}
        elif cmd == "stop":
            app.action_stop()
            return {"status": "ok", "action": "stop"}
        elif cmd == "mute":
            app.action_mute()
            return {"status": "ok", "action": "mute"}
        elif cmd in ("vol", "volume"):
            if args:
                val_str = str(args[0]).strip()
                if val_str.startswith("+"):
                    delta = int(val_str[1:])
                    app.action_volume(delta)
                elif val_str.startswith("-"):
                    delta = -int(val_str[1:])
                    app.action_volume(delta)
                else:
                    target = int(val_str)
                    if app.player:
                        app.player.set_volume(target)
                        app._persist_volume(target)
            vol = app.player.volume if app.player else 0
            return {"status": "ok", "volume": vol}
        elif cmd == "status":
            song = app.queue.current
            is_playing = bool(app.player and app.player.active and not app.player.paused)
            is_paused = bool(app.player and app.player.active and app.player.paused)
            status_text = "playing" if is_playing else ("paused" if is_paused else "stopped")
            return {
                "status": status_text,
                "title": song.title if song else "",
                "artist": song.artist if song else "",
                "album": song.album if song else "",
                "duration": song.duration if song else 0,
                "position": round(app.player.position if app.player else 0.0, 1),
                "volume": app.player.volume if app.player else 0,
                "view": app.view,
            }
        else:
            return {"status": "error", "error": f"Unknown command: {cmd}"}
