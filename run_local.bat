@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo No se pudo crear el entorno virtual. Instala Python 3.12.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
pause
