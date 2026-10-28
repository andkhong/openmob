"""History's background writer (perf/prelaunch-1-4, 2026-10-20): step, event, prompt and model-run writes leave the
agent's thread for one writer thread, in order, and every read through History sees the writes queued before it."""

import sqlite3
import threading
import time

from openmob.history import History


def heard(task, message="[phone] open settings", t=None):
    return {"seq": 1, "time": t or time.time(), "kind": "heard", "message": message, "task": task}


def final(task, summary="Done.", steps=2):
    return {"seq": 2, "time": time.time(), "kind": "result", "message": f"{summary} ({steps} steps)", "task": task,
            "data": {"final": True, "success": True, "steps": steps}}


def step(idx, **extra):
    return {"idx": idx, "tool": "tap", "args": {"x": 1, "y": 2}, "is_error": False, "total_ms": 100, **extra}


def test_reads_see_every_write_queued_before_them(tmp_path):
    h = History(tmp_path / "h.sqlite", background=True)
    assert h._writer is not None
    chat = h.create_chat("acct", "dev", "Pixel", "open settings")
    h.record(chat, heard("t1"))
    for i in range(1, 51):
        h.record_step(chat, "t1", step(i), account_id="acct")
    h.record(chat, final("t1"))
    turn = h.turn("acct", "t1")
    assert turn["finished"] is not None and turn["summary"] == "Done." and turn["steps"] == 2
    assert [s["idx"] for s in h.steps("acct", "t1")] == list(range(1, 51))
    assert [e["kind"] for e in h.events("acct", chat)] == ["heard", "result"]


def test_the_callers_thread_doesnt_wait_for_the_disk(tmp_path):
    h = History(tmp_path / "h.sqlite", background=True)
    chat = h.create_chat("acct", "dev", "Pixel", "x")
    h.record(chat, heard("t1"))
    h.flush()
    with h._lock:  # the database is busy (a slow write, a long read): the writer can't get in
        started = time.perf_counter()
        h.record_step(chat, "t1", step(1), account_id="acct")
        h.record(chat, final("t1"))
        took = time.perf_counter() - started
    assert took < 0.05
    assert len(h.steps("acct", "t1")) == 1  # the read waited for the queued writes


def test_a_step_is_saved_as_it_was_when_recorded(tmp_path):
    """The agent updates a step's record later (a streamed reply's tokens) and records it again."""
    h = History(tmp_path / "h.sqlite", background=True)
    chat = h.create_chat("acct", "dev", "Pixel", "x")
    record = step(1)
    with h._lock:
        h.record_step(chat, "t1", record, account_id="acct")
        record["args"]["x"] = 999
        record["input_tokens"] = 5
    assert h.steps("acct", "t1")[0]["args"] == {"x": 1, "y": 2}
    assert h.steps("acct", "t1")[0]["input_tokens"] is None
    h.record_step(chat, "t1", record, account_id="acct")
    assert h.steps("acct", "t1")[0]["input_tokens"] == 5


def test_a_failed_write_doesnt_stop_the_writer(tmp_path, capsys):
    h = History(tmp_path / "h.sqlite", background=True)
    chat = h.create_chat("acct", "dev", "Pixel", "x")
    h.record("no-such-chat", heard("t9"))  # violates the chats foreign key
    h.record(chat, heard("t1"))
    assert h.turn("acct", "t1") is not None
    assert "History not saved" in capsys.readouterr().out


def test_close_flushes_to_disk(tmp_path):
    path = tmp_path / "h.sqlite"
    h = History(path, background=True)
    chat = h.create_chat("acct", "dev", "Pixel", "x")
    for i in range(1, 201):
        h.record_step(chat, "t1", step(i), account_id="acct")
    h.record_model_run("acct", "t1", "m", True, 200)
    h.record_prompt("t1", {"kind": "action", "decision": "approved"}, account_id="acct")
    h.close()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 200
        assert db.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 1
    h.record_step(chat, "t1", step(201), account_id="acct")  # after close: inline, still saved
    assert len(h.steps("acct", "t1")) == 201


def test_writes_from_many_threads_all_land(tmp_path):
    h = History(tmp_path / "h.sqlite", background=True)
    chats = [h.create_chat("acct", f"dev{i}", "Pixel", "x") for i in range(20)]

    def phone(i):
        h.record(chats[i], heard(f"t{i}"))
        for n in range(1, 31):
            h.record_step(chats[i], f"t{i}", step(n), account_id="acct")
        h.record(chats[i], final(f"t{i}", steps=30))

    threads = [threading.Thread(target=phone, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(len(h.steps("acct", f"t{i}")) == 30 for i in range(20))
    assert all(h.turn("acct", f"t{i}")["steps"] == 30 for i in range(20))


def test_the_writer_is_off_by_default_and_the_switch_turns_it_on(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMOB_HISTORY_WRITER", raising=False)
    assert History(tmp_path / "a.sqlite", background=False)._writer is None
    monkeypatch.setenv("OPENMOB_HISTORY_WRITER", "on")
    on = History(tmp_path / "c.sqlite")
    assert on._writer is not None
    on.close()
    monkeypatch.delenv("OPENMOB_HISTORY_WRITER")
    h = History(tmp_path / "b.sqlite")
    assert h._writer is None
    chat = h.create_chat("acct", "dev", "Pixel", "x")
    h.record_step(chat, "t1", step(1), account_id="acct")
    with sqlite3.connect(tmp_path / "b.sqlite") as db:  # no flush needed: it's already there
        assert db.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 1


def test_a_malformed_step_still_fails_in_the_caller(tmp_path):
    import pytest

    h = History(tmp_path / "h.sqlite", background=True)
    with pytest.raises(KeyError):
        h.record_step("c", "t1", {"tool": "tap"})
