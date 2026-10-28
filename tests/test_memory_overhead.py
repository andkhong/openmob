"""The in-process memory overhead check (bench/memory_overhead.py, ruling R14) and `openmob bench --memory-account`."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from openmob import bench
from openmob.memory import Memory

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("memory_overhead", ROOT / "bench" / "memory_overhead.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["memory_overhead"] = module
    spec.loader.exec_module(module)
    return module


def test_memory_adds_no_model_call_and_keeps_the_cached_prefix(tmp_path):
    overhead = _load()
    rows = overhead.measure(bench.load_tasks(ROOT / "bench" / "vision_tasks.yaml"), tmp_path, repeats=3)
    assert len(rows) == 3
    for r in rows:
        assert r["extra_model_calls"] == 0 and r["system_identical"] and r["tools_prefix_ok"]
        assert r["tools_appended"] == ["remember", "recall"]
        assert r["memory_ms_median"] < 10 and r["block_chars"] <= 1600
    # The Clock task gets the Clock note and the about-you notes; no person line (the request names no person).
    clock = next(r for r in rows if r["task"] == "clock-stopwatch")
    assert clock["block_chars"] > 0 and clock["block_tokens_est"] == round(clock["block_chars"] / 4)


def test_seed_file_has_the_three_kinds_and_fifteen_extras(tmp_path):
    store = Memory(tmp_path / "m.sqlite")
    assert bench.seed_memory(store, "acct") == 1 + 1 + 1 + 15
    notes = store.list("acct", status="active")
    assert {n["kind"] for n in notes} == {"about_you", "app", "person"} and len(notes) == 18
    assert next(n for n in notes if n["kind"] == "app")["package"] == "com.google.android.deskclock"


def test_memory_account_option_wires_a_seeded_store_into_the_agent(monkeypatch):
    import openmob.main as main_module
    from openmob.config import Config

    built, runs = [], []

    class FakeAgent:
        def __init__(self, cfg, memory):
            self.cfg, self.memory, self.account_id = cfg, memory, None
            self.timer = SimpleNamespace(task_totals=lambda: {})
            self.usage = SimpleNamespace(as_dict=lambda: {})

        def run(self, instruction, **kw):
            runs.append(kw)
            return SimpleNamespace(success=True, steps=1, summary="", timings={}, usage=SimpleNamespace(as_dict=lambda: {}),
                                   fast_steps=0)

    def fake_build(cfg, io, driver=None, label_cache=None, memory=None):
        agent = FakeAgent(cfg, memory)
        built.append(agent)
        return agent

    monkeypatch.setattr(main_module, "build_agent", fake_build)
    args = SimpleNamespace(tasks=str(ROOT / "bench" / "vision_tasks.yaml"), conditions=None, only="off", serial=None,
                           model=None, no_home=True, memory_account="owner-1")
    bench.main(Config(), args)
    assert built and all(a.memory is not None and a.account_id == "owner-1" and a.cfg.memory for a in built)
    assert len(built[0].memory.list("owner-1", status="active")) == 18  # seeded, active
    assert runs and all(kw.get("memory_allowed") is True for kw in runs)
    # Without the option nothing changes: no store, memory_allowed not passed.
    built.clear(), runs.clear()
    args.memory_account = None
    bench.main(Config(), args)
    assert all(a.memory is None for a in built) and all("memory_allowed" not in kw for kw in runs)
