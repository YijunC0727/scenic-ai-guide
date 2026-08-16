# 部署指南 + 接口协议（阶段四）

> 本文件是「对话大脑」与机器人控制层的**对接契约**，以及现场部署的操作手册。
> 机器人语音层只需要做三件事：**ASR → 调 `/chat` → TTS**，中间全部由本 API 承担。

---

## 1. 概览

| 项 | 值 |
|----|----|
| 服务入口 | `python scripts/api_server.py` |
| 默认地址 | `http://0.0.0.0:8000`（`0.0.0.0` 允许局域网/机器人访问） |
| 接口文档 | 启动后访问 `/docs`（FastAPI 自动生成，含交互式调试） |
| 技术栈 | FastAPI + uvicorn，复用 `rag_pipeline.py` 全链路 |
| 依赖 LLM | DeepSeek 云端 API（v4-flash，thinking=disabled） |

接口一览：

| 接口 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康检查（机器人启动时探活 + 预热） |
| `/chat` | POST | 单轮对话（机器人主调用） |
| `/reset` | POST | 清空对话历史（切游客 / 结束一轮） |

---

## 2. 快速启动

```bash
cd scenic-ai-guide
# 首次需装依赖（fastapi/uvicorn 为本阶段新增）
pip install fastapi uvicorn

# 启动（默认 0.0.0.0:8000）
python scripts/api_server.py
# 指定端口
python scripts/api_server.py --port 8000
```

**注意**：首次调用 `/chat` 或 `/health` 会触发 RAG 全链路加载（BGE 模型 + ChromaDB + sentence-transformers），
实测约 **1 分钟**（77s）。建议机器人上电后先请求一次 `/health` 完成预热，避免第一句对话卡顿。

---

## 3. 接口协议（机器人对接契约）

### 3.1 `GET /health` — 健康检查

用于机器人启动时探活，也用于预热。会尝试加载 pipeline 并返回真实状态。

响应示例（就绪）：

```json
{
  "status": "ok",
  "model_loaded": true,
  "error": null,
  "circuit": { "is_open": false, "fail_count": 0, "fail_threshold": 5, "reset_timeout": 60 }
}
```

响应示例（加载失败）：

```json
{ "status": "error", "model_loaded": false, "error": "<具体异常信息>", "circuit": null }
```

- `status` 为 `ok` 才可正常对话；为 `error` 时机器人应提示「服务不可用」并重试。
- `circuit.is_open == true` 表示 LLM 熔断器已打开（连续失败触发的冷却中），此时对话会走兜底话术。

### 3.2 `POST /chat` — 单轮对话（核心）

请求：

```jsonc
{
  "text": "鲁迅先生，您为什么弃医从文？",   // 必填，ASR 识别出的文本
  "session_id": "tourist-001",              // 可选，多轮对话隔离用
  "force_mode": null,                       // 可选，"narrator" | "luxun" | null(自动)
  "include_debug": false                    // 可选，是否返回调试信息
}
```

响应（成功）：

```json
{
  "success": true,
  "reply": "……（鲁迅口吻回答）……",
  "intent": "luxun",
  "mode": "🎭 鲁迅数字人",
  "guard_status": "PASS",
  "latency_ms": 1800,
  "error": null,
  "debug": null
}
```

响应（兜底——接口不抛 5xx，永远返回可播报文本）：

