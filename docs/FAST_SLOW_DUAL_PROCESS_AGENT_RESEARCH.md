# Fast–Slow / Dual-Process / Asynchronous Reasoning：实时 AI Agent 架构文献调研与运动教练设计推导

> 调研日期：2026-09-08  
> 面向项目：Real-Time AI Fitness Coach / Vision Agent  
> 核心问题：如何让 Agent 在连续、实时的人机交互中，同时满足**低延迟、强推理、可控性和自然交互**。

---

## 1. TL;DR

Fast–Slow、Dual-Process 和 Asynchronous Reasoning 经常一起出现，但它们不是同一个概念：

- **Fast–Slow**：从系统约束出发，把决策分成低延迟的快速路径和高能力的慢速路径。
- **Dual-Process**：从认知/功能分工出发，用 Type 1 / Type 2 描述“自动快速处理”和“工作记忆参与的审慎处理”。
- **Asynchronous Reasoning**：从计算机系统实现出发，让慢推理不阻塞实时交互主循环。

对实时运动教练，推荐的不是“所有事情都交给两个 LLM”，而是：

```text
Perception
    ↓
State Estimator
    ↓
Event Stream
    ↓
Feedback Arbiter
   /      |       \
IGNORE   FAST      SLOW
          |         |
      FSM/Policy    LLM Reasoner
          |         |
          |     Coaching State
          |        /
          └───────┘
              ↓
          Talker / TTS
              ↓
             User
```

核心研究对象不是“用了几个模型”，而是：

> **什么信息应该立刻处理，什么问题值得花更多计算，慢推理结果如何在不中断交互的前提下改变后续行为。**

---

# 2. 从第一性原理推导：为什么实时 Agent 必然走向 Fast–Slow

## 2.1 第一条事实：环境不会等 Agent 思考

普通 Chatbot 的交互是离散的：

```text
User → Agent → Answer → User
```

用户发完消息后，世界基本可以“停住”等模型回答。

实时运动场景不是这样：

```text
t0   t1   t2   t3   t4   t5 ...
│    │    │    │    │    │
用户身体持续运动 ───────────→
心率持续变化   ───────────→
相机持续产生帧 ───────────→
```

Agent 在推理时，环境仍在变化。

因此某条反馈的价值不仅取决于“是否正确”，还取决于：

\[
U = f(\text{correctness}, \text{timeliness}, \text{relevance})
\]

一个完全正确、但三秒后才到达的动作纠正，可能已经失去价值。

所以实时 Agent 的优化目标不能只是：

\[
\max Accuracy
\]

而更接近：

\[
\max \mathbb{E}
[
U(a_t, s_t)
-\lambda L_t
-\mu C_t
-\eta I_t
]
\]

其中：

- \(a_t\)：Agent 在时刻 \(t\) 的动作/反馈；
- \(s_t\)：当前环境和用户状态；
- \(L_t\)：反馈延迟；
- \(C_t\)：计算成本；
- \(I_t\)：对用户造成的打扰；
- \(\lambda,\mu,\eta\)：不同约束的重要性。

这就是 Fast–Slow 的第一个根源：

> **不是所有决策都值得用同样多的时间和计算。**

---

## 2.2 第二条事实：推理能力与计算时间存在真实代价

设两个决策器：

```text
Fast Policy
延迟：100 ms
能力：中等

Slow Reasoner
延迟：1500 ms
能力：高
```

如果所有事件都走 Slow：

\[
T_{\text{response}}
=
T_{\text{perception}}
+
T_{\text{reasoning}}
+
T_{\text{generation}}
+
T_{\text{speech}}
\]

串行执行时，总延迟由所有阶段直接累加。

但现实中的事件有不同难度。

例如：

### 问题 A

> 当前深蹲是否完成一次有效 repetition？

