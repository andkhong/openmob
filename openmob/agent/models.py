"""Model adapters: one interface for the agent loop, whichever provider serves the model.

The loop keeps its conversation in a provider-neutral shape, and each adapter translates it to and
from its provider's API on every call:

    message:  {"role": "user" | "assistant", "content": str | [block, ...]}
    blocks:   {"type": "text", "text": str}
              {"type": "image", "media_type": "image/jpeg", "data": <base64 str>}
              {"type": "tool_call", "id": str, "name": str, "input": dict}          (assistant)
              {"type": "tool_result", "call_id": str, "content": [text/image blocks],
               "is_error": bool}                                                 (user)
              {"type": "opaque", "provider": str, "data": ...}   provider-only content (e.g. thinking)
                                                                 that its own adapter sends back as is
    tools:    {"name", "description", "parameters": <JSON schema>}

Blocks may carry `"meta": {provider: {...}}`, data an adapter must round-trip (Gemini's thought
signatures). Shared context is plain text in the system prompt and messages, so it is the same
for every model.

SDK clients are created lazily from keys in the environment (see config.py); tests inject fakes.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..config import PROVIDERS, Config, infer_provider
from ..usage import TokenUsage

DEFAULT_MAX_TOKENS = 1024


class ModelUnavailable(Exception):
    """The model isn't allowed, isn't known, or its provider has no key on this server."""


class ModelError(Exception):
    """A provider call failed. The message is neutral (no provider names); details go to the server log.
    `kind`: timeout | rate_limited | overloaded | connection | failed (see _call)."""

    kind: str = "failed"


@dataclass
class Capabilities:
    vision: bool = True  # takes screenshots
    tools: bool = True  # calls functions
    prompt_caching: bool = False  # the provider caches the stable prefix (explicitly or automatically)
    context_tokens: int = 128_000

    @property
    def operates_phone(self) -> bool:
        return self.vision and self.tools


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelRequest:
    model: str
    system: str
    tools: list[dict]
    messages: list[dict]
    max_tokens: int = DEFAULT_MAX_TOKENS
    # Mark the conversation for prompt caching where the provider needs it (Anthropic); the history
    # must then stay byte-identical between calls for the cache to hit (see Agent._trim_history).
    cache_history: bool = False
    # Claude: this call's effort, instead of the model's own (canvas screens; Agent._decision_effort).
    effort: str | None = None
    # The task's cancel: a streamed reply closes its HTTP stream once it's set (the agent stopped waiting already).
    abort: threading.Event | None = field(default=None, repr=False, compare=False)


@dataclass
class ModelResponse:
    content: list[dict]  # neutral assistant blocks, appended to the history as they are
    stop_reason: str  # tool_use | end_turn | max_tokens | refusal | other
    model: str | None = None  # the model the provider says served the call
    usage: TokenUsage | None = None

    @property
    def text(self) -> list[str]:
        return [b["text"] for b in self.content if b["type"] == "text"]

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [ToolCall(b["id"], b["name"], b["input"]) for b in self.content if b["type"] == "tool_call"]


class ModelAdapter(Protocol):
    provider: str

    def capabilities(self, model: str) -> Capabilities: ...
    def complete(self, request: ModelRequest) -> ModelResponse: ...


def _get(obj, name, default=None):
    """Attribute or key: SDK objects, SimpleNamespace fakes and plain dicts alike."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# Providers that are often a model on the self-hoster's own machine (Ollama, LM Studio, vLLM): the 20 s / 60 s
# timeouts and the retry apply to them only with model_timeout_self_hosted (or OPENMOB_MODEL_TIMEOUT_S set; review
# 2026-10-21, I2); otherwise
# their calls keep main's behaviour (the SDK's own 600 s and 2 retries).
SELF_HOSTED_PROVIDERS = frozenset({"openai_compatible", "qwen"})

# A call with at most this many output tokens gets the short timeout (a vision step under vision_max_tokens);
# a bigger one (a thinking model's room, a full-length retry, complete_text) gets the long one.
SHORT_CALL_TOKENS = 512


@dataclass
class CallPolicy:
    """How long one provider call may take and when it's tried again (config: model_timeout_s and friends).

    Measured: the main model's median is 1.1-1.5 s a decision (docs/benchmarks.md, the Samsung 2026-10-08 and prod
    2026-10-20); there is no recorded tail. The SDK defaults (600 s, 2 retries, retry-after honored up to a minute;
    Gemini no timeout) let one stalled call hold a task for minutes. 20 s is about 15x the median and above 512
    output tokens at the slowest model's speed (estimate: ~40 tokens/s), so it only cuts off a stalled call."""

    timeout_s: float = 20.0
    long_timeout_s: float = 60.0
    retries: int = 3
    max_wait_s: float = 5.0  # the longest Retry-After honored (a longer one fails at once) and the backoff's cap

    def timeout_for(self, max_tokens: int) -> float:
        return self.timeout_s if max_tokens <= SHORT_CALL_TOKENS else max(self.long_timeout_s, self.timeout_s)

    @classmethod
    def from_config(cls, cfg: Config, provider: str | None = None) -> CallPolicy | None:
        """None when model_timeout_s is 0: the SDKs' own defaults, as before 2026-10-20. None too for a self-hosted
        provider (SELF_HOSTED_PROVIDERS) unless model_timeout_self_hosted is on (OPENMOB_MODEL_TIMEOUT_S sets it): a
        local vision model prefilling an image can take longer than 20 s."""
        timeout = float(getattr(cfg, "model_timeout_s", 0) or 0)
        if timeout <= 0:
            return None
        if provider in SELF_HOSTED_PROVIDERS and not getattr(cfg, "model_timeout_self_hosted", False):
            return None
        return cls(timeout, float(getattr(cfg, "model_timeout_long_s", 60.0) or timeout),
                   max(0, int(getattr(cfg, "model_retries", 3))), float(getattr(cfg, "model_retry_max_wait_s", 5.0)))


