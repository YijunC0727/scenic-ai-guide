# 在线体验 Demo 部署指南 —— HuggingFace Spaces

> ⚠️ **2026 年 7 月起，HuggingFace 免费 `cpu-basic` 上的 Gradio / Docker Space 改收 PRO（$9/月）。**
> 免费部署请改用 [docs/render-deploy.md](render-deploy.md)（Render 免费档）。本页保留给日后愿意付费 PRO、或需要 HF 生态的场景。

把 `space/` 目录部署成一个可公网访问的在线 Demo。游客打开网页即可体验「鲁迅数字人 · 双模式对话」。

## 0. 这个 Demo 怎么跑起来的

| 资源 | 在 Space 上如何获得 |
|------|--------------------|
| 代码（app.py + scripts/ + prompts/）| 随 `space/` 一起提交 |
| 向量库 `chroma_db/`（约 3MB）| 随 `space/` 一起提交 |
| BGE 模型（约 100MB）| **不提交**，Space 冷启动时从 HF 官方源自动下载 |
| DeepSeek API Key | **不提交**，通过 Space 的 Secret 注入 |

> 关键：`space/` 里的 `chroma_db/` 已经随仓库提交（已在本仓库 `.gitignore` 中为 `space/chroma_db/` 加了例外），BGE 模型和 API Key 都**不进 git**。

## 1. 前置

- 一个 [HuggingFace](https://huggingface.co) 账号（免费）
- DeepSeek API Key（团队共用的那个，`LLM_API_KEY`）
- 本仓库已 clone 到本地

## 2. 创建 Space

1. 打开 https://huggingface.co/new-space
2. **Space name**：如 `luxun-digital-human`（URL 会变成 `https://huggingface.co/spaces/<你的用户名>/luxun-digital-human`）
3. **License**：按需（团队内部 demo 可选 `mit` 或留空）
4. **SDK**：选 `Gradio`
5. **Gradio** 版本：选 `6.22.0`（或直接留默认，`requirements.txt` 会再锁定一次）
6. **Hardware**：`CPU basic`（免费即可，BGE 是 CPU 推理）
7. 点 **Create Space**

## 3. 上传 `space/` 内容

### 方式 A：git 推送（推荐，可版本管理）

```bash
# 1. clone 空 Space 到本地
git clone https://huggingface.co/spaces/<你的用户名>/luxun-digital-human
cd luxun-digital-human

# 2. 把本仓库 space/ 里的内容复制进来（注意是复制“内容”，不是整个 space/ 目录）
cp -r ../../scenic-ai-guide/space/* .

# 3. 提交并推送
git add .
git commit -m "feat: 在线体验 Demo（鲁迅数字人 · 双模式对话）"
git push
```

### 方式 B：网页上传（最简单，不涉及 git）

1. 进入 Space 页面 → **Files** 标签 → **Add files** → **Upload files**
2. 上传以下内容（保持目录结构）：
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `scripts/` 下的 7 个 `.py`
   - `prompts/` 下的 2 个 `.md`
   - `chroma_db/` 下的 `chroma.sqlite3`（连同 UUID 子目录）
3. 点 **Commit**

> 提示：方式 B 逐文件上传较繁琐，推荐方式 A。

## 4. 配置 Secret（API Key）

Space 里**没有 `.env` 文件**，改由环境变量注入。进入 Space → **Settings** → **Variables and secrets**：

| Name | Value | 类型 |
|------|-------|------|
| `LLM_API_KEY` | 你的 DeepSeek Key | **Secret**（隐藏） |
| `LLM_BASE_URL` | `https://api.deepseek.com` | Variable |
| `LLM_MODEL` | `deepseek-v4-flash` | Variable |
| `LLM_THINKING` | `disabled` | Variable |

> ⚠️ `LLM_API_KEY` 务必选 **Secret**，不要选 Variable（Variable 会明文显示、可能被记录）。
> 改完 Secret 后，Space 会自动重启加载新环境变量。

## 5. 验证

1. 打开 `https://huggingface.co/spaces/<你的用户名>/luxun-digital-human`
2. 首次冷启动约 1–2 分钟（容器启动 + 安装依赖 + 下载 BGE 模型 100MB），页面顶部会显示「✅ 就绪」
3. 输入 `这个展厅主要展什么？`（应触发讲解员模式）
4. 输入 `鲁迅先生，您为什么要弃医从文？`（应触发数字人模式，鲁迅口吻作答）
5. 右侧「调试面板」能看到意图判定、检索结果、守卫状态

## 6. 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| 顶部显示「⚠️ 服务未就绪」 | `LLM_API_KEY` 等 Secret 未配好 | 检查第 4 步，确认变量名拼写完全一致（`LLM_API_KEY`） |
| 首次提问很慢（1 分钟+） | BGE 模型冷启动下载/加载 | 正常，之后有缓存会快很多 |
| 报 `RAG 管线导入失败` | BGE 模型下载失败 | 看 Space 的 **Logs**，通常网络/存储问题，重建即可 |
| 回答「电线那一头睡过去了」 | DeepSeek API 超时/不可达 | 检查 `LLM_BASE_URL` 是否填对、Key 是否有效 |
| 想更新 Demo | 改了主仓库 `scripts/` 后 | 重新复制 7 个脚本到 `space/scripts/`，再推送 Space |

## 7. 更新维护

`space/scripts/` 是 `scripts/` 中 7 个文件的副本（`rag_pipeline.py` 等）。若主链路代码有改动，记得同步复制：

```bash
cp scripts/{rag_pipeline,intent_classifier,llm_client,query_rewriter,quality_guard,hallucination_checker,consistency_checker}.py space/scripts/
```

> `space/scripts/rag_pipeline.py` 与主仓库一致，已内置「Space 上用 HF 官方源、本地用 hf-mirror」的判断，无需额外改动。
