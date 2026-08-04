@echo off
chcp 65001 >nul
REM Create Windows Scheduled Task for EACO Daily Agent v5.0
REM This script creates a daily scheduled task that runs at 08:00 AM
REM Run this script ONCE as Administrator to set up the task

echo ============================================
echo  EACO Daily Agent v5.0 - Task Scheduler Setup
echo ============================================
echo.
echo Creating scheduled task: EACO_Daily_Agent
echo Schedule: Daily at 08:00 AM (Beijing Time)
echo Script: run_daily.bat
echo.

REM Create the scheduled task
schtasks /create /tn "EACO_Daily_Agent" /tr "C:\Users\Administrator\.qianfan\workspace\53548a18c33549c5b5c15d8bd451594d\eaco-agent\run_daily.bat" /sc daily /st 08:00 /f

if %errorlevel% equ 0 (
    echo.
    echo SUCCESS! Scheduled task created.
    echo The EACO Daily Agent will run automatically every day at 08:00 AM.
    echo.
    echo To test immediately: run_daily.bat --test
    echo To run normally:     run_daily.bat
    echo To view task:        schtasks /query /tn "EACO_Daily_Agent" /v
    echo To delete task:      schtasks /delete /tn "EACO_Daily_Agent" /f
) else (
    echo.
    echo FAILED to create scheduled task. Try running as Administrator.
)

echo.
pause
