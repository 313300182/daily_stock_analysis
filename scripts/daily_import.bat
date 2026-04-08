@echo off
chcp 65001 >nul
setlocal

:: 步骤 3：导入分析结果 → 生成日报 + 发邮件
echo ============================================
echo  步骤 2/2：导入结果 + 生成日报 + 发邮件
echo ============================================

set PYTHON=D:\python\envs\py311\python.exe
set PROJECT_DIR=d:\个人开发\daily_stock_analysis

cd /d "%PROJECT_DIR%"

:: 获取今天日期
for /f %%i in ('%PYTHON% -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d'))"') do set TODAY=%%i

set RESULTS_DIR=exports\%TODAY%\results

:: 检查结果目录是否有文件
dir /b "%RESULTS_DIR%\*.json" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未找到分析结果文件: %RESULTS_DIR%
    echo 请先在 Cursor 中完成分析，将结果保存到 results 目录
    pause
    exit /b 1
)

echo 导入目录: exports\%TODAY%
%PYTHON% main.py --import-analysis exports/%TODAY%

if %ERRORLEVEL% NEQ 0 (
    echo [错误] 导入失败，请检查日志
    pause
    exit /b 1
)

echo.
echo ============================================
echo  日报已生成并发送！
echo  报告文件: reports\report_%TODAY%.md
echo ============================================
pause