def _status(exc) -> int | None:
    for name in ("status_code", "code", "status"):
        value = _get(exc, name)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _failure_kind(exc) -> str | None:
    """timeout | rate_limited | overloaded | connection, or None for a failure trying again won't fix."""
    names = [c.__name__ for c in type(exc).__mro__]
    if any("Timeout" in n for n in names):
        return "timeout"
    status = _status(exc)
    if status == 429:
        return "rate_limited"
    if status in (500, 502, 503, 504, 529):
        return "overloaded"
    if any(n in ("APIConnectionError", "ConnectError", "RemoteProtocolError") for n in names):
        return "connection"
    return None


def _retry_after(exc) -> float | None:
    """The provider's Retry-After, in seconds, where the SDK error carries the response."""
    headers = getattr(_get(exc, "response"), "headers", None)
    if headers is None:
        return None
    try:
        if headers.get("retry-after-ms"):
            return float(headers.get("retry-after-ms")) / 1000
        if headers.get("retry-after"):
            return float(headers.get("retry-after"))
    except (TypeError, ValueError):  # an HTTP date: not worth parsing, use the default wait
        return None
    return None


# The wait before the first retry when the provider sends no Retry-After; each later one waits 4x longer, up to
# max_wait_s (connection 0.25, 1, 4 s). AndroidWorld 2026-10-24: two 2-try connection failures each ended a long task.
DEFAULT_WAIT_S = {"timeout": 0.0, "connection": 0.25, "rate_limited": 1.0, "overloaded": 0.5}
BACKOFF = 4
# A timeout is tried again once only, whatever `retries` says: each attempt can take the whole timeout (20 s).
TIMEOUT_RETRIES = 1


def _sleep(seconds: float) -> None:  # a seam for tests
    import time

    time.sleep(seconds)


def _call(provider: str, fn, *, policy: CallPolicy | None = None, timeout_s: float | None = None,
          abort: threading.Event | None = None, **kwargs):
    """One provider call. With a policy: a connection failure, a 429 or an overload is tried again `policy.retries`
    times after a growing wait (the provider's Retry-After when it sends one, up to max_wait_s), a timeout once,
    then fails with a ModelError that says which. The caller puts the timeout in kwargs (each SDK names it its way)."""
    attempt = 0
    while True:
        try:
            return fn(**kwargs)
        except Exception as exc:
            # Provider SDK errors name the provider and the model; keep that in the server log only.
            print(f"⚠️  {provider} call failed: {exc!r}", flush=True)
            kind = _failure_kind(exc) if policy is not None else None
            wait = _retry_after(exc)
            if wait is None:
                wait = min(policy.max_wait_s if policy else 0.0, DEFAULT_WAIT_S.get(kind or "", 0.0) * BACKOFF ** attempt)
            limit = min(policy.retries, TIMEOUT_RETRIES) if kind == "timeout" else (policy.retries if policy else 0)
            if (kind is not None and attempt < limit and wait <= policy.max_wait_s
                    and not (abort is not None and abort.is_set())):
                attempt += 1
                _sleep(max(0.0, wait))
                if not (abort is not None and abort.is_set()):  # a Stop during the wait sends no paid retry
                    continue
            traceback.print_exc()
            status = _status(exc) or _get(exc, "status")
            if kind == "timeout":
                message = f"The model didn't answer within {timeout_s:g} s." if timeout_s else "The model timed out."
            elif kind == "rate_limited":
                message = "The model provider is rate-limiting this server (429); try again in a moment."
            elif kind == "overloaded":
                message = f"The model provider is overloaded ({status}); try again in a moment."
            elif kind == "connection":
                message = "The model provider couldn't be reached."
            else:
                message = f"The model request failed ({type(exc).__name__}{f' {status}' if status else ''})."
            if kind is not None and attempt:
                message = message[:-1] + f" (tried {attempt + 1} times)."
            error = ModelError(message)
            error.kind = kind or "failed"
            raise error from exc


def _limits(adapter, request: ModelRequest, timeout_key: str | None = "timeout") -> dict[str, Any]:
    """_call's policy arguments for this request, plus the SDK's own per-request timeout (`timeout_key`)."""
    policy = getattr(adapter, "policy", None)
    if policy is None:
        return {}
    timeout = policy.timeout_for(request.max_tokens)
    out: dict[str, Any] = {"policy": policy, "timeout_s": timeout, "abort": getattr(request, "abort", None)}
    if timeout_key:
        out[timeout_key] = timeout
    return out


# Set once a provider refused the 1-hour prompt-cache ttl (AnthropicAdapter._create): for the rest of the process.
_TTL_REFUSED = threading.Event()


def _refuses_ttl(exc) -> bool:
    """A 400 whose error names the cache ttl ("cache_control.ttl: Extra inputs are not permitted")."""
    if exc is None or _status(exc) != 400:
        return False
    text = f"{exc} {_get(exc, 'message') or ''} {_get(exc, 'body') or ''}".lower()
    return bool(re.search(r"\bttl\b", text))


def _result_text(block: dict) -> str:
    return "\n".join(b["text"] for b in block.get("content") or [] if b["type"] == "text")


def _result_images(block: dict) -> list[dict]:
    return [b for b in block.get("content") or [] if b["type"] == "image"]


def _blocks(content) -> list[dict]:
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


# --- Anthropic ---------------------------------------------------------------


