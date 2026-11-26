@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "URL=http://127.0.0.1:8000"
set "SYS=%SystemRoot%\System32"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
set "PY="
set "ERP_PY="

echo ========================================
echo    ERP 经营分析实验室 一键启动
echo ========================================
echo.

"%SYS%\curl.exe" -sf -o nul --max-time 2 "%URL%/health" >nul 2>&1
if not errorlevel 1 (
    echo [OK] 服务已经在运行，直接打开浏览器
    goto open
)

rem ---- 找一个真正装了 uvicorn 的解释器：项目虚拟环境优先 ----
if exist "%~dp0.venv\Scripts\python.exe" call :probe "%~dp0.venv\Scripts\python.exe"
if defined PY goto found
for /f "delims=" %%p in ('where python 2^>nul') do call :probe "%%p"
if defined PY goto found
for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do call :probe "%%~d\python.exe"
if defined PY goto found
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :probe "%%~d\python.exe"
if defined PY goto found
goto nopython

:found
set "ERP_PY=%PY%"
echo [1/3] 解释器：%ERP_PY%
echo [2/3] 启动后端服务，会新开一个窗口，请不要关闭
start "ERP Server" /D "%~dp0" cmd /k scripts\serve.cmd

echo [3/3] 等待服务就绪
for /l %%i in (1,1,30) do (
    "%SYS%\curl.exe" -sf -o nul --max-time 1 "%URL%/health" >nul 2>&1
    if not errorlevel 1 goto open
    "%SYS%\ping.exe" -n 2 127.0.0.1 >nul 2>&1
)

echo.
echo [X] 启动超时，请看 ERP Server 窗口里的报错
echo     常见原因：端口 8000 被占用、依赖没装全
pause
exit /b 1

:nopython
echo [X] 没找到装了依赖的 Python 解释器
echo.
echo     在项目根目录（本文件的同级目录）依次执行：
echo         python -m venv .venv
echo         .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo     装完再双击本文件即可。
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
"%SYS%\ping.exe" -n 9 127.0.0.1 >nul 2>&1
exit /b 0

rem ---- 子过程：测试候选解释器能否 import uvicorn ----
:probe
if defined PY exit /b 0
if not exist %1 exit /b 0
echo %~1 | "%SYS%\find.exe" /i "WindowsApps" >nul 2>&1
if not errorlevel 1 exit /b 0
%1 -c "import uvicorn" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0
