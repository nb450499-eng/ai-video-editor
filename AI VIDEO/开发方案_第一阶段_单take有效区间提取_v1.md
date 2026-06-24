# 开发方案 · 第一阶段：单 take 有效区间提取（窄垂直切片）

> 配套设计文档：《AI 有效镜头区间定位与剪映自动剪辑系统_更新技术方案_v2.0.docx》
> 本文是**可执行开发方案**，由 codex 照此实现。Claude 只负责出方案，操作由 codex 执行。
> 版本 v1 · 2026-06-24

---

## 0. 本阶段的唯一目标与边界

**唯一交付物**：
> 输入一条 5–10 秒 take（+ 它的 shot_spec），输出经过截取复检的 `valid_window.json`：
> `source_in_ms / source_out_ms / event_timeline / confidence / grade / pass`，
> 并能解释「动作从哪开始、结果在哪出现、为什么去掉前后废片」；
> 当无可用区间时，正确输出拒绝 + 补拍请求。

**本阶段做**：标准化 → 技术信号 → 粗定位（Gemini）→ 精扫 → 窗口求解 → 截取复检 → 拒绝/补拍 → 中立 timeline.json + ffmpeg 预览。

**本阶段不做**（留接口/留到后续）：
- 跨 take 组内排序（listwise）、A/B/C/D 全量分级——本阶段单 take 只产 0–N 窗口即可。
- 剪映 / CapCut 草稿适配。
- Grounding DINO / SAM2 真实视觉跟踪——**只留接口 + 桩实现**。
- PostgreSQL、watchdog 目录监听、FastAPI 服务化、监控告警。
- 口播词级对齐与同步（sync_engine）——本阶段先不平移调速。

**判停红线**：步骤 4 的边界精度（Temporal IoU 中位数 ≥ 0.75，起点误差 ≤ 300ms，终点 ≤ 400ms）若不达标，**停下调参/调 prompt，不要往后做复检和输出**。

---

## 1. 技术选型（本阶段锁定）

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.12 | |
| Schema/校验 | Pydantic v2 | shot_spec、各 JSON 产物全部走 Pydantic 模型 |
| 媒体 | FFmpeg + ffprobe | 标准化、固定帧率代理、精确截取、预览 |
| 技术视觉 | OpenCV | sharpness/exposure/motion 等信号曲线 |
| 切镜检测 | PySceneDetect 0.7 | 仅用于识别真实切镜，防止跨镜头取窗口 |
| 视频语义主模型 | **Gemini 3.5 Flash（稳定版）** | 粗定位事件时间线 + 截取后复检 |
| 产品定位/跟踪 | Grounding DINO / SAM2 | **本阶段仅接口 + 桩**，返回占位值 |
| 存储 | SQLite + 本地 JSON | PoC 够用，不上 PG |
| 测试 | pytest + Golden Dataset | 真值集驱动验收 |
| 日志 | structlog | 记录模型版本、请求 ID、输入哈希（复现性） |

**Gemini 关键约束（必须遵守，否则漏快速动作）**：
- 调用视频理解时**显式指定剪辑区间**（只送候选区间，不送整条）。
- **显式设置自定义采样 FPS**，不要用默认约 1 FPS。
- 强制结构化输出（JSON schema 约束），字段见 §4。

---

## 2. 代码结构（本阶段实际落地的子集）

```
ai-clip/
├── manifest/
│   ├── schemas.py          # shot_spec / valid_window / take_analysis 的 Pydantic 模型
│   ├── loader.py           # 读取 manifest + 镜头文件夹
│   └── validator.py        # 输入契约校验
├── media/
│   ├── ffprobe.py          # 读元数据（分辨率/帧率/旋转/时长/VFR）
│   ├── normalize.py        # 生成固定30FPS代理；保留原始
│   └── frame_sampler.py    # 按区间+FPS抽帧（粗扫/精扫共用）
├── signals/
│   ├── sharpness.py        # sharpness(t)
│   ├── exposure.py         # exposure(t)
│   ├── motion.py           # global_motion(t) + subject_motion(t)
│   └── extract.py          # 汇总成一条带时间轴的信号曲线
├── temporal/
│   ├── proposal_generator.py   # 多尺度滑窗候选
│   ├── coarse_grounding.py     # Gemini 事件时间线（指定区间+FPS）
│   ├── fine_boundary_locator.py# 局部高FPS精扫+边界搜索
│   └── valid_window_solver.py  # window_score + 硬约束求解
├── vision/
│   ├── multimodal_client.py    # Gemini 封装（区间/FPS/结构化输出/重试/日志）
│   ├── product_detector.py     # 【桩】Grounding DINO 接口
│   └── object_tracker.py       # 【桩】SAM2 接口
├── selection/
│   ├── hard_filters.py     # 6.1 硬性淘汰规则
│   └── rejection.py        # 全失败→补拍请求
├── verification/
│   └── extracted_clip_qc.py# 截取后独立复检（不同路径）
├── timeline/
│   └── builder.py          # 输出中立 timeline.json
├── render/
│   └── ffmpeg_preview.py   # rough_cut.mp4 + captions.srt
├── reports/
│   ├── shot_report.py      # 单镜头窗口/淘汰原因
│   └── reshoot_report.py   # 补拍请求（定位到时间+问题）
├── eval/
│   ├── metrics.py          # IoU/边界误差/拒绝召回 等指标计算
│   └── run_eval.py         # 对真值集跑分
└── tests/
    ├── golden_windows/     # 真值样本
    ├── temporal_boundaries/
    └── rejection/
```

