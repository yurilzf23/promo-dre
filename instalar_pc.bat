@echo off
REM Promo Dre - prepara o ambiente Python no PC (rodar uma vez)
cd /d "%~dp0"
python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Pronto. Agora crie o webhook.txt e rode coletar_pc.bat para testar.
pause
