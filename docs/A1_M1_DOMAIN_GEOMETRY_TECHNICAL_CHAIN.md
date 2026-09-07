# A1/M1 完整技术链：领域模型与几何纯函数

状态：设计完成，尚未实现  
目标文件：`coach/models.py`、`coach/geometry.py`、`tests/test_geometry.py`  
上游基线：[方案 A 技术路线](./SCHEME_A_TECHNICAL_ROADMAP.md)  
运行基线：Python `>=3.13,<3.14`

## 1. 本阶段目标

A1/M1 建立确定性运动内核的最小可信地基，把 YOLO 的数组输出转换为稳定、可验证、与 GUI/网络/GPU 无关的领域语言。

本阶段完成以下能力：

1. 固化 COCO Pose 17 个关键点的索引和人体左右语义。
2. 定义不可变的 `Keypoint`、`PoseSample` 和几何测量结果。
3. 提供关节夹角、像素等价距离、身体尺度归一化距离和水平镜像纯函数。
4. 明确传播缺点、低置信度、零长度向量和零参考尺度，不用 `0` 或 `NaN` 假装有效结果。
5. 使用完全合成的关键点构造单元测试，不导入 YOLO、不加载模型、不访问摄像头。

完成后形成如下技术链：

```text
YOLO 原始结果（A2 才接入）
          ↓ adapter：索引映射、坐标归一化、缺点转 None
PoseSample（本阶段定义）
          ↓ geometry：有效性门控 + 纵横比修正
ScalarMeasurement
          ├─ VALID(value)
          └─ INVALID(reason, invalid_points)
                    ↓
MotionFeatures / Calibration / ExerciseFSM（A2–A4 消费）
```

## 2. 范围边界

### 2.1 本阶段包含

- 单人、单帧的姿态数据契约。
- COCO 17 点索引。
- 归一化图像坐标和原始帧尺寸。
- 角度和距离的纯函数。
- 水平镜像的坐标变换与不变量测试。
- 缺点、低置信度和退化几何的结构化失败。
- 合成数据测试、导入依赖检查和静态质量检查。

### 2.2 本阶段不包含

- YOLO `Results/Boxes/Keypoints` 解析；归入 A2/M2 adapter。
- 多人主目标选择、`person_id` 跟踪；归入 A2/M2。
- EMA、移动中值、短时缺点填补；归入 A2/M2。
- 个人校准和动作阈值；归入 A3/M3。
- 深蹲阶段、计数、质量规则；归入 A4/M4。
- `CoachEvent`、反馈节流、Qwen 桥接和 UI。

特别注意：“缺点传播”不等于“缺点插值”。A1 只诚实地返回不可测；A2 才能根据时间序列决定是否短暂沿用历史值。

## 3. 设计原则

### 3.1 两类失败分开处理

构造领域对象时遇到结构错误，立即抛出 `ValueError`：

- 关键点数量不是 17。
- 帧宽或帧高小于 1。
- 坐标、置信度或时间戳不是有限数。
- 归一化坐标不在 `[0, 1]`。
- 置信度不在 `[0, 1]`。

运行时观测不足不抛异常，而返回无效测量：

- 某关键点为 `None`。
- 关键点置信度低于阈值。
- 构成角度的向量长度为零。
- 归一化距离的参考尺度为零。

这样可以区分“程序传错数据”和“摄像头暂时看不清”。

### 3.2 不用哨兵数值

- 缺失关键点只能用 `None`，不能用 `(0, 0)`。
- 无效角度不能返回 `0.0`，因为 `0°` 本身是合法角度。
- 不返回 `NaN`；`NaN` 会污染比较、序列化和 FSM。
- 所有有效标量必须是有限 `float`。

### 3.3 不混淆三种坐标

| 坐标 | 表示 | 用途 |
|---|---|---|
| 归一化图像坐标 | `x_norm=x_px/width`、`y_norm=y_px/height` | 存储、跨分辨率传递 |
| 像素等价坐标 | `x=x_norm*width`、`y=y_norm*height` | 正确计算角度和欧氏距离 |
| 身体尺度归一化距离 | 目标像素距离 / 参考身体像素距离 | 跨远近、跨分辨率比较 |

不能直接在 `(x_norm, y_norm)` 上算角度。对于 16:9 图像，x 和 y 使用不同缩放，直接计算会扭曲夹角。几何函数必须先恢复像素等价坐标。

