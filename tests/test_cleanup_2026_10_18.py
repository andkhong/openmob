"""Small bugs found in the 2026-10-18 cleanup, each with its regression test."""

import asyncio
from types import SimpleNamespace

from openmob.phone.base import DeviceError
from openmob.phone.remote import PhoneLink


class _GrowingFuture:
    """A pending call whose failure lets the event loop register another call (the race in PhoneLink.close)."""

    def __init__(self, link: PhoneLink):
        self.link = link
        self.error = None

    def done(self) -> bool:
        return self.error is not None

    def set_exception(self, exc) -> None:
        self.error = exc
        self.link._pending[f"late-{len(self.link._pending)}"] = _Done()


class _Done:
    def done(self) -> bool:
        return True


def test_closing_a_link_while_a_call_registers_fails_every_pending_call():
    # PhoneLink.close runs on a threadpool thread (attach_remote replacing a socket, close_links) while the event
    # loop can add to _pending. Iterating the live dict raised "dictionary changed size during iteration", which
    # left the old socket unclosed.
    loop = asyncio.new_event_loop()
    try:
        link = PhoneLink(object(), loop)
        first, second = _GrowingFuture(link), _GrowingFuture(link)
        link._pending.update({"a": first, "b": second})
        link.close()
        assert link.closed
        assert isinstance(first.error, DeviceError) and isinstance(second.error, DeviceError)
    finally:
        loop.close()


def test_account_add_with_a_bare_password_file_name(tmp_path, monkeypatch):
    # `openmob account add EMAIL --password-file pw.txt` called os.makedirs("") and crashed (FileNotFoundError).
    from openmob import accounts, main

    created = []

    class Store:
        def account_id_for(self, email):
            return None

        def create_account(self, email, password):
            created.append((email, password))

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENMOB_PASSWORD", raising=False)
    monkeypatch.setattr(accounts, "AccountStore", Store)
    main.cmd_account(None, SimpleNamespace(action="add", email="new@example.com", password_file="pw.txt"))
    secret = (tmp_path / "pw.txt").read_text()
    assert created == [("new@example.com", secret)] and len(secret) >= 20
    assert (tmp_path / "pw.txt").stat().st_mode & 0o777 == 0o600


def test_a_nan_wait_timeout_falls_back_to_the_default():
    # The model's wait_until timeout_s "nan" got through the clamp as NaN: the deadline never came, and only a Stop
    # ended the wait. "inf" was already clamped to the maximum; NaN now gets the default.
    from openmob.agent import waiting

    assert waiting.parse({"until": "screen_changes", "timeout_s": "nan"}).timeout_s == waiting.DEFAULT_TIMEOUT_S
    assert waiting.parse({"until": "screen_changes", "timeout_s": "inf"}).timeout_s == waiting.MAX_TIMEOUT_S
    assert waiting.parse({"until": "screen_changes", "timeout_s": 5}).timeout_s == 5
