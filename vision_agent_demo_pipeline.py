"""
Vision Agent 实时交互感知演示
基于 GetStream Vision-Agents 官方框架
"""
import logging
import asyncio
import os
import ssl
import sys
import certifi
from dotenv import load_dotenv

# Python.org builds on macOS may not include a usable system CA bundle. The
# Stream SDK opens WebSockets with Python's default SSL context, so point it at
# certifi's maintained CA bundle before the SDK creates any connections.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

# ``vision-agents agent`` imports aiohttp before this module, so aiohttp may
# already have cached an empty default context. Refresh only that broken cache;
# keep verification enabled and leave a valid/custom context untouched.
try:
    import aiohttp.connector

    cached_context = aiohttp.connector._SSL_CONTEXT_VERIFIED
    if not cached_context.get_ca_certs():
        aiohttp.connector._SSL_CONTEXT_VERIFIED = ssl.create_default_context(
            cafile=os.environ["SSL_CERT_FILE"]
        )
except (ImportError, AttributeError, OSError):
    # aiohttp is an indirect SDK dependency; its absence is handled by the SDK.
    pass

from vision_agents.core import User, Agent, Runner
from vision_agents.core.agents import AgentLauncher
from vision_agents.plugins import getstream, ultralytics, gemini, qwen

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()


async def create_agent(**kwargs) -> Agent:
    """
    创建 Vision Agent 实例
    - 使用 Stream Edge 进行视频传输
    - 集成 Qwen 实时 AI 视觉模型
    - YOLO 姿态检测处理器
    """
    logger.info("正在初始化 Vision Agent...")

    try:
        agent = Agent(
            edge=getstream.Edge(),  # Stream 的超低延迟视频基础设施
            agent_user=User(name="AI 健身教练"),
            instructions="Read @docs/COACHING_INSTRUCTIONS.md",  # 读取指令文件
            # llm=gemini.Realtime(fps=3),  # 降低到 3 fps 减少负载
            llm=qwen.Realtime(
                fps=1,
                # DashScope keys are region-scoped; this is the China endpoint
                # used by the configured key. Set DASHSCOPE_BASE_URL for intl.
                base_url=os.getenv(
                    "DASHSCOPE_BASE_URL",
                    "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                ),
            ),
            processors=[
                # YOLO 姿态检测 - 实时追踪人体关键点
                ultralytics.YOLOPoseProcessor(
                    model_path="yolo11n-pose.pt",
                    device="mps"  # 使用 GPU 请改为 "cuda"
                )
            ],
        )
        logger.info("✓ Vision Agent 初始化成功")
        return agent
    except Exception as e:
        logger.error(f"✗ Agent 初始化失败: {e}")
        raise


async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
    """
    加入视频通话并开始交互
    """
    try:
        logger.info(f"正在创建通话: {call_type}/{call_id}")
        call = await agent.create_call(call_type, call_id)
        logger.info(f"✓ 通话创建成功")

        # 加入通话并启动演示环境
        logger.info("Agent 正在加入通话...")
        async with agent.join(call):
            logger.info(f"✓ Agent 已成功加入通话: {call_id}")
            logger.info("等待 3 秒确保连接稳定...")
            await asyncio.sleep(3)

            # Qwen Realtime accepts audio input only; Gemini also supports a
            # text-triggered greeting when that backend is selected.
            if getattr(agent.llm, "provider_name", "") == "qwen_realtime":
                logger.info("Qwen 实时模型等待用户语音输入，不发送文本问候")
            else:
                logger.info("发送初始问候...")
                try:
                    async for _ in agent.llm.simple_response(
                        text="你好！我是你的专业 AI 健身教练。今天想练什么动作？我可以指导深蹲、俯卧撑、平板支撑等训练！准备好了就开始吧！"
                    ):
                        pass
                    logger.info("✓ 初始问候已发送")
                except Exception as e:
                    logger.warning(f"发送问候时出错（可忽略）: {e}")

            # 保持运行直到通话结束
            logger.info("Agent 运行中，等待用户交互...")
            logger.info("提示：在浏览器中对着摄像头说话或做动作")
            await agent.finish()

    except Exception as e:
        logger.error(f"✗ 通话过程出错: {e}")
        logger.error("请检查：")
        logger.error("1. Stream API 密钥是否正确")
        logger.error("2. 网络连接是否正常")
        logger.error("3. AI API（Gemini 或 Qwen）是否可用")
        raise


# Runner is the public lifecycle/CLI entry point in vision-agents >= 0.6.
runner = Runner(
    launcher=AgentLauncher(create_agent=create_agent, join_call=join_call),
)


if __name__ == "__main__":
    # Keep the existing ``python vision_agent_demo.py`` workflow while also
    # allowing ``run``/``serve`` subcommands when passed explicitly.
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command in {"run", "serve"}:
        runner.cli()
    else:
        runner.cli(args=["run", *sys.argv[1:]])
