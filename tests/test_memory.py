"""Memory: owner-confirmed notes per account (about you, an app, a person), with full-text search."""

import pytest

from openmob.config import load_config
from openmob.memory import MAX_NOTES, MAX_PROPOSED, MAX_TEXT, Memory, NoteError


@pytest.fixture
def mem(tmp_path):
    return Memory(tmp_path / "memory.sqlite")


def test_notes_are_per_account(mem):
    a = mem.add("alice", "I prefer dark mode", "about_you", status="active")
    mem.add("bob", "Use my work account", "about_you", status="active")
    assert [n["text"] for n in mem.list("alice")] == ["I prefer dark mode"]
    assert mem.get("bob", a["id"]) is None
    assert mem.update("bob", a["id"], text="hacked") is None
    assert mem.confirm("bob", a["id"]) is None
    assert mem.delete("bob", a["id"]) is False
    assert mem.get("alice", a["id"])["text"] == "I prefer dark mode"
    assert "account_id" not in a


def test_kinds_and_people_fields(mem):
    mem.add("alice", "Call me Al", "about_you", status="active")
    mem.add("alice", "Quests are under the scroll icon", "app", package="com.netease.yysls", status="active")
    p = mem.add("alice", "My sister, text her short", "person", relation="sis", contact_name="Maya", status="active")
    assert p["kind"] == "person" and p["relation"] == "sis" and p["contact_name"] == "Maya"
    assert [n["text"] for n in mem.about_you("alice")] == ["Call me Al"]
    assert [n["text"] for n in mem.for_app("alice", "com.netease.yysls")] == ["Quests are under the scroll icon"]
    assert mem.for_app("alice", "com.other") == []
    assert [n["id"] for n in mem.people("alice", "SIS")] == [p["id"]]
    assert [n["id"] for n in mem.people("alice", "maya")] == [p["id"]]
    assert mem.people("alice", "mom") == []
    with pytest.raises(NoteError):
        mem.add("alice", "x", "nonsense")
    with pytest.raises(NoteError):
        mem.add("alice", "x", "app")  # no package
    with pytest.raises(NoteError):
        mem.add("alice", "x", "person", contact_name="Maya")  # no relation


@pytest.mark.parametrize("bad", ["+1 555 0100", "(555) 010-0100", "5550100", "maya@example.com", "", "  "])
def test_contact_name_cannot_be_a_number_or_email(mem, bad):
    with pytest.raises(NoteError):
        mem.add("alice", "my wife", "person", relation="wife", contact_name=bad)
    p = mem.add("alice", "my wife", "person", relation="wife", contact_name="Dana")
    with pytest.raises(NoteError):
        mem.update("alice", p["id"], contact_name=bad)
    assert mem.get("alice", p["id"])["contact_name"] == "Dana"


def test_proposals_are_not_used_until_confirmed(mem):
    p = mem.add("alice", "The user likes lo-fi music", "about_you", source="agent")
    assert p["status"] == "proposed"
    assert mem.about_you("alice") == []
    assert [n["id"] for n in mem.list("alice", status="proposed")] == [p["id"]]
    assert mem.confirm("alice", p["id"])["status"] == "active"
    assert [n["text"] for n in mem.about_you("alice")] == ["The user likes lo-fi music"]


def test_near_duplicates_are_saved_once(mem):
    p = mem.add("alice", "Use my second account", "about_you", source="agent")
    again = mem.add("alice", "use my  second account!", "about_you", status="active")
    assert again["id"] == p["id"] and again["status"] == "active"
    assert len(mem.list("alice")) == 1


def test_validation(mem):
    with pytest.raises(NoteError):
        mem.add("alice", "   ", "about_you")
    with pytest.raises(NoteError):
        mem.add("alice", "ok", "about_you", status="sneaky")


def test_limits(mem):
    with pytest.raises(NoteError):
        mem.add("alice", "x" * (MAX_TEXT + 1), "about_you")
    assert MAX_TEXT == 300 and MAX_NOTES == 200 and MAX_PROPOSED == 20
    for i in range(MAX_PROPOSED):
        mem.add("alice", f"proposal number {i}", "about_you")
    with pytest.raises(NoteError):
        mem.add("alice", "one proposal too many", "about_you")
    mem.add("alice", "an active note is still fine", "about_you", status="active")
    for i in range(MAX_NOTES - MAX_PROPOSED - 1):
        mem.add("alice", f"active note number {i}", "about_you", status="active")
    assert len(mem.list("alice")) == MAX_NOTES
    with pytest.raises(NoteError):
        mem.add("alice", "the 201st note", "about_you", status="active")
    mem.add("bob", "other accounts have their own room", "about_you")