class AnthropicAdapter:
    """Messages API, with the system prompt and tools marked for prompt caching (they don't change
    between steps, so every step after the first reads them from the cache)."""

    provider = "anthropic"
    policy: CallPolicy | None = None  # timeouts and retries (ModelRouter sets it for the real SDK clients)
    CAPABILITIES = Capabilities(vision=True, tools=True, prompt_caching=True, context_tokens=200_000)

    def __init__(self, client, effort: str | None = None, thinking: str | None = None):
        self.client = client
        # None leaves the model's default. Both stay fixed for a task: changing either mid-task
        # invalidates the cached conversation.
        self.effort = effort
        self.thinking = thinking
        # The tools and system prompt are the same for every task, so their cache entry lives 1 hour (2026-10-21:
        # at launch traffic many tasks start more than 5 minutes after the last one; a cold first call measured
        # +0.5 s on Haiku, n=4). The conversation's breakpoints stay at the default 5 minutes: longer TTLs must
        # come first in the prefix, and tools and system render before messages. GA in the SDK, no beta header.
        # OPENMOB_PROMPT_CACHE_TTL=5m goes back to the default.
        # A provider that refuses the ttl (a gateway, an ANTHROPIC_BASE_URL, an older API) answers 400; the call is
        # then sent once more with the plain marker and the whole process keeps it (_ttl_refused; review I3).
        self._ttl_wanted = os.environ.get("OPENMOB_PROMPT_CACHE_TTL", "1h").strip().lower() == "1h"

    @property
    def prefix_cache(self) -> dict:
        if self._ttl_wanted and not _TTL_REFUSED.is_set():
            return {"type": "ephemeral", "ttl": "1h"}
        return {"type": "ephemeral"}

    def _create(self, request: ModelRequest, **extra):
        """messages.create through _call; a 400 that names the cache ttl is sent once more without it (I3)."""
        kwargs = self.request_kwargs(request)
        try:
            return _call(self.provider, self.client.messages.create, **extra, **_limits(self, request), **kwargs)
        except ModelError as exc:
            if not (self._ttl_wanted and not _TTL_REFUSED.is_set() and _refuses_ttl(exc.__cause__)):
                raise
            if not _TTL_REFUSED.is_set():
                _TTL_REFUSED.set()
                print("⚠️  The model provider refused the 1-hour prompt-cache ttl (400); using the default 5-minute "
                      "cache from now on (OPENMOB_PROMPT_CACHE_TTL=5m makes it permanent).", flush=True)
            return _call(self.provider, self.client.messages.create, **extra, **_limits(self, request),
                         **self.request_kwargs(request))

    def capabilities(self, model: str) -> Capabilities:
        return self.CAPABILITIES

    # Cache breakpoints in the conversation: Anthropic allows 4 per request, and system and tools take 2.
    HISTORY_BREAKPOINTS = 2

    def request_kwargs(self, request: ModelRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [self.message(m) for m in request.messages],
        }
        if request.cache_history:
            self.mark_history(kwargs["messages"])
        if request.system:
            kwargs["system"] = [{"type": "text", "text": request.system, "cache_control": dict(self.prefix_cache)}]
        if request.tools:
            tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in request.tools]
            tools[-1]["cache_control"] = dict(self.prefix_cache)
            kwargs["tools"] = tools
        if request.effort or self.effort:
            kwargs["output_config"] = {"effort": request.effort or self.effort}
        if self.thinking:
            kwargs["thinking"] = {"type": self.thinking}
        return kwargs

    @classmethod
    def mark_history(cls, messages: list[dict]) -> None:
        """Cache breakpoints at the end of the last two user messages: the newest (this call writes the
        conversation so far to the cache) and the one before (where the previous call wrote it, so this
        call reads everything up to there). Edits the request's own copy, never the agent's history."""
        marked = 0
        for message in reversed(messages):
            if marked == cls.HISTORY_BREAKPOINTS:
                break
            if message["role"] != "user" or not message["content"]:
                continue
            if isinstance(message["content"], str):
                message["content"] = [{"type": "text", "text": message["content"]}]
            message["content"][-1] = {**message["content"][-1], "cache_control": {"type": "ephemeral"}}
            marked += 1

    def complete(self, request: ModelRequest) -> ModelResponse:
        response = self._create(request)
        return ModelResponse(
            content=[self.block_in(b) for b in _get(response, "content") or []],
            stop_reason=_get(response, "stop_reason") or "end_turn",
            model=_get(response, "model"),
            usage=TokenUsage.from_anthropic(_get(response, "usage")),
        )

    def stream(self, request: ModelRequest):
        """The same call, streamed. Yields ("text", str) and ("tool_call", ToolCall) as each block
        completes, then ("response", ModelResponse) with everything, usage included. A tool call whose
        input doesn't parse (cut off by max_tokens) is not yielded, only kept in the response.
        Raises ModelError like complete()."""
        events = self._create(request, stream=True)
        blocks: dict[int, dict] = {}
        model, stop = None, None
        usage = TokenUsage()
        abort = getattr(request, "abort", None)
        try:
            for event in events:
                if abort is not None and abort.is_set():
                    # The task was stopped: close the connection so the model stops writing (and billing) a reply
                    # nobody will read. The agent stopped waiting on it already.
                    close = getattr(events, "close", None)
                    if close is not None:
                        close()
                    return
                kind = _get(event, "type")
                if kind == "message_start":
                    message = _get(event, "message")
                    model = _get(message, "model")
                    start = TokenUsage.from_anthropic(_get(message, "usage")) or TokenUsage()
                    usage = TokenUsage(start.input, start.output, start.cache_read, start.cache_write)
                elif kind == "content_block_start":
                    block = _get(event, "content_block")
                    data = dict(block) if isinstance(block, dict) else block.model_dump(exclude_none=True)
                    blocks[_get(event, "index")] = {"data": data, "json": "", "text": "", "thinking": "", "signature": ""}
                elif kind == "content_block_delta":
                    delta, held = _get(event, "delta"), blocks.get(_get(event, "index"))
                    if held is None:
                        continue
                    piece = _get(delta, "type")
                    if piece == "text_delta":
                        held["text"] += _get(delta, "text") or ""
                    elif piece == "input_json_delta":
                        held["json"] += _get(delta, "partial_json") or ""
                    elif piece == "thinking_delta":
                        held["thinking"] += _get(delta, "thinking") or ""
                    elif piece == "signature_delta":
                        held["signature"] += _get(delta, "signature") or ""
                elif kind == "content_block_stop":
                    held = blocks.get(_get(event, "index"))
                    if held is None:
                        continue
                    block = self._finish_block(held)
                    held["block"] = block
                    if block["type"] == "text" and block["text"]:
                        yield "text", block["text"]
                    elif block["type"] == "tool_call" and not held.get("broken"):
                        yield "tool_call", ToolCall(block["id"], block["name"], block["input"])
                elif kind == "message_delta":
                    stop = _get(_get(event, "delta"), "stop_reason") or stop
                    out = _get(_get(event, "usage"), "output_tokens")
                    if out is not None:
                        usage.output = out
        except GeneratorExit:  # the caller stopped reading (the task was stopped): hang up on the model
            close = getattr(events, "close", None)
            if close is not None:
                close()
            raise
        except ModelError:
            raise
        except Exception as exc:
            print(f"⚠️  {self.provider} stream failed: {exc!r}", flush=True)
            raise ModelError(f"The model request failed ({type(exc).__name__}).") from exc
        content = [held.get("block") or self._finish_block(held) for _, held in sorted(blocks.items())]
        yield "response", ModelResponse(content, stop or "end_turn", model, usage)

    @classmethod
    def _finish_block(cls, held: dict) -> dict:
        data = held["data"]
        kind = data.get("type")
        if kind == "text":
            return {"type": "text", "text": (data.get("text") or "") + held["text"]}
        if kind == "tool_use":
            try:
                args = json.loads(held["json"]) if held["json"].strip() else dict(data.get("input") or {})
            except json.JSONDecodeError:
                held["broken"] = True  # cut off mid-input: never run it
                args = {}
            return {"type": "tool_call", "id": data.get("id"), "name": data.get("name"),
                    "input": args if isinstance(args, dict) else {}}
        if kind == "thinking":
            data = {**data, "thinking": (data.get("thinking") or "") + held["thinking"],
                    "signature": (data.get("signature") or "") + held["signature"]}
        return {"type": "opaque", "provider": cls.provider, "data": data}

    @classmethod
    def message(cls, message: dict) -> dict:
        content = message["content"]
        if isinstance(content, str):
            return {"role": message["role"], "content": content}
        return {"role": message["role"], "content": [b for b in (cls.block_out(b) for b in content) if b is not None]}

    @classmethod
    def block_out(cls, block: dict) -> dict | None:
        kind = block["type"]
        if kind == "text":
            return {"type": "text", "text": block["text"]}
        if kind == "image":
            return {"type": "image", "source": {"type": "base64", "media_type": block["media_type"], "data": block["data"]}}
        if kind == "tool_call":
            return {"type": "tool_use", "id": block["id"], "name": block["name"], "input": block["input"]}
        if kind == "tool_result":
            out = {"type": "tool_result", "tool_use_id": block["call_id"],
                   "content": [cls.block_out(b) for b in block.get("content") or []]}
            if block.get("is_error"):
                out["is_error"] = True
            return out
        if kind == "opaque" and block.get("provider") == cls.provider:
            return block["data"]
        return None

    @classmethod
    def block_in(cls, block) -> dict:
        kind = _get(block, "type")
        if kind == "text":
            return {"type": "text", "text": _get(block, "text") or ""}
        if kind == "tool_use":
            return {"type": "tool_call", "id": _get(block, "id"), "name": _get(block, "name"), "input": dict(_get(block, "input") or {})}
        data = block if isinstance(block, dict) else block.model_dump(exclude_none=True)
        return {"type": "opaque", "provider": cls.provider, "data": data}


