"""remember and recall: proposals only, near-nothing leaks (Task 4)."""

from conftest import FakeDriver, RecordingIO, ScriptedClient, tool_use

from openmob.agent import memory_context
from openmob.agent.loop import Agent
from openmob.agent.tools import TOOLS
from openmob.config import Config
from openmob.memory import Memory
from openmob.phone.apps import AppResolver

SECRET = "zebra-print slippers"
DONE = tool_use("done", "d", summary="ok", success=True)


class IO(RecordingIO):
    def __init__(self):
        super().__init__()
        self.data = []
        self.steps = []

    def event(self, kind, message, data=None):
        self.events.append((kind, message))
        self.data.append((kind, data))

    def record_step(self, row):
        self.steps.append(dict(row))


def make(responses, tmp_path, **cfg):
    tmp_path.mkdir(parents=True, exist_ok=True)
    mem = Memory(tmp_path / "memory.sqlite")
    config = Config(**{"settle_delay": 0, "launch_settle_delay": 0, "memory": True, **cfg})
    driver = FakeDriver()
    agent = Agent(ScriptedClient(responses), driver, AppResolver(driver, label_cache=tmp_path / "l.json"), config,
                  IO(), use_ocr=False)
    agent.memory = mem
    return agent, mem


def run(agent, task, allowed=True):
    return agent.run(task, memory_allowed=allowed)


def proposals(mem):
    return [n for n in mem.list(None) if n["status"] == "proposed"]


def test_remember_always_proposes(tmp_path):
    agent, mem = make([[tool_use("remember", "r", text="I like oat milk", kind="about_you")], [DONE]], tmp_path)
    run(agent, "order coffee")
    (n,) = mem.list(None)
    assert n["status"] == "proposed" and n["text"] == "I like oat milk"
    assert ("memory", {"use": "proposed", "note_ids": [n["id"]]}) in agent.io.data


def test_owner_words_mark_source_user(tmp_path):
    agent, mem = make([[tool_use("remember", "r", text="I always want oat milk", kind="about_you")], [DONE]], tmp_path)
    run(agent, "order coffee, I always want oat milk")
    assert proposals(mem)[0]["source"] == "user"
    agent, mem = make([[tool_use("remember", "r", text="oat milk coffee please thanks", kind="about_you")], [DONE]],
                      tmp_path / "b")
    run(agent, "order me an oat milk coffee please")  # 4 of 5 words
    assert proposals(mem)[0]["source"] == "user"
    agent, mem = make([[tool_use("remember", "r", text="Prefers cats", kind="about_you")], [DONE]], tmp_path / "c")
    run(agent, "order coffee")
    assert proposals(mem)[0]["source"] == "agent"


def test_one_proposal_per_task(tmp_path):
    agent, mem = make([[tool_use("remember", "r1", text="First one", kind="about_you")],
                       [tool_use("remember", "r2", text="Second one", kind="about_you")], [DONE]], tmp_path)
    run(agent, "go")
    assert [n["text"] for n in proposals(mem)] == ["First one"]
    assert sum(1 for k, d in agent.io.data if k == "memory") == 1
    assert "already suggested" in str(agent.client.requests[2]["messages"])


def test_remember_with_done_adds_no_model_call(tmp_path):
    for calls in ([tool_use("remember", "r", text="Likes jazz", kind="about_you"), DONE],
                  [DONE, tool_use("remember", "r", text="Likes jazz", kind="about_you")]):
        agent, mem = make([calls], tmp_path / str(len(calls[0].name)))
        result = run(agent, "play music")
        assert result.success and len(agent.client.requests) == 1
        assert [n["text"] for n in proposals(mem)] == ["Likes jazz"]


def test_remember_and_an_action_in_one_reply_both_run(tmp_path):
    agent, mem = make([[tool_use("scroll", "s", direction="down"), tool_use("remember", "r", text="x y", kind="about_you")],
                       [DONE]], tmp_path)
    run(agent, "scroll")
    assert proposals(mem) and agent.driver.actions


def test_recall_finds_people_and_app_notes(tmp_path):
    agent, mem = make([[tool_use("recall", "c", query="sis")], [tool_use("recall", "c2", query="slack threads")], [DONE]],
                      tmp_path)
    mem.add(None, "likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")
    mem.add(None, "threads panel is on the left", "app", package="com.slack", status="active")
    mem.add(None, "hidden proposal about sis", "about_you", status="proposed")
    run(agent, "text my sis about the slack threads")  # recall answers only what the request names (review 5 M5-L2)
    first = str(agent.client.requests[1]["messages"])
    assert "Maya Lee" in first and "[m1]" in first and "hidden proposal" not in first
    second = str(agent.client.requests[2]["messages"])
    assert "threads panel" in second and "[m2]" in second  # a fresh alias, not m1 again


def test_recall_leaves_out_people_in_never_mode(tmp_path):
    from openmob import permissions as perm
    agent, mem = make([[tool_use("recall", "c", query="sis")], [DONE]], tmp_path)
    mem.add(None, "likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")
    never = perm.TaskPermissions("never", lambda: perm.normalize(perm.default_settings()))
    agent.run("text my sis", memory_allowed=True, permissions=never)
    assert "Maya" not in str(agent.client.requests[1]["messages"])


