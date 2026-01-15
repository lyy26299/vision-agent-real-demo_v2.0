# 快速开始指南

## 5 分钟快速部署

### 第一步：获取 API 密钥（3 分钟）

#### 1. Stream API（必需）
1. 访问 https://getstream.io
2. 点击 "Start for Free"
3. 注册账号（GitHub/Google 登录最快）
4. 进入 Dashboard，创建新应用
5. 复制 **API Key** 和 **Secret**

**免费额度**: 333,000 分钟/月（足够个人使用）

#### 2. Gemini API（推荐）
1. 访问 https://ai.google.dev/
2. 点击 "Get API Key"
3. 创建新项目或选择现有项目
4. 生成 API 密钥并复制

**免费额度**: 每天 1500 次请求（足够测试）

### 第二步：安装和配置（2 分钟）

```bash
# 1. 进入项目目录
cd vision-agent-real-demo

# 2. 运行安装脚本（macOS/Linux）
./setup.sh

# Windows 用户手动安装：
# pip install -e .
# copy .env.example .env
```

**编辑 .env 文件**:
```bash
nano .env  # 或使用你喜欢的编辑器
```

填入密钥：
```env
STREAM_API_KEY=你刚才复制的Stream_Key
STREAM_API_SECRET=你刚才复制的Stream_Secret
GEMINI_API_KEY=你刚才复制的Gemini_Key
```

保存并退出（nano: Ctrl+X, Y, Enter）

### 第三步：启动（30 秒）

```bash
# macOS/Linux
./run.sh

# Windows
run.bat

# 或直接运行
python vision_agent_demo.py
```

### 第四步：开始体验！

程序启动后会：
1. ✓ 自动打开浏览器
2. ✓ 显示视频通话界面
3. ✓ AI Agent 自动加入

**允许浏览器访问**：
- 点击"允许"摄像头权限
- 点击"允许"麦克风权限

**开始交互**：
- 对着摄像头挥手 → AI 会回应
- 做深蹲动作 → AI 会分析姿态
- 拿物品到镜头前 → AI 会识别

## 常见问题（1 分钟解决）

### Q: 提示 "STREAM_API_KEY 未配置"
**A**: 检查 `.env` 文件是否存在且密钥已正确填写（没有多余空格）

### Q: 浏览器没有自动打开
**A**: 手动访问终端中显示的 URL（通常是 `https://getstream.io/video/demos/join/...`）

### Q: 摄像头无法访问
**A**:
- 确保浏览器有摄像头权限
- 关闭其他占用摄像头的程序
- 刷新浏览器页面重新授权

### Q: YOLO 模型下载慢
**A**: 首次运行会自动下载约 6MB 模型，稍等片刻。如果网络慢可以手动下载：
```bash
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolo11n-pose.pt
```

### Q: Python 版本不对
**A**: Vision-Agents 要求 Python 3.13+
```bash
# 检查版本
python3 --version

# macOS 升级
brew install python@3.13

# Ubuntu/Debian
sudo apt install python3.13
```

## 测试清单

启动成功的标志：
- [ ] 终端显示 "Agent 已加入通话"
- [ ] 浏览器打开视频界面
- [ ] 可以看到自己的摄像头画面
- [ ] AI 发出语音问候
- [ ] 做动作后 AI 有反馈

## 下一步

✅ **自定义 AI 行为**: 编辑 `vision_assistant.md`
✅ **调整性能**: 修改 `fps` 参数
✅ **添加功能**: 查看 README.md 的扩展建议

---

**遇到问题？**
- 查看完整 README.md
- GitHub Issues: https://github.com/GetStream/Vision-Agents/issues
- Stream 文档: https://getstream.io/video/docs/

**享受你的 AI 视觉交互体验！** 🎉
