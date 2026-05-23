$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path "node_modules")) {
  npm.cmd install
}

npm.cmd run dev
