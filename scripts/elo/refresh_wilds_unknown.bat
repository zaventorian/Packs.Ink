@echo off
REM Weekly Wilds Unknown refresh — run every Monday morning.
REM
REM Pulls the latest results for every Wilds Unknown event from RPH, applies
REM any new auto-merges, recomputes ELO, and pushes to Supabase. Idempotent:
REM events still in EVENT_FINISHED state with full data are skipped.
REM
REM Edit XLSX_PATH if you move the source spreadsheet.

setlocal
set XLSX_PATH=C:\Users\zaven\Downloads\Chicago Set Champs - wo_ Descriptions.xlsx
set SEASON=Wilds Unknown Summer 2026
cd /d "%~dp0"

echo === ingest =====================================
python ingest.py --xlsx "%XLSX_PATH%" --season "%SEASON%" --workers 8
if errorlevel 1 goto :fail

echo.
echo === auto-merge new player names ================
python suggest_aliases.py
python apply_aliases.py aliases_auto.csv

echo.
echo === recompute ELO ==============================
python elo.py --top 10 --min-matches 5

echo.
echo === push to Supabase ===========================
cd ..\..
python scripts\export_elo_to_supabase.py

echo.
echo done.
goto :eof

:fail
echo.
echo refresh FAILED. inspect output above.
exit /b 1
