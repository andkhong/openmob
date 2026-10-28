"""Server load test: many fake phones running tasks at once against one in-process server.

    .venv/bin/python bench/load_server.py --phones 30 --tasks 4 --steps 6 --model-ms 300
    .venv/bin/python bench/load_server.py --phones 30 --history-writer off     # history writes inline (as before)

The server (FastAPI + DeviceManager + History, token mode) runs in this process on a free port (never 8765), with a
fake model that sleeps --model-ms and then scrolls (--steps times) or finishes. The phones run in a child process
(tests/test_remote.FakePhone: the real phone protocol over a WebSocket, backed by tests/conftest.FakeDriver), so
the CPU and memory numbers are the server's own. Each phone sends --tasks commands one after another, all phones at
once. Measured and printed as JSON:

- event-loop lag: a coroutine on the server's loop asks for 10 ms sleeps; how late they wake (p50/p99/max);
- server time per step: the steps table's total_ms minus model_ms (observe, action, settle 0: the server's work plus
  the WebSocket round trips to the fake phones); and task wall time per step seen by the phones minus the model's;
- history time on the caller's thread (record / record_step: what the agent and the event paths wait for);
- CPU (user+system seconds of this process / wall) and peak RSS.

This measures this Mac, not a Fly shared-cpu-2x machine; read the numbers as relative (before/after), not as prod.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "tests"))

TOKEN = "load-test-token"


def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != 8765:  # the owner's live server
            return port


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(p / 100 * len(values)))], 2)


class FakeModel:
    """Anthropic-shaped client: after model_ms, scroll down `steps` times, then done."""

    def __init__(self, steps: int, model_ms: float):
        self.steps, self.model_ms = steps, model_ms
        self.messages = self

    def create(self, **kwargs):
        time.sleep(self.model_ms / 1000)
        turns = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        if turns < self.steps:
            block = SimpleNamespace(type="tool_use", id=f"s{turns}", name="scroll", input={"direction": "down"})
        else:
            block = SimpleNamespace(type="tool_use", id="d", name="done", input={"summary": "Finished.",
                                                                                "success": True})
        return SimpleNamespace(content=[block], stop_reason="tool_use", model="fake", usage=None)


# --- the phones (child process) ---------------------------------------------------------------------------------


def run_phones(url: str, phones: int, tasks: int) -> None:
    from conftest import FakeDriver
    from test_remote import FakePhone

    results: list[dict] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        driver = FakeDriver(packages=["com.android.settings"], labels={"com.android.settings": "Settings"})
        driver.package = "com.android.settings"
        phone = FakePhone(url, driver, device_id=f"load{i}", token=TOKEN)
        if not phone.welcome.wait(30):
            with lock:
                results.append({"phone": i, "error": "no welcome"})
            return
        for t in range(tasks):
            # A command sent in the instant after a result, while the task is still wrapping up, is taken as a
            # correction to that task and lost (seen in this harness, 2026-10-20): leave a human-sized gap.
            time.sleep(0.2)
            done_before = sum(1 for k, _ in phone.events if k in ("result", "error"))
            started = time.monotonic()
            phone.send({"type": "command", "text": f"scroll through settings {t}"})
            deadline = started + 180
            while time.monotonic() < deadline:
                finals = [(k, m) for k, m in phone.events if k in ("result", "error")]
                if len(finals) > done_before:
                    break
                time.sleep(0.005)
            finals = [(k, m) for k, m in phone.events if k in ("result", "error")]
            ok = len(finals) > done_before and finals[-1][0] == "result"
            with lock:
                results.append({"phone": i, "task": t, "ok": ok, "wall_s": time.monotonic() - started,
                                **({} if ok else {"last_events": phone.events[-4:]})})
        phone.disconnect()

    threads = [threading.Thread(target=one, args=(i,)) for i in range(phones)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    print(json.dumps({"results": results}), flush=True)


# --- the server (this process) ----------------------------------------------------------------------------------


def run_server(args) -> dict:
    os.environ.setdefault("OPENMOB_DATA_DIR", tempfile.mkdtemp(prefix="openmob-load-"))
    from openmob.agent.loop import Agent
    from openmob.config import Config
    from openmob.devices import DeviceManager
    from openmob.history import History
    from openmob.phone.apps import AppResolver
    from openmob.server import create_app, serve_in_background
    from openmob.voice.tts import Speaker

    data = Path(os.environ["OPENMOB_DATA_DIR"])
    try:
        history = History(data / "history.sqlite", background=args.history_writer == "on")
    except TypeError:  # a checkout from before the background writer (to measure "before" on the same script)
        history = History(data / "history.sqlite")
        history.flush = lambda: True
        args.history_writer = "none (before 2026-10-20)"

    # Time spent in history writes on the calling thread (the agent's, the event paths').
    write_ms: list[float] = []
    for name in ("record", "record_step"):
        original = getattr(history, name)

        def timed(*a, _original=original, **k):
            t0 = time.perf_counter()
            try:
                return _original(*a, **k)
            finally:
                write_ms.append((time.perf_counter() - t0) * 1000)
        setattr(history, name, timed)

    def build_agent(cfg, io, driver, label_cache):
        resolver = AppResolver(driver, label_cache=data / "labels.json")
        return Agent(FakeModel(args.steps, args.model_ms), driver, resolver, cfg, io, use_ocr=False)

    cfg = Config(settle_delay=0, launch_settle_delay=0, scroll_settle_delay=0, adaptive_settle=False,
                 jev_enabled=False, speak=False, fast_path="off", replay_paths=False, plan_execute=False,
                 deep_links=False, app_links=False)
    manager = DeviceManager(cfg, build_agent, Speaker(enabled=False), adb_discovery=False, history=history)
    app = create_app(manager, token=TOKEN)

    lags: list[float] = []
    stop = threading.Event()

    async def lag_monitor():
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            t0 = loop.time()
            await asyncio.sleep(0.01)
            lags.append((loop.time() - t0 - 0.01) * 1000)

    async def start_monitor():  # a request handler runs on the server's loop: start the monitor there
        asyncio.get_running_loop().create_task(lag_monitor())
        return {"ok": True}

    app.add_api_route("/__load_lag", start_monitor, methods=["GET"])
    port = free_port()
    serve_in_background(app, "127.0.0.1", port)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.05)

    import urllib.request

    urllib.request.urlopen(f"http://127.0.0.1:{port}/__load_lag?t={TOKEN}", timeout=5).read()
    time.sleep(0.5)
    if not lags:
        raise SystemExit("the event-loop monitor didn't start")
    lags.clear()
    usage0, wall0 = resource.getrusage(resource.RUSAGE_SELF), time.monotonic()
    child = subprocess.run([sys.executable, __file__, "--phones-role", "--url", f"ws://127.0.0.1:{port}",
                            "--phones", str(args.phones), "--tasks", str(args.tasks)],
                           capture_output=True, text=True, timeout=1800)
    wall = time.monotonic() - wall0
    usage1 = resource.getrusage(resource.RUSAGE_SELF)
    stop.set()
    lines = [line for line in child.stdout.splitlines() if line.startswith('{"results"')]
    if not lines:
        raise SystemExit(f"the phones failed:\n{child.stdout[-2000:]}\n{child.stderr[-4000:]}")
    results = json.loads(lines[-1])["results"]
    history.flush()
    rows = history._q("SELECT total_ms, model_ms FROM steps WHERE total_ms IS NOT NULL")
    server_ms = [r["total_ms"] - (r["model_ms"] or 0) for r in rows]
    ok = [r for r in results if r.get("ok")]
    per_step = [(r["wall_s"] * 1000 - (args.steps + 1) * args.model_ms) / (args.steps + 1) for r in ok]
    cpu = (usage1.ru_utime - usage0.ru_utime) + (usage1.ru_stime - usage0.ru_stime)
    rss = usage1.ru_maxrss / (1 if sys.platform == "darwin" else 1 / 1024)  # bytes on macOS, KiB on Linux
    failed = [r for r in results if not r.get("ok")]
    return {
        "failed_examples": failed[:3],
        "phones": args.phones, "tasks_per_phone": args.tasks, "steps_per_task": args.steps + 1,
        "model_ms": args.model_ms, "history_writer": args.history_writer,
        "tasks_ok": len(ok), "tasks_total": len(results), "wall_s": round(wall, 1),
        "loop_lag_ms": {"p50": pct(lags, 50), "p99": pct(lags, 99), "max": round(max(lags), 2) if lags else None,
                        "samples": len(lags)},
        "server_ms_per_step": {"p50": pct(server_ms, 50), "p95": pct(server_ms, 95), "p99": pct(server_ms, 99),
                               "steps": len(server_ms)},
        "phone_seen_overhead_ms_per_step": {"p50": pct(per_step, 50), "p95": pct(per_step, 95)},
        "history_call_ms": {"p50": pct(write_ms, 50), "p99": pct(write_ms, 99),
                            "max": round(max(write_ms), 2) if write_ms else None, "calls": len(write_ms)},
        "cpu_s": round(cpu, 1), "cpu_share": round(cpu / wall, 2), "peak_rss_mb": round(rss / 2**20, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phones", type=int, default=30)
    parser.add_argument("--tasks", type=int, default=4, help="tasks per phone, one after another")
    parser.add_argument("--steps", type=int, default=5, help="scrolls before done (a task is steps + 1 model calls)")
    parser.add_argument("--model-ms", type=float, default=300, help="the fake model's time per call")
    parser.add_argument("--history-writer", choices=("on", "off"), default="on",
                        help="off: history writes run on the caller's thread (before 2026-10-20)")
    parser.add_argument("--phones-role", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--url", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.phones_role:
        run_phones(args.url, args.phones, args.tasks)
        return
    print(json.dumps(run_server(args), indent=2), flush=True)
    os._exit(0)  # the server thread and the agents' workers are daemons; don't wait on them


if __name__ == "__main__":
    main()
