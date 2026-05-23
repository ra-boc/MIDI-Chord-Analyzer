@echo off
setlocal
cd /d "%~dp0.."

set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" -m backend.server --host 127.0.0.1 --port 8000
) else (
  python -m backend.server --host 127.0.0.1 --port 8000
)
