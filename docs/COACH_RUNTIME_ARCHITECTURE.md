# Vision Coach Runtime Architecture

## 1. 目标

本项目的实时健身教练建议采用：

**单 Agent 的双环混合范式：事件驱动 Reactive Loop + 分层状态机 HFSM + 受约束多模态 LLM。**

核心原则：

> **视觉与规则负责“判断”，LLM 负责“表达”。**

整体数据流：

```text
视频 → Pose/关键点 → 平滑与几何计算 → 动作 FSM → CoachEvent
                                              ↓
用户语音 → VAD / User Events ─────────────→ FeedbackArbiter
                                              ↓
                                      FeedbackDecision
                                              ↓
                                     Memory / RAG（慢环）
                                              ↓
                                           Qwen
                                              ↓
                                        简短语音反馈
```

---

## 2. 为什么采用双环架构

### 快环 Fast Loop

负责低延迟、可验证、确定性的判断：

- YOLO Pose
- 关键点提取
- 角度计算
- 时序平滑
- 动作阶段识别
- Rep 计数
- 动作质量规则
- Tracking confidence
- 安全/停止事件
- Feedback 仲裁

建议频率：

```text
Camera: ~30 FPS
YOLO Pose: ~10 FPS
```

### 慢环 Slow Loop

负责语义理解和个性化：

- 用户语言理解
- 自然语言反馈
- 个性化 cue
- 长期记忆
- 训练总结
- RAG
- 恢复与训练计划

Qwen Realtime 可以维持较低视频采样频率，例如约 1 FPS，用于辅助语义理解，而不是承担精确计数。

---

## 3. 目标架构

```text
agent_local.py
      │
      ↓
agent_local_agent.py
      │
      ↓
┌────────────────────────────────┐
│          CoachRuntime          │
│                                │
│ Pose → FSM → CoachEvent        │
│                ↓               │
│         FeedbackArbiter        │
│                ↓               │
│       FeedbackDecision         │
│                ↓               │
│       Memory / Knowledge       │
└───────────────┬────────────────┘
                ↓
              Qwen
                ↓
              Voice
```

职责划分：

- `agent_local.py`：UI、设备选择、开始/停止训练、画面显示。
- `agent_local_agent.py`：Vision Agents 生命周期、Qwen、Edge、Processor 接线。
- `coach/`：真正的健身教练业务逻辑。

---

## 4. 推荐目录结构

第一阶段不要拆得太细，先建立：

```text
coach/
├── __init__.py
├── models.py
├── geometry.py
├── smoothing.py
├── squat_fsm.py
├── arbiter.py
└── runtime.py
```

后续再扩展：

```text
coach/
├── exercises/
│   ├── base.py
│   ├── squat.py
│   ├── pushup.py
│   └── plank.py
├── memory/
│   ├── service.py
│   ├── episodic.py
│   └── semantic.py
└── rag/
    └── recovery.py
```

---

## 5. 核心内部 API

### 5.1 CoachRuntime

整个教练系统统一入口：

```python
class CoachRuntime:
    async def start_session(self, settings):
        ...

    def ingest_pose(self, observation):
        ...

    async def ingest_user_text(self, text):
        ...

    def next_feedback(self):
        ...

    async def end_session(self):
        ...
```

调用逻辑：

```text
开始训练
↓
start_session()

每次姿态结果
↓
ingest_pose()

用户讲话
↓
ingest_user_text()

检查是否需要反馈
↓
next_feedback()

结束训练
↓
end_session()
```

---

## 6. PoseObservation

YOLO 原始结果不应该直接进入 LLM。

统一转换为结构化对象：

```python
@dataclass
class PoseObservation:
    timestamp: float

    keypoints: list
    confidence: float

    knee_angle_left: float | None = None
    knee_angle_right: float | None = None

    hip_angle_left: float | None = None
    hip_angle_right: float | None = None

    torso_angle: float | None = None

    visible: bool = True
```

数据流：

```text
YOLO Result
    ↓
Keypoints
    ↓
Geometry
    ↓
Smoothing
    ↓
PoseObservation
```

### Confidence Gate

必须区分：

```text
看不清 ≠ 动作错误
```

例如：

```python
if observation.confidence < 0.6:
    emit(TRACKING_LOST)
```

不要在低置信度情况下给用户动作错误结论。

---

## 7. 自定义 CoachPoseProcessor

如果现有 `YOLOPoseProcessor` 不方便暴露结构化关键点，建议新增：

