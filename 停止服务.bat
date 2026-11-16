@echo off
chcp 936 >nul
setlocal EnableExtensions
title 慢性病患者健康风险预测与干预 · 停止服务
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"
echo ==================================================
echo   停止本项目的 API 服务（端口 %PORT%）
echo ==================================================
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% " ^| findstr /c:"LISTENING"') do set "FOUND=%%P"
if not defined FOUND (
    echo 端口 %PORT% 上没有正在监听的服务，无需停止。
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)
echo 端口 %PORT% 由进程 PID=%FOUND% 监听，正在结束 ...
taskkill /F /PID %FOUND% >nul 2>&1
if errorlevel 1 (
    echo [警告] 结束进程失败，请右键以管理员身份运行本文件。
) else (
    echo 已结束进程 PID=%FOUND%，端口 %PORT% 已释放。
)
ping -n 3 127.0.0.1 >nul
exit /b 0
