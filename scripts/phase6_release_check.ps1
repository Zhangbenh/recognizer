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

function Invoke-Step {
    param(
        [string]$Title,
        [string[]]$StepArgs
    )

    Write-Output "[Phase6] START: $Title"
    & $PythonExe @StepArgs
    if ($LASTEXITCODE -ne 0) {
        throw "[Phase6] FAILED: $Title (exit=$LASTEXITCODE)"
    }
    Write-Output "[Phase6] PASS : $Title"
}

Set-Location $repoRoot

try {
    Invoke-Step -Title "pytest" -StepArgs @("-m", "pytest", "-q")

    Invoke-Step -Title "phase4 mock acceptance" -StepArgs @(
        "scripts/phase4_real_runtime_acceptance.py",
        "--runtime", "mock",
        "--input", "keyboard",
        "--samples", "20",
        "--warmup", "3",
        "--sleep-s", "0.01",
        "--output", "reports/phase6_phase4_mock_report.json"
    )

    Invoke-Step -Title "phase5 mock acceptance" -StepArgs @(
        "scripts/phase5_sampling_mode_acceptance.py",
        "--runtime", "mock",
        "--input", "keyboard",
        "--cycles", "10",
        "--output", "reports/phase6_phase5_mock_report.json"
    )

    Write-Output "[Phase6] ALL CHECKS PASSED"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