### 3.4 左右是人体解剖语义

`LEFT_SHOULDER` 永远表示被检测者的左肩，不表示画面的左侧。水平镜像只执行 `x' = 1 - x`，不交换 `LEFT_*` 和 `RIGHT_*` 索引。

## 4. `coach/models.py` 设计

### 4.1 COCO 17 点索引

使用 `IntEnum`，值必须与 YOLO COCO Pose 输出一致：

| 值 | 枚举名 | 中文 |
|---:|---|---|
| 0 | `NOSE` | 鼻子 |
| 1 | `LEFT_EYE` | 左眼 |
| 2 | `RIGHT_EYE` | 右眼 |
| 3 | `LEFT_EAR` | 左耳 |
| 4 | `RIGHT_EAR` | 右耳 |
| 5 | `LEFT_SHOULDER` | 左肩 |
| 6 | `RIGHT_SHOULDER` | 右肩 |
| 7 | `LEFT_ELBOW` | 左肘 |
| 8 | `RIGHT_ELBOW` | 右肘 |
| 9 | `LEFT_WRIST` | 左腕 |
| 10 | `RIGHT_WRIST` | 右腕 |
| 11 | `LEFT_HIP` | 左髋 |
| 12 | `RIGHT_HIP` | 右髋 |
| 13 | `LEFT_KNEE` | 左膝 |
| 14 | `RIGHT_KNEE` | 右膝 |
| 15 | `LEFT_ANKLE` | 左踝 |
| 16 | `RIGHT_ANKLE` | 右踝 |

附加常量：

```python
COCO_KEYPOINT_COUNT = 17
DEFAULT_MIN_CONFIDENCE = 0.50
GEOMETRY_EPSILON = 1e-9
```

### 4.2 `Keypoint`

建议接口：

```python
@dataclass(frozen=True, slots=True)
class Keypoint:
    x: float             # 0..1，按帧宽归一化
    y: float             # 0..1，按帧高归一化
    confidence: float    # 0..1
```

`__post_init__` 负责验证有限性和范围。对象不可变，避免某个下游函数意外修改共享帧。

### 4.3 `PoseSample`

建议接口：

```python
@dataclass(frozen=True, slots=True)
class PoseSample:
    timestamp_s: float
    frame_id: int
    person_id: str
    keypoints: tuple[Keypoint | None, ...]
    frame_width: int
    frame_height: int
    mirrored: bool = False

    def point(self, index: CocoKeypoint) -> Keypoint | None: ...
```

约束：

- `keypoints` 必须恰好 17 项，槽位与 `CocoKeypoint` 一一对应。
- `timestamp_s` 使用单调时钟的秒值；A1 只验证有限性，不验证跨帧递增。
- `frame_id >= 0`，`person_id` 去除首尾空白后不能为空。
- `frame_width`、`frame_height` 为正整数。
- `mirrored` 描述当前坐标是否已相对传感器画面水平翻转，不改变关键点解剖标签。
- 不保存 NumPy 数组、YOLO 对象、Tk 图像或设备句柄。

### 4.4 测量状态与结果

建议定义：

```python
class MeasurementStatus(StrEnum):
    VALID = "valid"
    MISSING_KEYPOINT = "missing_keypoint"
    LOW_CONFIDENCE = "low_confidence"
    ZERO_LENGTH_VECTOR = "zero_length_vector"
    ZERO_REFERENCE_SCALE = "zero_reference_scale"


@dataclass(frozen=True, slots=True)
class ScalarMeasurement:
    value: float | None
    status: MeasurementStatus
    required_points: tuple[CocoKeypoint, ...]
    invalid_points: tuple[CocoKeypoint, ...] = ()

    @property
    def is_valid(self) -> bool: ...
```

不变量：

- `status == VALID` 时 `value` 必须是有限数，`invalid_points` 必须为空。
- 非 `VALID` 时 `value is None`。
- `invalid_points` 按索引升序排列，测试和日志才具有确定性。
- `required_points` 保留测量来源，方便后续可见性提示和调试。

状态优先级固定为：

```text
MISSING_KEYPOINT
    > LOW_CONFIDENCE
    > ZERO_LENGTH_VECTOR / ZERO_REFERENCE_SCALE
    > VALID
```

