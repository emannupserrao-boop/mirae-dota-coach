@echo off
setlocal
cd /d "%~dp0"
echo ALPHA 0.2 - TEST MODE - use partida SOLO contra bots.
echo Vision inicia DESLIGADO e exige calibracao e ativacao explicitas.
call Start-Coach.cmd --test-mode
