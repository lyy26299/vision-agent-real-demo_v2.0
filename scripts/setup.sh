#!/bin/bash

echo "=========================================="
echo "  Vision Agent 实时交互感知演示 - 安装"
echo "=========================================="
echo ""

# 检查 Python 版本
echo "检查 Python 版本..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required_version="3.13"

echo "当前 Python 版本: $python_version"
echo "要求版本: >= $required_version"
echo ""

# 检查是否安装了 uv
if command -v uv &> /dev/null; then
    echo "✓ 检测到 uv 包管理器"
    use_uv=true
else
    echo "⚠ 未检测到 uv，推荐安装以获得更快的依赖安装速度"
    echo ""
    read -p "是否现在安装 uv? (y/n): " install_uv
    if [ "$install_uv" = "y" ]; then
        echo "安装 uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
        use_uv=true
    else
        use_uv=false
    fi
fi

echo ""
echo "----------------------------------------"
echo "安装依赖包..."
echo "----------------------------------------"

if [ "$use_uv" = true ]; then
    echo "使用 uv sync 安装依赖..."
    uv sync
else
    echo "使用 pip 安装依赖..."
    pip3 install -e .
fi

echo ""
echo "----------------------------------------"
echo "配置环境变量..."
echo "----------------------------------------"

if [ ! -f .env ]; then
    echo "创建 .env 文件..."
    cp .env.example .env
    echo ""
    echo "⚠ 重要: 请编辑 .env 文件并填入你的 API 密钥"
    echo ""
    echo "需要的 API 密钥:"
    echo "1. Stream API (必需) - https://getstream.io"
    echo "2. Gemini API (推荐) - https://ai.google.dev/"
    echo "   或 OpenAI API - https://platform.openai.com/"
    echo ""
    read -p "按回车键打开 .env 文件进行编辑..."

    if command -v nano &> /dev/null; then
        nano .env
    elif command -v vim &> /dev/null; then
        vim .env
    else
        echo "请手动编辑 .env 文件: nano .env 或 vim .env"
    fi
else
    echo "✓ .env 文件已存在"
fi

echo ""
echo "----------------------------------------"
echo "下载 YOLO 模型（如果需要）..."
echo "----------------------------------------"

if [ ! -f yolo11n-pose.pt ]; then
    echo "下载 YOLO 11 Pose 模型..."
    echo "注意: 首次运行时 Ultralytics 会自动下载"
else
    echo "✓ YOLO 模型已存在"
fi

echo ""
echo "=========================================="
echo "  安装完成！"
echo "=========================================="
echo ""
echo "下一步:"
echo "1. 确保 .env 文件中的 API 密钥已正确配置"
echo "2. 运行程序: ./run.sh 或 python3 vision_agent_demo.py"
echo ""
echo "快速测试 API 配置:"
echo "  python3 -c 'from dotenv import load_dotenv; import os; load_dotenv(); print(\"Stream Key:\", \"✓\" if os.getenv(\"STREAM_API_KEY\") else \"✗\"); print(\"Gemini Key:\", \"✓\" if os.getenv(\"GEMINI_API_KEY\") else \"✗\")'"
echo ""
