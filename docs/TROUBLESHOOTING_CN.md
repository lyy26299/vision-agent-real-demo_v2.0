# 故障排除指南

## ⚠️ 常见错误：TimeoutError - Track Published

### 错误信息
```
TimeoutError: Timeout waiting for pending track: 2 (video) from user...
Waited 10.0s but WebRTC track_added with matching kind was never received.
```

### 这是什么？
这是 Vision-Agents SDK 中的一个已知问题。Agent 尝试发布视频轨道（track）但超时了。

### 重要：这个错误**可以忽略**！

**原因**：
- Agent 不需要发布自己的视频（它没有摄像头）
- Agent 只需要**接收**用户的视频
- 音频轨道已成功发布
- 这个超时不影响核心功能

### 如何判断 Agent 是否正常工作？

✅ **Agent 正常工作的标志**：
1. 终端显示：`✓ Agent 已成功加入通话`
2. 浏览器自动打开 Stream 视频界面
3. 你能看到自己的摄像头画面
4. 能听到 AI 的语音问候
5. 对着摄像头说话或做动作，AI 有反馈

### 解决方案

#### 方案 1：忽略错误，继续使用（推荐）

如果看到以上✅标志，**直接忽略这个错误**，Agent 功能正常！

#### 方案 2：降低 fps 减少压力

编辑 `vision_agent_demo.py`:
```python
llm=gemini.Realtime(fps=1),  # 从 3 改为 1
```

#### 方案 3：使用简化版（不使用 YOLO）

创建一个测试版本，先不使用 YOLO processor：

```python
# 注释掉 processors
agent = Agent(
    edge=getstream.Edge(),
    agent_user=User(name="AI 健身教练"),
    instructions="Read @vision_assistant.md",
    llm=gemini.Realtime(fps=3),
    # processors=[  # 暂时注释掉
    #     ultralytics.YOLOPoseProcessor(...)
    # ],
)
```

测试是否能正常对话。如果可以，说明问题在 YOLO processor。

---

## 其他常见问题

### 1. Gemini API 错误

**错误**: `429 Too Many Requests` 或 `API key invalid`

**解决方案**:
```bash
# 检查 API 密钥
cat .env | grep GEMINI

# 访问 https://ai.google.dev/ 检查配额
# 或降低 fps 减少请求次数
```

### 2. Stream API 连接失败

**错误**: `401 Unauthorized`

**解决方案**:
```bash
# 检查 Stream API 密钥
cat .env | grep STREAM

# 确保密钥来自 https://getstream.io
# 检查是否有多余空格或引号
```

### 3. 浏览器没有自动打开

**解决方案**:
- 查看终端输出中的 URL
- 手动复制到浏览器
- 通常格式：`https://getstream.io/video/demos/join/...`

### 4. 摄像头无法访问

**解决方案**:
1. Chrome: 设置 → 隐私和安全 → 网站设置 → 摄像头
2. 允许 `getstream.io` 访问
3. 刷新页面
4. 关闭其他占用摄像头的程序（Zoom、Teams 等）

### 5. YOLO 模型下载失败

**错误**: `Unable to download yolo11n-pose.pt`

**解决方案**:
```bash
# 手动下载
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolo11n-pose.pt

# 或使用国内镜像（如果有）
```

### 6. 没有语音反馈

**检查清单**:
- [ ] 浏览器音量是否开启
- [ ] 允许了麦克风权限
- [ ] Gemini API 是否正常
- [ ] 查看终端是否有错误

### 7. AI 看不到我的动作

**可能原因**:
1. **光线太暗** - 增加光线
2. **距离太近/太远** - 保持 1.5-2 米
3. **不在画面中** - 确保全身或上半身在视野内
4. **YOLO 未运行** - 查看终端是否有 YOLO 相关日志

**测试 YOLO**:
```python
# 在终端看到这些信息说明 YOLO 工作正常
[INFO] YOLOPoseProcessor initialized
[INFO] Detected 17 keypoints
```

### 8. Agent 卡住不响应

**解决方案**:
1. 按 `Ctrl+C` 停止
2. 等待 5-10 秒清理连接
3. 重新运行 `./run.sh`

### 9. 内存占用过高

**解决方案**:
- 降低 fps: `fps=1`
- 减少 YOLO 模型大小（使用 nano 版本）
- 关闭其他程序

### 10. CPU 占用 100%

**原因**: YOLO 姿态检测计算密集

**解决方案**:
```python
# 使用 GPU（如果有）
device="cuda"

# 或降低处理频率
llm=gemini.Realtime(fps=1),
```

---

## 调试技巧

### 查看详细日志

```bash
# 设置为 DEBUG 级别
export LOG_LEVEL=DEBUG
uv run python vision_agent_demo.py
```

### 测试各个组件

**测试 1: Stream 连接**
```bash
uv run python -c "from vision_agents.plugins import getstream; print('Stream OK')"
```

**测试 2: Gemini API**
```bash
uv run python -c "from vision_agents.plugins import gemini; print('Gemini OK')"
```

**测试 3: YOLO**
```bash
uv run python -c "from vision_agents.plugins import ultralytics; print('YOLO OK')"
```

### 检查网络连接

```bash
# 测试 Stream API
curl -H "Authorization: Bearer $STREAM_API_KEY" https://stream-io-api.com/api/v2/health

# 测试 Gemini
curl "https://generativelanguage.googleapis.com/v1/models?key=$GEMINI_API_KEY"
```

---

## 性能优化

### 降低成本和延迟

```python
# vision_agent_demo.py
llm=gemini.Realtime(fps=1),  # 最低 fps
```

### 提升检测精度

```python
# 使用更大的 YOLO 模型
ultralytics.YOLOPoseProcessor(
    model_path="yolo11l-pose.pt",  # large 版本
    device="cuda"  # GPU 加速
)
```

### 平衡配置（推荐）

```python
llm=gemini.Realtime(fps=3),  # 平衡速度和成本
ultralytics.YOLOPoseProcessor(
    model_path="yolo11n-pose.pt",  # nano 版本
    device="cpu"
)
```

---

## 何时需要帮助

如果遇到以下情况，可能需要查看 GitHub Issues：

1. Agent 完全无法启动
2. 浏览器显示白屏或错误页面
3. Stream API 一直返回 401/403
4. Gemini API 配额正常但仍无法调用

**官方资源**:
- Vision-Agents Issues: https://github.com/GetStream/Vision-Agents/issues
- Stream 文档: https://getstream.io/video/docs/
- Gemini 文档: https://ai.google.dev/docs

---

## 快速诊断清单

运行这个检查脚本：

```bash
uv run python test_setup.py
```

应该看到：
- ✓ Python 版本: 通过
- ✓ vision-agents: 通过
- ✓ STREAM_API_KEY: 通过
- ✓ GEMINI_API_KEY: 通过
- ✓ vision_assistant.md: 通过

如果全部通过，Agent 应该可以正常运行！

---

**记住**: TimeoutError 是已知问题，如果其他功能正常，可以忽略！
