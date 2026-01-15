# Troubleshooting Guide

## Common Issues and Solutions

### ⚠️ TimeoutError: Waiting for Track

**Error Message:**
```
TimeoutError: Timeout waiting for pending track: 2 (video) from user...
Waited 10.0s but WebRTC track_added with matching kind was never received.
```

**What is this?**
This is a known issue in the Vision-Agents SDK. The agent tries to publish a video track but times out.

**Important: This error can be IGNORED!**

**Reason:**
- The agent doesn't need to publish video (it doesn't have a camera)
- The agent only needs to RECEIVE user's video
- Audio track is successfully published
- This timeout doesn't affect core functionality

**Signs the Agent is Working:**
- ✅ Terminal shows: `✓ Agent successfully joined call`
- ✅ Browser automatically opens Stream video interface
- ✅ You can see your webcam feed
- ✅ You can hear AI voice greeting
- ✅ AI responds to your movements or speech

**Solutions:**

1. **Ignore and Continue** (Recommended)
   - If you see the ✅ signs above, everything works!

2. **Lower FPS to Reduce Load**
   ```python
   # vision_agent_demo.py
   llm=gemini.Realtime(fps=1),  # Change from 3 to 1
   ```

3. **Test Without YOLO**
   ```python
   # Comment out processors temporarily
   agent = Agent(
       edge=getstream.Edge(),
       agent_user=User(name="AI Fitness Coach"),
       instructions="Read @docs/COACHING_INSTRUCTIONS.md",
       llm=gemini.Realtime(fps=3),
       # processors=[  # Temporarily commented
       #     ultralytics.YOLOPoseProcessor(...)
       # ],
   )
   ```

---

## Other Common Issues

### 1. Gemini API Errors

**Error:** `429 Too Many Requests` or `API key invalid`

**Solutions:**
```bash
# Check API key
cat .env | grep GEMINI

# Visit https://ai.google.dev/ to check quota
# Or reduce FPS to lower request rate
```

### 2. Stream API Connection Failed

**Error:** `401 Unauthorized`

**Solutions:**
```bash
# Check Stream API keys
cat .env | grep STREAM

# Ensure keys are from https://getstream.io
# Check for extra spaces or quotes
```

### 3. Browser Doesn't Auto-Open

**Solution:**
- Look for URL in terminal output
- Manually copy to browser
- Format usually: `https://getstream.io/video/demos/join/...`

### 4. Camera Access Denied

**Solutions:**
1. Chrome: Settings → Privacy and security → Site settings → Camera
2. Allow `getstream.io` access
3. Refresh page
4. Close other apps using camera (Zoom, Teams, etc.)

### 5. YOLO Model Download Failed

**Error:** `Unable to download yolo11n-pose.pt`

**Solution:**
```bash
# Manual download
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolo11n-pose.pt

# Or use mirror if available
```

### 6. No Voice Feedback

**Checklist:**
- [ ] Browser volume enabled
- [ ] Microphone permission allowed
- [ ] Gemini API working
- [ ] Check terminal for errors

### 7. AI Can't See My Movements

**Possible Causes:**
1. **Poor lighting** - Increase light
2. **Wrong distance** - Stay 1.5-2 meters away
3. **Out of frame** - Ensure full body or upper body visible
4. **YOLO not running** - Check terminal for YOLO logs

**Test YOLO:**
```python
# Look for these in terminal
[INFO] YOLOPoseProcessor initialized
[INFO] Detected 17 keypoints
```

### 8. Agent Stuck/Frozen

**Solutions:**
1. Press `Ctrl+C` to stop
2. Wait 5-10 seconds for cleanup
3. Re-run `./scripts/run.sh`

### 9. High Memory Usage

**Solutions:**
- Lower FPS: `fps=1`
- Use smaller YOLO model (already using nano)
- Close other applications

### 10. High CPU Usage

**Cause:** YOLO pose detection is computationally intensive

**Solutions:**
```python
# Use GPU if available
device="cuda"

# Or reduce processing frequency
llm=gemini.Realtime(fps=1),
```

---

## Debugging Tips

### Enable Detailed Logging

```bash
# Set DEBUG level
export LOG_LEVEL=DEBUG
uv run python vision_agent_demo.py
```

### Test Individual Components

**Test 1: Stream Connection**
```bash
uv run python -c "from vision_agents.plugins import getstream; print('Stream OK')"
```

**Test 2: Gemini API**
```bash
uv run python -c "from vision_agents.plugins import gemini; print('Gemini OK')"
```

**Test 3: YOLO**
```bash
uv run python -c "from vision_agents.plugins import ultralytics; print('YOLO OK')"
```

### Check Network Connectivity

```bash
# Test Stream API
curl -H "Authorization: Bearer $STREAM_API_KEY" https://stream-io-api.com/api/v2/health

# Test Gemini
curl "https://generativelanguage.googleapis.com/v1/models?key=$GEMINI_API_KEY"
```

---

## Performance Optimization

### Lower Cost and Latency

```python
# vision_agent_demo.py
llm=gemini.Realtime(fps=1),  # Minimum FPS
```

### Improve Detection Accuracy

```python
# Use larger YOLO model
ultralytics.YOLOPoseProcessor(
    model_path="yolo11l-pose.pt",  # Large version
    device="cuda"  # GPU acceleration
)
```

### Balanced Configuration (Recommended)

```python
llm=gemini.Realtime(fps=3),  # Balance speed and cost
ultralytics.YOLOPoseProcessor(
    model_path="yolo11n-pose.pt",  # Nano version
    device="cpu"
)
```

---

## When to Seek Help

Contact us if you experience:

1. Agent completely fails to start
2. Browser shows white screen or error page
3. Stream API consistently returns 401/403
4. Gemini API has quota but still can't call

**Official Resources:**
- Vision-Agents Issues: https://github.com/GetStream/Vision-Agents/issues
- Stream Docs: https://getstream.io/video/docs/
- Gemini Docs: https://ai.google.dev/docs

---

## Quick Diagnostic Checklist

Run this test script:

```bash
uv run python tests/test_setup.py
```

You should see:
- ✓ Python version: Pass
- ✓ vision-agents: Pass
- ✓ STREAM_API_KEY: Pass
- ✓ GEMINI_API_KEY: Pass
- ✓ COACHING_INSTRUCTIONS.md: Pass

If all pass, the agent should work!

---

**Remember**: TimeoutError is a known issue. If other functionality works, you can ignore it!

---

## Platform-Specific Issues

### macOS

**Issue:** Permission denied for camera
**Solution:** System Preferences → Security & Privacy → Camera → Allow Terminal/Chrome

### Linux

**Issue:** V4L2 camera errors
**Solution:**
```bash
sudo apt install v4l-utils
v4l2-ctl --list-devices
```

### Windows

**Issue:** Script execution error
**Solution:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

For more help, see [GitHub Issues](https://github.com/MindDock/vision-agent-real-demo/issues)