```python
CoachPoseProcessor
```

职责：

```text
Video Frame
      ↓
CoachPoseProcessor
      │
      ├──→ annotated frame → UI / Qwen
      │
      └──→ PoseObservation → CoachRuntime
```

这样一次 YOLO 推理同时用于：

1. 骨架可视化
2. FSM 和动作规则

避免重复执行模型。

---

## 8. ExerciseFSM

每个动作实现统一接口：

```python
class ExerciseFSM:
    def update(
        self,
        observation: PoseObservation,
    ) -> list["CoachEvent"]:
        ...

    def reset(self):
        ...
```

后续：

```text
ExerciseFSM
├── SquatFSM
├── PushUpFSM
├── PlankFSM
└── ...
```

---

## 9. 第一阶段只实现 SquatFSM

先把一个动作做可靠，再扩展其它动作。

深蹲状态：

```python
class SquatPhase(Enum):
    STANDING = "standing"
    DESCENDING = "descending"
    BOTTOM = "bottom"
    ASCENDING = "ascending"
```

状态转移：

```text
STANDING
   ↓
DESCENDING
   ↓
BOTTOM
   ↓
ASCENDING
   ↓
STANDING
   ↓
REP_COMPLETED
```

核心原则：

> Rep 计数由 FSM 决定，不由 LLM 猜测。

---

## 10. Smoothing

YOLO 关键点会存在帧间抖动。

例如：

```text
102°
96°
105°
91°
```

在进入 FSM 前应进行：

- EMA
- Median Filter
- 简单窗口平均

处理顺序：

```text
YOLO
 ↓
Raw Keypoints
 ↓
Smoothing
 ↓
Geometry
 ↓
FSM
```

避免状态反复跳变。

---

## 11. CoachEvent

FSM 不直接说话，只产生结构化事件。

```python
@dataclass
class CoachEvent:
    type: str
    priority: int

    timestamp: float

    exercise: str | None = None
    rep_index: int | None = None

    message_key: str | None = None

    severity: float = 0.0
    confidence: float = 1.0

    data: dict = field(default_factory=dict)
```

示例：

```python
CoachEvent(
    type="rep_completed",
    priority=50,
    exercise="squat",
    rep_index=5,
)
```

动作纠正：

```python
CoachEvent(
    type="form_warning",
    priority=70,
    exercise="squat",
    message_key="knee_valgus",
    severity=0.62,
    confidence=0.91,
)
```

---

## 12. EventType

建议统一事件类型：

```python
class EventType(Enum):
    SESSION_STARTED = "session_started"
    SESSION_COMPLETED = "session_completed"

    REP_STARTED = "rep_started"
    REP_COMPLETED = "rep_completed"
    SET_COMPLETED = "set_completed"

    FORM_WARNING = "form_warning"
    FORM_IMPROVED = "form_improved"

    TRACKING_LOST = "tracking_lost"

    USER_INTERRUPT = "user_interrupt"

    SAFETY_STOP = "safety_stop"
```

---

## 13. FeedbackArbiter

多个事件同时出现时，由仲裁器决定“现在最值得说什么”。

优先级：

```text
紧急/停止
>
用户打断
>
安全或重要纠正
>
Rep 计数
>
鼓励
>
静默
```

可以实现：

```python
class Priority(IntEnum):
    EMERGENCY = 100
    USER_INTERRUPT = 90
    SAFETY = 80
    FORM_CORRECTION = 70
    REP_COUNT = 50
    ENCOURAGEMENT = 30
```

接口：

```python
class FeedbackArbiter:
    def submit(self, event: CoachEvent):
        ...

    def next(self) -> CoachEvent | None:
        ...
```

---

## 14. Cooldown / 去重

不能每帧重复同一个提示。

例如 YOLO 10 FPS，某动作问题持续 2 秒可能产生约 20 次同类判断。

因此为事件配置：

```python
FeedbackPolicy(
    event_type="knee_valgus",
    cooldown=5.0,
)
```

规则：

```text
同一种非紧急提示
在 cooldown 时间内
默认只反馈一次
```

除非：

- severity 明显增加
- 用户主动询问
- 状态发生重要变化

---

## 15. FeedbackDecision

Arbiter 输出的不是自然语言，而是结构化决策：

```python
@dataclass
class FeedbackDecision:
    kind: str
    priority: int
    event: CoachEvent

    should_speak: bool = True
    template: str | None = None
    llm_needed: bool = True
```

