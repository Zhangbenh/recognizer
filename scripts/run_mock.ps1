param(
    [int]$MaxTicks,
    [double]$IdleSleep = 0.02,
    [string]$LogLevel = "INFO"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv/Scripts/python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

$args = @(
    "app/main.py",
    "--runtime", "mock",
    "--input", "keyboard",
    "--idle-sleep", "$IdleSleep",
    "--log-level", "$LogLevel"
)

if ($PSBoundParameters.ContainsKey("MaxTicks")) {
    $args += @("--max-ticks", "$MaxTicks")
}

Set-Location $repoRoot
& $pythonExe @args
exit $LASTEXITCODE
