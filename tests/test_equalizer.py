import pytest
from theiaplayer.player import Player, NullPlayer, MPV_AVAILABLE, create_player


def test_null_player_equalizer_stubs():
    player = NullPlayer()
    # Verify calling set_equalizer does not throw exceptions on NullPlayer stubs
    player.set_equalizer([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    player.set_equalizer([])
    assert True


def test_real_player_equalizer_logic():
    if not MPV_AVAILABLE:
        pytest.skip("libmpv not installed; skipping real player EQ logic test")

    # Instantiate player with dummy callbacks
    player = Player(
        on_position=lambda p, d: None,
        on_track_end=lambda f: None,
    )
    
    try:
        # 1. Test Flat/Bypass (gains all 0.0 or empty)
        player.set_equalizer([])
        assert not player._m.af

        player.set_equalizer([0.0] * 10)
        assert not player._m.af

        # 2. Test Custom gains
        gains = [3.0, 2.0, 1.0, 0.0, -1.0, -2.0, -3.0, 1.0, 2.0, 3.0]
        player.set_equalizer(gains)
        
        # Verify the generated filter string on the mpv instance
        af_val = player._m.af
        assert len(af_val) == 1
        assert af_val[0]["name"] == "lavfi"
        
        graph_val = af_val[0]["params"]["graph"]
        assert "equalizer=f=31:" in graph_val
        assert "g=3.0" in graph_val
        assert "equalizer=f=16000:" in graph_val
        assert "g=3.0" in graph_val
        
        print("Success: Real player EQ lavfi filter strings verified on mpv.")
        
    finally:
        player.terminate()


def test_resolve_genre_preset_mappings():
    from theiaplayer.screens import resolve_genre_preset, PRESETS

    assert resolve_genre_preset("Rock / Alternative") == "rock"
    assert resolve_genre_preset("Heavy Metal") == "rock"
    assert resolve_genre_preset("Synth-Pop / Electronic") == "electronic"
    assert resolve_genre_preset("Bossa Nova / Jazz") == "jazz"
    assert resolve_genre_preset("Pop / Mainstream") == "pop"
    assert resolve_genre_preset("Modern Classical") == "classical"
    assert resolve_genre_preset("Folk / Acoustic") == "acoustic"
    assert resolve_genre_preset("Cabaret / Vocal") == "vocal"
    assert resolve_genre_preset("Hip Hop / Rap") == "bass"
    assert resolve_genre_preset(None) == "flat"
    assert resolve_genre_preset("Unknown Genre") == "flat"

    # All resolved presets must exist in PRESETS
    for g in ["Rock", "Electronic", "Jazz", "Pop", "Classical", "Acoustic", "Vocal", "Hip Hop", None]:
        preset_name = resolve_genre_preset(g)
        assert preset_name in PRESETS
        assert len(PRESETS[preset_name]) == 10
