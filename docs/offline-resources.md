# 离线资源清单 — 三件套核验

> 阶段四 · 窦一禾 · 资源清单与校验
> 核对日期：2026-08-17
> 状态：✅ 资源就绪，⚠️ 2 项需处理

本清单用于阶段四部署集成：确认「三件套」离线资源（知识库 JSON + 向量库 + BGE 嵌入模型）完整性，保证在演示设备上可以离线重建/一键启动。

---

## 1. 知识库 JSON（data/processed/）

5 个域共 **348 条**，与阶段三入库口径一致。

| 文件 | 条目数 | 说明 |
|------|--------|------|
| venue.json | 30 | 纪念馆场馆知识 |
| work.json | 129 | 鲁迅作品 |
| bio.json | 65 | 鲁迅生平 |
| quote.json | 99 | 名言引用 |
| persona.json | 25 | 数字人设定 |
| **合计** | **348** | |

---

## 2. 向量库（chroma_db/）

根目录 `chroma_db/` 为当前生效向量库，**collection = `luxun_know_base`，399 chunk**。

| 项目 | 值 |
|------|-----|
| 路径 | `chroma_db/` |
| collection | `luxun_know_base` |
| chunk 数 | 399 |
| 入库条目 | 348 条 → 399 块（滑动窗口分块）|
| 嵌入模型 | BAAI/bge-small-zh-v1.5（与入库时一致）|

> ⚠️ **问题 A**：`data/chroma_db/` 下存在旧向量库 `scenic_ai_guide`（113 chunk），为阶段一二遗留，代码不再引用。部署时**只需打包根目录 `chroma_db/`**，旧目录可忽略（后续可清理）。

---

## 3. BGE 嵌入模型

模型为 `BAAI/bge-small-zh-v1.5`，权重 `model.safetensors` 91 MB。

| 项 | 状态 |
|----|------|
| 约定位置 | `scripts/bge-small-zh-v1.5/` |
| 当前实际位置 | ❌ **目录不存在**；模型在 HuggingFace 缓存 `~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots/<hash>/` |

> 🔴 **问题 B（硬伤，对应方案 D2）**：`rag_pipeline.py` / `ingest.py` 的逻辑是「优先加载 `scripts/bge-small-zh-v1.5/` 本地目录，否则走 `HF_MODEL_NAME` 联网下载」。当前模型只存在于 HF cache（本机网络可达时能加载），**换一台离线设备直接加载失败**。必须由打包脚本把模型复制到 `scripts/bge-small-zh-v1.5/` 随包分发。

模型文件清单（snapshot 目录内）：

| 文件 | 用途 | 大小 |
|------|------|------|
| model.safetensors | 模型权重 | 91 MB |
| config.json | 模型配置 | ~0.6 KB |
| tokenizer.json / tokenizer_config.json | 分词器 | ~0.6 MB |
| vocab.txt | 词表 | ~0.4 MB |
| special_tokens_map.json | 特殊 token | ~0.1 KB |
| modules.json / sentence_bert_config.json / config_sentence_transformers.json | sentence-transformers 配置 | ~0.5 KB |
| 1_Pooling/config.json | 池化配置 | ~0.2 KB |

---

## 4. 校验结论

| # | 资源 | 结果 |
|---|------|------|
| 1 | 5 域 JSON 条目数 | ✅ 348 条 |
| 2 | 向量库 chunk 数 | ✅ 399 chunk（`luxun_know_base`）|
| 3 | 模型文件可加载 | ⚠️ 本机可加载（HF cache），但未落到 `scripts/bge-small-zh-v1.5/` |
| 4 | 旧资源清理 | ⚠️ `data/chroma_db/`（113 chunk）遗留 |

**待办（由 `pack_offline.py` 完成）**：
1. 从 HF cache 复制 BGE 模型 → `scripts/bge-small-zh-v1.5/`
2. 打包三件套：`bge-small-zh-v1.5/` + `chroma_db/`（399 chunk）+ `data/processed/`（348 条）
3. 生成 `offline_resources.zip` 独立分发（不入 git）

---

## 5. 现场部署清单（演示设备）

| 步骤 | 说明 |
|------|------|
| 1 | 解压 `offline_resources.zip`，按 README 放置 `bge-small-zh-v1.5/` → `scripts/`，`chroma_db/`、`data/processed/` → 项目根目录 |
| 2 | 确认 `.env` 中 `LLM_MODEL=deepseek-v4-flash`、`LLM_API_KEY` 已配置（Key 用环境变量注入，不硬编码）|
| 3 | 设备需能访问 `api.deepseek.com`（云端生成）；若现场断网，走「离线降级模式」|
| 4 | 一键启动（花敬皓 `start.bat`/`start.sh`）后，`/health` 探活通过即就绪 |
