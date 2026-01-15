@echo off
echo ==========================================
echo   启动 Vision Agent 实时交互感知系统
echo ==========================================
echo.

REM 检查 .env 文件
if not exist .env (
    echo ❌ 错误: .env 文件不存在
    echo.
    echo 请先复制 .env.example 为 .env 并填入 API 密钥
    pause
    exit /b 1
)

echo ✓ 环境配置文件存在
echo.
echo ----------------------------------------
echo 正在启动 Agent...
echo ----------------------------------------
echo.
echo Agent 启动后会：
echo 1. 创建视频通话
echo 2. 自动打开浏览器演示界面
echo 3. Agent 加入通话并开始交互
echo.
echo 提示：
echo - 允许浏览器访问摄像头和麦克风
echo - 对着摄像头做动作或展示物品
echo - AI 会实时分析并给出反馈
echo.
echo 按 Ctrl+C 停止运行
echo.
echo ==========================================
echo.

REM 运行 agent
python vision_agent_demo.py

pause