这可能只需要状态机：

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
```

### 问题 B

> 用户最近 10 分钟为什么配速下降，同时主观感觉越来越累，下一阶段应该如何调整教练策略？

这个问题需要：

- 历史状态；
- 用户目标；
- 多传感器信息；
- 长期趋势；
- 复杂推理。

如果 A、B 都交给大型 Reasoner，系统就是在用昂贵的通用计算解决本可以快速确定的问题。

因此需要一个路由函数：

\[
r_t = \pi(s_t)
\]

其中：

\[
r_t \in
\{
\text{IGNORE},
\text{FAST},
\text{SLOW},
\text{DELAY}
\}
\]

这一步就是实时 Agent 的核心控制问题。

---

# 3. Fast–Slow 到底是什么？

Fast–Slow 首先是一个**计算资源分配思想**。

它不规定 Fast 一定是小 LLM，也不规定 Slow 一定是大 LLM。

可以是：

| Fast | Slow |
|---|---|
| Rule | LLM |
| FSM | LLM |
| Classifier | LLM |
| Small Language Model | Frontier LLM |
| Cached Policy | Planner |
| Full-duplex SpeechLM | RAG / Tools / Reasoner |

Fast 的核心属性：

```text
低延迟
可预测
高频运行
处理熟悉/明确事件
```

Slow 的核心属性：

```text
高计算量
低频调用
处理不确定/复杂问题
维护长期策略
```

因此更准确的表达不是：

> Fast = System 1 模型  
> Slow = System 2 模型

而是：

> **系统按照任务价值、复杂度和时间预算，为不同决策分配不同计算深度。**

---

# 4. Dual-Process Theory 是什么？

Dual-Process Theory 来自认知心理学。

常见的通俗表达是：

```text
System 1
fast / intuitive / automatic

System 2
slow / deliberate / analytical
```

但学术上需要谨慎。

Evans 与 Stanovich 更倾向使用：

```text
Type 1 processing
Type 2 processing
```

而不是把它们理解成人脑里两个完全独立的“模块”。

一个更严谨的区分是：

### Type 1

- autonomous；
- 能快速产生 default response；
- 通常不依赖大量工作记忆。

### Type 2

- 依赖 working memory；
- 支持 hypothetical thinking；
- 可以检查、修改甚至覆盖默认响应。

可以抽象成：

```text
Observation
    ↓
Type 1
    ↓
default action
    │
    ├────────────→ execute
    │
    ↓
Type 2 detects need for intervention
    ↓
reason / revise / override
```

这叫 **default-interventionist** 思想。

对 Agent 来说，它提供了一种非常自然的架构灵感：

```text
fast default policy
        ↓
   normally act
        ↑
slow reasoner intervenes
when necessary
```

需要强调：

> Dual-Process 是认知理论启发，不代表 AI 必须复制人脑，也不证明一定存在两个独立神经系统。

对工程设计最有价值的是“不同处理机制具有不同资源需求，并可以协作/干预”的抽象。

---

# 5. Asynchronous Reasoning 是什么？

这是三个概念中最“计算机科学”的一个。

同步执行：

```python
state = perceive()
reasoning = await slow_reasoner(state)
feedback = generate(reasoning)
speak(feedback)
```

执行关系是：

```text
Perception
   ↓
Reasoner
   ↓
Generation
   ↓
Speech
```

Reasoner 没结束：

```text
整个链条都在等
```

这叫 **blocking**。

---

## 5.1 异步的第一性原理

如果任务 A 和任务 B 不存在严格的数据依赖：

\[
A \not\rightarrow B
\]

为什么一定要：

```text
A 完成
↓
B 开始
```

而不是：

```text
A ─────────────→
B ───────→
```

并行推进？

实时 Agent 中：

```text
Realtime Loop
```

与：

```text
Reasoning Loop
```

通常没有必要每一步严格同步。

所以可以：

```text
                ┌──── Fast Loop ────────────→
Sensor → Event ─┤
                └──── Slow Reasoner ────────→
