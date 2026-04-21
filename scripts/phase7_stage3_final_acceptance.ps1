param(
    [string]$PythonExe
)

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

$pytestXmlPath = Join-Path $repoRoot "reports/phase7_stage3_pytest.xml"
$samplingReportPath = Join-Path $repoRoot "reports/phase7_stage3_sampling_report.json"
$finalReportPath = Join-Path $repoRoot "reports/phase7_stage3_final_acceptance_report.json"

function Invoke-Step {
    param(
        [string]$Title,
        [string[]]$StepArgs,
        [scriptblock]$Runner
    )

    Write-Output "[Phase7-Stage3] START: $Title"
    if ($Runner) {
        & $Runner
    } else {
        & $PythonExe @StepArgs
    }

    if ($LASTEXITCODE -ne 0) {
        throw "[Phase7-Stage3] FAILED: $Title (exit=$LASTEXITCODE)"
    }
    Write-Output "[Phase7-Stage3] PASS : $Title"
}

Set-Location $repoRoot

try {
    Invoke-Step -Title "stage3 pytest suite" -StepArgs @(
        "-m", "pytest", "-q",
        "tests/test_normal_mode_e2e.py",
        "tests/test_sampling_mode_e2e.py",
        "tests/test_sampling_mode_phase5.py",
        "tests/test_state_transitions.py",
        "--junitxml", "reports/phase7_stage3_pytest.xml"
    )

    Invoke-Step -Title "phase5 sampling acceptance (mock)" -StepArgs @(
        "scripts/phase5_sampling_mode_acceptance.py",
        "--runtime", "mock",
        "--input", "keyboard",
        "--cycles", "10",
        "--output", "reports/phase7_stage3_sampling_report.json"
    )

    Invoke-Step -Title "mock runtime no-deadlock smoke" -Runner {
        powershell -ExecutionPolicy Bypass -File scripts/run_mock.ps1 -MaxTicks 200 -LogLevel ERROR
    }

    [xml]$x = Get-Content $pytestXmlPath
    $suite = $x.testsuites.testsuite
    if (-not $suite) { $suite = $x.testsuite }

    $tests = [int]$suite.tests
    $failures = [int]$suite.failures
    $errors = [int]$suite.errors
    $skipped = [int]$suite.skipped
    $passed = $tests - $failures - $errors - $skipped

    $sampling = Get-Content $samplingReportPath | ConvertFrom-Json

    $report = [ordered]@{
        generated_at = (Get-Date).ToString("o")
        stage = "Phase7-Stage3"
        scope = [ordered]@{
            phase3a = "normal_mode_minimal_flow"
            phase3b = "sampling_mode_flow_and_stats"
            phase3c = "error_handling_and_safe_fallback"
        }
        checks = [ordered]@{
            pytest = [ordered]@{
                tests = $tests
                passed = $passed
                failed = $failures
                errors = $errors
                skipped = $skipped
                xml_report = "reports/phase7_stage3_pytest.xml"
            }
            sampling_acceptance = [ordered]@{
                overall = [bool]$sampling.pass.overall
                recognized_count = [int]$sampling.sampling.recognized_count
                recorded_delta_count = [int]$sampling.sampling.recorded_delta_count
                stats_items_count = [int]$sampling.stats.items_count
                json_report = "reports/phase7_stage3_sampling_report.json"
            }
            no_deadlock_smoke = [ordered]@{
                max_ticks = 200
                result = "pass"
            }
        }
        pass = [ordered]@{
            phase3a = ($failures -eq 0 -and $errors -eq 0)
            phase3b = ([bool]$sampling.pass.overall)
            phase3c = ($failures -eq 0 -and $errors -eq 0)
            overall = ($failures -eq 0 -and $errors -eq 0 -and [bool]$sampling.pass.overall)
        }
        note = "mock path verified in Windows; real hardware acceptance should be executed on Raspberry Pi"
    }

    ($report | ConvertTo-Json -Depth 8) | Set-Content -Path $finalReportPath -Encoding UTF8

    Write-Output "[Phase7-Stage3] REPORT: reports/phase7_stage3_final_acceptance_report.json"
    Write-Output ("[Phase7-Stage3] SUMMARY: tests={0} passed={1} failed={2} errors={3} sampling_overall={4}" -f $tests,$passed,$failures,$errors,$sampling.pass.overall)
    exit 0
} catch {
    Write-Error $_
    exit 1
}