例如一个角度既缺少脚踝、又有低置信度膝盖时，返回 `MISSING_KEYPOINT`，同时只在 `invalid_points` 中报告缺失槽位。调用方修复最高优先级问题后再得到下一状态。

## 5. `coach/geometry.py` 设计

该模块只允许导入 Python 标准库和 `coach.models`。禁止导入 `numpy`、`cv2`、`av`、`ultralytics`、Tkinter、Vision-Agents 或任何网络库。

### 5.1 公共 API

```python
def angle_degrees(
    pose: PoseSample,
    first: CocoKeypoint,
    vertex: CocoKeypoint,
    third: CocoKeypoint,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> ScalarMeasurement: ...


def pixel_distance(
    pose: PoseSample,
    first: CocoKeypoint,
    second: CocoKeypoint,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> ScalarMeasurement: ...


def normalized_distance(
    pose: PoseSample,
    first: CocoKeypoint,
    second: CocoKeypoint,
    reference_first: CocoKeypoint,
    reference_second: CocoKeypoint,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> ScalarMeasurement: ...


def mirror_horizontal(pose: PoseSample) -> PoseSample: ...
```

### 5.2 公共参数约束

- `min_confidence` 必须是有限数且在 `[0, 1]`，否则抛 `ValueError`。
- 重复索引是允许输入，但可能形成零长度向量或零参考尺度，并返回结构化无效结果。
- 函数不得修改 `pose`，不得读取时间、环境变量、文件或全局可变状态。
- 相同输入必须得到逐字段相同的输出。

### 5.3 关键点门控

三个几何函数共用一个私有纯函数：

```python
def _resolve_points(
    pose: PoseSample,
    indices: tuple[CocoKeypoint, ...],
    min_confidence: float,
) -> tuple[tuple[Keypoint, ...] | None, ScalarMeasurement | None]: ...
```

处理顺序：

1. 收集值为 `None` 的索引；存在则返回 `MISSING_KEYPOINT`。
2. 收集 `confidence < min_confidence` 的索引；存在则返回 `LOW_CONFIDENCE`。
3. 所有点合格后才进入几何计算。

置信度恰好等于阈值视为有效，即判定条件是 `confidence >= min_confidence`。

### 5.4 像素等价转换

```python
x_px = point.x * pose.frame_width
y_px = point.y * pose.frame_height
```

无需四舍五入，保留浮点值。它不是为了恢复原始整数像素，而是消除宽高分别归一化造成的纵横比畸变。

### 5.5 角度算法

`angle_degrees(first, vertex, third)` 的顶点是第二个参数：

```text
u = first_px - vertex_px
v = third_px - vertex_px
denominator = norm(u) * norm(v)
```

若任一向量长度 `<= GEOMETRY_EPSILON`，返回 `ZERO_LENGTH_VECTOR`。

有效时：

```python
cosine = dot(u, v) / denominator
cosine = min(1.0, max(-1.0, cosine))
angle = degrees(acos(cosine))
```

必须钳制 cosine，避免浮点误差把近似共线结果推到 `[-1, 1]` 之外。返回范围为闭区间 `[0.0, 180.0]`。

### 5.6 像素距离

`pixel_distance` 在像素等价坐标上使用 `math.hypot(dx, dy)`。它主要用于调试和实现 `normalized_distance`，不直接作为跨用户动作阈值。

两点重合时像素距离 `0.0` 是有效值；只有角度向量或参考身体尺度为零时才是退化几何。

### 5.7 身体尺度归一化距离

定义：

```text
normalized = distance(first, second)
             / distance(reference_first, reference_second)
```

示例：膝间距除以踝间距、腕到肩距离除以肩宽。结果是无单位比值，因此对分辨率和人物整体远近缩放不敏感。

处理规则：

1. 一次性门控四个所需槽位；重复索引在 `required_points` 中只保留第一次出现的顺序。
2. 目标距离为零允许返回 `0.0`。
3. 参考距离 `<= GEOMETRY_EPSILON` 返回 `ZERO_REFERENCE_SCALE`。
4. A1 不提供隐式默认参考点；调用方必须显式选择符合动作和视角的身体尺度。

### 5.8 水平镜像

对每个非空关键点执行：

```python
Keypoint(x=1.0 - point.x, y=point.y, confidence=point.confidence)
```