# --- OpenAI Chat Completions (OpenAI and compatible endpoints) ---------------

_OPENAI_STOP = {"tool_calls": "tool_use", "function_call": "tool_use", "stop": "end_turn",
                "length": "max_tokens", "content_filter": "refusal"}


class OpenAIAdapter:
    """Chat Completions with function tools and image input.

    Tool messages hold text only, so a screenshot that belongs with tool results goes in the user
    message that follows them. OpenAI caches long prompt prefixes automatically."""

    provider = "openai"
    policy: CallPolicy | None = None
    max_tokens_param = "max_completion_tokens"
    EXTRA_BODY: dict | None = None
    CAPABILITIES = Capabilities(vision=True, tools=True, prompt_caching=True, context_tokens=400_000)

    def __init__(self, client):
        self.client = client

    def capabilities(self, model: str) -> Capabilities:
        return self.CAPABILITIES

    def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": self.messages(request.system, request.messages),
            self.max_tokens_param: request.max_tokens,
        }
        if self.EXTRA_BODY:
            kwargs["extra_body"] = dict(self.EXTRA_BODY)
        if request.tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
                for t in request.tools
            ]
        response = _call(self.provider, self.client.chat.completions.create, **_limits(self, request), **kwargs)
        return self.response(response)

    @staticmethod
    def image_part(block: dict) -> dict:
        return {"type": "image_url", "image_url": {"url": f"data:{block['media_type']};base64,{block['data']}"}}

    @classmethod
    def messages(cls, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}] if system else []
        for message in messages:
            content = message["content"]
            if message["role"] == "assistant":
                blocks = _blocks(content)
                text = "".join(b["text"] for b in blocks if b["type"] == "text")
                entry: dict[str, Any] = {"role": "assistant", "content": text or None}
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                         for b in blocks if b["type"] == "tool_call"]
                if calls:
                    entry["tool_calls"] = calls
                elif not text:
                    entry["content"] = ""
                out.append(entry)
                continue
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            parts: list[dict] = []
            for block in content:
                if block["type"] == "tool_result":
                    text = _result_text(block) or "(no output)"
                    out.append({"role": "tool", "tool_call_id": block["call_id"],
                                "content": f"Error: {text}" if block.get("is_error") and not text.startswith("Error") else text})
                    parts.extend(cls.image_part(b) for b in _result_images(block))
                elif block["type"] == "text":
                    parts.append({"type": "text", "text": block["text"]})
                elif block["type"] == "image":
                    parts.append(cls.image_part(block))
            if parts:
                out.append({"role": "user", "content": parts})
        return out

    @classmethod
    def response(cls, response) -> ModelResponse:
        choice = (_get(response, "choices") or [None])[0]
        message = _get(choice, "message")
        content: list[dict] = []
        if text := _get(message, "content"):
            content.append({"type": "text", "text": text})
        for call in _get(message, "tool_calls") or []:
            function = _get(call, "function")
            if function is None:  # a custom (non-function) tool call: not one of ours
                continue
            try:
                args = json.loads(_get(function, "arguments") or "{}")
            except json.JSONDecodeError:
                args = {}  # the tool then reports what's missing, and the model retries
            content.append({"type": "tool_call", "id": _get(call, "id") or f"call_{uuid.uuid4().hex[:8]}",
                            "name": _get(function, "name"), "input": args if isinstance(args, dict) else {}})
        stop = _OPENAI_STOP.get(_get(choice, "finish_reason"), "other")
        if _get(message, "refusal"):
            stop = "refusal"
            if not content:
                content.append({"type": "text", "text": _get(message, "refusal")})
        elif any(b["type"] == "tool_call" for b in content):
            stop = "tool_use"
        usage = _get(response, "usage")
        tokens = None
        if usage is not None:
            cached = _get(_get(usage, "prompt_tokens_details"), "cached_tokens") or 0
            tokens = TokenUsage(input=(_get(usage, "prompt_tokens") or 0) - cached,
                                output=_get(usage, "completion_tokens") or 0, cache_read=cached)
        return ModelResponse(content, stop, _get(response, "model"), tokens)


