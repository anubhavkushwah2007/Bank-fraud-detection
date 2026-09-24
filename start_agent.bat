@echo off
title HHGOA Fraud Investigation Platform - Launching
color 0A

echo =====================================================================
echo   HHGOA Agentic Fraud Investigation Platform
echo   TigerGraph + LangGraph + GraphRAG + Vision UI Dashboard
echo =====================================================================
echo.

:: Resolve target agent directory
set "BASE_DIR=%~dp0"
if exist "%BASE_DIR%fraud-investigation-agent\server.py" (
    cd /d "%BASE_DIR%fraud-investigation-agent"
) else (
    cd /d "%BASE_DIR%"
)

echo Current working directory: %CD%
echo.

:: 1. Launch TigerGraph MCP Server on port 8765 in a dedicated window
echo [1/3] Launching TigerGraph MCP Server on port 8765...
start "HHGOA - TigerGraph MCP Server (Port 8765)" cmd /k "title MCP Server [Port 8765] && color 0B && python -m uvicorn graph.mcp_server:app --host 0.0.0.0 --port 8765"

:: Wait 3 seconds for MCP server socket to initialize
timeout /t 3 /nobreak >nul

:: 2. Launch Unified Platform Server (FastAPI + Vision UI) on port 8000
echo [2/3] Launching Unified Agent & Vision UI Server on port 8000...
start "HHGOA - Unified Agent Platform (Port 8000)" cmd /k "title Agent & Vision UI Server [Port 8000] && color 0A && python server.py"

:: Wait 3 seconds for server to bind
timeout /t 3 /nobreak >nul

:: 3. Open browser to the dashboard
echo [3/3] Opening Vision UI Dashboard in your default browser...
start http://localhost:8000

echo.
echo =====================================================================
echo   SUCCESS: Both services are now running in separate terminal windows!
echo.
echo   * Vision UI Dashboard  : http://localhost:8000
echo   * System API Status    : http://localhost:8000/api/status
echo   * 20 Benchmark Cases   : http://localhost:8000/api/cases
echo   * TigerGraph MCP Tools : http://localhost:8765/health
echo =====================================================================
echo   Keep the two opened terminal windows running while using the platform.
echo   To shut down both servers, run stop_agent.bat or close their windows.
echo.
pause
