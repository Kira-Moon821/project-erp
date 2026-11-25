@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "URL=http://127.0.0.1:8000"
set "SYS=%SystemRoot%\System32"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

echo ========================================
echo    ERP 经营分析实验室 一键启动
echo ========================================
echo.

"%SYS%\curl.exe" -sf -o nul --max-time 2 "%URL%/health" >nul 2>&1
if not errorlevel 1 (
    echo [OK] 服务已经在运行，直接打开 Edge
    goto open
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [X] 没有检测到 Python 3.11 以上版本
    echo     请先安装 Python，安装时勾选 Add Python to PATH
    pause
    exit /b 1
)

echo [1/2] 启动后端服务，会新开一个窗口，请不要关闭
start "ERP Server" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [2/2] 等待服务就绪
for /l %%i in (1,1,20) do (
    "%SYS%\curl.exe" -sf -o nul --max-time 1 "%URL%/health" >nul 2>&1
    if not errorlevel 1 goto open
    "%SYS%\timeout.exe" /t 1 /nobreak >nul
)

echo.
echo [X] 启动超时，请查看 ERP Server 窗口里的报错
echo     如果提示端口被占用，先关闭旧的 ERP Server 窗口
pause
exit /b 1

:open
if exist "%EDGE%" (
    start "" "%EDGE%" "%URL%"
) else (
    start "" "%URL%"
)
echo.
echo 网站地址：%URL%
echo 登录账号：analyst
echo 登录密码：Analyst@123456
echo.
echo 关闭本窗口不影响网站，停止服务请关闭 ERP Server 窗口
"%SYS%\timeout.exe" /t 8 /nobreak >nul
exit /b 0
