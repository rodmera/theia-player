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
