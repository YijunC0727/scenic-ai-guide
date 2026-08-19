# 广州鲁迅纪念馆 · 鲁迅数字人（对话大脑）

面向广州鲁迅纪念馆的**具身智能**项目——机器人的「AI 大脑」。游客可跟「鲁迅」语音对话，也可切换讲解员模式了解场馆。

本仓库负责软件核心链路：**意图理解 → 查询改写 → 知识检索 → Prompt 拼接 → LLM 生成**，语音 I/O（ASR/TTS）由机器人硬件层处理。

## 项目阶段

1. **知识库构建** — 鲁迅作品/生平/场馆/语录/人设 5 域语料向量化入库（348 条 / 399 chunks）
2. **对话管线** — RAG 全链路 + 讲解员 / 鲁迅数字人双模式自动切换
3. **鲁棒性** — 4 层越界防护 + 幻觉检测 + 一致性校验 + 质量守卫
4. **API 化部署** — FastAPI 接口服务，机器人「ASR → `/chat` → TTS」直接对接

## 技术栈

| 层 | 选型 |
|----|------|
| LLM | DeepSeek 云端 API（`deepseek-v4-flash`，thinking=disabled）|
| Embedding | `BAAI/bge-small-zh-v1.5`（~91MB，本地）|
| 向量库 | ChromaDB（本地持久化）|
| 检索 | sentence-transformers + 多子查询合并去重 |
| 服务 | FastAPI + uvicorn（默认 `0.0.0.0:8000`）|
| 语言 | Python 3.12 |

## 目录结构

```
scenic-ai-guide/
├── scripts/
│   ├── api_server.py          # 阶段四：FastAPI 服务（机器人对接入口）
│   ├── rag_pipeline.py        # RAG 全链路 + 质量守卫
│   ├── ingest.py              # 数据入库（重建向量库）
│   ├── pack_offline.py        # 三件套离线资源打包
│   ├── start.bat              # Windows 一键启动
│   └── bge-small-zh-v1.5/     # BGE 模型（gitignored，来自资源包）
├── data/processed/            # 5 域知识库 JSON（gitignored）
├── chroma_db/                 # 向量库（gitignored）
├── docs/                      # 部署指南 / 接口协议 / 各阶段方案
├── prompts/                   # 双模式 System Prompt
├── requirements.txt           # 锁定版本依赖
└── .env.example               # 环境变量模板
```

## 快速开始

### 0. 前置

- Python 3.12（实测 3.12.1）
- git

### 1. 获取代码 + 三件套资源

```bash
git clone https://github.com/zhangjiaxin13553-source/scenic-ai-guide.git
cd scenic-ai-guide
```

> ⚠️ **代码仓库不包含三件套离线资源**（BGE 模型 / `chroma_db/` / `data/processed/`，均已 gitignore）。
> 换机部署前，先从团队分发处取得 `releases/offline_resources.zip`，解压后按包内 `README.txt` 放置：
>
> | 包内路径 | 放置到 |
> |----------|--------|
> | `bge-small-zh-v1.5/` | `scripts/bge-small-zh-v1.5/` |
> | `chroma_db/` | 项目根目录 |
> | `data/processed/` | 项目根目录 |
>
> 若某台机器已具备三件套，可自行生成资源包：`python scripts/pack_offline.py`

### 2. 安装依赖

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置 API Key

```bash
cp .env.example .env            # Windows: copy .env.example .env
# 编辑 .env，填入 LLM_API_KEY（DeepSeek 密钥，勿提交 git）
```

### 4. 启动

```bash
# Windows 一键启动（校验环境 + 装依赖 + 校验资源 + 启动服务）
scripts\start.bat

# 或手动启动
python scripts/api_server.py    # 默认 0.0.0.0:8000
```

### 5. 验证

```bash
curl http://localhost:8000/health
```

返回 `"status":"ok"` 即就绪。**首次加载约 1 分钟**（实测 77s，BGE 模型 + ChromaDB），建议机器人上电后先请求一次 `/health` 预热。

## 接口

机器人对接契约详见 [docs/deployment-guide.md](docs/deployment-guide.md)。服务启动后访问 `http://localhost:8000/docs` 有交互式接口文档。

## 在线体验 Demo

`space/` / `scripts/gradio_app.py` 是可独立部署的在线体验 Demo（Gradio 界面，讲解员 / 鲁迅双模式 + 调试面板）。三条部署路线：

| 路线 | 公网可达 | 国内访问 | 说明 |
|------|---------|---------|------|
| **云服务器（推荐）** | ✅ 稳定 IP | ✅ 快 | 见 [docs/cloud-server-deploy.md](docs/cloud-server-deploy.md)，一键脚本 `scripts/deploy_cloud.sh` |
| Render 免费档 | ✅ | 🟡 一般 | 见 [docs/render-deploy.md](docs/render-deploy.md)，免费但会休眠、512MB 易 OOM |
| HuggingFace Spaces | ✅ | 🟡 | 免费 Gradio Space 已收 PRO（$9/月），见 [docs/hf-spaces-deploy.md](docs/hf-spaces-deploy.md) |

> ⚠️ `gradio --share` 临时链接在墙内**连不上**（frpc 无法直连美国中转服务器），不建议作为交付链接。

三件套资源（BGE 模型 / 向量库 / 知识库）与 DeepSeek API Key 均**不进 git**：
- 云服务器 / Render 冷启动自动下载 BGE 模型，向量库随 `space/chroma_db/` 提交（约 3MB）；
- API Key 通过环境变量（`LLM_API_KEY`）注入，**不写入代码**。

## 团队

| 成员 | 阶段四职责 |
|------|-----------|
| 张嘉欣 | 组长 · API Owner（`api_server.py` + 接口协议）|
| 花敬皓 | Core Dev（环境固化 + 打包）|
| 窦一禾 | 离线资源打包 |
| 陈奕君 | 机器人对接文档 + 演示脚本 |
| 杜佳琳 | 部署测试 + checklist |
