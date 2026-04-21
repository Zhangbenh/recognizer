"""Phase 5: Long-run stability script.

Drives AppController for a configurable duration (--max-minutes) and reports:
- Total ticks executed, errors encountered, crash count
- Memory growth via tracemalloc (sampled every --mem-interval ticks)
- JSON storage file size at end
- Whether stability criteria are met

Stability pass criteria:
  - crash_count == 0
  - memory growth < 2 MB over the full run
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

    # ── tracemalloc setup ─────────────────────────────────────────────────────
    tracemalloc.start()
    baseline_current, _ = tracemalloc.get_traced_memory()
    mem_snapshots: list[dict[str, Any]] = []

    # ── run loop ──────────────────────────────────────────────────────────────
    tick_count = 0
    error_count = 0
    crash_count = 0
    run_start = time.monotonic()

    controller._state_machine.start()

    print(f"[stability] starting run — max_minutes={args.max_minutes:.0f}, "
          f"runtime={args.runtime}", flush=True)

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
            if sm_state == "ERROR":
                error_count += 1

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
    pass_json_size = (json_size_bytes is None) or (json_size_bytes < JSON_SIZE_LIMIT_BYTES)
    pass_duration = total_elapsed_s >= (max_seconds * 0.99)  # allow 1% tolerance
    pass_overall = pass_no_crash and pass_memory and pass_json_size and pass_duration

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
        },
        "run": {
            "total_elapsed_s": round(total_elapsed_s, 2),
            "total_elapsed_min": round(total_elapsed_s / 60, 2),
            "tick_count": tick_count,
            "error_count": error_count,
            "crash_count": crash_count,
        },
        "memory": {
            "baseline_kb": round(baseline_current / 1024, 1),
            "final_kb": round(final_current / 1024, 1),
            "peak_kb": round(final_peak / 1024, 1),
            "growth_kb": round(memory_growth_kb, 1),
            "growth_mb": round(memory_growth_mb, 3),
            "snapshots": mem_snapshots,
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
        f"mem_growth={memory_growth_mb:.2f}MB",
        flush=True,
    )
    print(f"[stability] report: {output_path}", flush=True)
    return 0 if pass_overall else 1


if __name__ == "__main__":
    sys.exit(main())
