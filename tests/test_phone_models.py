"""The phone's model sheet (docs/phone-protocol.md §3.5): the list in `welcome`, `set_model`, and that a model change
touches only the model and effort (never the permission mode, approvals or gate decisions)."""

from types import SimpleNamespace

from conftest import FakeDriver
from test_remote import FakePhone, server, wait_for  # noqa: F401 (the fixture)

from openmob import phone_models
from openmob.agent.models import phone_model_list
from openmob.config import Config, normalize_model


def _agent(available, model="claude-haiku-5-5"):
    return SimpleNamespace(model=model, effort=None, model_available=lambda m: m in available)


def test_the_list_is_the_allowlist_minus_what_cant_run_here_with_no_provider_details():
    cfg = Config()
    cfg.models = [normalize_model(m) for m in [
        {"id": "claude-haiku-5-5", "label": "Haiku 5.5 (fastest, cheapest)", "provider": "anthropic"},
        {"id": "claude-opus-5-5", "label": "Opus 5.5 (smartest)", "provider": "anthropic"},
        {"id": "gpt-6-luna", "label": "GPT-6 Luna", "provider": "openai", "base_url": "https://secret.example",
         "api_key_env": "SECRET_ENV", "description": "A test model", "speed": "fast"},
        {"id": "qwen3.8-flash", "provider": "qwen"},
    ]]
    models = phone_model_list(cfg, lambda m: m != "qwen3.8-flash")  # no Qwen key here
    assert [m["id"] for m in models] == ["claude-haiku-5-5", "claude-opus-5-5", "gpt-6-luna"]
    haiku, opus, gpt = models
    assert haiku == {"id": "claude-haiku-5-5", "label": "Haiku 5.5", "description": "Fastest. Recommended for phone tasks",
                     "speed": "fast", "group": "main", "effort": True}
    assert opus["speed"] == "slow" and opus["group"] == "main"
    assert gpt == {"id": "gpt-6-luna", "label": "GPT-6 Luna", "description": "A test model", "speed": "fast",
                   "group": "more", "effort": False}
    for m in models:  # only these keys: never a key name, base URL or other provider config
        assert set(m) == {"id", "label", "description", "speed", "group", "effort"}


def test_nothing_runnable_means_no_model_state():
    assert phone_models.model_state(Config(), _agent(set())) is None


def test_set_model_takes_only_the_servers_own_list_and_known_efforts():
    cfg = Config()
    agent = _agent({"claude-haiku-5-5", "claude-sonnet-5-5"})
    assert phone_models.set_model(cfg, agent, {"model": "claude-opus-5-5"}, False) == \
        {"type": "model_set", "ok": False, "error": "not_offered"}  # allowlisted, but no way to run it here
    assert phone_models.set_model(cfg, agent, {"model": "my-own-model"}, False)["error"] == "not_offered"
    assert phone_models.set_model(cfg, agent, {"model": "claude-sonnet-5-5", "effort": "max"}, False)["error"] == "bad_effort"
    assert agent.model == "claude-haiku-5-5" and agent.effort is None  # refusals changed nothing
    reply = phone_models.set_model(cfg, agent, {"model": "claude-sonnet-5-5", "effort": "high"}, True)
    assert reply == {"type": "model_set", "ok": True, "model": "claude-sonnet-5-5", "effort": "high", "applies": "next task"}
    assert agent.model == "claude-sonnet-5-5" and agent.effort == "high"
    phone_models.set_model(cfg, agent, {"model": "claude-sonnet-5-5", "effort": "auto"}, False)
    assert agent.effort is None
    state = phone_models.model_state(cfg, agent)
    assert state["model"] == "claude-sonnet-5-5" and state["effort"] == "auto"


def test_explicit_effort_overrides_auto_for_claude_only(tmp_path):
    from conftest import ScriptedClient

    from openmob.agent.loop import Agent
    from openmob.phone.apps import AppResolver
    from openmob.phone.adb import UIElement

    driver = FakeDriver()
    cfg = Config(canvas_effort="high")
    agent = Agent(ScriptedClient([]), driver, AppResolver(driver, label_cache=tmp_path / "l.json"), cfg, None, use_ocr=False)
    claude = SimpleNamespace(spec=SimpleNamespace(provider="anthropic"))
    other = SimpleNamespace(spec=SimpleNamespace(provider="openai"))
    labeled = SimpleNamespace(elements=[UIElement(index=0, checked=None, text="Wi-Fi", desc="", resource_id="", cls="android.widget.TextView", clickable=True, bounds=(0, 0, 100, 50))])
    canvas = SimpleNamespace(elements=[])
    # Auto: the per-screen rule (low = the model's own on labeled screens, canvas_effort on canvas ones).
    assert agent._effort_for(claude, labeled) is None and agent._effort_for(claude, canvas) == "high"
    agent.task_effort = "medium"
    assert agent._effort_for(claude, labeled) == "medium" and agent._effort_for(claude, canvas) == "medium"
    assert agent._effort_for(other, canvas) is None  # effort is a Claude setting


def test_the_phone_gets_the_list_and_sets_the_model_and_nothing_else(server):  # noqa: F811
    url, manager, _ = server
    phone = FakePhone(url, FakeDriver())
    assert phone.welcome.wait(5)
    welcome = next(m for m in phone.received if m["type"] == "welcome")
    offered = {m["id"] for m in welcome["models"]["models"]}
    assert "claude-haiku-5-5" in offered  # the test agent's client is Anthropic-shaped: Claude models run
    assert not any(m["group"] == "more" for m in welcome["models"]["models"])  # no other provider's key here
    session = next(iter(manager.sessions.values()))
    agent = session.coordinator.agent
    before = (dict(vars(session.coordinator.permissions)) if hasattr(session.coordinator, "permissions") else None,
              manager.cfg.default_permission_mode)
    phone.send({"type": "set_model", "model": "claude-haiku-5-5", "effort": "low"})
    assert wait_for(lambda: any(m["type"] == "model_set" for m in phone.received))
    assert next(m for m in phone.received if m["type"] == "model_set")["ok"] is True
    assert wait_for(lambda: any(m["type"] == "model_state" for m in phone.received))
    assert agent.model == "claude-haiku-5-5" and agent.effort == "low"
    phone.send({"type": "set_model", "model": "gpt-6-luna"})  # allowlisted but not runnable here
    assert wait_for(lambda: sum(m["type"] == "model_set" for m in phone.received) == 2)
    assert [m for m in phone.received if m["type"] == "model_set"][-1]["error"] == "not_offered"
    assert agent.model == "claude-haiku-5-5"
    after = (dict(vars(session.coordinator.permissions)) if hasattr(session.coordinator, "permissions") else None,
             manager.cfg.default_permission_mode)
    assert before == after  # the permission settings are untouched
    phone.disconnect()