```

Fast Loop 每几十/几百毫秒继续更新。

Reasoner 可能一两秒后完成。

完成后不是“返回给过去”，而是：

```text
Reasoner Result
      ↓
Shared State
      ↓
影响未来决策
```

---

# 6. Dual-Process 和 Asynchronous Reasoning 不是一回事

这是最容易混淆的地方。

## Dual-Process 解决：

> **谁负责什么？**

```text
Fast Process
vs
Slow Process
```

## Async 解决：

> **它们怎样在时间上同时运行？**

```text
Fast Loop ──────────────────→

Slow Task
     ├──────────────→ result
                       ↓
                 update state
```

所以可能出现：

### Dual-Process but synchronous

```text
Fast
 ↓
Slow
 ↓
Action
```

仍然会卡住。

### Async but not Dual-Process

```text
多个相同 LLM task
并行运行
```

虽然异步，但没有 Fast/Slow 功能分工。

最有价值的是：

```text
Dual-Process
+
Asynchronous Execution
```

即：

> **功能上分层，时间上解耦。**

---

# 7. 一个最小数学模型

假设事件 \(e_t\) 到达时，Agent 可以选择 Fast 或 Slow。

Fast：

\[
V_f
=
Q_f(e_t)
-
\lambda T_f
-
\mu C_f
\]

Slow：

\[
V_s
=
Q_s(e_t)
-
\lambda T_s
-
\mu C_s
\]

通常：

\[
Q_s > Q_f
\]

但：

\[
T_s \gg T_f
\]

因此不能简单认为：

\[
Q_s > Q_f
\Rightarrow
\text{always choose Slow}
\]

真正应该比较：

\[
r_t = \arg\max_{r \in \{f,s\}} V_r
\]

对于运动教练还要加入打扰成本：

\[
V_r
=
Q_r
-\lambda T_r
-\mu C_r
-\eta I_r
\]

所以 Agent 的问题变成：

> 这次反馈带来的收益，是否值得它占用用户注意力和计算资源？

这正对应“什么时候说”。

---

# 8. Fast–Slow Agent 最关键的模块不是 LLM，而是 Router / Arbiter

如果没有 Router：

```text
Event
 ↓
LLM
 ↓
Speech
```

其实不是完整的 Fast–Slow。

真正的架构需要：

```text
               Event
                 ↓
           Feedback Arbiter
          /      |       \
       Ignore   Fast     Slow
```

可以写成：

\[
\pi(s_t)
\rightarrow
\{
0,1,2,3
\}
\]

例如：

```text
0 = IGNORE
1 = FAST_FEEDBACK
2 = SLOW_REASONING
3 = DELAY_FEEDBACK
```

输入状态可以包括：

\[
s_t =
[
\text{exercise phase},
\text{error severity},
\text{confidence},
\text{fatigue trend},
\text{last feedback time},
\text{recent feedback count},
\text{conversation state},
\text{reasoner state}
]
\]

所以在实时运动 Agent 中：

> **FeedbackArbiter 实际上就是 cognition router。**

---

# 9. 为什么 FSM 特别适合 Fast Loop？

假设深蹲识别状态：

```text
READY
 ↓
DESCENDING
 ↓
BOTTOM
 ↓
ASCENDING
 ↓
COMPLETE
```

它的状态空间是有限且结构明确的。

我们并不需要一个 LLM 每帧回答：

> “用户现在大概处于什么动作阶段？”

FSM 的优势：

- O(1) 级状态转移；
- 可解释；
- 可测试；
- 延迟稳定；
- 不需要生成式模型；
- 不容易发生语言模型随机漂移。

因此：

```text
Perception
    ↓
FSM
    ↓
