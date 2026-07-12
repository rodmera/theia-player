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


def test_playqueue_add_songs():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A")]
    queue.set_songs(songs)

    new_songs = [make_test_song("2", "Song B"), make_test_song("3", "Song C")]
    queue.add(new_songs)

    assert len(queue.songs) == 3
    assert queue.songs[1] == new_songs[0]
    assert queue.songs[2] == new_songs[1]


def test_playqueue_add_next():
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


def test_playqueue_clear():
    queue = PlayQueue()
    songs = [make_test_song("1", "Song A")]
    queue.set_songs(songs)
    queue.clear()

    assert len(queue.songs) == 0
    assert queue.index == -1
    assert queue.current is None
