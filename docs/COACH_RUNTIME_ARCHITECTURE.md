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


---

## 28. 论文核验（截至 2026-09-06）

本节只保留已经核实到公开论文页面、正式会议页面或 arXiv 页面的方法，并区分“正式发表”和“预印本”。

### 28.1 BioCoach — 正式发表，CVPR 2026

**论文：** From 3D Pose to Prose: Biomechanics-Grounded Vision-Language Coaching

**状态：** CVPR 2026 正式论文。

BioCoach 面向 streaming fitness coaching，融合 visual appearance 与 3D skeletal kinematics。论文的三阶段核心包括：

- exercise-specific degree-of-freedom selection
- individualized morphometrics
- motion cycle / biomechanical constraints
- structured biomechanical context
- vision-biomechanics conditioned feedback

其核心思想是：将可解释的运动学证据显式提供给语言模型，而不是要求语言模型自己从像素中推断所有细粒度运动学信息。

BioCoach 官方结果中，在 QEVD-bio-fit-coach 设置上，LLM-Bio-Acc. 从 Stream-VLM 的 1.72 提升到 3.26，论文报告相对提升 89.5%。论文消融还显示 motion-quality context 是关键组件，morphometric context 也带来进一步提升。

对本项目的启示：

~~~text
RGB
+
Pose / Kinematics
+
Personal Calibration
+
Motion Phase
+
Constraints
↓
Structured Biomechanical Context
↓
MLLM
~~~

而不是：

~~~text
RGB Video
↓
MLLM
↓
直接裁判
~~~

链接：

- https://openaccess.thecvf.com/content/CVPR2026/html/Ji_From_3D_Pose_to_Prose_Biomechanics-Grounded_Vision-Language_Coaching_CVPR_2026_paper.html
- https://vilab-group.com/project/biocoach/
- https://github.com/VILab-Drexel/Biocoach

### 28.2 Can Vision Language Models Judge Action Quality? — 正式发表，CVPR Workshops 2026

**论文：** Can Vision Language Models Judge Action Quality? An Empirical Evaluation

**状态：** CVPR Workshops 2026 正式论文。

论文测试 Gemini 3.1 Pro、Qwen3-VL、InternVL3.5 等 VLM 在 fitness、figure skating、diving 等 Action Quality Assessment 任务上的能力。

主要结论：

- baseline 只略高于随机水平；
- skeleton information、grounding instructions、reasoning structures、in-context learning 能带来局部改善；
- 没有一种策略在不同任务中稳定解决细粒度动作质量判断；
- 模型存在倾向预测“动作正确”的系统性偏差；
- 纯 VLM 对细粒度 movement quality assessment 仍不可靠。

对本项目的启示：

> Realtime MLLM 可以参与解释、对话和高层语义判断，但不应成为 rep 计数、动作阶段和关键安全门控的唯一依据。

链接：

- https://openaccess.thecvf.com/content/CVPR2026W/SAUAFG/html/Monte_e_Freitas_Can_Vision_Language_Models_Judge_Action_Quality_An_Empirical_Evaluation_CVPRW_2026_paper.html
- https://arxiv.org/abs/2604.08294

### 28.3 FitAQA — 2026 arXiv 预印本

**论文：** FitAQA: A Benchmark of Fitness Action Quality Assessment for Multimodal Large Language Models

**状态：** 截至本次核验，确认到 arXiv 预印本，不按已发表会议论文处理。

数据规模：

- 2,219 个视频
- 5,512 个 QA
- 30 个徒手训练动作
- 38 类 recurring form errors
- 6 个质量维度：alignment、symmetry、stability、coordination、tempo、completeness

论文把能力拆成：

~~~text
Perception
↓
Judgement
↓
Temporal Grounding
~~~

一个重要结论是：当提供 ground-truth perceptual evidence 时，judgement 会明显改善，说明视觉感知本身是当前 MLLM 的关键瓶颈。

