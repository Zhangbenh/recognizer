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
from domain.errors import CloudTimeoutError
from infrastructure.cloud.baidu_plant_client import BaiduPlantCandidate, BaiduPlantResponse
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.logging.logger import create_logger


DEFAULT_SCENARIOS = ("cloud_success", "cloud_fallback", "local_only")


class _ScenarioSystemConfigRepository:
	def __init__(self, *, strategy: str) -> None:
		self._base = SystemConfigRepository()
		self._strategy = strategy

	def recognition_strategy(self) -> str:
		return self._strategy

	def __getattr__(self, name: str):
		return getattr(self._base, name)


class _ScenarioCloudClient:
	def __init__(self, outcome: BaiduPlantResponse | Exception) -> None:
		self._outcome = outcome

	def recognize_image_bytes(self, image_bytes: bytes, *, baike_num: int = 0) -> BaiduPlantResponse:
		_ = image_bytes, baike_num
		if isinstance(self._outcome, Exception):
			raise self._outcome
		return self._outcome


class _UnexpectedCloudClient:
	def recognize_image_bytes(self, image_bytes: bytes, *, baike_num: int = 0) -> BaiduPlantResponse:
		_ = image_bytes, baike_num
		raise AssertionError("cloud client should not be used in local_only scenario")


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
	parser.add_argument(
		"--scenario",
		choices=("all", *DEFAULT_SCENARIOS),
		default="all",
		help="recognition path scenario: cloud_success / cloud_fallback / local_only / all",
	)
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


def _scenario_response() -> BaiduPlantResponse:
	return BaiduPlantResponse(
		log_id=0,
		candidates=[BaiduPlantCandidate(name="芦荟", score=0.96)],
		raw_payload={"result": [{"name": "芦荟", "score": 0.96}]},
	)


def _scenario_build_kwargs(scenario: str) -> dict[str, Any]:
	build_kwargs: dict[str, Any] = {}
	if scenario == "cloud_success":
		build_kwargs["baidu_plant_client"] = _ScenarioCloudClient(_scenario_response())
		build_kwargs["frame_encoder"] = lambda frame: json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")
	elif scenario == "cloud_fallback":
		build_kwargs["baidu_plant_client"] = _ScenarioCloudClient(
			CloudTimeoutError("cloud request timed out", retryable=True)
		)
		build_kwargs["frame_encoder"] = lambda frame: json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")
	elif scenario == "local_only":
		build_kwargs["system_config_repository"] = _ScenarioSystemConfigRepository(strategy="local_only")
		build_kwargs["baidu_plant_client"] = _UnexpectedCloudClient()
		build_kwargs["frame_encoder"] = lambda frame: json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")
	else:
		raise ValueError(f"unsupported scenario: {scenario}")
	return build_kwargs


def _classify_result_path(result) -> str:
	if getattr(result, "source", None) == "cloud" and not getattr(result, "fallback_used", False):
		return "cloud_success"
	if getattr(result, "source", None) == "local" and getattr(result, "fallback_used", False):
		return "cloud_fallback"
	if getattr(result, "source", None) == "local":
		return "local_only"
	return "unknown"


def _scenario_budgets(system_config: SystemConfigRepository, scenario: str) -> dict[str, float]:
	budget = system_config.performance_budget()
	if scenario == "cloud_success":
		return {
			"capture_s": float(budget.get("capture_s", 0.0)),
			"infer_s": float(system_config.cloud_request_timeout_s()),
			"full_flow_s": float(budget.get("cloud_success_s", budget.get("full_flow_s", 0.0))),
		}
	if scenario == "cloud_fallback":
		return {
			"capture_s": float(budget.get("capture_s", 0.0)),
			"infer_s": float(system_config.infer_timeout_s()),
			"full_flow_s": float(budget.get("cloud_fallback_s", budget.get("full_flow_s", 0.0))),
		}
	return {
		"capture_s": float(budget.get("capture_s", 0.0)),
		"infer_s": float(system_config.local_infer_timeout_s()),
		"full_flow_s": float(budget.get("full_flow_s", 0.0)),
	}


