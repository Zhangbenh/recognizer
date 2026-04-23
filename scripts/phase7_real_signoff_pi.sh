#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PHASE4_OUTPUT="${PHASE4_OUTPUT:-reports/phase7_phase4_real_report.json}"
PHASE5_OUTPUT="${PHASE5_OUTPUT:-reports/phase7_phase5_real_report.json}"

PHASE4_SAMPLES="${PHASE4_SAMPLES:-30}"
PHASE4_WARMUP="${PHASE4_WARMUP:-5}"
PHASE4_SLEEP_S="${PHASE4_SLEEP_S:-0.02}"

PHASE5_CYCLES="${PHASE5_CYCLES:-20}"
PHASE5_MAP_NAV="${PHASE5_MAP_NAV:-1}"
PHASE5_REGION_NAV="${PHASE5_REGION_NAV:-2}"

mkdir -p reports

echo "[Phase7-Real] START: Phase4 real acceptance"
"$PYTHON_BIN" scripts/phase4_real_runtime_acceptance.py \
  --runtime real \
  --input keyboard \
  --samples "$PHASE4_SAMPLES" \
  --warmup "$PHASE4_WARMUP" \
  --sleep-s "$PHASE4_SLEEP_S" \
  --output "$PHASE4_OUTPUT"

echo "[Phase7-Real] START: Phase5 real acceptance"
"$PYTHON_BIN" scripts/phase5_sampling_mode_acceptance.py \
  --runtime real \
  --input keyboard \
  --cycles "$PHASE5_CYCLES" \
  --map-nav "$PHASE5_MAP_NAV" \
  --region-nav "$PHASE5_REGION_NAV" \
  --output "$PHASE5_OUTPUT"

echo "[Phase7-Real] VERIFY: pass criteria"
"$PYTHON_BIN" - "$PHASE4_OUTPUT" "$PHASE5_OUTPUT" <<'PY'
import json
import sys
from pathlib import Path

phase4_path = Path(sys.argv[1])
phase5_path = Path(sys.argv[2])

phase4 = json.loads(phase4_path.read_text(encoding="utf-8"))
phase5 = json.loads(phase5_path.read_text(encoding="utf-8"))

phase4_pass = bool(phase4.get("pass", {}).get("overall", False))
phase5_pass = bool(phase5.get("pass", {}).get("overall", False))

print("[Phase7-Real] Phase4 overall:", phase4_pass)
print("[Phase7-Real] Phase5 overall:", phase5_pass)

phase4_scenarios = phase4.get("scenario_results") or {}
if phase4_scenarios:
    for scenario_name, scenario_report in phase4_scenarios.items():
        metrics = scenario_report["metrics"]
        budgets = scenario_report["budget_s"]
        print(
            f"[Phase7-Real] Phase4 {scenario_name} p95/budget:",
            "capture=%.4fs/%.4fs" % (
                float(metrics["capture_s"]["p95_s"]),
                float(budgets["capture_s"]),
            ),
            "infer=%.4fs/%.4fs" % (
                float(metrics["infer_s"]["p95_s"]),
                float(budgets["infer_s"]),
            ),
            "full=%.4fs/%.4fs" % (
                float(metrics["full_flow_s"]["p95_s"]),
                float(budgets["full_flow_s"]),
            ),
        )
else:
    print(
        "[Phase7-Real] Phase4 p95/budget:",
        "capture=%.4fs/%.4fs" % (
            float(phase4["metrics"]["capture_s"]["p95_s"]),
            float(phase4["budget_s"]["capture_s"]),
        ),
        "infer=%.4fs/%.4fs" % (
            float(phase4["metrics"]["infer_s"]["p95_s"]),
            float(phase4["budget_s"]["infer_s"]),
        ),
        "full=%.4fs/%.4fs" % (
            float(phase4["metrics"]["full_flow_s"]["p95_s"]),
            float(phase4["budget_s"]["full_flow_s"]),
        ),
    )

phase5_scenarios = phase5.get("scenario_results") or {}
if phase5_scenarios:
    for scenario_name, scenario_report in phase5_scenarios.items():
        print(
            f"[Phase7-Real] Phase5 {scenario_name} counters:",
            "recognized_count=%s" % scenario_report["sampling"]["recognized_count"],
            "recorded_delta_count=%s" % scenario_report["sampling"]["recorded_delta_count"],
            "stats_items_count=%s" % scenario_report["stats"]["items_count"],
        )
else:
    print(
        "[Phase7-Real] Phase5 counters:",
        "recognized_count=%s" % phase5["sampling"]["recognized_count"],
        "recorded_delta_count=%s" % phase5["sampling"]["recorded_delta_count"],
        "stats_items_count=%s" % phase5["stats"]["items_count"],
    )

if not (phase4_pass and phase5_pass):
    raise SystemExit(1)
PY

echo "[Phase7-Real] ALL SIGNOFF CHECKS PASSED"