对本项目的启示：

> YOLO / Pose / Geometry / FSM 的价值不是和 MLLM 竞争，而是向它提供更可靠的 perceptual evidence。

链接：

- https://arxiv.org/abs/2608.08736

### 28.4 CoachMe — 正式发表，ACL 2025

**论文：** CoachMe: Decoding Sport Elements with a Reference-Based Coaching Instruction Generation Model

**状态：** ACL 2025 Long Paper。

核心思路：

~~~text
Learner Motion
+
Reference Motion
↓
Temporal + Physical Difference
↓
Instruction Generation
~~~

CoachMe 显式比较 learner 与 reference 的运动差异；其架构包含 Concept Difference、Human Pose Perception 和 Instruct Motion。

论文在 G-Eval 上报告：相对 GPT-4o，在 figure skating 上提升 31.6%，boxing 上提升 58.3%。

对本项目的启示：

> 对深蹲、俯卧撑等具有标准运动周期的动作，可以保存高质量 reference motion，将用户的角度/骨架轨迹与 reference 做时间对齐，而不是把所有标准写成单一绝对角度阈值。

链接：

- https://aclanthology.org/2025.acl-long.1413/
- https://motionxperts.github.io/

### 28.5 ExpertAF — 正式发表，CVPR 2025

**论文：** ExpertAF: Expert Actionable Feedback from Video

**状态：** CVPR 2025 正式论文。

输入包括 video demonstration 和 accompanying 3D body pose。输出不仅有动作分析，还包括：

1. free-form expert commentary
2. visual expert demonstration / correction

对本项目的启示：

后期可以将 CoachEvent 从简单错误标签升级为：

~~~text
Detected issue
+
Why it matters
+
Actionable correction
+
Optional reference/demo
~~~

链接：

- https://openaccess.thecvf.com/content/CVPR2025/html/Ashutosh_ExpertAF_Expert_Actionable_Feedback_from_Video_CVPR_2025_paper.html
- https://vision.cs.utexas.edu/projects/ExpertAF/

### 28.6 LLaMo — 正式发表，CVPR 2025

**论文：** Human Motion Instruction Tuning

**状态：** CVPR 2025 正式论文。

论文提出 LLaMo（Large Language and Human Motion Assistant）。关键点是保留 motion-native representation，并联合 video、motion、text 做 instruction tuning，而不是只把 motion 压缩成普通语言描述。

对本项目的启示：

如果以后进入自训练模型阶段，可以考虑：

~~~text
Video Features
+
Pose / Motion Features
+
Text
↓
Motion-aware Multimodal Model
~~~

链接：

- https://openaccess.thecvf.com/content/CVPR2025/html/Li_Human_Motion_Instruction_Tuning_CVPR_2025_paper.html

### 28.7 TAGS — 正式发表，ICCV Workshops 2025

**论文：** Generating Tennis Action Instruction Based on a Large Language Model

**状态：** ICCV Workshops 2025 正式论文。

TAGS 的流程为：

~~~text
Video
↓
3D Skeleton
↓
Structured Pose-Language Representation
↓
Prompt-based LLM
↓
Action Assessment + Guidance
~~~

对本项目的启示：

> 在不训练自定义 MLLM 的情况下，可以先把 Pose 转成结构化 motion context，再交给 Qwen。

链接：

- https://openaccess.thecvf.com/content/ICCV2025W/AMFG/html/Wang_Generating_Tennis_Action_Instruction_Based_on_a_Large_Language_Model_ICCVW_2025_paper.html

### 28.8 FormCoach — 2025 arXiv 预印本

**论文：** FormCoach: Lift Smarter, Not Harder

**状态：** 截至本次核验，确认到 arXiv 预印本。

公开摘要描述：

- always-on interactive fitness coaching
- VLM-based form correction
- 1,700 个 expert-annotated user-reference video pairs
- 22 个 strength / mobility exercises
- 当前 VLM 与 human-level coaching 之间仍有明显差距