Fast Policy
```

非常适合作为 System 1-like path。

ACL 2025 的 DPT-Agent 正是类似思路：System 1 使用 FSM + code-as-policy，System 2 使用 ToM + asynchronous reflection。

---

# 10. Slow Reasoner 应该做什么？

Slow Reasoner 不应该承担：

```text
每一帧姿态分类
每一次 rep counting
每一个固定阈值判断
```

而应该负责需要跨时间、跨模态、跨目标的信息整合：

```text
Session history
+
Current performance
+
User goal
+
Past feedback
+
Exercise knowledge
+
Conversation context
```

得到更高层：

```text
Coaching State
```

例如：

```json
{
  "fatigue_trend": "rising",
  "form_stability": "declining",
  "recent_feedback_density": "high",
  "strategy": "reduce_interruptions",
  "next_focus": "movement_quality"
}
```

注意一个非常重要的设计：

> Reasoner 最好输出**状态/策略**，而不是随时直接抢占语音输出。

即：

```text
Reasoner
   ↓
Coaching State
   ↓
Feedback Arbiter
   ↓
Talker
```

这样才能让“长期智能”和“实时交互控制”解耦。

---

# 11. Shared State 为什么是双过程 Agent 的核心？

Fast 与 Slow 是不同时间尺度。

因此必然产生：

```text
Fast Loop 当前看到的状态
≠
Slow Reasoner 启动时看到的状态
```

例如：

```text
t0:
Reasoner 开始分析
user_fatigue = medium

t1:
Fast Loop 继续运行

t2:
user_fatigue = high

t3:
Reasoner 返回
建议基于 t0
```

这产生经典分布式系统问题：

> **stale state（过时状态）**

因此 Shared State 不能只是一个随便的 Python dict。

推荐至少包含：

```text
state_version
timestamp
source
confidence
valid_until
```

例如：

```json
{
  "version": 135,
  "timestamp": 1720000000,
  "fatigue": "high",
  "confidence": 0.82
}
```

Reasoner 返回：

```json
{
  "based_on_version": 128,
  "strategy_update": "reduce_feedback_frequency"
}
```

系统需要判断：

```text
128 与当前 135 是否仍然兼容？
```

这就是异步 Agent 从 Demo 走向可靠系统时必须解决的问题。

---

# 12. 从 Talker–Reasoner 到 2026：技术路线演化

## 12.1 Talker–Reasoner — 2024

**Agents Thinking Fast and Slow: A Talker-Reasoner Architecture**

作者：Konstantina Christakopoulou, Shibl Mourad, Maja Matarić  
状态：NeurIPS 2024 Open-World Agents Workshop

核心：

```text
Talker
System 1-like
real-time conversation

        ↕

Shared State

        ↕

Reasoner
System 2-like
planning / tools / actions
```

意义：

> 第一次把“对话”和“深度推理/行动规划”明确拆成两个时间尺度的 Agent 角色。

局限：

- 更像架构范式；
- Fast path 仍主要由语言 Agent 表达；
- 还没有充分解决 full-duplex、持续感知、复杂异步一致性。

Paper: https://arxiv.org/abs/2410.08328  
NeurIPS Workshop: https://neurips.cc/virtual/2024/100894

---

## 12.2 Moshi — 2024

**Moshi: a speech-text foundation model for real-time dialogue**

核心目标不是复杂 Agent planning，而是解决：

```text
listen
+
speak
```

能否同时进行。

传统：

```text
VAD
 ↓
ASR
 ↓
LLM
 ↓
TTS
```

Moshi：

```text
User Audio Stream ───────→
                       Model
Agent Audio Stream ←──────
```

它建模双音频流，实现 full-duplex spoken dialogue。

论文报告：

- theoretical latency：160 ms；
- practical latency：约 200 ms。

意义：

> Fast Loop 开始从“文本 LLM + TTS”进一步演化成原生实时语音模型。

Paper: https://arxiv.org/abs/2410.00037  
Code: https://github.com/kyutai-labs/moshi

---

## 12.3 DPT-Agent — ACL 2025 Main

**Leveraging Dual Process Theory in Language Agent Framework for Real-time Simultaneous Human-AI Collaboration**

核心：

```text
System 1
FSM
+
Code-as-Policy
+
fast controllable decisions

           ↕

