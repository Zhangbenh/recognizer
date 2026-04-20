"""Phase 5 sampling-mode runtime acceptance script.

This script drives the Phase 5 sampling path with keyboard-like events and
outputs a JSON report that can be used on desktop or Raspberry Pi.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
	sys.path.insert(0, str(APP_DIR))


import main as app_main
from application.events import Event, EventType
from application.states import State
from infrastructure.logging.logger import create_logger


def utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], p: float) -> float:
	if not values:
		return 0.0
	if len(values) == 1:
		return values[0]

	sorted_values = sorted(values)
	rank = (len(sorted_values) - 1) * p
	lower = int(rank)
	upper = min(lower + 1, len(sorted_values) - 1)
	weight = rank - lower
	return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def summarize(values: list[float]) -> dict[str, float]:
	if not values:
		return {
			"count": 0,
			"min_s": 0.0,
			"max_s": 0.0,
			"mean_s": 0.0,
			"median_s": 0.0,
			"p95_s": 0.0,
			"p99_s": 0.0,
			"stdev_s": 0.0,
		}

	stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
	return {
		"count": len(values),
		"min_s": min(values),
		"max_s": max(values),
		"mean_s": statistics.fmean(values),
		"median_s": statistics.median(values),
		"p95_s": percentile(values, 0.95),
		"p99_s": percentile(values, 0.99),
		"stdev_s": stdev,
	}


def format_ms(seconds: float) -> str:
	return f"{seconds * 1000.0:.2f} ms"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Phase 5 sampling-mode acceptance runner")
	parser.add_argument("--runtime", choices=("real", "mock"), default="mock")
	parser.add_argument("--input", choices=("keyboard", "gpio"), default="keyboard")
	parser.add_argument("--cycles", type=int, default=10, help="sampling cycles count")
	parser.add_argument("--map-nav", type=int, default=0, help="NAV presses in MAP_SELECT before confirm")
	parser.add_argument("--region-nav", type=int, default=0, help="NAV presses in REGION_SELECT before confirm")
	parser.add_argument("--max-ticks", type=int, default=500, help="max ticks for each wait step")
	parser.add_argument(
		"--output",
		type=str,
		default="reports/phase5_sampling_mode_report.json",
		help="output json report path (absolute or repo-relative)",
	)
	parser.add_argument("--log-level", type=str, default="INFO")
	parser.add_argument("--print-cycles", action="store_true")
	return parser.parse_args()


def resolve_output_path(output: str) -> Path:
	path = Path(output)
	if path.is_absolute():
		return path
	return REPO_ROOT / path


def ensure_keyboard_simulation_capability(controller) -> None:
	if not hasattr(controller._input_adapter, "push_simulated_event"):
		raise RuntimeError("input adapter does not support simulated events; use --input keyboard")


def push_event(controller, raw_event: str) -> None:
	controller._input_adapter.push_simulated_event(raw_event)


def tick_until_state(controller, target_state: State, *, max_ticks: int) -> tuple[int, list[str]]:
	trace: list[str] = []
	for index in range(max_ticks):
		controller.tick()
		state_value = controller._state_machine.current_state.value
		trace.append(state_value)
		if controller._state_machine.current_state == target_state:
			return index + 1, trace
	raise RuntimeError(
		f"did not reach state={target_state.value} within {max_ticks} ticks, tail={trace[-20:]}"
	)


def tick_until(controller, predicate, *, max_ticks: int) -> tuple[int, list[str]]:
	trace: list[str] = []
	for index in range(max_ticks):
		controller.tick()
		state = controller._state_machine.current_state
		trace.append(state.value)
		if predicate(state):
			return index + 1, trace
	raise RuntimeError(f"predicate did not match within {max_ticks} ticks, tail={trace[-20:]}")


def total_records_count(snapshot) -> int:
	if snapshot is None:
		return 0
	return sum(max(0, int(item.count)) for item in snapshot.items)


def run_sampling_cycle(controller, *, max_ticks: int) -> dict[str, Any]:
	ctx = controller._state_machine.context

	start = time.perf_counter()
	push_event(controller, "BTN1_SHORT")
	ticks_to_display, _ = tick_until_state(controller, State.DISPLAY, max_ticks=max_ticks)
	after_display = time.perf_counter()

	result = ctx.last_recognition_result
	recognized = bool(result and result.is_recognized)
	display_name = result.display_name if result else None

	controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="phase5.acceptance"))
	ticks_to_preview, trace = tick_until(controller, lambda state: state == State.PREVIEW, max_ticks=max_ticks)
	after_preview = time.perf_counter()

	return {
		"recognized": recognized,
		"display_name": display_name,
		"capture_to_display_s": after_display - start,
		"full_cycle_s": after_preview - start,
		"ticks_to_display": ticks_to_display,
		"ticks_to_preview": ticks_to_preview,
		"recording_seen": State.RECORDING.value in trace,
	}


def main() -> int:
	args = parse_args()
	if args.cycles <= 0:
		raise ValueError("--cycles must be > 0")
	if args.map_nav < 0:
		raise ValueError("--map-nav must be >= 0")
	if args.region_nav < 0:
		raise ValueError("--region-nav must be >= 0")
	if args.max_ticks <= 0:
		raise ValueError("--max-ticks must be > 0")

	logger = create_logger(name="phase5.sampling.acceptance", level=args.log_level)
	controller = app_main.build_controller(
		runtime_backend=args.runtime,
		input_backend=args.input,
		logger=logger,
	)

	ensure_keyboard_simulation_capability(controller)

	state_trace: list[str] = []
	cycle_details: list[dict[str, Any]] = []
	capture_to_display_samples: list[float] = []
	full_cycle_samples: list[float] = []
	recognized_count = 0
	recording_seen_count = 0
	selected_region_id = ""
	stats_items_count = 0
	stats_total_pages = 1
	baseline_records_total = 0
	final_records_total = 0
	recorded_delta_count = 0

	boot_start = time.perf_counter()
	try:
		_, trace = tick_until_state(controller, State.HOME, max_ticks=args.max_ticks)
		state_trace.extend(trace)
		boot_elapsed_s = time.perf_counter() - boot_start

		# HOME(normal) -> HOME(sampling) -> MAP_SELECT
		push_event(controller, "BTN2_SHORT")
		push_event(controller, "BTN1_SHORT")
		_, trace = tick_until_state(controller, State.MAP_SELECT, max_ticks=args.max_ticks)
		state_trace.extend(trace)

		for _ in range(args.map_nav):
			push_event(controller, "BTN2_SHORT")
			_, trace = tick_until_state(controller, State.MAP_SELECT, max_ticks=args.max_ticks)
			state_trace.extend(trace)

		# MAP_SELECT -> REGION_SELECT
		push_event(controller, "BTN1_SHORT")
		_, trace = tick_until_state(controller, State.REGION_SELECT, max_ticks=args.max_ticks)
		state_trace.extend(trace)

		for _ in range(args.region_nav):
			push_event(controller, "BTN2_SHORT")
			_, trace = tick_until_state(controller, State.REGION_SELECT, max_ticks=args.max_ticks)
			state_trace.extend(trace)

		selected_region_id = controller._state_machine.context.selected_region_id or ""
		stats_handler = controller._state_machine._handlers.get(State.STATS)
		stats_service = getattr(stats_handler, "_statistics_query_service", None)
		if stats_service is not None and selected_region_id:
			baseline_records_total = total_records_count(stats_service.snapshot_for_region(selected_region_id))

		# REGION_SELECT -> PREVIEW
		push_event(controller, "BTN1_SHORT")
		_, trace = tick_until_state(controller, State.PREVIEW, max_ticks=args.max_ticks)
		state_trace.extend(trace)

		for index in range(args.cycles):
			detail = run_sampling_cycle(controller, max_ticks=args.max_ticks)
			cycle_details.append(detail)
			capture_to_display_samples.append(detail["capture_to_display_s"])
			full_cycle_samples.append(detail["full_cycle_s"])
			if detail["recognized"]:
				recognized_count += 1
			if detail["recording_seen"]:
				recording_seen_count += 1

			if args.print_cycles:
				print(
					f"cycle={index + 1:02d} capture_to_display={format_ms(detail['capture_to_display_s'])} "
					f"full_cycle={format_ms(detail['full_cycle_s'])} "
					f"recognized={detail['recognized']} recording_seen={detail['recording_seen']}"
				)

		# PREVIEW -> REGION_SELECT -> STATS
		push_event(controller, "BTN2_LONG")
		_, trace = tick_until_state(controller, State.REGION_SELECT, max_ticks=args.max_ticks)
		state_trace.extend(trace)

		push_event(controller, "BTN1_LONG")
		_, trace = tick_until_state(controller, State.STATS, max_ticks=args.max_ticks)
		state_trace.extend(trace)

		snapshot = controller._state_machine.context.current_stats_snapshot
		if snapshot is not None:
			stats_items_count = len(snapshot.items)
			stats_total_pages = snapshot.total_pages
			final_records_total = total_records_count(snapshot)
			recorded_delta_count = max(0, final_records_total - baseline_records_total)

	except Exception as exc:
		controller.stop()
		raise RuntimeError(f"phase5 acceptance failed during flow: {exc}") from exc
	finally:
		controller.stop()

	capture_display_summary = summarize(capture_to_display_samples)
	full_cycle_summary = summarize(full_cycle_samples)

	pass_flags = {
		"state_flow_completed": True,
		"recognized_exists": recognized_count > 0,
		"recording_path_seen": recorded_delta_count > 0,
		"stats_has_items": stats_items_count > 0,
	}
	overall_pass = all(pass_flags.values())

	report: dict[str, Any] = {
		"generated_at": utc_now_iso(),
		"runtime": args.runtime,
		"input_backend": args.input,
		"platform": {
			"system": platform.system(),
			"release": platform.release(),
			"machine": platform.machine(),
			"python": platform.python_version(),
		},
		"config": {
			"cycles": args.cycles,
			"map_nav": args.map_nav,
			"region_nav": args.region_nav,
			"max_ticks": args.max_ticks,
		},
		"selection": {
			"selected_region_id": selected_region_id,
		},
		"sampling": {
			"boot_elapsed_s": boot_elapsed_s,
			"recognized_count": recognized_count,
			"recording_seen_count": recording_seen_count,
			"recorded_delta_count": recorded_delta_count,
			"baseline_records_total": baseline_records_total,
			"final_records_total": final_records_total,
			"capture_to_display_s": capture_display_summary,
			"full_cycle_s": full_cycle_summary,
		},
		"stats": {
			"items_count": stats_items_count,
			"total_pages": stats_total_pages,
		},
		"pass": {
			**pass_flags,
			"overall": overall_pass,
		},
		"cycle_details": cycle_details,
		"state_trace_tail": state_trace[-80:],
	}

	output_path = resolve_output_path(args.output)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

	print("=" * 64)
	print("Phase 5 Sampling Mode Acceptance Report")
	print(f"runtime: {args.runtime}")
	print(f"input: {args.input}")
	print(
		f"cycles: {args.cycles}, recognized: {recognized_count}, "
		f"recorded_delta: {recorded_delta_count}"
	)
	print(
		f"capture->display p95={format_ms(capture_display_summary['p95_s'])}, "
		f"full-cycle p95={format_ms(full_cycle_summary['p95_s'])}"
	)
	print(
		f"stats: region={selected_region_id}, items={stats_items_count}, pages={stats_total_pages}"
	)
	print(f"overall pass: {overall_pass}")
	print(f"json report: {output_path}")
	print("=" * 64)

	return 0 if overall_pass else 1


if __name__ == "__main__":
	raise SystemExit(main())
