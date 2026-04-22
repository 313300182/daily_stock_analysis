@echo off
chcp 65001 >nul
setlocal

:: 步骤 1：导出 Prompt（数据采集 + 组装 prompt）
echo ============================================
echo  步骤 1/2：采集数据 + 导出 Prompt
echo ============================================

set PYTHON=D:\python\envs\py311\python.exe
set PROJECT_DIR=d:\个人开发\daily_stock_analysis

cd /d "%PROJECT_DIR%"
%PYTHON% main.py --export-prompts --force-run

if %ERRORLEVEL% NEQ 0 (
    echo [错误] 导出失败，请检查日志
    pause
    exit /b 1
)

:: 获取今天的日期目录
for /f "tokens=1-3 delims=/ " %%a in ('echo %date%') do set TODAY=%%a%%b%%c
:: 兼容不同日期格式
for /f %%i in ('%PYTHON% -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d'))"') do set TODAY=%%i

echo.
echo ============================================
echo  导出完成！Prompt 目录: exports\%TODAY%\prompts
echo ============================================
echo.
echo  [下一步] 在 Cursor 中对 Claude 说:
echo.
echo  读取 exports/%TODAY%/prompts 目录下所有文件逐个分析,
echo  个股 prompt 结果保存到 exports/%TODAY%/results/ 目录,
echo  大盘复盘结果保存到 exports/%TODAY%/results/_market_review.md
echo.
echo  分析完成后, 运行 daily_import.bat 生成日报并发送邮件。
echo ============================================
pause