System 2
Theory of Mind
+
Asynchronous Reflection
```

这是对实时运动 Agent 特别重要的一篇。

原因：

> 它证明 Fast path 没必要也是一个大语言模型。

真正实时的部分可以是：

```text
FSM
Rules
Policy
```

复杂长期决策才进入 LLM。

Paper: https://aclanthology.org/2025.acl-long.206/  
Code: https://github.com/sjtu-marl/DPT-Agent

---

## 12.4 Talker–Reasoner Voice-Agent Pattern — 2026

LiveKit 在 2026 年专门给出了 production voice agent 中的 Talker–Reasoner Pattern：

```text
Talker
fast conversation
      │
      ├──── Shared State ────┐
      │                      ↓
      │                  Reasoner
      │                  tools
      │                  planning
      │                  research
      │                      │
      └──────────────────────┘
```

重点已经从“论文提出架构”转向：

- background task；
- shared session state；
- context injection；
- stale data；
- orchestration。

这说明 Talker–Reasoner 已经从论文概念进入 Voice Agent 工程 pattern。

Guide: https://livekit.com/blog/talker-reasoner-pattern-voice-agents

---

# 13. 2026 的进一步演化：Thinking While Speaking

## 13.1 ConvFill

**Thinking While Speaking: Inference-Time Knowledge Transfer for Responsive and Intelligent Conversational Voice Agents**

状态：EMNLP Findings 2026

它进一步提出：

```text
On-device Small Talker
        ↓
立刻开始生成
        ↓
“Let me check ...”
        ↓
继续说 ──────────────────→

Cloud Reasoner
        ↓
reasoning / retrieval / tools
        ↓
knowledge stream
        ↓
Talker 在生成过程中吸收
```

传统 Talker–Reasoner：

```text
Reasoner 完成
      ↓
Talker 下一轮使用
```

ConvFill：

```text
Reasoner 输出知识流
      ↓
Talker 正在说话时融入
```

这就是：

> **Conversational Infill / Thinking While Speaking**

其公开材料报告：

- 290,571 个训练示例；
- Talker 规模约 135M–1.7B；
- 与对应 frontier reasoner 的能力差距缩小到 6.3% 内；
- 进行了真实用户实验。

Paper: https://arxiv.org/abs/2511.07397  
Code: https://github.com/vysri/conversational-infill

---

# 14. LTS-VoiceAgent：Thinking While Listening

2026 年的 **LTS-VoiceAgent** 又向前推进了一步。

问题：

传统 pipeline：

```text
User 完全说完
      ↓
ASR 完成
      ↓
LLM 开始想
      ↓
TTS
```

但人类不是这样听别人讲话的。

用户还在说：

```text
“我最近跑步的时候……”
```

我们已经开始形成假设。

所以 LTS：

```text
User Speech ─────────────────────→

        semantic prefix
              ↓
       Background Thinker
              ↓
      incremental state

User Speech continues ───────────→

                           ↓
                    Foreground Speaker
```

核心贡献是：

- Dynamic Semantic Trigger；
- Background Thinker；
- Foreground Speaker；
- incremental reasoning。

它把：

```text
Listen → Think → Speak
```

变成部分重叠：

```text
Listen ──────────────────→
       Think ────────────→
                    Speak ─────→
```

Paper: https://arxiv.org/abs/2601.19952

---

# 15. MoshiRAG：Full-Duplex + Async Backend

**MoshiRAG: Asynchronous Knowledge Retrieval for Full-Duplex Speech Language Models**

状态：ICML 2026

它解决一个新的冲突：

```text
Full-duplex SpeechLM
很快、很自然

但是

事实知识 / 数学 / 外部信息
不够强
```

如果把 SpeechLM 直接放大：

```text
模型越大
 ↓