def test_delete_all_only_touches_that_account(mem):
    mem.add("alice", "one", "about_you")
    mem.add("alice", "two", "app", package="com.x")
    mem.add("bob", "three", "about_you")
    assert mem.delete_all("alice") == 2
    assert mem.list("alice") == [] and len(mem.list("bob")) == 1


def test_search_ranks_relevant_active_notes(mem):
    mem.add("alice", "Call me Al", "about_you", status="active")
    mem.add("alice", "Soda is bad for me", "about_you", status="active")
    best = mem.add("alice", "Favorite soda on Amazon: Coke Zero 12-pack", "about_you", status="active")
    mem.add("alice", "Favorite soda: Pepsi", "about_you")  # proposed
    mem.add("bob", "Favorite soda: Sprite", "about_you", status="active")
    found = mem.search("alice", "add my favorite soda")
    assert found[0]["id"] == best["id"]
    assert all(n["status"] == "active" and "Pepsi" not in n["text"] for n in found)
    assert mem.search("alice", "add my the") == [] and mem.search("alice", "") == []


@pytest.mark.parametrize("query", ['soda "coke', "-soda*", "AND NEAR( soda", "soda) OR (", "'; DROP TABLE notes;--"])
def test_search_tolerates_query_syntax(mem, query):
    mem.add("alice", "Favorite soda: Coke Zero", "about_you", status="active")
    mem.search("alice", query)  # must not raise


def test_get_many_scopes_to_account(mem):
    a = mem.add("alice", "mine", "about_you")
    b = mem.add("bob", "theirs", "about_you")
    got = mem.get_many("alice", [a["id"], b["id"], "missing"])
    assert list(got) == [a["id"]] and got[a["id"]]["text"] == "mine"
    assert mem.get_many("alice", []) == {}


def _file_bytes(tmp_path):
    return b"".join(f.read_bytes() for f in tmp_path.glob("memory.sqlite*"))


def test_secure_delete_leaves_no_text_in_the_file(tmp_path):
    m = Memory(tmp_path / "memory.sqlite")
    n = m.add("alice", "Zebraquartz marmalade passphrasehint", "about_you", status="active")
    m.add("alice", "keep this other note around", "about_you", status="active")
    assert b"zebraquartz" in _file_bytes(tmp_path).lower()  # the check can see it while it exists
    assert m.delete("alice", n["id"])
    data = _file_bytes(tmp_path).lower()  # no checkpoint here: delete itself must scrub db, -wal and -shm
    for needle in (b"zebraquartz", b"marmalade", b"passphrasehint", b"zebraquartz marmalade"):
        assert needle not in data, needle
    m.close()


def test_edit_leaves_no_old_text_in_the_file(tmp_path):
    m = Memory(tmp_path / "memory.sqlite")
    n = m.add("alice", "Zebraquartz marmalade passphrasehint", "about_you", status="active")
    m.update("alice", n["id"], text="Something entirely different")
    data = _file_bytes(tmp_path).lower()
    for needle in (b"zebraquartz", b"marmalade", b"passphrasehint"):
        assert needle not in data, needle
    assert [x["id"] for x in m.search("alice", "different")] == [n["id"]]
    m.close()


def test_two_contacts_with_one_relation_are_both_kept(mem):
    a = mem.add("a", "My sister, text her short", "person", relation="sis", contact_name="Maya", status="active")
    b = mem.add("a", "My sister, text her short", "person", relation="sis", contact_name="Priya", status="active")
    assert a["id"] != b["id"]
    assert {n["contact_name"] for n in mem.people("a", "sis")} == {"Maya", "Priya"}
    assert mem.add("a", "My sister, text her short", "person", relation="sis", contact_name="maya", status="active")["id"] == a["id"]


def test_mark_used_counts(mem):
    n = mem.add("alice", "x note", "about_you", status="active")
    mem.mark_used([n["id"]])
    assert mem.get("alice", n["id"])["uses"] == 1


def test_config_memory_switch_defaults_off(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("model: claude-sonnet-5-5\n")
    monkeypatch.delenv("OPENMOB_MEMORY", raising=False)
    assert load_config(cfg_file).memory is False
    monkeypatch.setenv("OPENMOB_MEMORY", "on")
    assert load_config(cfg_file).memory is True
    cfg_file.write_text("memory: true\n")
    monkeypatch.setenv("OPENMOB_MEMORY", "off")
    assert load_config(cfg_file).memory is False
