"""In-process cost of preferences memory (docs/benchmarks.md, "Memory overhead"; ruling R14).

Runs the real Agent loop with a scripted model and a fake phone, the bench task set's requests with memory off and
on, against a store seeded from bench/memory_seed.yaml. Reports, per task: `memory_ms` (median / max over the
repeats), the injected block's size in characters and an ESTIMATED token count (chars / 4), the model calls on and
off (the difference must be 0 for a request with no "my ..." possessive), and whether the system prompt and the
tools prefix are byte-identical (the cache property).

It measures the server-side retrieval only. Real-provider cache_read_tokens and on-phone latency are not measured here.

    python bench/memory_overhead.py [tasks.yaml] [--repeats 20]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]  # the test doubles: FakeDriver, ScriptedClient, RecordingIO

from conftest import FakeDriver, RecordingIO, ScriptedClient, system_text, tool_use  # noqa: E402

from openmob.agent.loop import Agent  # noqa: E402
from openmob.bench import load_tasks, seed_memory  # noqa: E402
from openmob.config import Config  # noqa: E402
from openmob.memory import Memory  # noqa: E402
from openmob.phone.apps import AppResolver  # noqa: E402

CLOCK = "com.google.android.deskclock"
PACKAGES = ["com.android.settings", CLOCK, "com.android.chrome"]
LABELS = {"com.android.settings": "Settings", CLOCK: "Clock", "com.android.chrome": "Chrome"}
DONE = [tool_use("done", "d", summary="ok", success=True)]


def _strip(tools) -> list:
    return [{k: v for k, v in t.items() if k != "cache_control"} for t in tools]  # the last tool carries the marker


def _run(request: str, workdir: Path, store, on: bool):
    driver = FakeDriver(packages=PACKAGES, labels=LABELS)
    resolver = AppResolver(driver, label_cache=workdir / "labels.json")
    client = ScriptedClient([DONE])
    agent = Agent(client, driver, resolver, Config(settle_delay=0, launch_settle_delay=0, memory=on), RecordingIO(),
                  use_ocr=False)
    agent.memory = store if on else None
    resolver.ensure_labels()  # the installed-app index, read when the phone connected
    result = agent.run(request, isolated=True, memory_allowed=on)
    return client, result


def measure(tasks, workdir: Path, repeats: int = 20) -> list[dict]:
    store = Memory(workdir / "memory.sqlite")
    seed_memory(store, None)
    rows = []
    for task in tasks:
        times, block = [], 0
        for _ in range(repeats):  # interleaved: off, on, off, on
            off_client, _ = _run(task.instruction, workdir, store, False)
            on_client, result = _run(task.instruction, workdir, store, True)
            times.append(result.timings["memory_ms"])
            first = on_client.requests[0]["messages"][0]["content"][0]["text"]
            block = len(first) - len(f"Request: {task.instruction}\n\n")
        off_tools, on_tools = _strip(off_client.requests[0]["tools"]), _strip(on_client.requests[0]["tools"])
        rows.append({
            "task": task.name,
            "memory_ms_median": statistics.median(times),
            "memory_ms_max": max(times),
            "block_chars": max(block, 0),
            "block_tokens_est": round(max(block, 0) / 4),
            "extra_model_calls": len(on_client.requests) - len(off_client.requests),
            "system_identical": system_text(on_client.requests[0]) == system_text(off_client.requests[0]),
            "tools_prefix_ok": on_tools[:len(off_tools)] == off_tools and len(on_tools) > len(off_tools),
            "tools_appended": [t["name"] for t in on_tools[len(off_tools):]],
        })
    store.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", nargs="?", default=str(ROOT / "bench" / "vision_tasks.yaml"))
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="openmob-memory-overhead-") as tmp:
        rows = measure(load_tasks(args.tasks), Path(tmp), args.repeats)
    print(f"{'task':<40}{'ms med':>8}{'ms max':>8}{'chars':>7}{'tok~':>6}{'extra':>6}{'sys=':>6}{'tools':>7}")
    for r in rows:
        print(f"{r['task'][:39]:<40}{r['memory_ms_median']:>8.2f}{r['memory_ms_max']:>8.2f}{r['block_chars']:>7}"
              f"{r['block_tokens_est']:>6}{r['extra_model_calls']:>6}{str(r['system_identical']):>6}"
              f"{str(r['tools_prefix_ok']):>7}")
    print("tok~ = chars / 4, an estimate. tools: the off list is a strict prefix of the on list; appended: "
          + ", ".join(rows[0]["tools_appended"]))


if __name__ == "__main__":
    main()