同时把 `PoseSample.mirrored` 取反，其他字段保持不变。`None` 仍为 `None`，17 个槽位顺序不变。

镜像不变量：

- 角度不变。
- 像素距离不变。
- 身体尺度归一化距离不变。
- 连续镜像两次恢复原对象；浮点比较使用容差。

## 6. 缺点与低置信度传播矩阵

| 输入情况 | 角度 | 像素距离 | 归一化距离 | 镜像 |
|---|---|---|---|---|
| 所需点为 `None` | `MISSING_KEYPOINT` | 同左 | 同左 | 原槽位保持 `None` |
| 所需点置信度低 | `LOW_CONFIDENCE` | 同左 | 同左 | 坐标和置信度原样镜像 |
| 非相关点缺失 | 不影响 | 不影响 | 不影响 | 保持缺失 |
| 角度边相邻点重合 | `ZERO_LENGTH_VECTOR` | 可返回 `0.0` | 视参考尺度而定 | 正常 |
| 参考点重合 | 不适用 | 可返回 `0.0` | `ZERO_REFERENCE_SCALE` | 正常 |

本阶段不做以下“便利处理”：

- 不自动改用身体另一侧关键点。
- 不自动降低置信度阈值。
- 不从上一帧补点。
- 不对无效测量返回默认角度。

这些决策会改变动作语义，必须由后续视角选择器、平滑器或 FSM 显式完成。

## 7. `tests/test_geometry.py` 设计

测试框架使用标准库 `unittest`，与现有测试一致。所有夹具均为合成对象。

### 7.1 合成夹具

测试文件提供私有辅助函数：

```python
def kp(x: float, y: float, confidence: float = 1.0) -> Keypoint: ...

def pose_with(
    points: Mapping[CocoKeypoint, Keypoint | None],
    *,
    width: int = 640,
    height: int = 480,
) -> PoseSample: ...
```

`pose_with` 先生成长度为 17 的全 `None` tuple，再替换指定槽位。测试不得从图片、JSON、NumPy 或 YOLO 创建夹具。

### 7.2 领域模型测试

至少包含：

1. `CocoKeypoint` 的 17 个值与 COCO 顺序完全一致。
2. 合法 `Keypoint` 和 `PoseSample` 可构造，且不可变。
3. 16/18 个关键点被拒绝。
4. `None` 是合法槽位。
5. `NaN`、`inf`、越界坐标和越界置信度被拒绝。
6. 非正帧尺寸、负 `frame_id` 和空 `person_id` 被拒绝。
7. `ScalarMeasurement` 的有效/无效不变量不可被破坏。

### 7.3 角度边界测试

至少包含：

| 用例 | 期望 |
|---|---:|
| 三点成直线、顶点在中间 | `180°` |
| 两条射线同方向 | `0°` |
| 水平与垂直射线 | `90°` |
| 非正方形帧中的已知直角 | 仍为 `90°` |
| 接近共线的浮点输入 | 有限且在 `[0,180]` |
| 第一/第三点与顶点重合 | `ZERO_LENGTH_VECTOR` |

角度断言使用 `assertAlmostEqual(..., places=7)` 或绝对容差 `1e-7`，不直接比较一般浮点结果。

### 7.4 镜像测试

1. 任意姿态镜像后 `x'=1-x`，y、置信度和索引不变。
2. 缺失槽位仍然缺失。
3. 镜像前后角度相等。
4. 镜像前后像素距离和归一化距离相等。
5. 镜像两次恢复原始姿态，`mirrored` 恢复原值。

### 7.5 归一化距离测试

1. 目标距离为参考距离一半时返回 `0.5`。
2. 所有坐标整体平移后结果不变。
3. 同比例放大人物骨架后结果不变。
4. 换用不同分辨率但保持相同像素几何比例时结果不变。
5. 目标两点重合时有效返回 `0.0`。
6. 参考两点重合时返回 `ZERO_REFERENCE_SCALE`。

### 7.6 缺点和置信度测试

1. 角度任一点缺失时返回 `MISSING_KEYPOINT` 和准确槽位。
2. 归一化距离的目标点或参考点缺失时传播失败。
3. 非相关槽位缺失不影响测量。
4. 置信度低于 `0.5` 无效，等于 `0.5` 有效。
5. 自定义阈值生效。
6. 同时存在缺点和低置信度时，缺点状态优先。
7. 无效结果的 `value is None`，且从不产生 `NaN`。

