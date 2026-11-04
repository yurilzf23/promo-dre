@echo off
REM Promo Dre - coleta da Pichau pelo seu PC (a Pichau bloqueia os servidores do GitHub)
REM Use pelo Agendador de Tarefas a cada 3 horas. Passo a passo no README.
cd /d "%~dp0"
set PROMODRE_PERFIL=pc
set PYTHONUTF8=1
echo ==== %date% %time% ====>> coletar_pc.log
git pull --rebase -q origin main >> coletar_pc.log 2>&1
".venv\Scripts\python.exe" -m promodre.main coletar --so pichau >> coletar_pc.log 2>&1
git add data/historico_pc.csv data/estado_pc.json data/imagens_pc.json >> coletar_pc.log 2>&1
git commit -q -m "coleta pc %date% %time%" >> coletar_pc.log 2>&1
git push -q origin main >> coletar_pc.log 2>&1