**隔离原则**：模型/格式相关代码不许漏进核心 `temporal/`；DINO/SAM2 桩与真实实现共用同一接口签名，后续替换零改动。

---

## 3. 数据契约（Pydantic 模型，先于一切代码定下来）

### 3.1 ShotSpec（输入，对应文档 §4）
```python
class Timing(BaseModel):
    pre_roll_ms: int
    post_roll_ms: int
    min_result_hold_ms: int
    max_speed_change: float = 1.08

class SyncPoint(BaseModel):
    voice_text: str
    visual_event: str

class ShotSpec(BaseModel):
    shot_id: str
    folder: str
    target_duration_ms: int
    voice_text: str
    role: str                      # product_demo / before_after / product_closeup ...
    required_states: list[str]
    required_events: list[str]     # 决定有效窗口必须覆盖哪些事件
    forbidden: list[str]
    timing: Timing
    sync_points: list[SyncPoint] = []
    product_refs: list[str] = []   # 本阶段可空
```

### 3.2 TakeAnalysis（中间产物，对应文档 10.1）
含 `technical`（blur/shake/exposure 比例）、`candidate_windows`、`event_timeline`。

### 3.3 ValidWindow（核心输出，对应文档 10.2）
```python
class ValidWindow(BaseModel):
    asset_id: str
    source_in_ms: int
    source_out_ms: int
    grade: Literal["A","B","C","D"]
    score: float
    event_coverage: float
    verification_passed: bool
    confidence: float
    reasons: list[str]
    rejected: bool = False
    reject_reason: str | None = None
```

> **codex 注意**：所有时间一律**整数毫秒**；分析在代理文件上做，最终截取从**原始素材**取帧。

---

## 4. 按步骤实现（每步 = 一个 PR + 验收门）

### 步骤 0 · 真值标注规范（无代码，但必须先做）
- 范围：1 个产品、5–8 个镜头文件夹、每文件夹 3–5 个 take。
- 每条 take 标注：`[source_in, source_out]` + `action_start / result_first_visible / result_hold_end`。
- 每条 take 可标 **0–N 个**可用窗口（含「无可用窗口」样本，用于验证拒绝）。
- 产物：`tests/golden_windows/*.json` + 一份《标注规范.md》。
- **验收**：≥ 20 条 take 真值入库，含 ≥ 3 条「应拒绝」样本。

### 步骤 1 · 输入契约 + 媒体标准化
- 实现 `manifest/schemas.py`（§3 全部模型）、`loader.py`、`validator.py`。
- `media/ffprobe.py` 读元数据；`normalize.py` 用 FFmpeg 生成固定 30FPS 代理，保留原始；`frame_sampler.py` 支持「指定区间 + 指定 FPS」抽帧。
- **验收**：任给一条 take，输出代理文件 + 元数据 JSON；frame_sampler 能按 [in,out]@12fps 正确取帧。

### 步骤 2 · 逐帧技术信号（轻量版先行）
- 实现 `sharpness/exposure/motion`，`signals/extract.py` 汇总成随时间曲线（**不是单一总分**）。
- `vision/product_detector.py`、`object_tracker.py` 仅留接口 + 桩：`product_visibility(t)`、`occlusion(t)` 返回固定占位（如 1.0/0.0）并标注 `is_stub=True`。
- **验收**：对一条 take 输出 4 条信号曲线图/数组；桩接口签名与真实版一致。

### 步骤 3 · 粗定位（Gemini 事件时间线）
- `proposal_generator.py`：多尺度滑窗 0.8/1.5/2.5/4s，每窗保留前后上下文；PySceneDetect 仅切真实转场，**不得**把一次连续动作拆成多镜头。
- `coarse_grounding.py` + `multimodal_client.py`：对候选区间调 Gemini，**指定区间 + 自定义 FPS**，强制返回：
```json
{
  "events": [{"name":"pull_starts","start_ms":1540,"end_ms":1690,"confidence":0.91}],
  "coarse_valid_window": {"start_ms":1350,"end_ms":3650},
  "missing_events": [],
  "forbidden_detected": []
}
```
- **验收（看这个数）**：粗定位**召回率** = 人工窗口落入某候选的比例 ≥ 90%（宁可多召回，别漏）。