class OpenAIResponsesAdapter(OpenAIAdapter):
    """Responses API for GPT-6 and Codex. Keep encrypted reasoning with tool calls so a
    stateless conversation can continue without storing phone content at the API."""

    def __init__(self, client, reasoning_effort: str = "low"):
        super().__init__(client)
        self.reasoning_effort = reasoning_effort

    def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": request.model, "input": self.input_items(request.messages),
            "max_output_tokens": request.max_tokens, "store": False,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": self.reasoning_effort},
        }
        if request.system:
            kwargs["instructions"] = request.system
        if request.tools:
            kwargs["tools"] = [
                {"type": "function", "name": t["name"], "description": t["description"],
                 "parameters": t["parameters"], "strict": False}
                for t in request.tools
            ]
        response = _call(self.provider, self.client.responses.create, **_limits(self, request), **kwargs)
        return self.response(response)

    @classmethod
    def input_items(cls, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for message in messages:
            parts: list[dict] = []

            def flush() -> None:
                if parts:
                    out.append({"role": message["role"], "content": list(parts)})
                    parts.clear()

            for block in _blocks(message["content"]):
                kind = block["type"]
                if kind == "text":
                    parts.append({"type": "input_text", "text": block["text"]})
                elif kind == "image":
                    parts.append({"type": "input_image", "image_url": f"data:{block['media_type']};base64,{block['data']}"})
                elif kind == "tool_call":
                    flush()
                    out.append({"type": "function_call", "call_id": block["id"], "name": block["name"],
                                "arguments": json.dumps(block["input"]), **(block.get("meta") or {}).get(cls.provider, {})})
                elif kind == "tool_result":
                    flush()
                    text = _result_text(block) or "(no output)"
                    out.append({"type": "function_call_output", "call_id": block["call_id"],
                                "output": f"Error: {text}" if block.get("is_error") else text})
                    parts.extend({"type": "input_image", "image_url": f"data:{b['media_type']};base64,{b['data']}"}
                                 for b in _result_images(block))
                elif kind == "opaque" and block.get("provider") == cls.provider:
                    flush()
                    out.append(block["data"])
            flush()
        return out

    @classmethod
    def response(cls, response) -> ModelResponse:
        if _get(response, "status") == "failed":
            raise ModelError("The model request failed.")
        content: list[dict] = []
        refused = False
        for item in _get(response, "output") or []:
            kind = _get(item, "type")
            if kind == "reasoning":
                data = item if isinstance(item, dict) else item.model_dump(exclude_none=True)
                content.append({"type": "opaque", "provider": cls.provider, "data": data})
            elif kind == "function_call":
                if _get(response, "status") == "incomplete":
                    continue  # never execute a tool call from a truncated or filtered response
                try:
                    args = json.loads(_get(item, "arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                meta = {k: _get(item, k) for k in ("id", "status") if _get(item, k) is not None}
                content.append({"type": "tool_call", "id": _get(item, "call_id"), "name": _get(item, "name"),
                                "input": args if isinstance(args, dict) else {}, "meta": {cls.provider: meta}})
            elif kind == "message":
                for part in _get(item, "content") or []:
                    if _get(part, "type") == "output_text":
                        content.append({"type": "text", "text": _get(part, "text")})
                    elif _get(part, "type") == "refusal":
                        refused = True
                        content.append({"type": "text", "text": _get(part, "refusal")})
        reason = _get(_get(response, "incomplete_details"), "reason")
        stop = ("refusal" if refused or reason == "content_filter" else "max_tokens" if reason == "max_output_tokens" else
                "tool_use" if any(b["type"] == "tool_call" for b in content) else "end_turn")
        usage = _get(response, "usage")
        tokens = None
        if usage is not None:
            cached = _get(_get(usage, "input_tokens_details"), "cached_tokens") or 0
            tokens = TokenUsage(input=(_get(usage, "input_tokens") or 0) - cached,
                                output=_get(usage, "output_tokens") or 0, cache_read=cached)
        return ModelResponse(content, stop, _get(response, "model"), tokens)


class OpenAICompatibleAdapter(OpenAIAdapter):
    """Any Chat Completions endpoint at a base_url (vLLM, Ollama, LM Studio, OpenRouter…). What the
    model can do isn't discoverable, so the config says (vision, tools, context)."""

    provider = "openai_compatible"
    max_tokens_param = "max_tokens"  # widely supported; max_completion_tokens is not
    CAPABILITIES = Capabilities(vision=True, tools=True, prompt_caching=False, context_tokens=32_000)

    def __init__(self, client, capabilities: Capabilities | None = None):
        super().__init__(client)
        self._capabilities = capabilities or self.CAPABILITIES

    def capabilities(self, model: str) -> Capabilities:
        return self._capabilities


class QwenAdapter(OpenAICompatibleAdapter):
    """Model Studio's OpenAI-compatible API; non-thinking mode for the synchronous phone loop."""

    provider = "qwen"
    EXTRA_BODY = {"enable_thinking": False}
    CAPABILITIES = Capabilities(vision=True, tools=True, prompt_caching=True, context_tokens=1_000_000)


class XAIAdapter(OpenAIResponsesAdapter):
    """xAI Responses, preserving Grok's encrypted reasoning through tool calls."""

    provider = "xai"
    CAPABILITIES = Capabilities(vision=True, tools=True, prompt_caching=True, context_tokens=500_000)


# --- Google Gemini (google-genai) --------------------------------------------

_GEMINI_REFUSALS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "IMAGE_SAFETY"}


class GeminiAdapter:
    """generate_content with function declarations. Requests are plain dicts, which the SDK
    validates into its types. Gemini 3 rejects a history whose function calls lost their thought
    signatures, so those ride along in each block's `meta`. Gemini caches prefixes implicitly."""

    provider = "google"
    policy: CallPolicy | None = None
    CAPABILITIES = Capabilities(vision=True, tools=True, prompt_caching=True, context_tokens=1_000_000)

    def __init__(self, client, thinking_level: str | None = None):
        self.client = client
        self.thinking_level = thinking_level

    def capabilities(self, model: str) -> Capabilities:
        return self.CAPABILITIES

    def complete(self, request: ModelRequest) -> ModelResponse:
        config: dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
            "automatic_function_calling": {"disable": True},  # the agent loop runs the tools
        }
        if request.system:
            config["system_instruction"] = request.system
        if self.thinking_level:
            config["thinking_config"] = {"thinking_level": self.thinking_level}
        if request.tools:
            config["tools"] = [{"function_declarations": [
                {"name": t["name"], "description": t["description"], "parameters_json_schema": t["parameters"]}
                for t in request.tools
            ]}]
        limits = _limits(self, request, timeout_key=None)
        if limits.get("timeout_s"):  # the SDK takes milliseconds, per request, in the config
            config["http_options"] = {"timeout": int(limits["timeout_s"] * 1000)}
        response = _call(self.provider, self.client.models.generate_content, **limits,
                         model=request.model, contents=self.contents(request.messages), config=config)
        return self.response(response)

    @classmethod
    def contents(cls, messages: list[dict]) -> list[dict]:
        names: dict[str, str] = {}  # call id -> function name: Gemini's function_response needs the name
        out = []
        for message in messages:
            parts: list[dict] = []
            for block in _blocks(message["content"]):
                kind = block["type"]
                signature = (block.get("meta") or {}).get(cls.provider, {}).get("thought_signature")
                if kind == "text":
                    part: dict[str, Any] = {"text": block["text"]}
                elif kind == "image":
                    part = {"inline_data": {"mime_type": block["media_type"], "data": base64.b64decode(block["data"])}}
                elif kind == "tool_call":
                    names[block["id"]] = block["name"]
                    call = {"name": block["name"], "args": block["input"]}
                    if not block["id"].startswith("gemini_"):  # an id Gemini issued: send it back
                        call["id"] = block["id"]
                    part = {"function_call": call}
                elif kind == "tool_result":
                    text = _result_text(block)
                    reply = {"name": names.get(block["call_id"], "unknown"),
                             "response": {"error": text} if block.get("is_error") else {"output": text}}
                    if not block["call_id"].startswith("gemini_"):
                        reply["id"] = block["call_id"]
                    parts.append({"function_response": reply})
                    parts.extend({"inline_data": {"mime_type": b["media_type"], "data": base64.b64decode(b["data"])}}
                                 for b in _result_images(block))
                    continue
                elif kind == "opaque" and block.get("provider") == cls.provider:
                    part = dict(block["data"])
                else:
                    continue
                if signature:
                    part["thought_signature"] = signature
                parts.append(part)
            if parts:
                out.append({"role": "model" if message["role"] == "assistant" else "user", "parts": parts})
        return out

    @classmethod
    def response(cls, response) -> ModelResponse:
        candidates = _get(response, "candidates") or []
        candidate = candidates[0] if candidates else None
        content: list[dict] = []
        for part in _get(_get(candidate, "content"), "parts") or []:
            signature = _get(part, "thought_signature")
            meta = {"meta": {cls.provider: {"thought_signature": signature}}} if signature else {}
            call = _get(part, "function_call")
            if call is not None:
                content.append({"type": "tool_call", "id": _get(call, "id") or f"gemini_{uuid.uuid4().hex[:8]}",
                                "name": _get(call, "name"), "input": dict(_get(call, "args") or {}), **meta})
            elif _get(part, "thought"):  # a thought summary: not for the user, but sent back as is
                data = part if isinstance(part, dict) else part.model_dump(exclude_none=True)
                content.append({"type": "opaque", "provider": cls.provider, "data": data})
            elif _get(part, "text") is not None:
                content.append({"type": "text", "text": _get(part, "text"), **meta})
        reason = _get(candidate, "finish_reason")
        reason = str(_get(reason, "name", reason) or "")
        if any(b["type"] == "tool_call" for b in content):
            stop = "tool_use"
        elif reason in _GEMINI_REFUSALS or (candidate is None and _get(_get(response, "prompt_feedback"), "block_reason")):
            stop = "refusal"
        else:
            stop = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}.get(reason, "other")
        usage = _get(response, "usage_metadata")
        tokens = None
        if usage is not None:
            cached = _get(usage, "cached_content_token_count") or 0
            tokens = TokenUsage(input=(_get(usage, "prompt_token_count") or 0) - cached,
                                output=(_get(usage, "candidates_token_count") or 0) + (_get(usage, "thoughts_token_count") or 0),
                                cache_read=cached)
        return ModelResponse(content, stop, _get(response, "model_version"), tokens)