实时推理越贵
```

MoshiRAG 的答案：

```text
         Full-Duplex Frontend
                │
        keep talking/listening
                │
        need knowledge?
                ↓
          retrieval trigger
                │
          ┌─────┴─────┐
          ↓           │
     Async Backend    │
     RAG / Search     │
          ↓           │
      reference       │
          └────→ inject
                      ↓
                 speech continues
```

它最关键的思想是：

> **Realtime interaction plane 和 knowledge/reasoning plane 可以是两个并行系统。**

Paper: https://arxiv.org/abs/2604.12928  
Code: https://github.com/kyutai-labs/moshi-rag

---

# 16. 技术路线总结

可以把 2024–2026 的路线抽象成：

```text
2024
Talker–Reasoner
Conversation vs Reasoning
        │
        ↓
2025
DPT-Agent
FSM/Policy vs Async LLM
        │
        ↓
2026
┌───────────────┬─────────────────┬──────────────────┐
↓               ↓                 ↓
ConvFill        LTS               MoshiRAG
small talker    think while       full-duplex
+ reasoner      listening         + async retrieval
└───────────────┴─────────────────┴──────────────────┘
                        ↓
          Asynchronous Multi-Timescale Agent
```

真正长期留下来的未必是：

> “Talker–Reasoner”这个名字

而是：

> **不同时间尺度上的智能模块协作。**

---

# 17. 推荐用于实时 AI 运动教练的架构

## 17.1 Layer 1：Perception

输入：

```text
Camera
Heart Rate
Pace
IMU
Audio
```

输出统一状态：

```text
World / User State
```

例如：

```json
{
  "exercise": "squat",
  "phase": "ascending",
  "knee_alignment": "warning",
  "confidence": 0.91,
  "rep": 7
}
```

---

## 17.2 Layer 2：Event Detection

不要把所有 frame 都交给 Agent。

把连续信号转换成：

```text
REP_COMPLETED
FORM_ERROR_STARTED
FORM_ERROR_PERSISTED
REST_STARTED
PACE_DROP
USER_SPEAKING
```

即：

\[
continuous\ signal
\rightarrow
discrete\ event
\]

这样 Agent 才能在事件级别思考。

---

## 17.3 Layer 3：Feedback Arbiter

这是整个系统最重要的研究模块。

输入：

```text
Event
+
Session State
+
Conversation State
+
Feedback History
+
Reasoner State
```

输出：

```text
IGNORE
FAST
SLOW
DELAY
```

例如：

```python
if error.confidence < threshold:
    IGNORE

elif error.is_urgent and cooldown_ok:
    FAST

elif trend_requires_analysis:
    SLOW

elif user_is_speaking:
    DELAY
```

这直接解决：

> **什么时候说？**

---

## 17.4 Layer 4：Fast Loop

负责：

- rep counting；
- movement phase；
- 明确姿态错误；
- cooldown；
- priority；
- 简短即时反馈；
- interruption control。

实现：

```text
FSM
Rules
Code-as-Policy
Small classifier
Template / Small LLM
```

---

## 17.5 Layer 5：Slow Reasoner

负责：

- session-level analysis；
- 趋势分析；
- coaching strategy；
- 个性化；
- 用户意图；
- tool use；
- memory；
- 多因素综合决策。

输出：

```text
Strategy Update
```

而不是直接控制麦克风。

---

## 17.6 Layer 6：Talker / Voice Interface

Talker 负责：

> **怎么说？**

例如 Reasoner 输出：

```json
{
  "goal": "reduce pace slightly",
  "reason": "form quality declining",
  "tone": "concise"
}
```

Talker 决定：

```text
“稍微放慢一点，把动作稳定住。”
```

Talker 不需要重新做全部 reasoning。

---

# 18. 推荐的最终系统

```text
┌─────────────────────────────────────┐
│            Sensors                  │
│ Camera / HR / Pace / IMU / Audio    │
└─────────────────┬───────────────────┘
                  ↓