然后才进入 Qwen。

---

## 16. LLM 的职责

### 当前不推荐

```text
视频
 ↓
LLM
 ↓
理解动作
 ↓
判断次数
 ↓
判断错误
 ↓
决定是否反馈
 ↓
生成文本
```

### 推荐

```text
YOLO
 ↓
Geometry
 ↓
FSM
 ↓
Rules
 ↓
Arbiter
 ↓
FeedbackDecision
 ↓
Qwen
 ↓
自然、简短的措辞
```

例如 Qwen 输入：

```json
{
  "event": "form_warning",
  "exercise": "squat",
  "rep": 7,
  "issue": "knee_valgus",
  "severity": 0.61,
  "preferred_cue": "膝盖向外",
  "max_sentences": 1
}
```

Qwen 只需要将其转成自然反馈。

---

## 17. 顶层 HFSM

Session 建议使用分层状态机：

```text
PRECHECK
   ↓
CALIBRATION
   ↓
TRAINING
   ↓
REST
   ↓
SUMMARY
```

### Calibration

用于：

- 判断全身是否进入画面
- 关键点置信度检查
- 建立初始站立姿态
- 人体尺度校准
- 左右侧确认

这样可以减少不同用户身体比例、距离和摄像头位置造成的误判。

---

## 18. 用户打断

用户语音优先级高于普通教练反馈。

推荐：

```text
UserTurnStarted
      ↓
USER_INTERRUPT
      ↓
FeedbackArbiter
      ↓
暂停/取消低优先级反馈
```

不要单独再实现一套和 Qwen/Vision Agents 冲突的 VAD 管线。

---

## 19. Memory 架构

Memory 应属于慢环。

建议分层：

```text
Working Memory
当前 Session

Episodic Memory
一次具体训练事件

Semantic Memory
长期动作模式与偏好

Training State
数值与趋势

Knowledge RAG
训练与恢复知识
```

推荐：

| 类型 | 内容 | 技术 |
|---|---|---|
| Working Memory | 当前 set/rep/最近错误/最近 cue | Python RAM |
| Episodic | 某次动作问题或改善 | Zep Episode |
| Semantic | 长期动作模式、偏好 | Zep / Graphiti |
| Training State | rep、质量分、训练趋势 | SQLite/PostgreSQL |
| Knowledge RAG | 动作、训练、恢复资料 | Vector Retrieval |

---

## 20. Memory 与 CoachEvent

Memory 不逐帧工作。

推荐粒度：

```text
Frame
 ↓ 不进入长期记忆
Rep
 ↓ 有意义事件才保存
Set
 ↓ 保存摘要
Session
 ↓ 保存总结
Pattern
 ↓ 转为长期语义记忆
```

最终：

```text
CoachEvent
    +
Relevant Memory
    ↓
FeedbackDecision
    ↓
Qwen
```

例如：

```text
当前事件：
late-set knee valgus

历史：
过去 3 次训练后半组曾出现相同问题

过去最有效 cue：
“膝盖向外”
```

这样可以实现真正的个性化教练。

---

## 21. RAG 与恢复模块

恢复 RAG 不应该进入逐帧快环。

推荐：

```text
训练历史
+
Training State
+
专业知识 RAG
↓
训练前建议
训练后总结
计划调整
```

用户自身状态与知识库必须分开：

```text
Personal Memory ≠ Expert Knowledge
```

---

## 22. 分阶段修改路线

### V2.1 — 提取 Pose 数据

目标：

```text
Camera
↓
YOLO
↓
Keypoints
↓
角度打印
```

成功标准：

- 能稳定获得关键点
- 能计算膝、髋、躯干等角度
- 暂时不修改 LLM

---

### V2.2 — Smoothing

加入：

- EMA / Median
- Confidence Gate

成功标准：

- 静止时关键点与角度不剧烈抖动
- 低置信度不会被误判为动作问题

---

### V2.3 — SquatFSM

输出：

```text
STANDING
DESCENDING
BOTTOM
ASCENDING
REP COMPLETED: 1
```

成功标准：

- 真实完成 10 个深蹲时计数稳定接近 10
- Rep 不依赖 LLM

---

### V2.4 — CoachEvent

将：

```python
print("REP COMPLETED")
```

替换为：

```python
CoachEvent(...)
```

建立统一事件协议。

---

### V2.5 — FeedbackArbiter