# --- which adapter serves which model ----------------------------------------


@dataclass
class ModelSpec:
    id: str
    label: str
    provider: str
    options: dict = field(default_factory=dict)  # base_url, api_key_env, max_tokens, vision, tools, context

    @property
    def max_tokens(self) -> int:
        return int(self.options.get("max_tokens") or DEFAULT_MAX_TOKENS)


def model_spec(cfg: Config, model: str) -> ModelSpec | None:
    """The configured entry for a model id: from `models:`, else a tier naming it, else its name."""
    for entry in cfg.models:
        if entry["id"] == model:
            options = {k: v for k, v in entry.items() if k not in ("id", "label", "provider")}
            return ModelSpec(entry["id"], entry.get("label") or entry["id"], entry.get("provider") or infer_provider(model) or "", options)
    for tier in cfg.api_tiers.values():
        if tier.get("model") == model and tier.get("provider"):
            return ModelSpec(model, model, tier["provider"])
    provider = infer_provider(model)
    return ModelSpec(model, model, provider) if provider else None


def _key(cfg: Config, spec: ModelSpec) -> str | None:
    if env := spec.options.get("api_key_env"):
        return os.environ.get(env)
    return {"anthropic": cfg.api_key, "openai": cfg.openai_api_key, "google": cfg.google_api_key,
            "qwen": cfg.qwen_api_key, "xai": cfg.xai_api_key,
            "openai_compatible": cfg.compatible_api_key}.get(spec.provider)


