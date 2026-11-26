@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0pet_app.py"
) else (
    start "" pythonw "%~dp0pet_app.py"
)
