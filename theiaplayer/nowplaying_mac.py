"""macOS NowPlaying and RemoteCommand integration via PyObjC.

Runs the Cocoa NSRunLoop in a background thread to receive media key events
asynchronously, bridging them safely to the main Textual app thread via
the event loop.

If pyobjc isn't installed or we are not on macOS, this module gracefully
degrades to a no-op façade, making it safe to import anywhere.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from theiaplayer.models import Song

MAC_MEDIA_AVAILABLE = False
# MediaPlayer framework is exclusive to macOS
if sys.platform == "darwin":
    try:
        import objc
        from Foundation import NSDictionary, NSDate, NSRunLoop
        from AppKit import NSImage
        from MediaPlayer import (
            MPNowPlayingInfoCenter,
            MPRemoteCommandCenter,
            MPNowPlayingPlaybackStatePlaying,
            MPNowPlayingPlaybackStatePaused,
            MPNowPlayingPlaybackStateStopped,
            MPRemoteCommandHandlerStatusSuccess,
        )
        MAC_MEDIA_AVAILABLE = True
    except Exception:
        MAC_MEDIA_AVAILABLE = False


class MacMediaController:
    """Thread-safe façade for macOS media controls.

    Silently no-ops if PyObjC is unavailable or we're on a non-Mac platform.
    """

    def __init__(self, callbacks: dict | None = None) -> None:
        self._callbacks = callbacks or {}
        self._thread: threading.Thread | None = None
        self._running = False
        self._info_center = None
        self._command_center = None

    def start(self) -> None:
        if not MAC_MEDIA_AVAILABLE:
            return
        
        self._running = True
        # Run Cocoa event-dispatching loop in a dedicated background daemon thread
        # This isolates macOS UI overhead from the main terminal TUI loop.
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        try:
            self._info_center = MPNowPlayingInfoCenter.defaultActiveInfoCenter()
            self._command_center = MPRemoteCommandCenter.sharedCommandCenter()
            self._register_commands()
            
            # Keep the current thread's NSRunLoop alive to receive MPRemoteCommandCenter callbacks
            run_loop = NSRunLoop.currentRunLoop()
            while self._running:
                run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        except Exception:
            self._info_center = None
            self._command_center = None

    def _register_commands(self) -> None:
        if self._command_center is None:
            return
            
        cc = self._command_center
        
        # Helper wrapper to map Objective-C target-action delegates to Python callbacks
        # Using native MPRemoteCommandHandlerStatusSuccess status code
        def handle_play(event):
            if "play" in self._callbacks:
                self._callbacks["play"]()
            return MPRemoteCommandHandlerStatusSuccess

        def handle_pause(event):
            if "pause" in self._callbacks:
                self._callbacks["pause"]()
            return MPRemoteCommandHandlerStatusSuccess

        def handle_play_pause(event):
            if "play_pause" in self._callbacks:
                self._callbacks["play_pause"]()
            return MPRemoteCommandHandlerStatusSuccess

        def handle_next(event):
            if "next" in self._callbacks:
                self._callbacks["next"]()
            return MPRemoteCommandHandlerStatusSuccess

        def handle_prev(event):
            if "prev" in self._callbacks:
                self._callbacks["prev"]()
            return MPRemoteCommandHandlerStatusSuccess

        # Register targets using PyObjC API wrappers
        cc.playCommand().addTargetWithHandler_(handle_play)
        cc.pauseCommand().addTargetWithHandler_(handle_pause)
        cc.togglePlayPauseCommand().addTargetWithHandler_(handle_play_pause)
        cc.nextTrackCommand().addTargetWithHandler_(handle_next)
        cc.previousTrackCommand().addTargetWithHandler_(handle_prev)

    def stop(self) -> None:
        self._running = False
        if self._command_center is not None:
            try:
                # Remove targets to prevent system resource leaks
                self._command_center.playCommand().removeTarget_(None)
                self._command_center.pauseCommand().removeTarget_(None)
                self._command_center.togglePlayPauseCommand().removeTarget_(None)
                self._command_center.nextTrackCommand().removeTarget_(None)
                self._command_center.previousTrackCommand().removeTarget_(None)
            except Exception:
                pass
        self.set_stopped()

    def set_song(self, song: Song | None, art_path: str = "") -> None:
        if not MAC_MEDIA_AVAILABLE or self._info_center is None:
            return
            
        if song is None:
            self._info_center.setNowPlayingInfo_(None)
            return

        # standard MediaPlayer metadata keys
        info = {
            "title": song.title,
            "artist": song.artist,
            "albumTitle": song.album,
            "playbackDuration": float(song.duration),
        }

        # Load cover art into Cocoa natively if available on disk
        if art_path and os.path.exists(art_path):
            try:
                image = NSImage.alloc().initWithContentsOfFile_(art_path)
                if image:
                    # In macOS, MPMediaItemArtwork is represented as MPNowPlayingInfoCenter's artwork property
                    # which accepts an NSImage directly in standard PyObjC MediaPlayer wrappers
                    info["artwork"] = image
            except Exception:
                pass

        # Update macOS NowPlaying panel dictionary
        self._info_center.setNowPlayingInfo_(NSDictionary.dictionaryWithDictionary_(info))

    def set_playing(self, playing: bool) -> None:
        if not MAC_MEDIA_AVAILABLE or self._info_center is None:
            return
        state = MPNowPlayingPlaybackStatePlaying if playing else MPNowPlayingPlaybackStatePaused
        self._info_center.setPlaybackState_(state)

    def set_stopped(self) -> None:
        if not MAC_MEDIA_AVAILABLE or self._info_center is None:
            return
        self._info_center.setPlaybackState_(MPNowPlayingPlaybackStateStopped)

    def set_position(self, seconds: float) -> None:
        if not MAC_MEDIA_AVAILABLE or self._info_center is None:
            return
            
        # Sincronizar el progreso actual actualizando el diccionario de NowPlayingInfo
        # agregando la clave de progreso 'elapsed'
        info = self._info_center.nowPlayingInfo()
        if info:
            try:
                mutable_info = dict(info)
                mutable_info["elapsedPlaybackTime"] = float(seconds)
                self._info_center.setNowPlayingInfo_(NSDictionary.dictionaryWithDictionary_(mutable_info))
            except Exception:
                pass


def create(callbacks: dict | None = None) -> MacMediaController:
    ctrl = MacMediaController(callbacks)
    if MAC_MEDIA_AVAILABLE:
        try:
            ctrl.start()
        except Exception:
            pass
    return ctrl