def _base_url(cfg: Config, spec: ModelSpec) -> str | None:
    return spec.options.get("base_url") or {
        "openai_compatible": cfg.openai_compatible_base_url,
        "qwen": cfg.qwen_base_url, "xai": cfg.xai_base_url,
    }.get(spec.provider)


def provider_ready(cfg: Config, spec: ModelSpec) -> bool:
    """Whether this server can call the model's provider: a key, or for compatible endpoints a base_url."""
    if spec.provider == "openai_compatible":
        return bool(_base_url(cfg, spec))
    return spec.provider in PROVIDERS and bool(_key(cfg, spec))


def _capabilities(adapter_caps: Capabilities, spec: ModelSpec) -> Capabilities:
    o = spec.options
    return Capabilities(
        vision=bool(o.get("vision", adapter_caps.vision)),
        tools=bool(o.get("tools", adapter_caps.tools)),
        prompt_caching=adapter_caps.prompt_caching,
        context_tokens=int(o.get("context") or adapter_caps.context_tokens),
    )


_DEFAULT_CAPS = {a.provider: a.CAPABILITIES for a in
                 (AnthropicAdapter, OpenAIAdapter, GeminiAdapter, QwenAdapter, XAIAdapter, OpenAICompatibleAdapter)}


def model_capabilities(spec: ModelSpec) -> Capabilities:
    return _capabilities(_DEFAULT_CAPS.get(spec.provider, Capabilities(vision=False, tools=False)), spec)


def model_listing(cfg: Config) -> dict:
    """What the dashboard's model picker shows: every allowlisted model, and whether it can run here
    (its provider has a key, and it can see screenshots and call tools)."""
    models = []
    for entry in cfg.models:
        spec = model_spec(cfg, entry["id"])
        models.append({
            "id": entry["id"], "label": entry.get("label") or entry["id"], "provider": spec.provider,
            "available": provider_ready(cfg, spec) and model_capabilities(spec).operates_phone,
        })
    return {"default": cfg.model, "models": models}


# The phone's model sheet (docs/phone-protocol.md §3.5): a short description and a speed class per model.
# Config may set `description` and `speed` on a `models:` entry; else these, by model family; else none.
PHONE_SPEEDS = ("fast", "medium", "slow")
_PHONE_MODEL_INFO = (
    ("claude-haiku", "Fastest. Recommended for phone tasks", "fast"),
    ("claude-sonnet", "Slower per step. Better on tricky screens", "medium"),
    ("claude-opus", "Slowest. For long, multi-app tasks", "slow"),
)
PHONE_EFFORTS = ("auto", "low", "medium", "high")


def phone_model_list(cfg: Config, available: Callable[[str], bool]) -> list[dict]:
    """The models this phone may pick: allowlisted (cfg.models) AND runnable here (`available`: the provider has a
    key and the model can operate a phone). Only id, label, description, speed, the group ("main" for Claude,
    "more" for other providers) and whether the effort setting applies: never a provider's keys, base URLs or other
    options."""
    out = []
    for entry in cfg.models:
        model_id = entry["id"]
        try:
            if not available(model_id):
                continue
        except Exception:  # an unknown provider or a broken entry: not offered
            continue
        family = next((info for info in _PHONE_MODEL_INFO if model_id.startswith(info[0])), None)
        description = str(entry.get("description") or (family[1] if family else ""))[:80]
        speed = entry.get("speed") if entry.get("speed") in PHONE_SPEEDS else (family[2] if family else "medium")
        claude = entry.get("provider") == "anthropic"
        out.append({
            "id": model_id,
            # The dashboard's labels carry notes in parentheses ("Haiku 5.5 (fastest, cheapest)"): the name only.
            "label": str(entry.get("label") or model_id).split(" (")[0][:40],
            "description": description, "speed": speed,
            "group": "main" if claude else "more", "effort": claude,
        })
    return out


