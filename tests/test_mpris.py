"""Tests for theiaplayer.mpris thread-init guard.

Verifies two things:

1. After the module is imported, ``_assert_threads_inited()`` is a no-op
   (i.e. the module-level ``dbus.mainloop.glib.threads_init()`` ran and
   set the ``_THREADS_INITED`` flag).

2. ``MprisController`` is safe to instantiate and call when dbus is
   unavailable (catches the ``NameError`` gotcha that used to break the
   import when dbus-python wasn't installed).
"""

from __future__ import annotations

import pytest

from theiaplayer import mpris


def test_threads_init_was_called_at_import():
    """Importing mpris must call dbus threads_init.

    If dbus-python is installed, the flag must be True; if not, the whole
    module goes into a no-op mode (``MPRIS_AVAILABLE = False``) and the
    guard becomes a no-op too. Either path is fine — what matters is that
    the flag and ``MPRIS_AVAILABLE`` are consistent.
    """
    if mpris.MPRIS_AVAILABLE:
        assert mpris._THREADS_INITED is True, (
            "dbus-python is installed but threads_init() was not called at import. "
            "This will deadlock the MPRIS background thread on launch."
        )
    assert mpris._assert_threads_inited() is None  # no-op, no exception


def test_assert_threads_inited_raises_when_flag_is_wrong(monkeypatch):
    """Force the regression scenario and verify the guard catches it."""
    if not mpris.MPRIS_AVAILABLE:
        pytest.skip("dbus-python not installed; cannot exercise the guard")
    monkeypatch.setattr(mpris, "_THREADS_INITED", False)
    with pytest.raises(RuntimeError, match="threads_init"):
        mpris._assert_threads_inited()
    # Restore for any subsequent tests.
    monkeypatch.setattr(mpris, "_THREADS_INITED", True)


def test_mpris_controller_safe_without_dbus():
    """MprisController must no-op gracefully when dbus is unavailable.

    This is the regression net for the ``_define_service()`` NameError
    gotcha documented in CLAUDE.md: if the service class is parsed at
    import time without a guard, the whole module fails to import on
    machines without dbus-python.
    """
    ctrl = mpris.MprisController()
    # All public methods must be safe to call regardless of MPRIS state.
    ctrl.start()
    ctrl.set_song(None, "")
    ctrl.set_playing(True)
    ctrl.set_stopped()
    ctrl.set_position(0.0)
    ctrl.stop()


def test_mpris_controller_runs_loop_in_background_thread():
    """When dbus IS available, start() spawns a daemon thread.

    We can't actually drive the GLib loop in a unit test (no session bus),
    but we can verify the thread is created and is a daemon so it never
    blocks process shutdown. If dbus isn't installed, start() must no-op
    cleanly and not spawn a thread at all.
    """
    ctrl = mpris.MprisController()
    before_threads = mpris.threading.active_count()
    ctrl.start()
    if mpris.MPRIS_AVAILABLE:
        # A new daemon thread should be alive (the loop target is _run_loop).
        assert ctrl._thread is not None
        assert ctrl._thread.daemon is True
        assert mpris.threading.active_count() >= before_threads
        ctrl.stop()
    else:
        # No thread, no service — graceful no-op.
        assert ctrl._thread is None