"""A 1-hour prompt-cache lifetime for the tools and the system prompt (perf/launch-latency, 2026-10-21; latency review
rec. #5). At launch traffic many tasks start more than 5 minutes after the last one that shared the prefix; a cold
first call measured +0.5 s (Haiku, n=4, the owner's Samsung). The tools and system prompt are the same for every
task, so they get ttl 1h; the conversation's breakpoints keep the default 5 minutes (a longer TTL must come before a
shorter one, and tools and system render before messages). Memory's per-task block stays out of the cached prefix:
it rides in the first user message, so the system prompt is identical across tasks."""

import json

from conftest import system_text
from test_memory_agent import DONE, make, note, store

from openmob.agent.models import AnthropicAdapter, ModelRequest
from openmob.agent.tools import TOOL_SPECS

ONE_HOUR = {"type": "ephemeral", "ttl": "1h"}
FIVE_MIN = {"type": "ephemeral"}


def request():
    return ModelRequest(model="claude-sonnet-5-5", system="You operate a phone.", tools=TOOL_SPECS[:3],
                        max_tokens=512, cache_history=True,
                        messages=[{"role": "user", "content": "open settings"},
                                  {"role": "assistant", "content": "ok"},
                                  {"role": "user", "content": "now display"}])


def markers(kwargs) -> list[dict]:
    """Every cache_control in render order: tools, then system, then messages."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            if "cache_control" in value:
                found.append(value["cache_control"])
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for key in ("tools", "system", "messages"):
        walk(kwargs.get(key))
    return found


def test_tools_and_system_live_an_hour_and_the_conversation_five_minutes(monkeypatch):
    monkeypatch.delenv("OPENMOB_PROMPT_CACHE_TTL", raising=False)
    kwargs = AnthropicAdapter(client=None).request_kwargs(request())
    assert kwargs["tools"][-1]["cache_control"] == ONE_HOUR
    assert kwargs["system"][0]["cache_control"] == ONE_HOUR
    found = markers(kwargs)
    assert found == [ONE_HOUR, ONE_HOUR, FIVE_MIN, FIVE_MIN]  # longer TTLs first, at most 4 breakpoints
    assert "betas" not in kwargs and "extra_headers" not in kwargs  # GA: no beta header


def test_the_switch_goes_back_to_five_minutes(monkeypatch):
    monkeypatch.setenv("OPENMOB_PROMPT_CACHE_TTL", "5m")
    kwargs = AnthropicAdapter(client=None).request_kwargs(request())
    assert markers(kwargs) == [FIVE_MIN] * 4


def test_the_installed_sdk_accepts_the_ttl():
    from typing import get_type_hints

    from anthropic.types import CacheControlEphemeralParam

    assert "ttl" in get_type_hints(CacheControlEphemeralParam)


def test_memorys_block_is_not_in_the_cached_prefix(tmp_path):
    mem = store(tmp_path / "a")
    note(mem, "I prefer dark mode")
    a, client_a, _, _ = make([DONE], tmp_path / "a", mem)
    a.run("open settings", memory_allowed=True)
    mem_b = store(tmp_path / "b")
    note(mem_b, "My favourite colour is green")
    b, client_b, _, _ = make([DONE], tmp_path / "b", mem_b)
    b.run("open the camera", memory_allowed=True)
    first_a, first_b = client_a.requests[0], client_b.requests[0]
    assert "dark mode" in json.dumps(first_a["messages"]) and "dark mode" not in system_text(first_a)
    assert system_text(first_a) == system_text(first_b)  # identical across tasks and notes
    assert json.dumps(first_a["tools"]) == json.dumps(first_b["tools"])