## 8. 实施顺序

### M1.1：领域类型

修改 `coach/models.py`：

1. 增加 COCO 枚举和常量。
2. 实现 `Keypoint`、`PoseSample`。
3. 实现 `MeasurementStatus`、`ScalarMeasurement`。
4. 只加入结构验证，不加入运动业务规则。

完成门：模型测试通过，模块仅使用标准库。

### M1.2：有效性门控和基础距离

修改 `coach/geometry.py`：

1. 实现阈值验证与 `_resolve_points`。
2. 实现像素等价坐标转换。
3. 实现 `pixel_distance`。

完成门：缺点、低置信度、相同点和非正方形帧测试通过。

### M1.3：角度、归一化距离和镜像

继续修改 `coach/geometry.py`：

1. 实现带 cosine 钳制的 `angle_degrees`。
2. 实现显式参考尺度的 `normalized_distance`。
3. 实现 `mirror_horizontal`。

完成门：角度边界、镜像不变量、零向量和零参考尺度通过。

### M1.4：质量门禁

新增并完成 `tests/test_geometry.py`，执行全部质量检查。A1/M1 不修改 `agent_local.py`、`agent_local_agent.py`，也不接入真实摄像头。

## 9. 验收命令

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_geometry -v

.venv/bin/ruff check --cache-dir /tmp/coach-ruff-cache \
  coach/models.py coach/geometry.py tests/test_geometry.py

.venv/bin/black --check \
  coach/models.py coach/geometry.py tests/test_geometry.py

PYTHONPYCACHEPREFIX=/tmp/coach-pycache .venv/bin/python -m compileall -q \
  coach/models.py coach/geometry.py tests/test_geometry.py
```

额外的依赖隔离检查：

```bash
rg -n "numpy|cv2|ultralytics|torch|tkinter|aiohttp|websocket|vision_agents" \
  coach/models.py coach/geometry.py
```

期望无匹配。测试模块可以导入 `unittest`，但不得导入任何模型、GUI、网络或 GPU 库。

## 10. 最终验收清单

- [ ] `CocoKeypoint` 恰好覆盖 COCO 17 点，索引无偏移。
- [ ] 左右标签明确为人体解剖方向。
- [ ] `PoseSample` 恰好包含 17 个 `Keypoint | None` 槽位。
- [ ] 坐标契约、帧尺寸和纵横比修正有测试保护。
- [ ] `angle_degrees` 覆盖 `0°`、`90°`、`180°` 和近共线输入。
- [ ] 水平镜像不改变角度和距离结果。
- [ ] `normalized_distance` 使用显式身体参考尺度。
- [ ] 零长度角度向量返回 `ZERO_LENGTH_VECTOR`。
- [ ] 零参考尺度返回 `ZERO_REFERENCE_SCALE`。
- [ ] 缺点返回 `MISSING_KEYPOINT`，不返回伪数值。
- [ ] 低置信度返回 `LOW_CONFIDENCE`，阈值边界行为确定。
- [ ] 所有无效测量 `value is None`，所有有效测量为有限数。
- [ ] 纯函数没有 I/O、时钟、随机数或全局可变状态。
- [ ] `coach/models.py`、`coach/geometry.py` 不依赖 GUI、网络、YOLO、NumPy 或 GPU。
- [ ] 合成测试、Ruff、Black 和编译检查全部通过。

## 11. 向 A2/M2 的交付契约

A1/M1 交付的不是动作识别，而是 A2 可以稳定依赖的边界：

```text
A2 YOLO Adapter 必须输出合法 PoseSample
    ├─ 超界/非有限原始点：由 adapter 丢弃或按明确容差处理
    ├─ 未检测到的点：写入 None
    ├─ 不得用上一帧数据冒充当前帧
    └─ 不得把画面左右改写成人体左右

A2 Smoothing 只消费 ScalarMeasurement / PoseSample
    ├─ 可按时间序列短暂容忍缺点
    ├─ 不可把无效值变成 0
    └─ 必须保留测量状态供 FSM 和 UI 判断可见性
```

只有本页全部验收项通过，才能开始 A2/M2 的 YOLO adapter、人物跟踪和平滑；否则后续计数误差会无法区分是模型、坐标、几何还是状态机造成的。
