$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Get-Command python -ErrorAction SilentlyContinue) {
  $python = "python"
} elseif (Test-Path $bundledPython) {
  $python = $bundledPython
} else {
  throw "Python was not found. Install Python 3.11+ or run this from Codex with the bundled runtime."
}

Set-Location $repoRoot
& $python -m backend.server --host 127.0.0.1 --port 8000
