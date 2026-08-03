@echo off
chcp 65001 >nul
REM EACO Daily Agent - Windows Task Scheduler Batch File
REM This script runs the EACO daily agent and logs output

set PYTHON_PATH=D:\dazi\lightsandbox\python\python.exe
set AGENT_DIR=C:\Users\Administrator\.qianfan\workspace\53548a18c33549c5b5c15d8bd451594d\eaco-agent
set LOG_FILE=%AGENT_DIR%\eaco_agent_scheduler.log

echo ============================================================ >> "%LOG_FILE%"
echo [%date% %time%] Scheduler triggered >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

cd /d "%AGENT_DIR%"
"%PYTHON_PATH%" eaco_daily_agent.py >> "%LOG_FILE%" 2>&1

echo [%date% %time%] Scheduler finished >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
