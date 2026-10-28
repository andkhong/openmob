"""Preferences memory in the agent: which notes a task gets, where they go, and which tasks get them (Task 2)."""

import threading
import time

from conftest import FakeDriver, RecordingIO, ScriptedClient, system_text, text_block, tool_use

from openmob import permissions as perm
from openmob.agent import app_links, memory_context, replay
from openmob.agent.loop import Agent, AgentResult
from openmob.config import Config
from openmob.devices import DeviceInfo, DeviceManager
from openmob.memory import Memory
from openmob.phone.apps import AppResolver
from openmob.runner import Coordinator
from openmob.voice.tts import Speaker

AMAZON = "com.amazon.mShop.android.shopping"
WWM = "com.netease.wwm"
DONE = [tool_use("done", "d", summary="ok", success=True)]
SODA = "My favorite soda is Coke Zero 12-pack"


def store(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return Memory(tmp_path / "memory.sqlite")


def note(mem, text, kind="about_you", **kw):
    return mem.add(None, text, kind, status="active", **kw)["id"]


def make(responses, tmp_path, mem=None, driver=None, **cfg):
    config = Config(**{"settle_delay": 0, "launch_settle_delay": 0, "memory": True, **cfg})
    driver = driver or FakeDriver(packages=[AMAZON, WWM, "com.android.settings"],
                                  labels={WWM: "Where Winds Meet", AMAZON: "Amazon Shopping"})
    resolver = AppResolver(driver, label_cache=tmp_path / "l.json")
    client = ScriptedClient(responses)
    io = RecordingIO()
    agent = Agent(client, driver, resolver, config, io, use_ocr=False)
    agent.memory = mem
    return agent, client, driver, io


def first_text(client, index=0) -> str:
    return client.requests[index]["messages"][0]["content"][0]["text"]


# --- placement ---------------------------------------------------------------------------------------

def test_system_prompt_and_tools_identical_with_memory_on_and_off(tmp_path):
    mem = store(tmp_path)
    note(mem, "I prefer dark mode")
    on, client_on, _, _ = make([DONE], tmp_path, mem)
    on.run("open settings", memory_allowed=True)
    off, client_off, _, _ = make([DONE], tmp_path, None, memory=False)
    off.run("open settings")
    assert "dark mode" in str(client_on.requests[0]["messages"])  # memory did reach the model
    assert system_text(client_on.requests[0]) == system_text(client_off.requests[0])
    # Task 4: remember and recall are appended after every other tool (a stable prefix), only when memory is allowed.
    on_tools, off_tools = client_on.requests[0]["tools"], client_off.requests[0]["tools"]
    strip = lambda tools: [{k: v for k, v in t.items() if k != "cache_control"} for t in tools]  # the last tool carries the marker
    assert strip(on_tools[:-2]) == strip(off_tools) and [t["name"] for t in on_tools[-2:]] == ["remember", "recall"]


def test_block_follows_the_request_in_the_first_user_message(tmp_path):
    mem = store(tmp_path)
    nid = note(mem, "I prefer dark mode")
    agent, client, _, io = make([DONE], tmp_path, mem)
    agent.run("open settings", memory_allowed=True)
    text = first_text(client)
    assert text.startswith("Request: open settings\n\n" + memory_context.HEADER)
    assert "- [m1] I prefer dark mode" in text
    assert "dark mode" not in str(io.events) and nid not in text  # no note text in events, no ids to the model
    # Not allowed (or no store): the first message is the request alone.
    agent, client, _, _ = make([DONE], tmp_path, mem)
    agent.run("open settings")
    assert first_text(client) == "Request: open settings"


def test_block_has_caps_and_budget(tmp_path):
    mem = store(tmp_path)
    for i in range(14):
        note(mem, f"About me number {i}: " + "x" * 60)
    for i in range(7):
        note(mem, f"Amazon tip {i}", kind="app", package=AMAZON)
    block = memory_context.task_block(mem, None, "search amazon for socks", [AMAZON], people_ok=True)
    assert len(block.relevant_ids) == 5 and len(block.ids) <= 15
    about = [i for i in block.ids if i not in block.relevant_ids]
    assert len(about) <= 10
    assert len(block.text) <= 1600 and block.text.startswith(memory_context.HEADER)
    assert sorted(block.aliases.values()) == sorted(block.ids) and set(block.aliases) == {f"m{n}" for n in range(1, len(block.ids) + 1)}
    # Long notes: trimmed lowest-ranked first (about-you go before the relevant ones).
    for i in range(10):
        note(mem, f"Long note {i} " + "y" * 280)
    block = memory_context.task_block(mem, None, "search amazon for socks", [AMAZON], people_ok=True)
    assert len(block.text) <= 1600 and len(block.relevant_ids) == 5
    # People lines and the rule line.
    mem2 = Memory(tmp_path / "m2.sqlite")
    mem2.add(None, "she likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")
    block = memory_context.task_block(mem2, None, "text my sis happy birthday", [], people_ok=True)
    assert "- [m1] your sis: Maya Lee (a contact in their phone) — she likes voice notes" in block.text
    assert memory_context.PEOPLE_RULE in block.text and block.relevant_ids == block.ids
    assert memory_context.task_block(mem2, None, "open youtube", [], people_ok=True).text == ""


def test_no_phone_call_while_building_the_block(tmp_path, monkeypatch):
    mem = store(tmp_path)
    note(mem, "I prefer dark mode")
    note(mem, SODA, kind="app", package=AMAZON)

    class Counting(FakeDriver):
        calls = 0

        def __getattribute__(self, name):
            attr = object.__getattribute__(self, name)
            if callable(attr) and not name.startswith("_"):
                object.__setattr__(self, "calls", object.__getattribute__(self, "calls") + 1)
            return attr

    driver = Counting(packages=[AMAZON], labels={AMAZON: "Amazon Shopping"})
    agent, client, _, _ = make([DONE], tmp_path, mem, driver=driver)
    agent.resolver.ensure_labels()  # the installed-app index, read when the phone connected
    seen = {}
    real = memory_context.task_block

    def spy(*a, **kw):
        before = driver.calls
        out = real(*a, **kw)
        seen["calls"] = driver.calls - before
        seen["at"] = before
        return out

    monkeypatch.setattr(memory_context, "task_block", spy)
    start = driver.calls
    agent.run("open amazon shopping", memory_allowed=True)
    assert seen == {"calls": 0, "at": start}  # nothing asked of the phone from the task's start to the block
    assert "Coke Zero" in first_text(client)


def test_app_notes_flush_once_per_app_and_skip_launcher(tmp_path):
    mem = store(tmp_path)
    note(mem, "Quests are under the scroll icon", kind="app", package=WWM)
    note(mem, "Launcher note", kind="app", package="com.android.launcher3")
    steps = [[tool_use("launch_app", "a", app="Where Winds Meet")],
             [tool_use("press_key", "b", key="HOME")],
             [tool_use("launch_app", "c", app="Where Winds Meet")],
             [tool_use("wait", "w1", seconds=0.1)], [tool_use("wait", "w2", seconds=0.1)],
             DONE]
    agent, client, driver, io = make(steps, tmp_path, mem, fast_path_lazy_screenshot=False, keep_screenshots=1)
    driver.key = lambda name: (driver.actions.append(("key", name)), setattr(driver, "package", "com.android.launcher3"))
    agent.run("do the quest thing", memory_allowed=True)
    assert "scroll icon" not in str(client.requests[0]["messages"])  # not before the game came to the front
    assert "scroll icon" in str(client.requests[1]["messages"])  # with the first look at it
    everything = str(client.requests[-1]["messages"])
    # Once per app (not again on its second launch), and kept when old observations are trimmed.
    assert everything.count("Quests are under the scroll icon") == 1
    assert "Launcher note" not in everything
    assert memory_context.APP_HEADER in everything
    assert "scroll icon" not in str(io.events)
    assert memory_context.app_block(mem, None, "com.android.systemui", {}).text == ""


# --- where memory applies ------------------------------------------------------------------------------

class MemoryAgent:
    """A fake agent that records whether each task was allowed memory."""

    def __init__(self):
        self.config = Config(memory=True)
        self.allowed = []
        self.ran = threading.Event()

    def run(self, text, cancel, go_home=False, memory_allowed=False, **kw):
        self.allowed.append(memory_allowed)
        self.ran.set()
        return AgentResult(True, "ok", 1)


def run_on(coordinator, text, source):
    coordinator.agent.ran.clear()
    coordinator.enqueue(text, source)
    assert coordinator.agent.ran.wait(2)
    time.sleep(0.02)
    return coordinator.agent.allowed[-1]


def test_memory_only_for_dashboard_and_trusted_phones(tmp_path):
    c = Coordinator(Speaker(enabled=False))
    c.agent = MemoryAgent()
    trusted = {"ok": True}
    c.memory_trusted = lambda: trusted["ok"]
    c.start()
    assert run_on(c, "open maps", "dashboard") is True
    assert run_on(c, "open maps", "phone") is True
    for source in ("api", "mcp", "drive", "terminal", "mic"):
        assert run_on(c, "open maps", source) is False
    trusted["ok"] = False  # an untrusted phone: not even its dashboard tasks
    assert run_on(c, "open maps", "dashboard") is False
    assert run_on(c, "open maps", "phone") is False
    trusted["ok"] = True
    c.agent.config = Config(memory=False)  # the switch off
    assert run_on(c, "open maps", "dashboard") is False
    # A caller can't ask for memory through the options.
    c.agent.config = Config(memory=True)
    c.agent.ran.clear()
    c.enqueue("open maps", "api", {"memory_allowed": True})
    assert c.agent.ran.wait(2)
    time.sleep(0.02)
    assert c.agent.allowed[-1] is False


def test_memory_trust_is_the_acting_phones_approval_trust(tmp_path):
    def build_agent(cfg, io, driver, cache):
        return Agent(ScriptedClient([]), driver, AppResolver(driver, label_cache=tmp_path / "l.json"), cfg, io,
                     use_ocr=False)

    mem = store(tmp_path)
    manager = DeviceManager(Config(memory=True), build_agent, Speaker(enabled=False), adb_discovery=False, memory=mem)
    session = manager._create(DeviceInfo("p1", "", "Pixel", "app"), FakeDriver(), "acct")
    agent = session.coordinator.agent
    assert agent.memory is mem and agent.account_id == "acct"
    assert session.coordinator.memory_trusted() is True  # no accounts store (local mode): trusted
    manager.approval_trust = lambda s: s is not session  # set late, looked up at call time
    assert session.coordinator.memory_trusted() is False
    manager.approval_trust = lambda s: s is session
    assert session.coordinator.memory_trusted() is True
    manager.approval_trust = lambda s: 1 / 0  # fail closed
    assert session.coordinator.memory_trusted() is False
    # Switch off: no store handed to the agent.
    off = DeviceManager(Config(), build_agent, Speaker(enabled=False), adb_discovery=False)
    assert off._create(DeviceInfo("p2", "", "Pixel", "app"), FakeDriver()).coordinator.agent.memory is None


def test_people_not_injected_in_never_mode(tmp_path):
    mem = store(tmp_path)
    mem.add(None, "she likes voice notes", "person", relation="sis", contact_name="Maya Lee", status="active")
    note(mem, "I prefer dark mode")
    agent, client, _, _ = make([DONE], tmp_path, mem)
    never = perm.TaskPermissions("never", lambda: perm.normalize(perm.default_settings()))
    agent.run("text my sis happy birthday", memory_allowed=True, permissions=never)
    text = first_text(client)
    assert "Maya" not in text and memory_context.PEOPLE_RULE not in text and "dark mode" in text
    agent, client, _, _ = make([DONE], tmp_path, mem)
    agent.run("text my sis happy birthday", memory_allowed=True)
    assert "Maya Lee" in first_text(client)


# --- fast paths, replay and timing -------------------------------------------------------------------

def test_link_step_uses_a_matched_preference(tmp_path, monkeypatch):
    mem = store(tmp_path)
    note(mem, SODA, kind="app", package=AMAZON)
    task = "add my favorite soda to my Amazon cart"
    search = next(link for link in app_links.LINKS if link.app == "amazon" and link.intent == "search")
    agent, client, driver, _ = make([[text_block('{"q": "Coke Zero 12-pack"}')], DONE], tmp_path, mem)
    monkeypatch.setattr(agent, "_link_match", lambda state: app_links.Match(search, {}, tuple(search.params)))
    agent.run(task, memory_allowed=True)
    asked = client.requests[0]
    assert asked["model"] == agent.config.resolver_model and "Coke Zero" in str(asked["messages"])
    assert any(a[0] == "url" and "Coke%20Zero" in a[1] for a in driver.actions)
    assert len(client.requests) == 2  # no extra calls: the text model and the main model's done


def test_replay_skipped_only_for_relevant_matches(tmp_path):
    class Recording(replay.PathStore):
        asked = 0

        def get(self, key):
            Recording.asked += 1
            return super().get(key)

    mem = store(tmp_path)
    note(mem, "I prefer dark mode")  # about-you only: replay is still looked up
    paths = Recording()
    agent, _, _, _ = make([DONE], tmp_path, mem, replay_paths=True)
    agent.paths = paths
    agent.run("open amazon", memory_allowed=True)
    assert Recording.asked == 1
    note(mem, "Use the Subscribe & Save tab", kind="app", package=AMAZON)  # relevant to the request: no replay
    agent, _, _, _ = make([DONE], tmp_path, mem, replay_paths=True)
    agent.paths = paths
    agent.run("open amazon", memory_allowed=True)
    assert Recording.asked == 1


def test_memory_ms_is_recorded_per_task(tmp_path):
    mem = store(tmp_path)
    note(mem, "I prefer dark mode")
    agent, _, _, _ = make([DONE], tmp_path, mem)
    result = agent.run("open settings", memory_allowed=True)
    assert isinstance(result.timings["memory_ms"], float) and 0 <= result.timings["memory_ms"] < 1000
    agent, _, _, _ = make([DONE], tmp_path, mem)
    assert "memory_ms" not in agent.run("open settings").timings  # no memory for this task: no field


# --- review round 1 ----------------------------------------------------------------------------------

def test_the_newest_about_you_notes_reach_the_task(tmp_path):
    mem = store(tmp_path)
    ids = [note(mem, f"About me {i}") for i in range(12)]
    block = memory_context.task_block(mem, None, "open settings", [], people_ok=True)
    assert len(block.ids) == 10 and ids[10] in block.ids and ids[11] in block.ids
    assert ids[0] not in block.ids and ids[1] not in block.ids  # the oldest two drop out
    # A search hit among older about-you notes still makes it, inside the cap.
    hit = memory_context.task_block(mem, None, "about me 0 please", [], people_ok=True)
    assert len(hit.ids) == 10 and ids[0] in hit.ids


def test_a_possessive_link_value_comes_from_the_matched_preference(tmp_path):
    task = "search amazon for my favorite soda"
    mem = store(tmp_path)
    note(mem, "Favorite soda: Coke Zero 12-pack", kind="app", package=AMAZON)
    agent, client, driver, _ = make([[text_block('{"q": "Coke Zero 12-pack"}')], DONE], tmp_path, mem)
    agent.run(task, memory_allowed=True)  # the real link match: no stub
    asked = client.requests[0]
    assert asked["model"] == agent.config.resolver_model and "Coke Zero" in str(asked["messages"])
    assert [a[1] for a in driver.actions if a[0] == "url"] == ["https://www.amazon.com/s?k=Coke%20Zero%2012-pack"]
    assert len(client.requests) == 2  # one fast call, then the main model's done
    # No matching note: the literal value, no text-model call.
    other = store(tmp_path / "other")
    note(other, "I prefer dark mode")
    agent, client, driver, _ = make([DONE], tmp_path, other)
    agent.run(task, memory_allowed=True)
    assert [a[1] for a in driver.actions if a[0] == "url"] == ["https://www.amazon.com/s?k=my%20favorite%20soda"]
    assert len(client.requests) == 1
