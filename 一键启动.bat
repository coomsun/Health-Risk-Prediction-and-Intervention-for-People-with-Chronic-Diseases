@echo off
chcp 936 >nul
setlocal EnableExtensions
title 慢性病患者健康风险预测与干预 · 一键启动（翻页式大屏）
cd /d "%~dp0"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"
set "LOGDIR=%ROOT%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ==================================================
echo   慢性病患者健康风险预测与干预 · 一键启动
echo   目标页面：翻页式多屏大屏  /screen/
echo ==================================================
echo   项目目录 : %ROOT%
echo   服务端口 : %PORT%   （默认 8000；换端口：一键启动.bat 8010）
echo   数据口径 : CDC BRFSS 2012-2025 十四年（约 620 万条）
echo.

rem ---------- 1/4 定位 Python 解释器 ----------
set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY if exist "D:\期末作业\.venv\Scripts\python.exe" set "PY=D:\期末作业\.venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY (
    echo [错误] 没有找到 Python 解释器。
    echo        请安装 Python 3.12，然后在项目目录执行： python -m venv .venv
    echo        或者把解释器绝对路径写进本文件的 PY 变量。
    echo.
    pause
    exit /b 1
)
echo [1/4] 解释器 : %PY%
"%PY%" -c "import fastapi, uvicorn, pandas, numpy, joblib, lightgbm" >nul 2>nul
if errorlevel 1 (
    echo [错误] 该解释器缺少运行依赖，缺失项如下：
    "%PY%" -c "import fastapi, uvicorn, pandas, numpy, joblib, lightgbm"
    echo        安装命令： "%PY%" -m pip install -r "%ROOT%\requirements-api.txt"
    echo.
    pause
    exit /b 1
)
echo         依赖齐全。

rem ---------- 2/4 端口是否已被占用 ----------
"%PY%" -c "import socket,sys;s=socket.socket();sys.exit(0 if s.connect_ex(('127.0.0.1',int(sys.argv[1])))==0 else 1)" %PORT%
if not errorlevel 1 goto port_busy
echo [2/4] 端口 %PORT% 空闲。
goto launch

:port_busy
echo [2/4] 端口 %PORT% 已被占用，检查是否已经是本项目的服务 ...
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%PORT%/api/v1/health',timeout=3)" >nul 2>nul
if not errorlevel 1 goto already_running
echo [错误] 端口 %PORT% 被别的程序占用，本项目服务没有起来。
echo        换一个端口试试： 一键启动.bat 8010
echo        查占用进程    ： netstat -ano ^| findstr :%PORT%
echo.
pause
exit /b 1

:already_running
echo        本项目的 API 已经在 %PORT% 端口运行，不再重复启动。
goto open_dashboard

rem ---------- 3/4 启动服务并等待就绪 ----------
:launch
echo [3/4] 启动 FastAPI 服务（最小化窗口；日志写入 logs\api_%PORT%.log）...
start "慢性病风险预测-API-%PORT%" /min cmd /c ""%PY%" -m uvicorn api.main:app --host 127.0.0.1 --port %PORT% >> "%LOGDIR%\api_%PORT%.log" 2>&1"
set /a WAIT=0
:wait_ready
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%PORT%/api/v1/health',timeout=2)" >nul 2>nul
if not errorlevel 1 goto ready
set /a WAIT=%WAIT%+1
if %WAIT% geq 90 goto not_ready
ping -n 2 127.0.0.1 >nul
goto wait_ready

:not_ready
echo [错误] 90 秒内服务未就绪。日志末尾：
echo --------------------------------------------------
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGDIR%\api_%PORT%.log' -Tail 25 -Encoding UTF8" 2>nul
echo --------------------------------------------------
echo        完整日志： %LOGDIR%\api_%PORT%.log
echo.
pause
exit /b 1

:ready
echo        服务已就绪。

rem ---------- 4/4 打开翻页式大屏 ----------
:open_dashboard
set "DASH=http://127.0.0.1:%PORT%/screen/"
echo [4/4] 打开翻页式大屏： %DASH%
start "" "%DASH%"
echo        （若浏览器没有自动弹出，把上面这行地址复制到浏览器打开）
echo.
echo --------------------------------------------------
echo  翻页大屏 : %DASH%          （← 演示看这个）
echo  单页大屏 : http://127.0.0.1:%PORT%/                （初版单页，备用）
echo  API 文档 : http://127.0.0.1:%PORT%/docs
echo  健康检查 : http://127.0.0.1:%PORT%/api/v1/health
echo  运行日志 : %LOGDIR%\api_%PORT%.log
echo  停止服务 : 双击 停止服务.bat（或 停止服务.bat %PORT%）
echo --------------------------------------------------
echo  本窗口可关闭，服务在最小化窗口中继续运行。
ping -n 6 127.0.0.1 >nul
exit /b 0
