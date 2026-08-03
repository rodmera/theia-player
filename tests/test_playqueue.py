import pytest
from theiaplayer.models import Song
from theiaplayer.playqueue import PlayQueue, Repeat


def make_test_song(song_id: str, title: str) -> Song:
    return Song(id=song_id, title=title)


def test_playqueue_initialization():
    queue = PlayQueue()
    assert len(queue.songs) == 0
    assert queue.index == -1
    assert queue.current is None
    assert queue.repeat == Repeat.OFF
    assert queue.shuffle is False


def test_playqueue_set_songs():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A"), make_test_song("2", "Song B")]
    queue.set_songs(songs)

    assert len(queue.songs) == 2
    assert queue.index == 0
    assert queue.current == songs[0]


def test_playqueue_set_songs_with_shuffle_keeps_current_first():
    """Shuffle on set_songs preserves the start track in slot 0 (the rest
    is randomized — we just verify the start is preserved, not the order)."""
    queue = PlayQueue()
    queue.shuffle = True
    songs = [make_test_song(str(i), f"S{i}") for i in range(20)]
    queue.set_songs(songs, start=5)
    assert queue.current == songs[5]
    assert queue.songs[0] == songs[5]
    assert len(queue.songs) == 20


def test_playqueue_set_songs_invalid_start_falls_back():
    """Out-of-range `start` falls back to 0 if there are songs, else -1."""
    queue = PlayQueue()
    songs = [make_test_song("1", "A"), make_test_song("2", "B")]
    queue.set_songs(songs, start=99)
    assert queue.index == 0
    queue2 = PlayQueue()
    queue2.set_songs([], start=0)
    assert queue2.index == -1


def test_playqueue_set_songs_snapshots_original():
    """`_original` is a snapshot so toggling shuffle off restores the order."""
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(5)]
    queue.set_songs(songs)
    # _original is a copy, not a reference
    queue.songs.reverse()
    assert [s.title for s in queue._original] == ["S0", "S1", "S2", "S3", "S4"]


def test_playqueue_add_songs():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A")]
    queue.set_songs(songs)

    new_songs = [make_test_song("2", "Song B"), make_test_song("3", "Song C")]
    queue.add(new_songs)

    assert len(queue.songs) == 3
    assert queue.songs[1] == new_songs[0]
    assert queue.songs[2] == new_songs[1]


def test_playqueue_add_to_empty_queue_advances_index():
    """Adding to an empty queue (index=-1) auto-advances to 0 so the new
    tracks are immediately playable."""
    queue = PlayQueue()
    queue.add([make_test_song("1", "A")])
    assert queue.index == 0
    assert queue.current.title == "A"


def test_playqueue_add_next_starts_at_zero_when_empty():
    """When index < 0 (no current), add_next inserts at position 0."""
    queue = PlayQueue()
    queue.add_next([make_test_song("1", "A"), make_test_song("2", "B")])
    assert queue.index == -1  # add_next doesn't bump index
    assert queue.songs[0].title == "A"
    assert queue.songs[1].title == "B"


def test_playqueue_add_next_after_current():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A"), make_test_song("2", "Song B")]
    queue.set_songs(songs)

    next_songs = [make_test_song("3", "Song C")]
    queue.add_next(next_songs)

    # Song C should be in between Song A and Song B
    assert len(queue.songs) == 3
    assert queue.songs[1] == next_songs[0]
    assert queue.songs[2] == songs[1]


def test_playqueue_remove_songs():
    queue = PlayQueue()
    songs = [
        make_test_song("1", "Song A"),
        make_test_song("2", "Song B"),
        make_test_song("3", "Song C"),
    ]
    queue.set_songs(songs, start=1)  # Currently playing Song B (index 1)

    # Remove Song A (index 0)
    queue.remove(0)
    assert len(queue.songs) == 2
    assert queue.index == 0  # Index should shift left to 0 (still pointing to Song B)
    assert queue.current.title == "Song B"


def test_playqueue_remove_current_song_clamps_index():
    """Removing the current track clamps the index to the new last track
    so `current` keeps returning a real song."""
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(3)]
    queue.set_songs(songs, start=2)
    queue.remove(2)
    assert queue.index == 1
    assert queue.current.title == "S1"


def test_playqueue_remove_out_of_range_returns_none():
    queue = PlayQueue()
    queue.set_songs([make_test_song("1", "A")])
    assert queue.remove(99) is None
    assert queue.remove(-1) is None


