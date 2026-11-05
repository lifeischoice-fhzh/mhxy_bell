@echo off
setlocal
cd /d "%~dp0.."

rem One-stop dev venv setup: create .venv, install the pinned deps, then make
rem sure the DirectML build of onnxruntime wins over the CPU one (see the note
rem at the top of requirements.txt).

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [venv] creating .venv ...
    python -m venv .venv || goto :err
)

echo [venv] installing requirements ...
"%PY%" -m pip install -U pip || goto :err
"%PY%" -m pip install -r requirements.txt || goto :err

rem rapidocr-onnxruntime declares a dependency on the CPU "onnxruntime" wheel;
rem both wheels write the same onnxruntime/ directory, and whichever lands last
rem owns it. Force the DirectML build back on top, then verify the provider.
echo [venv] restoring onnxruntime-directml ...
"%PY%" -m pip install --force-reinstall --no-deps onnxruntime-directml==1.24.4 || goto :err

"%PY%" -c "import onnxruntime as o; ps = o.get_available_providers(); print('providers:', ps); import sys; sys.exit(0 if 'DmlExecutionProvider' in ps else 1)" || goto :err

echo [OK] .venv ready, DirectML available
exit /b 0

:err
echo [FAILED] see the error above
exit /b 1
