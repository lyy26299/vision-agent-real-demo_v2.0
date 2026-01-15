#!/usr/bin/env python3
"""
测试 Vision Agent 环境配置
运行此脚本检查所有依赖和 API 密钥是否正确配置
"""
import sys
import os
from pathlib import Path


def print_header(text):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_check(name, status, detail=""):
    icon = "✓" if status else "✗"
    status_text = "通过" if status else "失败"
    print(f"{icon} {name}: {status_text}")
    if detail:
        print(f"  → {detail}")


def check_python_version():
    print_header("检查 Python 版本")
    version = sys.version_info
    required = (3, 13)

    current = f"{version.major}.{version.minor}.{version.micro}"
    required_str = f"{required[0]}.{required[1]}+"

    is_ok = version >= required
    print_check(
        "Python 版本",
        is_ok,
        f"当前: {current}, 要求: {required_str}"
    )
    return is_ok


def check_dependencies():
    print_header("检查 Python 依赖包")

    checks = []

    # 检查 vision_agents
    try:
        import vision_agents
        print_check("vision-agents", True, f"版本: {getattr(vision_agents, '__version__', '未知')}")
        checks.append(True)
    except ImportError as e:
        print_check("vision-agents", False, f"未安装: {e}")
        checks.append(False)

    # 检查 dotenv
    try:
        import dotenv
        print_check("python-dotenv", True)
        checks.append(True)
    except ImportError:
        print_check("python-dotenv", False, "未安装")
        checks.append(False)

    # 检查 ultralytics
    try:
        import ultralytics
        print_check("ultralytics (YOLO)", True, f"版本: {ultralytics.__version__}")
        checks.append(True)
    except ImportError:
        print_check("ultralytics", False, "未安装")
        checks.append(False)

    return all(checks)


def check_env_file():
    print_header("检查环境变量配置")

    env_path = Path(".env")
    if not env_path.exists():
        print_check(".env 文件", False, "文件不存在，请复制 .env.example")
        return False

    print_check(".env 文件", True, "文件存在")

    # 加载环境变量
    from dotenv import load_dotenv
    load_dotenv()

    checks = []

    # 检查 Stream API
    stream_key = os.getenv("STREAM_API_KEY")
    stream_secret = os.getenv("STREAM_API_SECRET")

    if stream_key and stream_key != "your_stream_api_key_here":
        print_check("STREAM_API_KEY", True, f"已配置 ({stream_key[:10]}...)")
        checks.append(True)
    else:
        print_check("STREAM_API_KEY", False, "未配置或使用默认值")
        checks.append(False)

    if stream_secret and stream_secret != "your_stream_secret_here":
        print_check("STREAM_API_SECRET", True, f"已配置 ({stream_secret[:10]}...)")
        checks.append(True)
    else:
        print_check("STREAM_API_SECRET", False, "未配置或使用默认值")
        checks.append(False)

    # 检查 AI API（至少需要一个）
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    has_ai_key = False

    if gemini_key and gemini_key != "your_gemini_api_key_here":
        print_check("GEMINI_API_KEY", True, f"已配置 ({gemini_key[:10]}...)")
        has_ai_key = True
    else:
        print_check("GEMINI_API_KEY", False, "未配置")

    if openai_key and openai_key != "your_openai_api_key_here":
        print_check("OPENAI_API_KEY", True, f"已配置 ({openai_key[:10]}...)")
        has_ai_key = True
    else:
        print_check("OPENAI_API_KEY", False, "未配置")

    if not has_ai_key:
        print("\n⚠ 警告: 至少需要配置 GEMINI_API_KEY 或 OPENAI_API_KEY")
        checks.append(False)
    else:
        checks.append(True)

    return all(checks)


def check_yolo_model():
    print_header("检查 YOLO 模型")

    model_path = Path("yolo11n-pose.pt")

    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        print_check("yolo11n-pose.pt", True, f"已下载 ({size_mb:.1f} MB)")
        return True
    else:
        print_check("yolo11n-pose.pt", False, "首次运行时会自动下载")
        return True  # 不算失败，因为会自动下载


def check_instructions():
    print_header("检查指令文件")

    instructions_path = Path("vision_assistant.md")

    if instructions_path.exists():
        size_kb = instructions_path.stat().st_size / 1024
        print_check("vision_assistant.md", True, f"存在 ({size_kb:.1f} KB)")
        return True
    else:
        print_check("vision_assistant.md", False, "指令文件缺失")
        return False


def print_summary(results):
    print_header("测试总结")

    total = len(results)
    passed = sum(results.values())
    failed = total - passed

    print(f"\n总计: {total} 项检查")
    print(f"✓ 通过: {passed}")
    print(f"✗ 失败: {failed}")

    if all(results.values()):
        print("\n🎉 所有检查通过！你可以运行 ./run.sh 启动 Agent")
        print("\n快速启动:")
        print("  ./run.sh              # macOS/Linux")
        print("  run.bat               # Windows")
        print("  python vision_agent_demo.py")
        return 0
    else:
        print("\n⚠ 部分检查失败，请根据上述提示修复问题")
        print("\n常见解决方案:")

        if not results.get("python"):
            print("- Python 版本: 升级到 3.13+")
        if not results.get("deps"):
            print("- 依赖包: 运行 ./setup.sh 或 pip install -e .")
        if not results.get("env"):
            print("- 环境变量: 编辑 .env 文件并填入正确的 API 密钥")
        if not results.get("instructions"):
            print("- 指令文件: 确保 vision_assistant.md 存在")

        print("\n获取 API 密钥:")
        print("- Stream API: https://getstream.io")
        print("- Gemini API: https://ai.google.dev/")

        return 1


def main():
    print_header("Vision Agent 环境配置测试")
    print("此脚本将检查所有必需的依赖和配置")

    results = {}

    # 运行所有检查
    results["python"] = check_python_version()
    results["deps"] = check_dependencies()
    results["env"] = check_env_file()
    results["yolo"] = check_yolo_model()
    results["instructions"] = check_instructions()

    # 输出总结
    exit_code = print_summary(results)

    print("\n" + "=" * 60)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
