#!/bin/bash

echo "=========================================="
echo "  启动 Vision Agent 实时交互感知系统"
echo "=========================================="
echo ""

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "❌ 错误: .env 文件不存在"
    echo ""
    echo "请先运行 ./setup.sh 进行初始化配置"
    exit 1
fi

# 加载环境变量并检查
source .env 2>/dev/null || true

if [ -z "$STREAM_API_KEY" ]; then
    echo "❌ 错误: STREAM_API_KEY 未配置"
    echo ""
    echo "请编辑 .env 文件并填入你的 Stream API 密钥"
    echo "获取免费密钥: https://getstream.io"
    exit 1
fi

if [ -z "$GEMINI_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ 错误: 需要配置 GEMINI_API_KEY 或 OPENAI_API_KEY"
    echo ""
    echo "请编辑 .env 文件并填入至少一个 AI API 密钥"
    echo "- Gemini API: https://ai.google.dev/"
    echo "- OpenAI API: https://platform.openai.com/"
    exit 1
fi

echo "✓ 环境配置检查通过"
echo ""
echo "Stream API: ✓"
if [ -n "$GEMINI_API_KEY" ]; then
    echo "Gemini API: ✓"
fi
if [ -n "$OPENAI_API_KEY" ]; then
    echo "OpenAI API: ✓"
fi
echo ""
echo "----------------------------------------"
echo "正在启动 Agent..."
echo "----------------------------------------"
echo ""
echo "Agent 启动后会："
echo "1. 创建视频通话"
echo "2. 自动打开浏览器演示界面"
echo "3. Agent 加入通话并开始交互"
echo ""
echo "提示："
echo "- 允许浏览器访问摄像头和麦克风"
echo "- 对着摄像头做动作或展示物品"
echo "- AI 会实时分析并给出反馈"
echo ""
echo "按 Ctrl+C 停止运行"
echo ""
echo "=========================================="
echo ""

# 运行 agent
if command -v uv &> /dev/null; then
    echo "使用 uv 运行 Agent..."
    uv run python vision_agent_demo.py
else
    echo "使用 python3 运行 Agent..."
    python3 vision_agent_demo.py
fi
