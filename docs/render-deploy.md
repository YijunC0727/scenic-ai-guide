# 在线体验 Demo 部署指南 —— Render（免费）

把 `space/` 目录部署成一个可公网访问的在线 Demo（Gradio 界面，讲解员 / 鲁迅双模式 + 调试面板）。

> 背景：2026 年 7 月起 HuggingFace 免费 `cpu-basic` 上的 Gradio/Docker Space 改收 PRO（$9/月）。本方案改用 **Render 免费档**，代码几乎零改动。

## 0. 资源怎么来的

| 资源 | 处理方式 |
|------|---------|
| 代码（`space/` 里 app.py + scripts/ + prompts/）| 随仓库 push 到 GitHub |
| 向量库 `space/chroma_db/`（约 3MB）| 随仓库提交 |
| BGE 模型（约 100MB）| 冷启动时从 HF 官方源自动下载（不提交） |
| DeepSeek API Key | Render 后台环境变量注入（不写代码） |

## 1. 前置

- GitHub 账号（仓库已在上面）
- Render 账号（用 GitHub 直接登录，免费，**无需信用卡**）
- 把最新代码 push 到 GitHub（含 `render.yaml` 和 `space/` 目录）

## 2. 部署（Blueprint 方式，推荐）

1. 打开 https://dashboard.render.com → **New** → **Blueprint**
2. 连接 GitHub 仓库 `scenic-ai-guide`
3. Render 会自动识别根目录的 `render.yaml`，预览出一个 Web 服务 `luxun-digital-human`
4. 点 **Apply** / **Create**，等待构建（首次约 5–10 分钟，装 CPU torch + gradio）

### 手动方式（不用 Blueprint）

若 Blueprint 没识别出来，就 **New → Web Service**，手动填：

| 项 | 值 |
|----|----|
| Repository | `scenic-ai-guide` |
| Root Directory | `space` |
| Build Command | `pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt` |
| Start Command | `python app.py` |
| Instance Type | Free（Starter） |

## 3. 配置 API Key（必做）

服务建好后，进 **该服务 → Environment → Environment Variables**，添加：

| Key | Value | 备注 |
|-----|-------|------|
| `LLM_API_KEY` | 你的 DeepSeek Key | 勾选 **secret**（勿明文） |
| `LLM_BASE_URL` | `https://api.deepseek.com` | render.yaml 已带，可跳过 |
| `LLM_MODEL` | `deepseek-v4-flash` | render.yaml 已带 |
| `LLM_THINKING` | `disabled` | render.yaml 已带 |

> 加了 `LLM_API_KEY` 后，Render 会自动重启服务重新加载环境变量。

## 4. 验证

1. 打开 Render 给的 `https://luxun-digital-human.onrender.com`
2. 首次冷启动约 1–2 分钟（下载 100MB 模型 + 加载），顶部显示「✅ 就绪」
3. 输入 `这个展厅主要展什么？`（→ 讲解员模式）
4. 输入 `鲁迅先生，您为什么要弃医从文？`（→ 数字人模式）
5. 右侧调试面板能看到意图判定、检索结果、守卫状态

## 5. 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| 页面长时间加载 | 免费档 15 分钟无访问会**休眠**，下次访问冷启动 30-50s + 模型加载 | 正常，稍等即可 |
| 「服务未就绪」 | `LLM_API_KEY` 没配好 | 检查第 3 步，变量名拼写完全一致 |
| Build 报内存/超时 | 免费档 512MB，torch 偏紧 | 见下方「回退方案」 |
| 回答「电线那一头睡过去了」 | DeepSeek 不可达 | 检查 `LLM_BASE_URL` / Key 是否有效 |
| 想更新 | 改了主仓库 `scripts/` 后 | 重新复制 7 个脚本到 `space/scripts/`，push，Render 自动重建 |

## 6. 回退方案：临时 share 链接（不依赖任何云）

若 Render 的 512MB 内存跑 torch 确实 OOM（Build 或运行失败），就用本地临时公网链接应急——足够录演示视频和短期评审：

```bash
pip install gradio
cd scenic-ai-guide
python scripts/gradio_app.py --share
```

`--share` 会生成一个 72 小时有效的公网链接（`https://xxx.gradio.live`）。前提：本机已具备三件套（BGE 模型 / chroma_db / data）和 DeepSeek Key 的 `.env`。

> 更稳的免费长期方案是换成 Streamlit Community Cloud（~1GB 内存），但需要把 Gradio 界面重写成 Streamlit；如需要我再做。