┌─────────────────────────────────────┐
│         State Estimator             │
└─────────────────┬───────────────────┘
                  ↓
┌─────────────────────────────────────┐
│           Event Bus                 │
└─────────────────┬───────────────────┘
                  ↓
┌─────────────────────────────────────┐
│         Feedback Arbiter            │
│                                     │
│   IGNORE / FAST / SLOW / DELAY      │
└───────┬──────────────┬──────────────┘
        │              │
        ↓              ↓
┌──────────────┐  ┌───────────────────┐
│ Fast Loop    │  │ Slow Reasoner     │
│ FSM / Policy │  │ LLM / Tools       │
│ Rules        │  │ Memory / Strategy │
└──────┬───────┘  └─────────┬─────────┘
       │                     ↓
       │              ┌───────────────┐
       │              │ Shared State  │
       │              └───────┬───────┘
       │                      │
       └──────────┬───────────┘
                  ↓
         ┌────────────────┐
         │ Talker / TTS   │
         └───────┬────────┘
                 ↓
                User
```

推荐命名：

> **Event-Driven Dual-Process Real-Time Coaching Agent**

或者：

> **Hierarchical Fast–Slow Agent for Real-Time AI Coaching**

---

# 19. 对当前 Vision Agent 项目的映射

当前系统中的模块可以重新理解为：

| 当前模块/概念 | Fast–Slow 中的位置 |
|---|---|
| Camera / YOLO Pose | Perception |
| Pose State | State Estimator |
| FSM | Fast / System-1-like |
| Action Queue | Async execution / output serialization |
| FeedbackArbiter | Router / cognitive controller |
| Gemini / LLM Agent | Slow Reasoner + language generation |
| TTS | Talker output |
| WebRTC | Realtime interaction substrate |
| AEC | Full-duplex voice infrastructure |

下一阶段最值得拆开的，是当前“LLM Agent”承担的多个角色：

```text
Reasoning
+
Feedback Decision
+
Language Generation
```

推荐改成：

```text
Reasoner
    ↓
Strategy / State

Feedback Arbiter
    ↓
Should speak?

Talker
    ↓
