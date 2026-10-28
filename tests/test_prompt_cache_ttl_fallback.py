"""A provider that refuses the 1-hour prompt-cache ttl (review 2026-10-21, I3): a gateway, an ANTHROPIC_BASE_URL or
an older API answering 400 to `cache_control.ttl` would otherwise fail every Anthropic call. The call is sent once
more with the plain ephemeral marker, and the process remembers it (one warning, nothing secret)."""

from types import SimpleNamespace

import pytest

from openmob.agent import models
from openmob.agent.models import AnthropicAdapter, ModelError, ModelRequest
from openmob.agent.tools import TOOL_SPECS

REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "model": "m", "usage": None}


class BadRequest(Exception):
    def __init__(self, message):
        super().__init__(f"Error code: 400 - {{'type': 'error', 'error': {{'message': '{message}'}}}}")
        self.status_code = 400


class Create:
    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def request():
    return ModelRequest(model="claude-sonnet-5-5", system="You operate a phone.", tools=TOOL_SPECS[:2],
                        messages=[{"role": "user", "content": "hi"}], max_tokens=512)


def adapter(create):
    return AnthropicAdapter(SimpleNamespace(messages=SimpleNamespace(create=create)))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("OPENMOB_PROMPT_CACHE_TTL", raising=False)
    monkeypatch.setattr(models, "_TTL_REFUSED", models.threading.Event())


def test_a_refused_ttl_is_sent_again_without_it_and_remembered(capsys):
    create = Create(BadRequest("cache_control.ttl: Extra inputs are not permitted"), REPLY, REPLY)
    assert adapter(create).complete(request()).text == ["ok"]
    assert create.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert create.calls[1]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert create.calls[1]["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    adapter(create).complete(request())  # a new adapter in the same process: no ttl, no failed call first
    assert len(create.calls) == 3 and create.calls[2]["system"][0]["cache_control"] == {"type": "ephemeral"}
    out = capsys.readouterr().out
    assert out.count("refused the 1-hour prompt-cache ttl") == 1


def test_the_stream_falls_back_too():
    create = Create(BadRequest("cache_control: ttl not supported"), iter([]))
    list(adapter(create).stream(request()))
    assert len(create.calls) == 2 and create.calls[1]["stream"] is True
    assert create.calls[1]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_another_400_is_not_retried():
    create = Create(BadRequest("messages: at least one message is required"))
    with pytest.raises(ModelError):
        adapter(create).complete(request())
    assert len(create.calls) == 1 and not models._TTL_REFUSED.is_set()


def test_a_second_refusal_fails():
    create = Create(BadRequest("ttl"), BadRequest("ttl"))
    with pytest.raises(ModelError):
        adapter(create).complete(request())
    assert len(create.calls) == 2