@dataclass
class Route:
    adapter: ModelAdapter
    spec: ModelSpec
    capabilities: Capabilities


class ModelRouter:
    """Model id -> the adapter that serves it, with SDK clients made on first use and reused.

    `clients` injects ready clients by provider (tests, or a caller with its own client); a provider
    with an injected client counts as available."""

    def __init__(self, cfg: Config, clients: dict[str, Any] | None = None):
        self.cfg = cfg
        self._injected = dict(clients or {})
        self._clients: dict[tuple, Any] = {}
        self._lock = threading.Lock()

    def available(self, model: str) -> bool:
        spec = model_spec(self.cfg, model)
        if spec is None:
            return False
        ready = spec.provider in self._injected or provider_ready(self.cfg, spec)
        return ready and model_capabilities(spec).operates_phone

    def route(self, model: str) -> Route:
        spec = model_spec(self.cfg, model)
        if spec is None:
            raise ModelUnavailable(f"No provider is configured for the model {model!r}.")
        if not self.available(model):
            raise ModelUnavailable("The selected model isn't set up on this server (its provider has no API key).")
        client = self._injected.get(spec.provider) or self._client(spec)
        adapter: ModelAdapter
        if spec.provider == "anthropic":
            adapter = AnthropicAdapter(client, spec.options.get("effort"), spec.options.get("thinking"))
        elif spec.provider == "openai":
            if model.startswith("gpt-6") or "codex" in model.lower():
                adapter = OpenAIResponsesAdapter(client, spec.options.get("reasoning_effort", "low"))
            else:
                adapter = OpenAIAdapter(client)
        elif spec.provider == "google":
            adapter = GeminiAdapter(client, spec.options.get("thinking_level"))
        elif spec.provider == "qwen":
            adapter = QwenAdapter(client, model_capabilities(spec))
        elif spec.provider == "xai":
            adapter = XAIAdapter(client, spec.options.get("reasoning_effort", "low"))
        else:
            adapter = OpenAICompatibleAdapter(client, model_capabilities(spec))
        if spec.provider not in self._injected:  # injected clients are tests' fakes: their calls stay as they are
            adapter.policy = CallPolicy.from_config(self.cfg, spec.provider)
        return Route(adapter, spec, _capabilities(adapter.capabilities(model), spec))

    def complete_text(self, model: str, prompt: str, max_tokens: int = 100) -> str:
        """A one-shot text question (no tools, no screenshot), e.g. picking an app by name. A thinking
        model spends part of max_tokens on thought, so the model's own limit is the floor: a short
        answer stays short, but the thinking can't use up the room for it."""
        route = self.route(model)
        limit = max(max_tokens, route.spec.max_tokens)
        response = route.adapter.complete(ModelRequest(model, "", [], [{"role": "user", "content": prompt}], limit))
        return "".join(response.text).strip()

    def _client(self, spec: ModelSpec):
        key = _key(self.cfg, spec)
        base_url = _base_url(self.cfg, spec)
        with self._lock:
            cache_key = (spec.provider, base_url, key)
            if cache_key not in self._clients:
                self._clients[cache_key] = make_client(spec.provider, key, base_url, self.cfg)
            return self._clients[cache_key]


def _sdk_limits(cfg: Config | None, provider: str | None = None) -> dict[str, Any]:
    """Anthropic and OpenAI SDK clients: no retries of their own (_call retries, with shorter waits) and the long
    timeout as the ceiling for any call that doesn't set its own. Nothing when the policy is off (for `provider`)."""
    policy = CallPolicy.from_config(cfg, provider) if cfg else None
    return {} if policy is None else {"timeout": policy.long_timeout_s, "max_retries": 0}


def make_client(provider: str, api_key: str | None, base_url: str | None = None, cfg: Config | None = None):
    """The provider's official SDK client. Each SDK is an optional extra: pip install -e '.[openai]'."""
    try:
        if provider == "anthropic":
            import anthropic

            headers = {"anthropic-workspace-id": cfg.workspace_id} if cfg and cfg.workspace_id else None
            return anthropic.Anthropic(api_key=api_key, default_headers=headers, **_sdk_limits(cfg, provider))
        if provider in ("openai", "openai_compatible", "qwen", "xai"):
            import openai

            # Local servers usually take any key, but the SDK insists on one.
            return openai.OpenAI(api_key=api_key or "not-needed", base_url=base_url, **_sdk_limits(cfg, provider))
        if provider == "google":
            from google import genai

            policy = CallPolicy.from_config(cfg) if cfg else None
            if policy is None:
                return genai.Client(api_key=api_key)
            return genai.Client(api_key=api_key, http_options={"timeout": int(policy.long_timeout_s * 1000)})
    except ImportError as exc:
        extra = {"openai": "openai", "openai_compatible": "openai", "qwen": "openai", "xai": "openai",
                 "google": "gemini"}.get(provider, provider)
        raise ModelUnavailable(f"This server is missing the SDK for that model: pip install -e '.[{extra}]'") from exc
    raise ModelUnavailable(f"Unknown provider {provider!r}.")


def router_for(client, cfg: Config) -> ModelRouter:
    """The agent's router: given as is, or (older callers and tests) one Anthropic-shaped client."""
    if isinstance(client, ModelRouter):
        return client
    return ModelRouter(cfg, {"anthropic": client})