对本项目的启示：

> user-reference pair 是值得保留的设计方向，但不能把 VLM benchmark 理解成“纯 VLM 已经足够可靠”。

链接：

- https://arxiv.org/abs/2508.07501

### 28.9 Domain Adaptation of VLM for Soccer Video Understanding — 正式发表，CVPR Workshops 2025

这篇不是 fitness coaching 论文，但对“用大模型做动作分类”有参考价值。

论文使用领域数据和 curriculum-style instruction tuning 将通用 VLM 适配到 soccer，报告 downstream action classification accuracy 从 11.8% 提升到 63.5%。

重要限制：

> 这说明领域微调可以显著提高 VLM 动作分类能力，但不代表 zero-shot 通用 VLM 能可靠完成实时健身动作分类。

链接：

- https://openaccess.thecvf.com/content/CVPR2025W/CVSPORTS/html/Jiang_Domain_Adaptation_of_VLM_for_Soccer_Video_Understanding_CVPRW_2025_paper.html

---

## 29. 经过论文核验后的核心判断

目前最有证据支持的技术趋势不是：

~~~text
Camera
↓
Realtime MLLM
↓
让大模型负责所有判断
~~~

而是：

~~~text
Camera
├── RGB semantic stream
│
└── Pose / Motion stream
        ↓
   Kinematics / Temporal Structure
        ↓
   Structured Evidence
        ↓
       MLLM
        ↓
Actionable Feedback
~~~

对于本项目，应继续保留：

- deterministic rep FSM
- confidence gate
- calibration
- event arbitration

同时逐步增加：

- individualized motion baseline
- reference motion comparison
- structured biomechanics context
- MLLM semantic reasoning

目前没有上述核验论文给出证据说明“让 realtime LLM 在线直接重写 FSM transition graph”会更可靠。因此，LLM 修改 FSM 应保持为受约束参数建议，而不是直接控制状态机。

推荐：

~~~text
LLM Adjustment Proposal
↓
Range Check
↓
Historical Replay / Validation
↓
FSMConfig
~~~

不推荐：

~~~text
LLM
↓
直接修改 FSM state / transition
~~~

---

## 30. 多种可行修改方案

### 方案 A：2D Pose + 个体校准 + FSM + Realtime MLLM

**定位：当前最推荐，最适合先做可靠产品闭环。**

~~~text
Camera
↓
YOLO 2D Pose
↓
Smoothing
↓
Personal Calibration
↓
Geometry
↓
Exercise FSM
↓
CoachEvent
↓
FeedbackArbiter
↓
Qwen Realtime
~~~

LLM 负责：

- 用户对话
- 将 CoachEvent 转成自然语言
- 根据历史选择 cue
- 训练总结

LLM 不负责：

- rep count
- FSM state
- 低层关键点判断

优点：

- 延迟低
- 最容易解释和调试
- 直接兼容现有项目
- 不需要额外训练模型

缺点：

- 2D 视角敏感
- 复杂三维错误检测能力有限
- 规则需要逐动作设计

**建议用于 V2.1–V2.6。**

### 方案 B：BioCoach-inspired 个体化生物力学 Hybrid

**定位：最值得作为中期研究方向。**

~~~text
2D / 3D Pose
↓
Exercise-specific Joint Selection
↓
Individual Morphometrics
↓
Motion Cycle
↓
Biomechanical Constraints
↓
Structured Biomechanical Context
↓
MLLM
~~~

建议新增：

~~~python
@dataclass
class BiomechanicalContext:
    exercise: str
    phase: str
    selected_joints: list[str]
    joint_angles: dict[str, float]
    angular_velocities: dict[str, float]
    body_ratios: dict[str, float]
    constraints: list[str]
    violations: list[str]
    confidence: float
~~~

优点：

- 与 BioCoach 最新正式论文方向一致
- 个体差异处理更合理
- 可解释性很强
- 给 MLLM 的 evidence 更可靠