### 步骤 4 · 精扫 + 窗口求解（边界精度，判停红线在此）
- `fine_boundary_locator.py`：仅对 1–4s 候选做 8–15FPS 抽帧；边界前后扩 300–600ms 后做二分/逐帧边界搜索。
- `valid_window_solver.py`：实现文档 §5.6 加权打分：
  `0.28*event_coverage + 0.18*action_completeness + 0.16*result_visibility + 0.12*product_visibility + 0.10*technical_quality + 0.08*duration_fit + 0.08*voice_sync − occlusion_penalty − idle_frame_penalty − forbidden_penalty − speed_change_penalty`
  （product_visibility/occlusion 来自桩，本阶段权重项照算但值为占位）。
- 硬约束：覆盖全部 required_events、不含 forbidden、动作前有前摇/后有结果停留、不以模糊/遮挡/未完成帧作首尾。
- **验收（红线）**：Temporal IoU 中位数 ≥ 0.75；起点误差中位 ≤ 300ms；终点 ≤ 400ms。**不达标即停，回到 §3/§4 调参，不许往后走。**

### 步骤 5 · 截取后独立复检 + 拒绝/补拍
- `verification/extracted_clip_qc.py`：FFmpeg **真截出**子片段，重新问模型「这 N 秒是否独立完整表达脚本镜头」；**必须与步骤 3 不同输入形态/判断路径**，避免同一错误被复述确认。
- `selection/hard_filters.py`：实现文档 §6.1 全部 reject 规则。
- `selection/rejection.py` + `reports/reshoot_report.py`：全失败时输出**定位到时间+问题**的补拍请求（参照文档 §6.2 格式）。
- 复检分流：通过→产出窗口；低置信度→人工候选（不自动用）；失败→回退第二候选；全失败→补拍。
- **验收**：无有效片段正确拒绝召回 ≥ 85%；合格窗口误杀率 ≤ 10%。

### 步骤 6 · 中立时间线 + 预览（不碰剪映）
- `timeline/builder.py` → `timeline.json`（文档 §8.1 格式）。
- `render/ffmpeg_preview.py` → `rough_cut.mp4` + `captions.srt`。
- **验收**：timeline.json 通过 Pydantic 校验；预览片首尾对齐 source_in/out。

### 步骤 7 · 评测闭环
- `eval/metrics.py` + `run_eval.py`：对真值集自动算 Top-1 可用率、Top-2 覆盖、Temporal IoU、起止误差、严重无效帧混入率、拒绝召回、误杀率。
- 锁定测试集**禁止**用于调 prompt/阈值。
- **验收**：一条命令产出对照报告 HTML/JSON。

---

## 5. 本阶段验收目标（PoC，均为工程目标非厂商承诺）

| 指标 | 目标 |
|---|---|
| 有效窗口 Top-1 可用率 | ≥ 85%（本阶段单 take，看窗口本身可用性）|
| Temporal IoU 中位数 | ≥ 0.75 |
| 起点误差中位 / 终点误差中位 | ≤ 300ms / ≤ 400ms |
| 严重无效帧混入率 | ≤ 5% |
| 无有效片段拒绝召回 | ≥ 85% |
| 合格窗口误杀率 | ≤ 10% |

达标 → 进入第二阶段（跨 take 组内选优 + 剪映适配）；
召回高但边界差 → 迭代精定位，不扩产；
150+ 镜头后 Top-2 仍不稳 → No-Go，回看素材规范与事件定义。

---

## 6. 风险与规避（本阶段相关项）

| 风险 | 规避 |
|---|---|
| Gemini 稀疏采样漏快速动作 | 强制指定区间 + 自定义 FPS，绝不依赖默认 1FPS |
| 模型幻觉时间戳 | FFmpeg 真截后**独立路径**复检 |
| 动作本身没拍到 | 硬拒绝 + 补拍请求，不强凑 |
| 桩值掩盖遮挡问题 | product/occlusion 桩明确标 is_stub，相关验收项标注「待真实模型」|
| 复现性差 | 记录模型版本/请求 ID/输入哈希 |

---

## 7. 给 codex 的开工顺序（一句话）

先定 §3 数据契约 → 步骤 0 真值 → 步骤 1/2 打底 → **步骤 3 看召回、步骤 4 看边界（红线）** → 过线才做 5/6/7。每步一个 PR，附该步验收数。
