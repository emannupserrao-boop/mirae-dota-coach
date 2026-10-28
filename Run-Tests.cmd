@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Execute Install.cmd primeiro.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
set "test_result=%errorlevel%"
echo Testes de voz e imagens usam estimulos SINTETICOS; nao validam Dota real.
pause
exit /b %test_result%