缺点：

- 3D pose / body reconstruction 复杂
- constraints 需要专业设计与验证
- 实时算力要求更高

**建议先做 B-lite：2D + calibration + structured biomechanics，不要一开始完整复刻 BioCoach。**

### 方案 C：Reference-based Motion Coaching

**定位：非常适合深蹲、俯卧撑等周期动作，工程性价比高。**

借鉴 CoachMe / FormCoach：

~~~text
User Motion
+
Reference Motion
↓
Temporal Alignment
↓
Pose / Angle Difference
↓
CoachEvent
↓
MLLM
~~~

第一版无需训练新模型：

1. 收集高质量 reference squat；
2. 提取 reference joint-angle trajectory；
3. 用户完成一 rep 后得到 user trajectory；
4. 用 phase normalization 或 DTW 对齐；
5. 计算差异；
6. 找最大偏差 joint / phase；
7. 生成 CoachEvent；
8. Qwen 生成一句纠正。

建议数据结构：

~~~python
@dataclass
class MotionDifference:
    joint: str
    phase: str
    user_value: float
    reference_value: float
    delta: float
    confidence: float
~~~

优点：

- 不需要把所有标准写成绝对阈值
- 能处理动作速度不同
- 反馈证据容易解释
- 比完整 3D biomechanics 更容易落地

缺点：

- reference 必须可靠
- 身体比例差异需要归一化
- reference 不应被当作所有人的唯一正确姿势

### 方案 D：Pose Temporal Classifier + FSM + MLLM

**定位：解决“自由训练模式自动判断动作”。**

~~~text
YOLO Pose Sequence
↓
Temporal Feature Buffer
↓
Action Classifier
↓
exercise = squat / pushup / plank
↓
FSM Router
~~~

Classifier 可以逐级升级：

~~~text
规则特征
↓
Random Forest / XGBoost
↓
Temporal CNN / Transformer
↓
ST-GCN / Skeleton Model
~~~

当前阶段不建议把通用 MLLM 作为第一动作分类器。

低 confidence 时必须允许：

~~~text
UNKNOWN
~~~

而不是强行分类。

### 方案 E：领域微调 Motion-aware MLLM

**定位：研究版 / 后期版本。**

借鉴 LLaMo、TAGS、VLM domain adaptation：

~~~text
RGB Video
+
Pose Sequence
+
Structured Motion Features
+
Exercise / Coaching Instructions
↓
Domain Fine-tuned MLLM
↓
Action Understanding + Coaching
~~~

训练数据建议包含：

- Video / Pose
- Exercise label
- Phase
- Form error
- Temporal location
- Evidence
- Correction
- Coach wording

还可以采用 FitAQA 的六维 taxonomy：

- alignment
- symmetry
- stability
- coordination
- tempo
- completeness

优点：

- 研究价值高
- 有机会学习复杂 motion-language mapping
- 可以降低不同动作大量手写 prompt 的需求

缺点：

- 数据成本最高
- 训练与评测复杂
- realtime 部署成本高
- 不应完全取消 deterministic safety / FSM fallback

### 方案 F：Pure Realtime MLLM Baseline

~~~text
Camera
↓
Qwen / VLM
↓
exercise + rep + form + feedback
~~~

**不推荐作为主系统。**

但非常适合作为实验 baseline。

未来可以比较：

~~~text
Baseline 1: MLLM only
Baseline 2: YOLO + FSM
Baseline 3: YOLO + FSM + MLLM
Baseline 4: Pose + Reference + MLLM
Baseline 5: Biomechanics Hybrid
~~~

---

## 31. 各方案比较