def _run_scenario(args: argparse.Namespace, scenario: str, logger) -> tuple[dict[str, Any], dict[str, Any]]:
	controller = app_main.build_controller(
		runtime_backend=args.runtime,
		input_backend=args.input,
		ui_backend="text",
		logger=logger,
		**_scenario_build_kwargs(scenario),
	)

	release_gate_service = controller._release_gate_service
	recognition_service = controller._recognition_service
	system_config = SystemConfigRepository()
	budget_s = _scenario_budgets(system_config, scenario)

	boot_elapsed_s = 0.0
	capture_samples: list[float] = []
	infer_samples: list[float] = []
	full_flow_samples: list[float] = []
	confidence_samples: list[float] = []
	recognized_count = 0
	path_counts = {name: 0 for name in (*DEFAULT_SCENARIOS, "unknown")}
	sample_details: list[dict[str, Any]] = []

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
			path_name = _classify_result_path(result)

			capture_samples.append(capture_elapsed)
			infer_samples.append(infer_elapsed)
			full_flow_samples.append(full_elapsed)
			confidence_samples.append(float(result.confidence))
			path_counts[path_name] = path_counts.get(path_name, 0) + 1
			if result.is_recognized:
				recognized_count += 1

			sample_details.append(
				{
					"index": index + 1,
					"path": path_name,
					"source": result.source,
					"fallback_used": result.fallback_used,
					"display_name": result.display_name,
					"recognized": result.is_recognized,
					"capture_s": capture_elapsed,
					"infer_s": infer_elapsed,
					"full_flow_s": full_elapsed,
				}
			)

			if args.print_samples:
				print(
					f"scenario={scenario} sample={index + 1:02d} path={path_name} "
					f"capture={format_ms(capture_elapsed)} infer={format_ms(infer_elapsed)} full={format_ms(full_elapsed)}"
				)

			if args.sleep_s > 0:
				time.sleep(args.sleep_s)
	finally:
		controller.stop()

	capture_summary = summarize(capture_samples)
	infer_summary = summarize(infer_samples)
	full_summary = summarize(full_flow_samples)
	passes = {
		"capture_p95": capture_summary["p95_s"] <= budget_s["capture_s"],
		"infer_p95": infer_summary["p95_s"] <= budget_s["infer_s"],
		"full_flow_p95": full_summary["p95_s"] <= budget_s["full_flow_s"],
		"expected_path": path_counts.get(scenario, 0) == args.samples,
	}
	report = {
		"scenario": scenario,
		"sampling": {
			"samples": args.samples,
			"warmup": args.warmup,
			"sleep_s": args.sleep_s,
			"boot_elapsed_s": boot_elapsed_s,
		},
		"budget_s": budget_s,
		"metrics": {
			"capture_s": capture_summary,
			"infer_s": infer_summary,
			"full_flow_s": full_summary,
		},
		"recognition": {
			"recognized_count": recognized_count,
			"recognized_ratio": recognized_count / args.samples if args.samples > 0 else 0.0,
			"average_confidence": statistics.fmean(confidence_samples) if confidence_samples else 0.0,
			"path_counts": path_counts,
		},
		"pass": {
			**passes,
			"overall": all(passes.values()),
		},
		"sample_details": sample_details,
	}
	return report, {
		"capture_samples": capture_samples,
		"infer_samples": infer_samples,
		"full_flow_samples": full_flow_samples,
		"confidence_samples": confidence_samples,
		"recognized_count": recognized_count,
		"path_counts": path_counts,
	}