def test_screen_text_can_only_be_proposed_and_numbers_are_refused(tmp_path):
    agent, mem = make([
        [tool_use("remember", "r1", text="my wife is +1 555 0100", kind="person", relation="wife",
                  contact_name="+1 555 0100")],
        [tool_use("remember", "r2", text="my wife is Ana", kind="person", relation="wife", contact_name="Ana")],
        [DONE]], tmp_path)
    run(agent, "read my messages")  # the words came from the screen, not the owner
    (n,) = mem.list(None)
    assert n["status"] == "proposed" and n["source"] == "agent" and n["contact_name"] == "Ana"
    assert "not a number" in str(agent.client.requests[1]["messages"])


def test_no_note_text_in_steps_events_or_stdout(tmp_path, capsys):
    agent, mem = make([[tool_use("remember", "r", text=SECRET, kind="about_you")],
                       [tool_use("recall", "c", query=SECRET)], [DONE]], tmp_path)
    mem.add(None, SECRET + " too", "about_you", status="active")
    run(agent, "go")
    mem.add(None, SECRET, "about_you", status="active")
    out = capsys.readouterr()
    blob = str(agent.io.events) + str(agent.io.data) + str(agent.io.steps) + out.out + out.err
    assert SECRET not in blob and "zebra" not in blob
    rem = [s for s in agent.io.steps if s["tool"] == "remember"][0]
    rec = [s for s in agent.io.steps if s["tool"] == "recall"][0]
    (n,) = proposals(mem) or [None]
    assert rem["args"].keys() == {"note_id"} and rem["outcome"].startswith("proposed ")
    assert rec["args"] == {"query": "<redacted>"} or rec["args"] == {"query": "REDACTED"}
    assert rec["outcome"].endswith(" notes")
    shown = [m for k, m in agent.io.events if k == "action"]
    assert "remember: Proposed a preference" in shown and "recall: Checked saved preferences" in shown


def test_failed_remember_leaks_nothing_either(tmp_path):
    agent, mem = make([[tool_use("remember", "r", text=SECRET, kind="person", relation="x", contact_name="a@b.c")],
                       [DONE]], tmp_path)
    run(agent, "go")
    blob = str(agent.io.events) + str(agent.io.steps)
    assert SECRET not in blob and not mem.list(None)


def test_switch_off_hides_everything_and_keeps_data(tmp_path):
    agent, mem = make([[tool_use("remember", "r", text="Likes jazz", kind="about_you")], [DONE]], tmp_path)
    run(agent, "go")
    assert len(proposals(mem)) == 1
    off, _ = make([[DONE]], tmp_path / "off", memory=False)
    off.memory = mem
    run(off, "go")
    names = {t["name"] for t in off.client.requests[0]["tools"]}
    assert not names & {"remember", "recall"} and "Likes jazz" not in str(off.client.requests)
    assert len(proposals(mem)) == 1  # kept


def test_tools_absent_when_memory_not_allowed(tmp_path):
    agent, mem = make([[DONE]], tmp_path)
    run(agent, "go", allowed=False)
    assert not {t["name"] for t in agent.client.requests[0]["tools"]} & {"remember", "recall"}
    agent, mem = make([[DONE]], tmp_path / "on")
    run(agent, "go")
    assert {"remember", "recall"} <= {t["name"] for t in agent.client.requests[0]["tools"]}
    assert not {"remember", "recall"} & {t["name"] for t in TOOLS}


def test_streamed_remember_after_done_runs_with_one_model_call(tmp_path):
    from test_vision_speed import StreamingClient
    driver = FakeDriver()
    # done streams before remember: both still run, with one model call.
    client = StreamingClient([[("done", "d", {"summary": "ok", "success": True}),
                               ("remember", "r", {"text": "Likes jazz", "kind": "about_you"})]], driver)
    tmp_path.mkdir(parents=True, exist_ok=True)
    mem = Memory(tmp_path / "memory.sqlite")
    config = Config(settle_delay=0, launch_settle_delay=0, fast_path="off", vision_stream=True, memory=True)
    agent = Agent(client, driver, AppResolver(driver, label_cache=tmp_path / "l.json"), config, IO(), use_ocr=False)
    agent.memory = mem
    result = agent.run("go home", memory_allowed=True)
    assert result.success and len(client.requests) == 1
    assert [n["text"] for n in proposals(mem)] == ["Likes jazz"]


def test_a_memory_only_turn_does_no_settle_or_look_and_the_model_decides_next(tmp_path, monkeypatch):
    calls = []
    for helper in ("_fast_step", "_replay_step", "_plan_step", "_jev_tap_step"):
        monkeypatch.setattr(Agent, helper, lambda self, *a, _h=helper, **k: calls.append((_h, len(self.client.requests))))
    base, _ = make([[DONE]], tmp_path / "base")
    base.driver.looks = 0
    seen = {"n": 0}
    orig = base.driver.ui_elements
    base.driver.ui_elements = lambda: (seen.__setitem__("n", seen["n"] + 1), orig())[1]
    run(base, "go")
    baseline = seen["n"]
    calls.clear()
    agent, _ = make([[tool_use("recall", "c", query="anything")], [DONE]], tmp_path / "recall")
    seen["n"] = 0
    orig2 = agent.driver.ui_elements
    agent.driver.ui_elements = lambda: (seen.__setitem__("n", seen["n"] + 1), orig2())[1]
    agent.settle_calls = []
    monkeypatch.setattr(Agent, "_settle", lambda self, *a, **k: agent.settle_calls.append(a))
    result = run(agent, "go")
    assert result.success and len(agent.client.requests) == 2  # the model made the next call
    assert seen["n"] == baseline and agent.settle_calls == []  # no new look, no settle
    assert [c for c in calls if c[1] >= 1] == []  # after the recall turn no helper was even tried
