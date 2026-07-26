import pytest
from unittest.mock import MagicMock
from theiaplayer.app import TheIAPlayerApp


def test_volume_quantization_multiples_of_five():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.player = MagicMock()
    app.query_one = MagicMock()
    app.dirs = MagicMock()

    # Case 1: volume is at 97 and user presses '+' (vol_up, delta=+5)
    app.player.volume = 97
    app.action_volume(5)
    app.player.set_volume.assert_called_with(100)

    # Case 2: volume is at 97 and user presses '-' (vol_down, delta=-5)
    app.player.volume = 97
    app.action_volume(-5)
    app.player.set_volume.assert_called_with(95)

    # Case 3: volume is at 95 and user presses '+' (vol_up, delta=+5)
    app.player.volume = 95
    app.action_volume(5)
    app.player.set_volume.assert_called_with(100)

    # Case 4: mouse click on volume bar at 0.97 fraction
    app.set_volume_fraction(0.97)
    app.player.set_volume.assert_called_with(95)

    # Case 5: mouse click on volume bar at 0.99 fraction
    app.set_volume_fraction(0.99)
    app.player.set_volume.assert_called_with(100)
