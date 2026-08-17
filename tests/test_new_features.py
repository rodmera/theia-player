from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from theiaplayer.screens import SleepTimerModal, ListeningStatsModal
from theiaplayer.anim import VizModel, VIZ_STYLES
from theiaplayer.models import Song
from theiaplayer.ipc import IpcServer


def test_sleep_timer_modal_initialization():
    modal = SleepTimerModal(current_mode="30m", time_left_s=1790.0)
    assert modal._current_mode == "30m"
    assert modal._time_left_s == 1790.0


def test_visualizer_styles_cycle():
    viz = VizModel(bars=5, style="bars")
    assert viz.style == "bars"
    assert "bars" in VIZ_STYLES

    for expected in ["led", "braille", "wave", "peak", "bars"]:
        new_style = viz.cycle_style()
        assert new_style == expected

    # Test rendering under each style
    for style in VIZ_STYLES:
        viz.set_style(style)
        viz.energy = 1.0
        viz.tick()
        rendered = viz.render()
        assert len(rendered.plain) == 5


def test_listening_stats_modal_content():
    stats_data = {
        "total_songs": 4920,
        "total_albums": 463,
        "audio_device": "DAC USB (hw:0,0)",
        "audio_quality": "FLAC Lossless (24/96k)",
        "top_artists": [
            {"name": "Steely Dan", "plays": 120},
            {"name": "Depeche Mode", "plays": 95},
        ],
        "top_albums": [
            {"name": "Aja", "artist": "Steely Dan", "plays": 45},
        ]
    }
    modal = ListeningStatsModal(stats_data)
    content = modal._build_content().plain
    assert "4,920" in content
    assert "463" in content
    assert "Steely Dan" in content
    assert "Depeche Mode" in content
    assert "Aja" in content


@pytest.mark.asyncio
async def test_ipc_command_dispatch():
    app = MagicMock()
    app.queue = MagicMock()
    app.queue.current = Song(id="s1", title="Aja", artist="Steely Dan", album="Aja", duration=480)
    app.player = MagicMock()
    app.player.active = True
    app.player.paused = False
    app.player.position = 120.5
    app.player.volume = 85
    app.view = "home"

    server = IpcServer(app)

    # Test status
    status = await server._dispatch_command("status", [])
    assert status["status"] == "playing"
    assert status["title"] == "Aja"
    assert status["artist"] == "Steely Dan"
    assert status["volume"] == 85

    # Test play_pause
    res_pp = await server._dispatch_command("play-pause", [])
    assert res_pp["status"] == "ok"
    app.action_play_pause.assert_called_once()

    # Test next
    res_next = await server._dispatch_command("next", [])
    assert res_next["status"] == "ok"
    app.action_next_track.assert_called_once()
