@echo off
title HHGOA Fraud Investigation Platform - Launching
color 0A

echo =====================================================================
echo   HHGOA Agentic Fraud Investigation Platform
echo   TigerGraph + LangGraph + GraphRAG + Vision UI Dashboard
echo =====================================================================
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo [1/3] Launching TigerGraph MCP Server on port 8765...
start "HHGOA - TigerGraph MCP Server (Port 8765)" cmd /k "title MCP Server [Port 8765] && color 0B && python -m uvicorn graph.mcp_server:app --host 0.0.0.0 --port 8765"

timeout /t 3 /nobreak >nul

echo [2/3] Launching Unified Agent & Vision UI Server on port 8000...
start "HHGOA - Unified Agent Platform (Port 8000)" cmd /k "title Agent & Vision UI Server [Port 8000] && color 0A && python server.py"

timeout /t 3 /nobreak >nul

echo [3/3] Opening Vision UI Dashboard in your default browser...
start http://localhost:8000

echo.
echo =====================================================================
echo   SUCCESS: Both services are running in separate terminal windows!
echo   - Vision UI Dashboard : http://localhost:8000
echo   - Agent Status API    : http://localhost:8000/api/status
echo   - TigerGraph MCP Tool : http://localhost:8765/health
echo =====================================================================
echo   To stop all servers, run 'stop.bat' or close the terminal windows.
echo.
pause