实现：

- priority
- cooldown
- deduplication
- silent policy

成功标准：

> 有事件不等于一定说话。

---

### V2.6 — 接回 Qwen

Qwen 不再负责动作计数。

输入：

```text
REP_COMPLETED
FORM_WARNING
FORM_IMPROVED
```

输出简短自然反馈。

---

### V2.7 — User Interrupt

接 Agent/Qwen 的用户语音事件。

做到：

```text
用户开始说话
↓
暂停低优先级反馈
↓
优先响应用户
```

---

### V2.8 — Memory

再加入：

- Working Memory
- Episodic Memory
- Semantic Memory
- Cue Effectiveness

不要提前将 Memory 放进快环。

---

### V2.9 — Recovery RAG

最后添加：

- 训练历史趋势
- Session Summary
- 恢复知识
- 训练前/训练后慢环建议

---

## 23. 第一阶段最值得实现的 5 个文件

建议先建立：

```text
coach/
├── models.py
├── geometry.py
├── squat_fsm.py
├── arbiter.py
└── runtime.py
```

先完成：

```text
YOLO
 ↓
PoseObservation
 ↓
SquatFSM
 ↓
CoachEvent
 ↓
Arbiter
 ↓
Qwen
```

Memory、RAG、复杂规划全部后置。

---

## 24. 最终双环

```text
                    FAST LOOP
                      ~10 Hz

Camera
   ↓
YOLO Pose
   ↓
Keypoints
   ↓
Smoothing
   ↓
Geometry
   ↓
Exercise FSM
   ↓
Rules
   ↓
CoachEvent
   ↓
FeedbackArbiter
   │
   ├────────── no useful event ───────→ Silent
   │
   ↓
FeedbackDecision
   │
   │
   └──────────────────────────────┐
                                  │
                            SLOW LOOP
                                  │
                     ┌────────────┴───────────┐
                     ↓                        ↓
                   Memory                    RAG
                     ↓                        ↓
                     └────────────┬───────────┘
                                  ↓
                                Qwen
                                  ↓
                           Short Coaching Cue
                                  ↓
                                Voice
```

---

## 25. 核心原则总结

整个系统可以用下面七句话概括：

```text
YOLO       负责“看见”
Geometry   负责“计算”
Smoothing  负责“稳定”
FSM        负责“理解动作过程”
Rules      负责“判断”
Arbiter    负责“决定什么时候说”
Qwen       负责“把正确的信息说得像一个教练”
```

加入长期能力后：

```text
Memory     负责“认识这个人”
RAG        负责“补充专业知识”
```

最终目标不是：

```text
摄像头 → LLM → 说一句话
```

而是：

```text
Observe
  ↓
Structure
  ↓
Reason deterministically
  ↓
Generate CoachEvent
  ↓
Arbitrate
  ↓
Retrieve Memory
  ↓
LLM verbalization
  ↓
Observe response
  ↓
Update state/memory
```

---

## 26. 相关 API / 文档

### Vision Agents

- GitHub: https://github.com/GetStream/Vision-Agents
- Docs: https://visionagents.ai/
- Agent Core: https://visionagents.ai/core/agent-core
- Turn Detection: https://visionagents.ai/ai-technologies/turn-detection
- Custom Integration / Processor: https://visionagents.ai/integrations/create-your-own-plugin

> 注意：Vision Agents 仍在快速迭代。实现时应以项目 `pyproject.toml` 锁定版本对应的源码和文档为准，避免复制不同版本的 API 示例。

### Ultralytics Pose

- Pose Task: https://docs.ultralytics.com/tasks/pose/

重点关注：

```python
result.keypoints
result.keypoints.xy
result.keypoints.xyn
result.keypoints.data
```

### Qwen Realtime

- Qwen Realtime / Omni Realtime: https://help.aliyun.com/en/model-studio/realtime
- Realtime Client Events: https://help.aliyun.com/en/model-studio/client-events

重点：

- realtime audio
- video input
- server VAD
- user interruption / turn detection

---

## 27. 下一步

建议下一次代码修改只做 **V2.1**：

1. 创建 `coach/models.py`
2. 创建 `coach/geometry.py`
3. 新增 `PoseObservation`
4. 从 YOLO 输出拿到结构化关键点
5. 实时打印稳定的膝角/髋角
6. 不修改现有 Qwen 对话逻辑

当 PoseObservation 稳定后，再进入 SquatFSM。
