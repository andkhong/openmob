"""The phone's model picker (docs/phone-protocol.md §3.5): which models this phone may pick, and its `set_model`.

Not a safety setting: no screen lock. It sets only the agent's model and effort for this phone's next tasks, the
same two things the dashboard's model picker sets (POST /api/devices/{id}/model). It never touches the permission
mode, approvals or the gatekeeper. The message comes only from the OpenMob app over the phone's own WebSocket; the
agent can't send it (it has no access to that socket, and the phone's gatekeeper refuses its taps on OpenMob's own
screens).
"""

from __future__ import annotations

from .agent.models import PHONE_EFFORTS, phone_model_list
from .config import Config


def model_state(cfg: Config, agent) -> dict | None:
    """The `model_state` message for this phone, or None when no model can run here (the phone hides its chip)."""
    models = phone_model_list(cfg, agent.model_available)
    if not models:
        return None
    current = agent.model if any(m["id"] == agent.model for m in models) else models[0]["id"]
    return {"type": "model_state", "models": models, "model": current, "effort": agent.effort or "auto"}


def set_model(cfg: Config, agent, message: dict, running: bool) -> dict:
    """Apply a phone's `set_model` {model, effort}. The model must be one this server offers this phone (its own
    list, never the phone's word); effort is auto | low | medium | high. Returns the `model_set` reply."""
    model = str(message.get("model") or "")
    effort = str(message.get("effort") or "auto")
    offered = {m["id"] for m in phone_model_list(cfg, agent.model_available)}
    if model not in offered:
        return {"type": "model_set", "ok": False, "error": "not_offered"}
    if effort not in PHONE_EFFORTS:
        return {"type": "model_set", "ok": False, "error": "bad_effort"}
    agent.model = model
    agent.effort = None if effort == "auto" else effort
    return {"type": "model_set", "ok": True, "model": model, "effort": effort,
            "applies": "next task" if running else "now"}