def main() -> int:
	args = parse_args()
	if args.samples <= 0:
		raise ValueError("--samples must be > 0")
	if args.warmup < 0:
		raise ValueError("--warmup must be >= 0")
	if args.sleep_s < 0:
		raise ValueError("--sleep-s must be >= 0")

	logger = create_logger(name="phase4.real.acceptance", level=args.log_level)
	system_config = SystemConfigRepository()
	budget = system_config.performance_budget()
	scenarios = list(DEFAULT_SCENARIOS) if args.scenario == "all" else [args.scenario]
	scenario_results: dict[str, Any] = {}
	aggregate_capture: list[float] = []
	aggregate_infer: list[float] = []
	aggregate_full: list[float] = []
	aggregate_confidence: list[float] = []
	aggregate_recognized = 0
	aggregate_path_counts = {name: 0 for name in (*DEFAULT_SCENARIOS, "unknown")}
	pass_flags: dict[str, bool] = {}

	for scenario in scenarios:
		scenario_report, raw = _run_scenario(args, scenario, logger)
		scenario_results[scenario] = scenario_report
		aggregate_capture.extend(raw["capture_samples"])
		aggregate_infer.extend(raw["infer_samples"])
		aggregate_full.extend(raw["full_flow_samples"])
		aggregate_confidence.extend(raw["confidence_samples"])
		aggregate_recognized += int(raw["recognized_count"])
		for key, value in raw["path_counts"].items():
			aggregate_path_counts[key] = aggregate_path_counts.get(key, 0) + int(value)
		pass_flags[scenario] = bool(scenario_report["pass"]["overall"])

	capture_summary = summarize(aggregate_capture)
	infer_summary = summarize(aggregate_infer)
	full_summary = summarize(aggregate_full)
	overall_pass = all(pass_flags.values()) if pass_flags else False

	report: dict[str, Any] = {
		"generated_at": utc_now_iso(),
		"runtime": args.runtime,
		"input_backend": args.input,
		"scenario": args.scenario,
		"platform": {
			"system": platform.system(),
			"release": platform.release(),
			"machine": platform.machine(),
			"python": platform.python_version(),
		},
		"sampling": {
			"samples": args.samples * len(scenarios),
			"samples_per_scenario": args.samples,
			"warmup": args.warmup,
			"sleep_s": args.sleep_s,
			"boot_elapsed_s": sum(
				float(scenario_results[name]["sampling"]["boot_elapsed_s"]) for name in scenario_results
			),
		},
		"budget_s": {
			"capture_s": float(budget.get("capture_s", 0.0)),
			"infer_s": float(system_config.local_infer_timeout_s()),
			"full_flow_s": float(budget.get("full_flow_s", 0.0)),
			"paths": {
				name: _scenario_budgets(system_config, name) for name in DEFAULT_SCENARIOS
			},
		},
		"metrics": {
			"capture_s": capture_summary,
			"infer_s": infer_summary,
			"full_flow_s": full_summary,
		},
		"recognition": {
			"recognized_count": aggregate_recognized,
			"recognized_ratio": aggregate_recognized / (args.samples * len(scenarios)) if args.samples > 0 else 0.0,
			"average_confidence": statistics.fmean(aggregate_confidence) if aggregate_confidence else 0.0,
			"path_counts": aggregate_path_counts,
		},
		"pass": {
			**pass_flags,
			"overall": overall_pass,
		},
		"scenario_results": scenario_results,
	}

	output_path = resolve_output_path(args.output)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

	print("=" * 64)
	print("Phase 4 Real Runtime Acceptance Report")
	print(f"runtime: {args.runtime}")
	print(f"scenario: {args.scenario}")
	for scenario in scenarios:
		scenario_report = scenario_results[scenario]
		budgets = scenario_report["budget_s"]
		metrics = scenario_report["metrics"]
		print(
			f"[{scenario}] capture p95={format_ms(metrics['capture_s']['p95_s'])} "
			f"budget={format_ms(budgets['capture_s'])}"
		)
		print(
			f"[{scenario}] infer   p95={format_ms(metrics['infer_s']['p95_s'])} "
			f"budget={format_ms(budgets['infer_s'])}"
		)
		print(
			f"[{scenario}] full    p95={format_ms(metrics['full_flow_s']['p95_s'])} "
			f"budget={format_ms(budgets['full_flow_s'])} pass={scenario_report['pass']['overall']}"
		)
	print(f"overall pass: {overall_pass}")
	print(f"json report: {output_path}")
	print("=" * 64)

	return 0 if overall_pass else 1


if __name__ == "__main__":
	raise SystemExit(main())
