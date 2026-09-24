@echo off
title HHGOA Fraud Investigation Platform - Stopping Services
color 0C

echo =====================================================================
echo   Shutting down HHGOA Platform Services...
echo =====================================================================
echo.

echo [1/2] Terminating service on Port 8000 (Unified Server)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Stopping PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/2] Terminating service on Port 8765 (TigerGraph MCP Server)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765" ^| findstr "LISTENING"') do (
    echo Stopping PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo All HHGOA Platform services have been stopped.
echo.
pause
