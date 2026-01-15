"""
Vision Agent 实时交互感知演示
基于 GetStream Vision-Agents 官方框架
"""
import logging
import asyncio
from dotenv import load_dotenv

from vision_agents.core import User, Agent, cli
from vision_agents.core.agents import AgentLauncher
from vision_agents.plugins import getstream, ultralytics, gemini

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
    - 集成 Gemini 实时 AI 视觉模型
    - YOLO 姿态检测处理器
    """
    logger.info("正在初始化 Vision Agent...")

    try:
        agent = Agent(
            edge=getstream.Edge(),  # Stream 的超低延迟视频基础设施
            agent_user=User(name="AI 健身教练"),
            instructions="Read @docs/COACHING_INSTRUCTIONS.md",  # 读取指令文件
            llm=gemini.Realtime(fps=3),  # 降低到 3 fps 减少负载
            # 可选：切换到 OpenAI
            # llm=openai.Realtime(fps=3),
            processors=[
                # YOLO 姿态检测 - 实时追踪人体关键点
                ultralytics.YOLOPoseProcessor(
                    model_path="yolo11n-pose.pt",
                    device="cpu"  # 使用 GPU 请改为 "cuda"
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

            # 发送初始问候和指令
            logger.info("发送初始问候...")
            try:
                await agent.llm.simple_response(
                    text="你好！我是你的专业 AI 健身教练。今天想练什么动作？我可以指导深蹲、俯卧撑、平板支撑等训练！准备好了就开始吧！"
                )
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
        logger.error("3. Gemini API 是否可用")
        raise


if __name__ == "__main__":
    # 使用 CLI 启动 agent
    cli(AgentLauncher(create_agent=create_agent, join_call=join_call))