| 方案 | 实时性 | 工程难度 | 个体化 | 可解释性 | 数据需求 | 研究新颖度 |
|---|---:|---:|---:|---:|---:|---:|
| A. 2D Pose + FSM + MLLM | 高 | 低-中 | 中 | 高 | 低 | 中 |
| B. Biomechanics Hybrid | 中-高 | 高 | 高 | 很高 | 中 | 很高 |
| C. Reference-based | 高 | 中 | 中-高 | 高 | 低-中 | 高 |
| D. Pose Action Classifier | 高 | 中 | 中 | 高 | 中 | 中 |
| E. Fine-tuned Motion MLLM | 中 | 很高 | 高 | 中 | 很高 | 很高 |
| F. Pure MLLM | 中 | 低 | 中 | 低 | 低 | 适合作为 baseline |

---

## 32. 对当前仓库最推荐的实际路线

不建议现在直接跳到方案 E。

推荐顺序：

~~~text
Phase 1
方案 A
↓
把 SquatFSM + CoachEvent 跑稳定

Phase 2
方案 C
↓
加入 reference trajectory comparison

Phase 3
方案 B-lite
↓
Personal Calibration + Structured Biomechanical Context

Phase 4
Memory
↓
用户历史 + cue effectiveness + personalized range

Phase 5
根据研究目标选择：
B 完整 3D biomechanics
或
E motion-aware MLLM fine-tuning
~~~

对应代码演进：

~~~text
V2.1 PoseObservation
V2.2 Smoothing + Calibration
V2.3 SquatFSM
V2.4 CoachEvent + Arbiter
V2.5 ReferenceMotion + TemporalAlignment
V2.6 BiomechanicalContext
V2.7 Realtime MLLM structured feedback
V2.8 Memory
V3.x 3D Pose / domain fine-tuning
~~~

---

## 33. 推荐新增模块

~~~text
coach/
├── models.py
├── geometry.py
├── smoothing.py
├── calibration.py
├── squat_fsm.py
├── arbiter.py
├── runtime.py
│
├── reference/
│   ├── library.py
│   ├── alignment.py
│   └── comparison.py
│
├── biomechanics/
│   ├── context.py
│   ├── constraints.py
│   └── morphometrics.py
│
└── recognition/
    └── classifier.py
~~~

不要一次全部实现。

最先新增 calibration.py、reference/alignment.py、reference/comparison.py，会比直接训练新 VLM 更容易得到稳定收益。

---

## 34. 关于 LLM 参与修改 FSM 的最终建议

允许 LLM 参与“适配”，但通过受约束 Adaptive Config，而不是直接修改 state transition graph。

例如：

~~~python
@dataclass
class FSMConfig:
    standing_range: tuple[float, float]
    bottom_range: tuple[float, float]
    min_rep_duration: float
    confidence_threshold: float
~~~

MLLM 可以提出：

~~~text
FSMAdjustmentProposal
↓
Schema Validation
↓
Allowed Range Check
↓
Historical Rep Replay
↓
Performance Comparison
↓
Accept / Reject
~~~

更推荐参数本身主要由统计数据学习：

~~~text
High-quality historical reps
↓
Distribution Estimation
↓
Personal Range
~~~

LLM 更适合负责解释、提出候选和汇总证据，而不是成为唯一数值优化器。

---

## 35. 推荐研究问题与对照实验

### RQ1

结构化 Pose evidence 是否比纯 MLLM 视频输入提高动作质量判断？

### RQ2

个体 Calibration 是否比固定 FSM threshold 提高 rep / phase detection？

### RQ3

Reference-based comparison 是否比绝对 threshold 提供更准确的 form feedback？

### RQ4

Structured Biomechanical Context 是否提高 MLLM feedback 的准确性和可解释性？

### RQ5

长期 Memory 和 cue effectiveness 是否能提高后续训练中的个性化反馈质量？

推荐对照：

~~~text
Pure MLLM
vs
Pose + FSM
vs
Pose + FSM + MLLM
vs
Pose + Reference + MLLM
vs
Pose + Biomechanics + MLLM
~~~

这些对比比单纯“换一个更大的 LLM”更能说明系统架构的价值。
