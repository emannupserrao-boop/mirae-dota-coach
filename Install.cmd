@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto deps
py -3.13 -c "import tkinter" >nul 2>nul
if not errorlevel 1 (
  py -3.13 -m venv .venv
  goto check
)
py -3.12 -c "import tkinter" >nul 2>nul
if not errorlevel 1 (
  py -3.12 -m venv .venv
  goto check
)
python -c "import sys, tkinter; assert (3,12) <= sys.version_info[:2] <= (3,13)" >nul 2>nul
if errorlevel 1 goto missing
python -m venv .venv
:check
if not exist ".venv\Scripts\python.exe" goto failed
:deps
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-vision.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import tkinter, cv2, numpy, PIL, mss, psutil; print('Dependencias OK')"
if errorlevel 1 goto failed
echo Instalacao concluida. Abra Start-Bot-Test.cmd para o primeiro teste.
pause
exit /b 0
:missing
echo Instale Python 3.13 de 64 bits, incluindo Tcl/Tk e Python Launcher.
echo https://www.python.org/downloads/windows/
pause
exit /b 1
:failed
echo Falha na instalacao. Copie a mensagem acima. Nao e necessario executar como administrador.
pause
exit /b 1
