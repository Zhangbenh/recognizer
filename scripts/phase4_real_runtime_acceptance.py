"""Phase 4 hardware-side acceptance script for real runtime latency sampling.

This script measures capture / inference / full-flow latency on Raspberry Pi and
compares p95 values against performance budgets from config/system_config.json.
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
from infrastructure.config.system_config_repository import SystemConfigRepository
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
	parser = argparse.ArgumentParser(description="Phase 4 real runtime acceptance sampler")
	parser.add_argument("--runtime", choices=("real", "mock"), default="real")
	parser.add_argument("--input", choices=("keyboard", "gpio"), default="keyboard")
	parser.add_argument("--samples", type=int, default=30)
	parser.add_argument("--warmup", type=int, default=5)
	parser.add_argument("--sleep-s", type=float, default=0.0)
	parser.add_argument(
		"--output",
		type=str,
		default="reports/phase4_real_runtime_report.json",
		help="output json report path (absolute or repo-relative)",
	)
	parser.add_argument("--log-level", type=str, default="INFO")
	parser.add_argument("--print-samples", action="store_true")
	return parser.parse_args()


def resolve_output_path(output: str) -> Path:
	path = Path(output)
	if path.is_absolute():
		return path
	return REPO_ROOT / path


def main() -> int:
	args = parse_args()
	if args.samples <= 0:
		raise ValueError("--samples must be > 0")
	if args.warmup < 0:
		raise ValueError("--warmup must be >= 0")
	if args.sleep_s < 0:
		raise ValueError("--sleep-s must be >= 0")

	logger = create_logger(name="phase4.real.acceptance", level=args.log_level)
	controller = app_main.build_controller(
		runtime_backend=args.runtime,
		input_backend=args.input,
		ui_backend="text",
		logger=logger,
	)

	release_gate_service = controller._release_gate_service
	recognition_service = controller._recognition_service

	boot_elapsed_s = 0.0
	capture_samples: list[float] = []
	infer_samples: list[float] = []
	full_flow_samples: list[float] = []
	recognized_count = 0
	confidence_samples: list[float] = []

	try:
		boot_start = time.perf_counter()
		release_gate_service.ensure_pass()
		recognition_service.boot()
		boot_elapsed_s = time.perf_counter() - boot_start

		for _ in range(args.warmup):
			frame = recognition_service.capture_frame()
			recognition_service.recognize(frame)
			if args.sleep_s > 0:
				time.sleep(args.sleep_s)

		for index in range(args.samples):
			full_start = time.perf_counter()
			frame = recognition_service.capture_frame()
			after_capture = time.perf_counter()
			result = recognition_service.recognize(frame)
			after_infer = time.perf_counter()

			capture_elapsed = after_capture - full_start
			infer_elapsed = after_infer - after_capture
			full_elapsed = after_infer - full_start

			capture_samples.append(capture_elapsed)
			infer_samples.append(infer_elapsed)
			full_flow_samples.append(full_elapsed)

			if result.is_recognized:
				recognized_count += 1
			confidence_samples.append(float(result.confidence))

			if args.print_samples:
				print(
					f"sample={index + 1:02d} capture={format_ms(capture_elapsed)} "
					f"infer={format_ms(infer_elapsed)} full={format_ms(full_elapsed)} "
					f"recognized={result.is_recognized} confidence={result.confidence:.4f}"
				)

			if args.sleep_s > 0:
				time.sleep(args.sleep_s)
	finally:
		controller.stop()

	capture_summary = summarize(capture_samples)
	infer_summary = summarize(infer_samples)
	full_summary = summarize(full_flow_samples)

	system_config = SystemConfigRepository()
	budget = system_config.performance_budget()
	capture_budget_s = float(budget.get("capture_s", 0.0))
	infer_budget_s = float(budget.get("infer_s", 0.0))
	full_flow_budget_s = float(budget.get("full_flow_s", 0.0))

	passes = {
		"capture_p95": capture_summary["p95_s"] <= capture_budget_s,
		"infer_p95": infer_summary["p95_s"] <= infer_budget_s,
		"full_flow_p95": full_summary["p95_s"] <= full_flow_budget_s,
	}
	overall_pass = all(passes.values())

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
		"sampling": {
			"samples": args.samples,
			"warmup": args.warmup,
			"sleep_s": args.sleep_s,
			"boot_elapsed_s": boot_elapsed_s,
		},
		"budget_s": {
			"capture_s": capture_budget_s,
			"infer_s": infer_budget_s,
			"full_flow_s": full_flow_budget_s,
		},
		"metrics": {
			"capture_s": capture_summary,
			"infer_s": infer_summary,
			"full_flow_s": full_summary,
		},
		"recognition": {
			"recognized_count": recognized_count,
			"recognized_ratio": recognized_count / args.samples if args.samples > 0 else 0.0,
			"average_confidence": statistics.fmean(confidence_samples) if confidence_samples else 0.0,
		},
		"pass": {
			**passes,
			"overall": overall_pass,
		},
	}

	output_path = resolve_output_path(args.output)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

	print("=" * 64)
	print("Phase 4 Real Runtime Acceptance Report")
	print(f"runtime: {args.runtime}")
	print(f"samples: {args.samples}, warmup: {args.warmup}, boot: {format_ms(boot_elapsed_s)}")
	print(
		f"capture p95={format_ms(capture_summary['p95_s'])} "
		f"budget={format_ms(capture_budget_s)} pass={passes['capture_p95']}"
	)
	print(
		f"infer   p95={format_ms(infer_summary['p95_s'])} "
		f"budget={format_ms(infer_budget_s)} pass={passes['infer_p95']}"
	)
	print(
		f"full    p95={format_ms(full_summary['p95_s'])} "
		f"budget={format_ms(full_flow_budget_s)} pass={passes['full_flow_p95']}"
	)
	print(
		f"recognized: {recognized_count}/{args.samples} "
		f"({report['recognition']['recognized_ratio'] * 100.0:.1f}%)"
	)
	print(f"overall pass: {overall_pass}")
	print(f"json report: {output_path}")
	print("=" * 64)

	return 0 if overall_pass else 1


if __name__ == "__main__":
	raise SystemExit(main())