How to say?
```

---

# 20. 可以形成的研究问题

## RQ1：Fast–Slow 是否降低实时反馈延迟？

指标：

\[
TTFF = t_{\text{first feedback}} - t_{\text{event}}
\]

比较：

```text
Single LLM
vs
Fast–Slow Agent
```

---

## RQ2：Adaptive Arbiter 是否减少不必要打扰？

指标：

\[
InterruptionRate
=
\frac{\text{unnecessary interruptions}}
{\text{interaction duration}}
\]

以及用户主观打扰度。

---

## RQ3：Slow Reasoner 是否提高长期 coaching quality？

比较：

```text
Reactive only
vs
Reactive + Slow Reasoner
```

重点不是单句回答质量，而是整个 session 的：

- feedback relevance；
- consistency；
- context awareness；
- 用户主观体验。

---

## RQ4：异步 Reasoning 是否改善 latency–quality trade-off？

建立：

\[
Quality
\quad vs \quad
Latency
\]

Pareto frontier。

理想系统不是：

```text
只追求最低 latency
```

也不是：

```text
只追求最高 reasoning accuracy
```

而是在两者之间找到新的 Pareto 点。

---

# 21. 工程上最需要警惕的问题

## 21.1 Stale Reasoning

Reasoner 返回时环境已经改变。

解决思路：

```text
state version
timestamp
validity check
```

---

## 21.2 Race Condition

Fast Loop 和 Slow Loop 同时修改：

```text
coaching_state
```

需要：

- single writer；
- lock；
- immutable snapshot；
- event sourcing；

等并发控制策略。

---

## 21.3 Reasoner 抢占实时输出

不要：

```text
Reasoner finished
→ immediately speak
```

应该：

```text
Reasoner finished
→ update state
→ Arbiter decides when/if to speak
```

---

## 21.4 Feedback Storm

多个事件：

```text
knee warning
pace warning
rep complete
heart-rate event
reasoner result
```

同时发生。

需要：

```text
priority
cooldown
deduplication
coalescing
```

---

# 22. 最核心的第一性原理总结

整个 Fast–Slow Agent 其实可以从四条事实推出：

### 事实 1

\[
World\ does\ not\ wait
\]

现实世界持续变化。

### 事实 2

\[
Reasoning\ is\ not\ free
\]

推理需要时间和计算资源。

### 事实 3

\[
Not\ every\ decision\ has\ equal\ complexity
\]

不同事件需要不同推理深度。

### 事实 4

\[
Independent\ work\ need\ not\ be\ serial
\]

没有强数据依赖的任务可以异步重叠。

于是自然得到：

```text
Fast Process
+
Slow Process
+
Router
+
Shared State
+
Async Execution
```

这就是现代实时 Agent 的核心骨架。

---

# 23. 推荐阅读顺序

## 第一层：理论基础

1. Evans, J. St. B. T. (2008). **Dual-Processing Accounts of Reasoning, Judgment, and Social Cognition**  
   https://doi.org/10.1146/annurev.psych.59.103006.093629

2. Evans, J. St. B. T., & Stanovich, K. E. (2013). **Dual-Process Theories of Higher Cognition: Advancing the Debate**  
   https://doi.org/10.1177/1745691612460685

3. De Neys, W. (2025). **Defining deliberation for dual-process models of reasoning**  
   https://www.nature.com/articles/s44159-025-00466-6

## 第二层：Agent 架构

4. Christakopoulou, K., Mourad, S., & Matarić, M. (2024). **Agents Thinking Fast and Slow: A Talker-Reasoner Architecture**  
   https://arxiv.org/abs/2410.08328

5. Zhang, S. et al. (2025). **Leveraging Dual Process Theory in Language Agent Framework for Real-time Simultaneous Human-AI Collaboration** — ACL 2025 Main  
   https://aclanthology.org/2025.acl-long.206/

## 第三层：实时 Voice Agent

6. Défossez, A. et al. (2024). **Moshi: a speech-text foundation model for real-time dialogue**  
   https://arxiv.org/abs/2410.00037

7. LiveKit (2026). **The Talker-Reasoner Pattern for Voice Agents**  
   https://livekit.com/blog/talker-reasoner-pattern-voice-agents

8. Zou, W. et al. (2026). **LTS-VoiceAgent: A Listen-Think-Speak Framework for Efficient Streaming Voice Interaction via Semantic Triggering and Incremental Reasoning**  
   https://arxiv.org/abs/2601.19952

9. Srinivas, V. et al. (2026). **Thinking While Speaking: Inference-Time Knowledge Transfer for Responsive and Intelligent Conversational Voice Agents** — EMNLP Findings 2026  
   https://arxiv.org/abs/2511.07397

10. Chien, C.-M. et al. (2026). **MoshiRAG: Asynchronous Knowledge Retrieval for Full-Duplex Speech Language Models** — ICML 2026  
    https://arxiv.org/abs/2604.12928

---

# 24. 最终判断

截至 2026 年，Talker–Reasoner 并没有“消失”。

更准确地说：

```text
Talker–Reasoner
       ↓
Dual-Process Agent
       ↓
Fast–Slow Routing
       ↓
Async Reasoning
       ↓
Thinking While Listening/Speaking
       ↓
Full-Duplex Frontend + Async Intelligence Backend
```

因此，对实时运动教练最值得研究的不是：

> “如何复现 Talker–Reasoner？”

而是：

> **如何设计一个 Event-Driven、Multi-Timescale、Dual-Process Agent，使快速反应、慢速推理和实时语音交互在时间上并行，在策略上统一。**

这也是从现有 Vision Agent Demo 进一步走向研究型实时运动教练 Agent 最自然的技术路线。