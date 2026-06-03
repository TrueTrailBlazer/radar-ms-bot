@echo off
chcp 65001 >nul
echo ===================================================
echo     Radar MS - Sincronização Local (Anti-Bloqueio)
echo ===================================================
echo.
echo Puxando atualizacoes do GitHub...
git pull --rebase origin main

echo.
echo Rodando os robos (isso vai acessar o Diogrande com seu IP Brasileiro)...
python main.py --diogrande-only

echo.
echo Salvando vagas encontradas no GitHub...
git add database.json health.json
git commit -m "Auto-update do PC Local [skip ci]"
git push origin main

echo.
echo ===================================================
echo   Concluido! Verifique seu Telegram e o Painel.
echo ===================================================
timeout /t 5