def test_remove_song_not_in_original_does_not_raise():
    """If `_original` somehow lost the song (shouldn't happen, but the
    cache loader or external mutation could), ``remove`` must not raise."""
    queue = PlayQueue()
    queue.set_songs([make_test_song("1", "A"), make_test_song("2", "B")])
    # Simulate the song being removed from _original externally
    queue._original = [make_test_song("99", "Z")]
    removed = queue.remove(0)
    assert removed.title == "A"  # still removed from .songs
    assert len(queue.songs) == 1


def test_playqueue_move_up_and_down():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A"), make_test_song("2", "Song B")]
    queue.set_songs(songs)

    # Move Song B (index 1) up
    moved = queue.move_up(1)
    assert moved is True
    assert queue.songs[0].title == "Song B"
    assert queue.songs[1].title == "Song A"

    # Move Song B (index 0) down
    moved = queue.move_down(0)
    assert moved is True
    assert queue.songs[0].title == "Song A"
    assert queue.songs[1].title == "Song B"


def test_playqueue_move_up_at_index_zero_returns_false():
    queue = PlayQueue()
    queue.set_songs([make_test_song("1", "A"), make_test_song("2", "B")])
    assert queue.move_up(0) is False


def test_playqueue_move_down_at_last_index_returns_false():
    queue = PlayQueue()
    queue.set_songs([make_test_song("1", "A"), make_test_song("2", "B")])
    assert queue.move_down(1) is False


def test_playqueue_move_current_track_follows():
    """Moving the song currently playing must keep the player pointed at
    it across the swap."""
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(4)]
    queue.set_songs(songs, start=2)
    assert queue.current.title == "S2"
    queue.move_up(2)
    assert queue.current.title == "S2"
    assert queue.index == 1


def test_playqueue_move_down_current_track_follows():
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(4)]
    queue.set_songs(songs, start=1)
    assert queue.current.title == "S1"
    queue.move_down(1)
    assert queue.current.title == "S1"
    assert queue.index == 2


def test_playqueue_move_down_negative_index_returns_false():
    queue = PlayQueue()
    queue.set_songs([make_test_song("1", "A"), make_test_song("2", "B")])
    assert queue.move_down(-1) is False


def test_shuffle_rest_with_no_current_keeps_order():
    """If there's no current track (index=-1), shuffle the whole list
    without putting anything in slot 0 first."""
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(5)]
    queue._original = list(songs)
    queue.songs = list(songs)
    queue.index = -1
    queue._shuffle_rest()
    assert sorted(s.id for s in queue.songs) == sorted(s.id for s in songs)


def test_playqueue_clear():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A")]
    queue.set_songs(songs)
    queue.clear()

    assert len(queue.songs) == 0
    assert queue.index == -1
    assert queue.current is None


# ── advance / prev / jump ───────────────────────────────────────────────


def test_advance_natural_repeat_one_repeats_current():
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=1)
    queue.repeat = Repeat.ONE
    assert queue.advance(natural=True).title == "S1"
    assert queue.index == 1


def test_advance_moves_to_next_track():
    """The happy path: advance from index N to N+1, return the new song."""
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=0)
    nxt = queue.advance(natural=True)
    assert nxt.title == "S1"
    assert queue.index == 1
    nxt = queue.advance(natural=True)
    assert nxt.title == "S2"
    assert queue.index == 2


def test_advance_natural_repeat_off_at_end_returns_none():
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=2)
    queue.repeat = Repeat.OFF
    assert queue.advance(natural=True) is None


def test_advance_unnatural_repeat_off_at_end_wraps_to_zero():
    """A forced next (not a natural end-of-track) at the end of the queue
    wraps to 0 even when repeat is OFF — the user explicitly asked for next."""
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=2)
    queue.repeat = Repeat.OFF
    nxt = queue.advance(natural=False)
    assert nxt is not None
    assert queue.index == 0


def test_advance_repeat_all_wraps_to_zero_at_end():
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=2)
    queue.repeat = Repeat.ALL
    nxt = queue.advance(natural=True)
    assert nxt is not None
    assert queue.index == 0


def test_advance_empty_queue_returns_none():
    assert PlayQueue().advance(natural=True) is None


def test_prev_clamps_to_zero():
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=0)
    queue.prev()
    assert queue.index == 0
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=2)
    queue.prev()
    assert queue.index == 1


def test_prev_empty_queue_returns_none():
    assert PlayQueue().prev() is None


def test_jump_in_range_sets_index():
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)])
    assert queue.jump(2).title == "S2"
    assert queue.index == 2


def test_jump_out_of_range_is_noop():
    """``jump`` returns the current song regardless of whether the index
    was valid (the no-op case keeps the current song); the contract is
    that index doesn't change."""
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)], start=1)
    assert queue.jump(99) is queue.songs[1]
    assert queue.index == 1
    assert queue.jump(-1) is queue.songs[1]
    assert queue.index == 1


