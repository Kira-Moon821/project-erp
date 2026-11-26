@echo off
rem 由 启动网站.bat 调用：真正跑 uvicorn 的窗口
rem 解释器路径通过环境变量 ERP_PY 传入，避免嵌套引号被 cmd 吃掉
cd /d "%~dp0.."

if not defined ERP_PY (
    echo [X] 没有收到解释器路径（ERP_PY 未设置）
    echo     请不要直接双击本文件，改双击上一层的 启动网站.bat
    pause
    exit /b 1
)

echo 解释器：%ERP_PY%
echo 服务地址：http://127.0.0.1:8000
echo.
echo 启动中…… 启动成功后请不要关闭本窗口
echo 关闭本窗口即停止服务
echo ----------------------------------------
"%ERP_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo ----------------------------------------
echo.
echo [服务已退出] 退出码 %ERRORLEVEL%
echo 如果上面有报错信息，请把本窗口截图发给开发者
pause
exit /b %ERRORLEVEL%