```json
{
  "success": false,
  "reply": "这大约是什么缘故呢——我此刻竟想不起来了。你先问些别的罢。",
  "intent": "",
  "mode": "",
  "guard_status": "ERROR",
  "latency_ms": 120,
  "error": "pipeline 加载失败: ...",
  "debug": null
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `success` | 只要返回了可播报文本就为 `true`（兜底也算成功）。为 `false` 仅表示**服务级异常**，但 `reply` 仍是可播文本 |
| `reply` | **唯一必须交给 TTS 的字段**。任何情况下都非空 |
| `intent` | `narrator` / `luxun` / `ambiguous` / `reject_time` / `reject_irrelevant` |
| `mode` | 中文标签（给人看，机器人可忽略） |
| `guard_status` | 质量守卫判定：`PASS` / `WARN` / `AMEND` / `FALLBACK` / `N/A` / `ERROR` |
| `latency_ms` | 本问耗时，供延迟监控 |
| `error` | 仅 `success=false` 时非空 |

### 3.3 `POST /reset` — 清空历史

查询参数：`session_id`（可选）。

```
POST /reset                    → 清空全局单会话
POST /reset?session_id=tourist-001  → 清空指定会话
```

响应：`{ "success": true, "reset": "global" }` 或 `{ "success": true, "reset": "tourist-001", "existed": true }`

建议机器人**每接待一位新游客时调用一次**，避免上一游客的对话污染下一游客的上下文。

### 3.4 错误语义与兜底原则

**核心原则：`/chat` 永不返回 5xx 空响应。** 任何内部异常（LLM 失败、检索失败、检查器 bug）都会转成兜底文本，机器人 TTS 永远有词可播。

| 场景 | 机器人拿到的 `reply` |
|------|---------------------|
| LLM API 失败 / 超时 / 熔断 | 鲁迅口吻兜底：「这大约是什么缘故呢……你先问些别的罢。」 |
| 管线未加载 / 加载失败 | 同上 |
| 空输入（ASR 没识别出内容） | 「（请输入你的问题）」 |
| 时间越界 / 无关内容 | 由管线正常返回的越界/拒绝话术（`success=true`） |

**机器人侧唯一约定**：`reply` 非空就播报；`success=false` 仅作日志告警，不影响播报。

### 3.5 `session_id` 规则

- 缺省（`null`/不传）→ 全局单会话，历史共享（适合现场只有一个游客在聊）。
- 传入 `session_id` → 按会话隔离历史，不同游客互不干扰。
- 本轮 demo 主要单轮问答，若机器人控制层不便管理 session，**不传即可**，零心智负担。

### 3.6 超时约定

| 层 | 值 | 说明 |
|----|----|----|
| LLM 调用超时 | 30s | `llm_client.py` 内置，超时自动重试 + 兜底 |
| 熔断阈值 | 连续 5 次失败 | 触发后冷却 60s，期间走兜底 |
| 建议机器人读超时 | 10s | 超过则视为「服务慢」，可先播「请稍候」；但 `/chat` 内部不会因这个超时中断 |

---

## 4. 环境与依赖

| 组件 | 要求 |
|------|------|
| Python | 3.12（本机实测 3.12.1） |
| 核心依赖 | torch（CPU 即可）、transformers、chromadb、sentence-transformers、jieba、requests、python-dotenv、tqdm |
| 本阶段新增 | fastapi、uvicorn |
| 离线资源 | BGE 模型（`scripts/bge-small-zh-v1.5/`）+ `chroma_db/` + `data/processed/` |

> ⚠️ 三件套（模型/向量库/数据）与 `.env`（API Key）均不入 git，换机部署需手动搬运或重建。
> 完整依赖清单由花敬皓在阶段四固化（补全 `requirements.txt` 并锁版本）。

---

## 5. 常见故障排查

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| `/health` 返回 `error` | 模型文件缺失 / .env 未配 / 依赖缺失 | 检查 `scripts/bge-small-zh-v1.5/`、`.env` 的 `LLM_API_KEY`、`pip list` |
| `/chat` 一直返回兜底话术 | DeepSeek API 不可达 / 熔断已打开 | 检查设备能否访问 `api.deepseek.com`；看 `circuit.is_open` |
| 首问卡顿约 1 分钟 | 首次加载模型（实测 77s） | 启动后先调一次 `/health` 预热 |
| 中文乱码 | Windows 控制台 GBK | 启动前 `set PYTHONIOENCODING=utf-8`（脚本内部对 API 无影响） |