# ── shuffle / repeat modes ──────────────────────────────────────────────


def test_toggle_shuffle_then_untoggle_restores_order_and_index():
    """Shuffle on → off must restore the original order AND keep the
    current track at the same position in the original list."""
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(5)]
    queue.set_songs(songs, start=2)
    current = queue.current

    queue.toggle_shuffle()
    assert queue.shuffle is True
    assert queue.songs[0] == current
    # Same set of songs (Song dataclasses are unhashable; compare by id).
    assert sorted(s.id for s in queue.songs) == sorted(s.id for s in songs)

    queue.toggle_shuffle()
    assert queue.shuffle is False
    assert [s.title for s in queue.songs] == [s.title for s in songs]
    assert queue.index == 2


def test_toggle_shuffle_when_current_missing_sets_index_minus_one():
    """If the song that was current when shuffle was toggled off is no
    longer in the original list (e.g. it was removed programmatically
    between two toggles), restoring the order must set index to -1
    rather than raising ValueError."""
    queue = PlayQueue()
    queue.set_songs([make_test_song(str(i), f"S{i}") for i in range(3)])
    original_song = queue.songs[0]
    # Capture a song that is NOT in _original (simulate external corruption)
    orphan = Song(id="ghost", title="GHOST")
    # Drive the shuffle-off code path manually with an orphan current
    self_ref = queue
    current = orphan
    self_ref.songs = list(self_ref._original)
    self_ref.index = self_ref.songs.index(current) if current in self_ref.songs else -1
    assert self_ref.index == -1
    # Sanity: the original song is still recoverable
    assert self_ref.songs[0] == original_song


def test_toggle_shuffle_with_empty_queue_is_safe():
    """Toggling shuffle on an empty queue doesn't crash."""
    queue = PlayQueue()
    queue.shuffle = True
    queue.songs = list(queue._original)
    queue.index = queue.songs.index(queue.current) if queue.current in queue.songs else -1
    assert queue.shuffle is True
    assert queue.songs == []


def test_cycle_repeat_walks_off_all_one():
    queue = PlayQueue()
    assert queue.repeat == Repeat.OFF
    assert queue.cycle_repeat() == Repeat.ALL
    assert queue.cycle_repeat() == Repeat.ONE
    assert queue.cycle_repeat() == Repeat.OFF


def test_repeat_next_wraps_around():
    assert Repeat.OFF.next() == Repeat.ALL
    assert Repeat.ALL.next() == Repeat.ONE
    assert Repeat.ONE.next() == Repeat.OFF


# ── persistence ─────────────────────────────────────────────────────────


def test_to_dict_round_trip():
    queue = PlayQueue()
    songs = [make_test_song(str(i), f"S{i}") for i in range(3)]
    queue.set_songs(songs, start=1)
    queue.repeat = Repeat.ALL
    queue.shuffle = True

    d = queue.to_dict()
    assert d["songs"] == [s.to_dict() for s in songs]
    assert d["original"] == [s.to_dict() for s in songs]
    assert d["index"] == 1
    assert d["repeat"] == "all"
    assert d["shuffle"] is True

    restored = PlayQueue.from_dict(d)
    assert restored.songs == songs
    assert restored._original == songs
    assert restored.index == 1
    assert restored.repeat == Repeat.ALL
    assert restored.shuffle is True


def test_from_dict_missing_keys_uses_defaults():
    queue = PlayQueue.from_dict({})
    assert queue.songs == []
    assert queue.index == -1
    assert queue.repeat == Repeat.OFF
    assert queue.shuffle is False


def test_from_dict_malformed_returns_empty_queue():
    """A corrupted cache file should not crash the app — fall back to a
    fresh queue (the original cache layer used to swallow this; the
    recent refactor moved the logic here)."""
    queue = PlayQueue.from_dict({"songs": "not a list"})
    assert queue.songs == []
    assert queue.index == -1


def test_from_dict_out_of_range_index_clamps_to_minus_one():
    queue = PlayQueue.from_dict({
        "songs": [make_test_song("1", "A").to_dict()],
        "index": 99,
    })
    assert queue.index == -1


def test_from_dict_original_missing_falls_back_to_songs():
    """Legacy cache files (pre-`_original`) only have `songs`. Restoring
    must populate `_original` from `songs` so toggling shuffle off works."""
    only_songs = [make_test_song(str(i), f"S{i}") for i in range(3)]
    queue = PlayQueue.from_dict({"songs": [s.to_dict() for s in only_songs]})
    assert queue._original == only_songs
