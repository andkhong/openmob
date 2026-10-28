"""Model call timeouts and retries (perf/prelaunch-1-4, 2026-10-20). The SDK defaults (600 s, 2 retries with waits
up to a minute; Gemini no timeout) let one stalled call hold a task for minutes. Every provider call now has a
per-request timeout (20 s for a vision step, 60 s for a bigger call), one retry after a timeout, a connection
failure, a 429 or an overload (honoring a short Retry-After), and a clear ModelError otherwise. No live API calls."""

import json
from types import SimpleNamespace

import pytest

from openmob.agent import models
from openmob.agent.models import (
    AnthropicAdapter, CallPolicy, GeminiAdapter, ModelError, ModelRequest, ModelRouter, OpenAIAdapter,
    OpenAIResponsesAdapter, make_client,
)
from openmob.config import Config, load_config

POLICY = CallPolicy(timeout_s=20, long_timeout_s=60, retries=1, max_wait_s=5)


def request(max_tokens=512, abort=None):
    return ModelRequest(model="m", system="s", tools=[], messages=[{"role": "user", "content": "hi"}],
                        max_tokens=max_tokens, abort=abort)


class APITimeoutError(Exception):  # named like the Anthropic and OpenAI SDKs' own
    pass


class APIStatusError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f"status {status}")
        self.status_code = status
        self.response = SimpleNamespace(headers=headers or {})


ANTHROPIC_REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "model": "m", "usage": None}


class Scripted:
    """create(**kwargs): raise or return each scripted item in turn, recording the kwargs."""

    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def slept(monkeypatch):
    waits = []
    monkeypatch.setattr(models, "_sleep", waits.append)
    return waits


def anthropic(create):
    adapter = AnthropicAdapter(SimpleNamespace(messages=SimpleNamespace(create=create)))
    adapter.policy = POLICY
    return adapter


def test_a_vision_step_has_a_20_s_timeout_and_a_bigger_call_60_s(slept):
    create = Scripted(ANTHROPIC_REPLY, ANTHROPIC_REPLY)
    adapter = anthropic(create)
    adapter.complete(request(512))
    adapter.complete(request(8192))
    assert [c["timeout"] for c in create.calls] == [20, 60]


def test_a_timeout_is_tried_once_more_then_answers(slept):
    create = Scripted(APITimeoutError("read timed out"), ANTHROPIC_REPLY)
    assert anthropic(create).complete(request()).text == ["ok"]
    assert len(create.calls) == 2 and slept == [0.0]


def test_two_timeouts_fail_the_step_with_a_clear_error(slept):
    create = Scripted(APITimeoutError("x"), APITimeoutError("x"))
    with pytest.raises(ModelError) as info:
        anthropic(create).complete(request())
    assert info.value.kind == "timeout"
    assert str(info.value) == "The model didn't answer within 20 s (tried 2 times)."
    assert len(create.calls) == 2


def test_a_429_waits_for_a_short_retry_after(slept):
    create = Scripted(APIStatusError(429, {"retry-after": "2"}), ANTHROPIC_REPLY)
    assert anthropic(create).complete(request()).text == ["ok"]
    assert slept == [2.0]


def test_retry_after_ms_is_read_too(slept):
    create = Scripted(APIStatusError(529, {"retry-after-ms": "750"}), ANTHROPIC_REPLY)
    anthropic(create).complete(request())
    assert slept == [0.75]


def test_a_long_retry_after_fails_at_once(slept):
    create = Scripted(APIStatusError(429, {"retry-after": "30"}))
    with pytest.raises(ModelError) as info:
        anthropic(create).complete(request())
    assert info.value.kind == "rate_limited" and "429" in str(info.value)
    assert len(create.calls) == 1 and slept == []


def test_an_overload_without_retry_after_waits_half_a_second(slept):
    create = Scripted(APIStatusError(529), APIStatusError(529))
    with pytest.raises(ModelError) as info:
        anthropic(create).complete(request())
    assert info.value.kind == "overloaded" and slept == [0.5]
    assert str(info.value) == "The model provider is overloaded (529); try again in a moment (tried 2 times)."


# --- AndroidWorld 2026-10-24: two 2-try connection failures each ended a long task ---------------------------------

DEFAULT = CallPolicy()


class APIConnectionError(Exception):  # named like the Anthropic and OpenAI SDKs' own
    pass


