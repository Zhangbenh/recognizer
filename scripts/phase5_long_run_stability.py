"""Phase 5: Long-run stability script.

Drives AppController for a configurable duration (--max-minutes) and reports:
- Total ticks executed, errors encountered, crash count
- Post-boot Python memory growth via tracemalloc (sampled every --mem-interval ticks)
- Periodic capture+infer health probes for the live camera/inference chain
- JSON storage file size at end
- Whether stability criteria are met

Stability pass criteria:
  - crash_count == 0
    - post-boot memory growth < 2 MB over the measured runtime window
    - health probe failures == 0
  - json_size_bytes < 1MB (system_config constraint)

Run modes:
  --max-minutes 60   -> satisfies §6.2 >=1h requirement
  --max-minutes 180  -> satisfies Feature 4.1 >=3h requirement
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


import main as app_main
from application.states import State
from infrastructure.logging.logger import create_logger
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 5 long-run stability test")
    parser.add_argument(
        "--runtime", choices=("real", "mock"), default="real",
        help="runtime backend (real=Pi camera+tflite, mock=desktop-safe)",
    )
    parser.add_argument(
        "--input", choices=("keyboard", "gpio"), default="gpio",
        help="input backend",
    )
    parser.add_argument(
        "--max-minutes", type=float, default=60.0,
        help="total run duration in minutes (60=1h, 180=3h)",
    )
    parser.add_argument(
        "--mem-interval", type=int, default=500,
        help="tracemalloc snapshot interval in ticks",
    )
    parser.add_argument(
        "--idle-sleep-ms", type=float, default=20.0,
        help="sleep between ticks when idle (milliseconds)",
    )
    parser.add_argument(
        "--boot-timeout-s", type=float, default=30.0,
        help="timeout for BOOTING to settle into HOME or ERROR",
    )
    parser.add_argument(
        "--health-probe-interval-s", type=float, default=30.0,
        help="run capture+infer health probe every N seconds (0 disables probes)",
    )
    parser.add_argument(
        "--output", type=str,
        default=str(REPO_ROOT / "reports" / "phase5_long_run_stability_report.json"),
        help="output JSON report path",
    )
    parser.add_argument("--log-level", type=str, default="WARNING")
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _find_stats_json(repo_root: Path) -> Path | None:
    """Locate the sampling records JSON used by the running instance."""
    candidates = [
        repo_root / "data" / "sampling_records.json",
        repo_root / "sampling_records.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Fallback: find any .json under data/
    data_dir = repo_root / "data"
    if data_dir.is_dir():
        matches = list(data_dir.glob("*.json"))
        if matches:
            return matches[0]
    return None


def _tick_until_boot_ready(controller, *, idle_sleep_s: float, timeout_s: float) -> tuple[float, State]:
    """Drive the runtime until BOOTING settles into HOME or ERROR."""
    boot_start = time.monotonic()
    controller._state_machine.start()

    while True:
        current_state = controller._state_machine.current_state
        if current_state in {State.HOME, State.ERROR}:
            return time.monotonic() - boot_start, current_state

        if time.monotonic() - boot_start >= timeout_s:
            raise TimeoutError(
                f"boot did not settle within {timeout_s:.1f}s; current_state={current_state.value}"
            )

        did_work = controller.tick()
        if not did_work and idle_sleep_s > 0:
            time.sleep(idle_sleep_s)


def _run_health_probe(controller) -> dict[str, Any]:
    """Exercise capture+infer so long-run checks cover the live hardware chain."""
    recognition_service = controller._recognition_service

    capture_start = time.perf_counter()
    frame = recognition_service.capture_frame()
    after_capture = time.perf_counter()
    result = recognition_service.recognize(frame)
    after_infer = time.perf_counter()

    return {
        "capture_s": after_capture - capture_start,
        "infer_s": after_infer - after_capture,
        "full_s": after_infer - capture_start,
        "recognized": bool(result.is_recognized),
        "confidence": float(result.confidence),
        "display_name": result.display_name,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()
    logger = create_logger(level=args.log_level)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    max_seconds = args.max_minutes * 60.0
    idle_sleep_s = args.idle_sleep_ms / 1000.0

    logger.info("Building controller (runtime=%s, input=%s)", args.runtime, args.input)
    controller = app_main.build_controller(
        runtime_backend=args.runtime,
        input_backend=args.input,
        ui_backend="text",
        logger=logger,
    )

    # ── run loop ──────────────────────────────────────────────────────────────
    tick_count = 0
    error_count = 0
    crash_count = 0
    health_probe_count = 0
    health_probe_failures = 0
    health_probe_last: dict[str, Any] | None = None
    health_probe_history: list[dict[str, Any]] = []
    mem_snapshots: list[dict[str, Any]] = []
    visited_states: set[str] = set()

    boot_elapsed_s, boot_state = _tick_until_boot_ready(
        controller,
        idle_sleep_s=idle_sleep_s,
        timeout_s=max(1.0, args.boot_timeout_s),
    )
    if boot_state == State.ERROR:
        raise RuntimeError("boot failed; state machine settled in ERROR")

    # Measure runtime growth after one-time boot allocations have settled.
    tracemalloc.start()
    baseline_current, _ = tracemalloc.get_traced_memory()
    run_start = time.monotonic()
    next_health_probe_elapsed_s = max(0.0, args.health_probe_interval_s)

    print(f"[stability] starting run — max_minutes={args.max_minutes:.0f}, "
          f"runtime={args.runtime}", flush=True)
    if args.health_probe_interval_s > 0:
        print(
            f"[stability] boot settled in {boot_elapsed_s:.2f}s; "
            f"health_probe_interval={args.health_probe_interval_s:.1f}s",
            flush=True,
        )
    else:
        print(
            f"[stability] boot settled in {boot_elapsed_s:.2f}s; health probes disabled",
            flush=True,
        )

    try:
        while True:
            elapsed = time.monotonic() - run_start
            if elapsed >= max_seconds:
                break

            try:
                did_work = controller.tick()
            except Exception as exc:
                crash_count += 1
                logger.error("crash at tick %d: %s", tick_count, exc)
                if crash_count >= 5:
                    logger.critical("too many crashes (%d), aborting", crash_count)
                    break
                continue

            tick_count += 1

            # Count state-machine errors without crashing
            sm_state = controller._state_machine.current_state.value
            visited_states.add(sm_state)
            if sm_state == "ERROR":
                error_count += 1

            if args.health_probe_interval_s > 0 and elapsed >= next_health_probe_elapsed_s:
                try:
                    health_probe_last = _run_health_probe(controller)
                    health_probe_count += 1
                    health_probe_history.append(
                        {
                            "elapsed_s": round(elapsed, 1),
                            "capture_ms": round(health_probe_last["capture_s"] * 1000.0, 2),
                            "infer_ms": round(health_probe_last["infer_s"] * 1000.0, 2),
                            "full_ms": round(health_probe_last["full_s"] * 1000.0, 2),
                            "recognized": health_probe_last["recognized"],
                            "confidence": round(health_probe_last["confidence"], 4),
                            "display_name": health_probe_last["display_name"],
                        }
                    )
                except Exception as exc:
                    health_probe_failures += 1
                    logger.error("health probe failed at tick %d: %s", tick_count, exc)
                    print(
                        f"[stability] health_probe_failed elapsed={elapsed/60:.1f}min "
                        f"tick={tick_count} reason={exc}",
                        flush=True,
                    )
                    break

                next_health_probe_elapsed_s += args.health_probe_interval_s

            # Memory snapshot
            if tick_count % args.mem_interval == 0:
                current, peak = tracemalloc.get_traced_memory()
                growth_kb = (current - baseline_current) / 1024
                mem_snapshots.append({
                    "tick": tick_count,
                    "elapsed_s": round(elapsed, 1),
                    "current_kb": round(current / 1024, 1),
                    "growth_kb": round(growth_kb, 1),
                    "peak_kb": round(peak / 1024, 1),
                })
                print(
                    f"[stability] tick={tick_count} elapsed={elapsed/60:.1f}min "
                    f"mem_growth={growth_kb:.0f}KB state={sm_state}",
                    flush=True,
                )

            if not did_work:
                time.sleep(idle_sleep_s)

    except KeyboardInterrupt:
        print("[stability] interrupted by user", flush=True)
    finally:
        controller.stop()

    # ── final measurements ────────────────────────────────────────────────────
    final_current, final_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total_elapsed_s = time.monotonic() - run_start

    memory_growth_kb = (final_current - baseline_current) / 1024
    memory_growth_mb = memory_growth_kb / 1024

    # JSON file size check
    stats_json_path = _find_stats_json(REPO_ROOT)
    json_size_bytes: int | None = None
    if stats_json_path and stats_json_path.exists():
        json_size_bytes = stats_json_path.stat().st_size

    # ── pass criteria ─────────────────────────────────────────────────────────
    MEM_GROWTH_LIMIT_MB = 2.0
    JSON_SIZE_LIMIT_BYTES = 1 * 1024 * 1024

    pass_no_crash = crash_count == 0
    pass_memory = memory_growth_mb < MEM_GROWTH_LIMIT_MB
    pass_health_probes = health_probe_failures == 0
    pass_json_size = (json_size_bytes is None) or (json_size_bytes < JSON_SIZE_LIMIT_BYTES)
    pass_duration = total_elapsed_s >= (max_seconds * 0.99)  # allow 1% tolerance
    pass_overall = (
        pass_no_crash
        and pass_memory
        and pass_health_probes
        and pass_json_size
        and pass_duration
    )

    # ── report ────────────────────────────────────────────────────────────────
    report: dict[str, Any] = {
        "generated_at": _now_iso(),
        "runtime": args.runtime,
        "input_backend": args.input,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "config": {
            "max_minutes": args.max_minutes,
            "mem_interval_ticks": args.mem_interval,
            "idle_sleep_ms": args.idle_sleep_ms,
            "boot_timeout_s": args.boot_timeout_s,
            "health_probe_interval_s": args.health_probe_interval_s,
        },
        "run": {
            "boot_elapsed_s": round(boot_elapsed_s, 3),
            "boot_state": boot_state.value,
            "total_elapsed_s": round(total_elapsed_s, 2),
            "total_elapsed_min": round(total_elapsed_s / 60, 2),
            "tick_count": tick_count,
            "error_count": error_count,
            "crash_count": crash_count,
            "visited_states": sorted(visited_states),
            "activity_scope": "post_boot_capture_infer_probes" if args.health_probe_interval_s > 0 else "post_boot_idle_only",
        },
        "memory": {
            "baseline_kb": round(baseline_current / 1024, 1),
            "final_kb": round(final_current / 1024, 1),
            "peak_kb": round(final_peak / 1024, 1),
            "growth_kb": round(memory_growth_kb, 1),
            "growth_mb": round(memory_growth_mb, 3),
            "measurement_scope": "post_boot_runtime_only",
            "snapshots": mem_snapshots,
        },
        "health_probes": {
            "count": health_probe_count,
            "failures": health_probe_failures,
            "last": health_probe_last,
            "history": health_probe_history,
        },
        "storage": {
            "stats_json_path": str(stats_json_path) if stats_json_path else None,
            "json_size_bytes": json_size_bytes,
        },
        "criteria": {
            "no_crash": {"pass": pass_no_crash, "crash_count": crash_count},
            "memory_growth_lt_2mb": {
                "pass": pass_memory,
                "growth_mb": round(memory_growth_mb, 3),
                "limit_mb": MEM_GROWTH_LIMIT_MB,
            },
            "health_probes_ok": {
                "pass": pass_health_probes,
                "count": health_probe_count,
                "failures": health_probe_failures,
            },
            "json_size_lt_1mb": {
                "pass": pass_json_size,
                "size_bytes": json_size_bytes,
                "limit_bytes": JSON_SIZE_LIMIT_BYTES,
            },
            "duration_completed": {
                "pass": pass_duration,
                "elapsed_s": round(total_elapsed_s, 2),
                "required_s": max_seconds,
            },
        },
        "pass": {
            "no_crash": pass_no_crash,
            "memory": pass_memory,
            "health_probes": pass_health_probes,
            "json_size": pass_json_size,
            "duration": pass_duration,
            "overall": pass_overall,
        },
    }

    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    status = "PASS" if pass_overall else "FAIL"
    print(
        f"\n[stability] {status} | elapsed={total_elapsed_s/60:.1f}min "
        f"ticks={tick_count} crashes={crash_count} "
        f"mem_growth={memory_growth_mb:.2f}MB health_probes={health_probe_count}/{health_probe_failures}",
        flush=True,
    )
    print(f"[stability] report: {output_path}", flush=True)
    return 0 if pass_overall else 1


if __name__ == "__main__":
    sys.exit(main())
