# Vision Agent Real Demo 🤖💪

> **Professional AI Fitness Coach** powered by real-time vision AI, pose detection, and voice feedback

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Vision-Agents](https://img.shields.io/badge/vision--agents-0.2.10-green.svg)](https://github.com/GetStream/Vision-Agents)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![YOLO](https://img.shields.io/badge/YOLO-v11-red.svg)](https://github.com/ultralytics/ultralytics)

**[中文文档](./docs/README_CN.md)** | **[Quick Start](./docs/QUICKSTART.md)** | **[Fast–Slow Agent Research](./docs/FAST_SLOW_DUAL_PROCESS_AGENT_RESEARCH.md)** | **[Troubleshooting](./docs/TROUBLESHOOTING.md)**

---

## 🎯 What is this?

A **real-time AI fitness coach** that uses computer vision and voice AI to guide your workouts. Built on the official [GetStream/Vision-Agents](https://github.com/GetStream/Vision-Agents) framework, it combines:

- 🎥 **Real-time video analysis** via Stream's ultra-low-latency infrastructure
- 🦴 **Pose detection** with YOLO 11 tracking 17 body keypoints
- 🧠 **AI coach** powered by Google Gemini with visual understanding
- 🗣️ **Voice feedback** for instant form correction and encouragement

### Watch it in action

<p align="center">
  <img src="./docs/images/demo-preview.png" alt="Demo Preview" width="800"/>
</p>

> *AI coach analyzing a squat in real-time, detecting knee alignment and providing instant feedback*

---

## ✨ Features

### 🏋️ Professional Fitness Coaching

- **5 Core Exercises** with detailed form analysis
  - Squats - Lower body strength king
  - Push-ups - Upper body compound movement
  - Planks - Core stability foundation
  - Lunges - Single-leg balance and power
  - Crunches - Abdominal core training

- **Real-time Form Correction**
  - Detects 17 body keypoints
  - Calculates joint angles
  - Identifies common mistakes (knee valgus, lower back arch, etc.)
  - Instant voice feedback

- **Progressive Training**
  - Difficulty levels: Beginner → Intermediate → Advanced
  - Rep counting with quality standards
  - Personalized suggestions based on your performance

### 🔬 Technical Excellence

- **Ultra-low Latency** - Stream Edge Network (< 30ms)
- **Accurate Pose Detection** - YOLO 11 Pose (17 keypoints)
- **Multimodal AI** - Gemini Realtime (vision + audio)
- **Production Ready** - Built on official SDK, not a toy demo

---

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- Stream API Key ([get free](https://getstream.io))
- Gemini API Key ([get free](https://ai.google.dev))

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/MindDock/vision-agent-real-demo.git
cd vision-agent-real-demo

# 2. Install uv (fast package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install dependencies
uv sync

# 4. Configure API keys
cp .env.example .env
nano .env  # Fill in your API keys

# 5. Run the agent
./run.sh
```

**That's it!** Your browser will open automatically, and the AI coach will join the video call.

📖 **Detailed guide**: See [docs/QUICKSTART.md](./docs/QUICKSTART.md)

---

## 🎬 How It Works

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  Your       │  WebRTC │ Stream Edge  │ Process │ Python      │
│  Browser    │────────▶│  Network     │────────▶│  Agent      │
│  (Camera)   │         │ (< 30ms)     │         │             │
└─────────────┘         └──────────────┘         └──────┬──────┘
                                                        │
                                                        ▼
                                          ┌─────────────────────┐
                                          │ YOLO Pose Detection │
                                          │ (17 keypoints)      │
                                          └──────────┬──────────┘
                                                     │
                                                     ▼
                                          ┌─────────────────────┐
                                          │ Gemini AI Analysis  │
                                          │ (Vision + Voice)    │
                                          └──────────┬──────────┘
                                                     │
                                                     ▼
                                          ┌─────────────────────┐
                                          │ Voice Feedback      │
                                          │ "Knees out!"        │
                                          └─────────────────────┘
```

### Architecture

1. **Video Capture** - Your webcam streams video via WebRTC
2. **Edge Processing** - Stream's global network ensures ultra-low latency
3. **Pose Detection** - YOLO extracts 17 body keypoints per frame
4. **AI Analysis** - Gemini processes both video and pose data
5. **Voice Coaching** - Real-time audio feedback guides your form

---

## 🏃 Usage Examples

### Starting a Workout

```
You: "I want to do squats"
AI: "Great! Stand with feet shoulder-width apart, toes slightly out.
     I'll watch your form. Ready? Start!"

[You perform a squat]
AI: "Good depth! But watch your knees - they're caving in slightly.
     Push them outward. Let's try another one!"

[You adjust and do another]
AI: "Perfect! That's rep 1. Knees aligned, depth good. Keep it up!"
```

### Real-time Corrections

```
[During push-up]
AI: "Hold on - your hips are sagging. Tighten your core!
     Think of your body as a straight plank from head to heels."

[You correct the form]
AI: "Much better! That's the way. Keep breathing - down on inhale,
     up on exhale."
```

### Training Plan Suggestion

```
You: "What should I train today?"
AI: "Based on last session, let's focus on lower body:
     • Squats: 3 sets × 12 reps
     • Lunges: 3 sets × 10 reps each leg
     • Plank: 3 sets × 45 seconds

     Ready to start?"
```

---

## 📊 What the AI Sees

### YOLO Keypoints (17 detected)

```
1. Nose
2-3. Left Eye, Right Eye
4-5. Left Ear, Right Ear
6-7. Left Shoulder, Right Shoulder
8-9. Left Elbow, Right Elbow
10-11. Left Wrist, Right Wrist
12-13. Left Hip, Right Hip
14-15. Left Knee, Right Knee
16-17. Left Ankle, Right Ankle
```

### AI Analysis Metrics

- ✅ **Joint Angles** - Knee, elbow, hip flexion
- ✅ **Body Alignment** - Shoulder-hip-knee-ankle line
- ✅ **Movement Depth** - Squat depth, push-up range
- ✅ **Error Detection** - Knee valgus, back arch, etc.
- ✅ **Quality Scoring** - A/B/C/D grade per rep

---

## 🛠️ Configuration

### Adjust Performance

**Lower cost/latency**:
```python
# vision_agent_demo.py
llm=gemini.Realtime(fps=1),  # 1 frame per second
```

**Higher accuracy**:
```python
llm=gemini.Realtime(fps=10),  # 10 frames per second
device="cuda"  # GPU acceleration for YOLO
```

### Customize AI Behavior

Edit `vision_assistant.md` to change:
- Coaching style (strict/encouraging/technical)
- Exercise focus (strength/cardio/flexibility)
- Feedback verbosity (concise/detailed)

### Use OpenAI Instead of Gemini

```python
# vision_agent_demo.py
from vision_agents.plugins import openai

llm=openai.Realtime(fps=3),
```

---

## 📁 Project Structure

```
vision-agent-real-demo/
├── vision_agent_demo.py      # Main entry point
├── vision_assistant.md        # AI coaching instructions (18KB knowledge base)
├── pyproject.toml             # Dependencies
├── .env.example               # API key template
│
├── docs/
│   ├── README_CN.md           # Chinese documentation
│   ├── QUICKSTART.md          # Quick start guide
│   ├── TROUBLESHOOTING.md     # Common issues
│   └── images/                # Screenshots and demos
│
├── scripts/
│   ├── run.sh                 # Start script (macOS/Linux)
│   ├── run.bat                # Start script (Windows)
│   └── setup.sh               # Setup script
│
└── tests/
    └── test_setup.py          # Environment checker
```

---

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### Areas for Improvement

- 🎨 **Add AR visualization** - Draw skeleton overlay on video
- 🏃 **More exercises** - Add burpees, pull-ups, yoga poses
- 🌍 **Internationalization** - Support more languages
- 📱 **Mobile app** - iOS/Android native apps
- 🎯 **Custom training plans** - Weekly programs, goals
- 📊 **Progress tracking** - Save history, show improvement

### How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guidelines.

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.

---

## 🙏 Acknowledgments

- **[GetStream/Vision-Agents](https://github.com/GetStream/Vision-Agents)** - Official framework
- **[Ultralytics YOLO](https://github.com/ultralytics/ultralytics)** - Pose detection model
- **[Google Gemini](https://ai.google.dev/)** - Multimodal AI
- **[Stream](https://getstream.io/)** - Real-time video infrastructure

---

## 📞 Support

- 📖 **Documentation**: [docs/](./docs/)
- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/MindDock/vision-agent-real-demo/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/MindDock/vision-agent-real-demo/discussions)
- 📧 **Email**: support@minddock.com

---

## 🌟 Star History

If you find this project useful, please consider giving it a star! ⭐

[![Star History Chart](https://api.star-history.com/svg?repos=MindDock/vision-agent-real-demo&type=Date)](https://star-history.com/#MindDock/vision-agent-real-demo&Date)

---

## 📈 Roadmap

- [x] Core fitness coaching (5 exercises)
- [x] Real-time pose detection
- [x] Voice feedback system
- [ ] AR skeleton visualization
- [ ] Progress tracking dashboard
- [ ] Custom workout plans
- [ ] Mobile app (iOS/Android)
- [ ] Multi-language support
- [ ] Social features (share workouts)
- [ ] Advanced analytics

---

<p align="center">
  <strong>Built with ❤️ by <a href="https://github.com/MindDock">MindDock</a></strong>
</p>

<p align="center">
  <sub>Powered by Vision-Agents • YOLO • Gemini • Stream</sub>
</p>