def test_the_default_policy_tries_a_connection_failure_3_more_times_with_growing_waits(slept):
    create = Scripted(*[APIConnectionError("reset")] * 3, ANTHROPIC_REPLY)
    adapter = anthropic(create)
    adapter.policy = DEFAULT
    assert adapter.complete(request()).text == ["ok"]
    assert len(create.calls) == 4 and slept == [0.25, 1.0, 4.0]


def test_a_connection_failure_that_lasts_fails_after_4_tries(slept):
    create = Scripted(*[APIConnectionError("reset")] * 4)
    adapter = anthropic(create)
    adapter.policy = DEFAULT
    with pytest.raises(ModelError) as info:
        adapter.complete(request())
    assert info.value.kind == "connection"
    assert str(info.value) == "The model provider couldn't be reached (tried 4 times)."


def test_the_backoff_is_capped_at_max_wait(slept):
    create = Scripted(*[APIStatusError(529)] * 3, ANTHROPIC_REPLY)
    adapter = anthropic(create)
    adapter.policy = DEFAULT
    adapter.complete(request())
    assert slept == [0.5, 2.0, 5.0]


def test_a_timeout_is_still_tried_only_once_more(slept):
    create = Scripted(APITimeoutError("x"), APITimeoutError("x"))
    adapter = anthropic(create)
    adapter.policy = DEFAULT
    with pytest.raises(ModelError, match=r"tried 2 times"):
        adapter.complete(request())
    assert len(create.calls) == 2


def test_a_bad_request_is_not_tried_again(slept):
    create = Scripted(APIStatusError(400))
    with pytest.raises(ModelError, match=r"request failed \(APIStatusError 400\)"):
        anthropic(create).complete(request())
    assert len(create.calls) == 1


def test_a_stopped_task_is_not_tried_again(slept):
    import threading

    abort = threading.Event()
    abort.set()
    create = Scripted(APITimeoutError("x"))
    with pytest.raises(ModelError):
        anthropic(create).complete(request(abort=abort))
    assert len(create.calls) == 1


def test_no_policy_keeps_the_old_call(slept):
    """Adapters built around injected (test) clients: no timeout kwarg, no retry, the old message."""
    create = Scripted(APIStatusError(529))
    adapter = AnthropicAdapter(SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(ModelError) as info:
        adapter.complete(request())
    assert str(info.value) == "The model request failed (APIStatusError 529)."
    assert "timeout" not in create.calls[0] and slept == []


def test_openai_chat_and_responses_pass_the_timeout(slept):
    chat_reply = {"choices": [{"message": {"content": "ok", "tool_calls": None}, "finish_reason": "stop"}],
                  "model": "m", "usage": None}
    create = Scripted(APITimeoutError("x"), chat_reply)
    adapter = OpenAIAdapter(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    adapter.policy = POLICY
    assert adapter.complete(request()).text == ["ok"]
    assert create.calls[0]["timeout"] == 20 and len(create.calls) == 2

    responses_reply = {"status": "completed", "model": "m", "usage": None, "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}
    create = Scripted(responses_reply)
    adapter = OpenAIResponsesAdapter(SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter.policy = POLICY
    adapter.complete(request(8192))
    assert create.calls[0]["timeout"] == 60


def test_gemini_gets_the_timeout_in_milliseconds(slept):
    reply = {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finish_reason": "STOP"}], "usage_metadata": None}
    create = Scripted(APIStatusError(503), reply)
    adapter = GeminiAdapter(SimpleNamespace(models=SimpleNamespace(generate_content=create)))
    adapter.policy = POLICY
    adapter.complete(request())
    assert create.calls[0]["config"]["http_options"] == {"timeout": 20000}
    assert len(create.calls) == 2 and slept == [0.5]


def test_the_router_sets_the_policy_for_real_clients_only(monkeypatch):
    cfg = Config()
    cfg.api_key = "test-key"
    router = ModelRouter(cfg)
    route = router.route("claude-sonnet-5-5")
    assert route.adapter.policy == CallPolicy(20.0, 60.0, 3, 5.0)
    injected = ModelRouter(cfg, {"anthropic": SimpleNamespace()}).route("claude-sonnet-5-5")
    assert injected.adapter.policy is None


def test_a_zero_timeout_turns_it_all_off():
    cfg = Config()
    cfg.model_timeout_s = 0
    assert CallPolicy.from_config(cfg) is None
    client = make_client("anthropic", "test-key", None, cfg)
    assert client.max_retries == 2  # the SDK's own default


def test_sdk_clients_have_no_retries_of_their_own_and_a_ceiling():
    pytest.importorskip("anthropic")
    pytest.importorskip("openai")
    cfg = Config()
    for provider in ("anthropic", "openai"):
        client = make_client(provider, "test-key", None, cfg)
        assert client.max_retries == 0
        assert client.timeout == 60.0


def test_a_real_sdk_timeout_is_classified_and_retried(slept):
    """The Anthropic SDK over an offline transport that times out: the error is a timeout, tried twice."""
    anthropic_sdk = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")

    calls = []

    def respond(req):
        calls.append(req)
        raise httpx.ReadTimeout("timed out", request=req)

    client = anthropic_sdk.Anthropic(api_key="test-key", max_retries=0,
                                     http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    adapter = AnthropicAdapter(client)
    adapter.policy = POLICY
    with pytest.raises(ModelError) as info:
        adapter.complete(request())
    assert info.value.kind == "timeout" and len(calls) == 2


def test_config_knobs_and_env_override(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("model_timeout_s: 15\nmodel_timeout_long_s: 45\nmodel_retries: 0\nmodel_retry_max_wait_s: 2\n")
    cfg = load_config(path)
    assert CallPolicy.from_config(cfg) == CallPolicy(15.0, 45.0, 0, 2.0)
    monkeypatch.setenv("OPENMOB_MODEL_TIMEOUT_S", "0")
    monkeypatch.setenv("OPENMOB_MODEL_RETRIES", "2")
    cfg = load_config(path)
    assert cfg.model_timeout_s == 0 and cfg.model_retries == 2 and CallPolicy.from_config(cfg) is None
    path.write_text("model_retries: -1\n")
    monkeypatch.delenv("OPENMOB_MODEL_RETRIES")
    with pytest.raises(ValueError, match="can't be negative"):
        load_config(path)


def test_the_default_policy_is_documented_in_the_example_config():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "config.example.yaml").read_text()
    for key in ("model_timeout_s: 20", "model_timeout_long_s: 60", "model_retries: 3", "model_retry_max_wait_s: 5"):
        assert key in text
    assert json.dumps  # keep the import used


# --- fix round 1 (review 2026-10-21, I2): self-hosted providers keep main's timeouts unless set explicitly ----------


@pytest.mark.parametrize("provider", ["openai_compatible", "qwen"])
def test_self_hosted_providers_keep_the_sdk_defaults(provider):
    pytest.importorskip("openai")
    cfg = Config()
    assert CallPolicy.from_config(cfg, provider) is None
    client = make_client(provider, "test-key", "http://127.0.0.1:11434/v1", cfg)
    assert client.max_retries == 2 and client.timeout != 60.0  # the SDK's own (600 s), as on main
    for hosted in ("anthropic", "openai", "google", "xai"):
        assert CallPolicy.from_config(cfg, hosted) == CallPolicy(20.0, 60.0, 3, 5.0)


def test_the_router_gives_a_local_model_no_policy():
    pytest.importorskip("openai")
    cfg = Config(models=[{"id": "local-vl", "label": "Local", "provider": "openai_compatible",
                          "base_url": "http://127.0.0.1:11434/v1", "vision": True, "tools": True}])
    route = ModelRouter(cfg).route("local-vl")
    assert route.adapter.policy is None and route.adapter.client.max_retries == 2


@pytest.mark.parametrize("provider", ["openai_compatible", "qwen"])
def test_an_explicit_timeout_covers_self_hosted_providers(provider, tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("model_timeout_long_s: 90\n")
    monkeypatch.setenv("OPENMOB_MODEL_TIMEOUT_S", "45")
    assert CallPolicy.from_config(load_config(path), provider) == CallPolicy(45.0, 90.0, 3, 5.0)
    monkeypatch.delenv("OPENMOB_MODEL_TIMEOUT_S")
    assert CallPolicy.from_config(load_config(path), provider) is None
    path.write_text("model_timeout_self_hosted: true\n")
    assert CallPolicy.from_config(load_config(path), provider) == CallPolicy(20.0, 60.0, 3, 5.0)
