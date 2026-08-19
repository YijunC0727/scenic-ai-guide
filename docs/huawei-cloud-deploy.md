# 在线体验 Demo 部署教程 —— 华为云（详细版）

把「鲁迅数字人 · 双模式对话」部署到华为云，获得稳定公网链接 `http://<弹性公网IP>:7860`。

> 本教程面向**华为云弹性云服务器 ECS**，覆盖从零开始到跑通的全流程。
> 通用脚本与背景说明见 [docs/cloud-server-deploy.md](cloud-server-deploy.md)；本文是华为云专属的逐屏操作版。

---

## 0. 整体流程一览

```
[1] 注册华为云 + 实名/学生认证
        ↓
[2] 购买 ECS（Ubuntu 22.04 / 2核2GB / 绑定弹性公网IP）
        ↓
[3] 安全组放行 7860 端口
        ↓
[4] SSH 登录服务器（root）
        ↓
[5] 本机打包「三件套」并上传
        ↓
[6] 服务器上执行一键部署脚本
        ↓
[7] 浏览器访问 http://<公网IP>:7860 验证
```

---

## 1. 注册 + 认证（省钱可做）

1. 打开 https://www.huaweicloud.com → **注册** → 手机号注册
2. 登录后进入**「实名认证」**（个人认证即可，上传身份证）
3. 可选：搜索**「云创校园」**（华为云学生优惠计划），完成学生认证后可享优惠/免费额度

> 学生认证需要学信网信息，价格以官网实时为准。不认证也能用「按需付费」买，几小时演示成本很低。

---

## 2. 购买弹性云服务器 ECS

控制台首页搜索「**弹性云服务器 ECS**」→ 进入 → 点「**购买弹性云服务器**」。

### 2.1 计费模式 + 区域
- **计费模式**：演示可选「**按需计费**」（用多少付多少，随时释放）；长期可选「包年/包月」
- **区域**：选离你近的，如「华南-广州」「华北-北京四」均可

### 2.2 镜像（关键）
- 镜像类型：**公共镜像**
- 操作系统：**Ubuntu**
- 版本：**Ubuntu 22.04 server 64bit**（或 24.04）

### 2.3 规格
- 选 **2 vCPU | 2 GiB** 起步（如 `s6.medium.2`），4GB 更稳
- 不需要 GPU —— BGE 模型 CPU 推理，LLM 走 DeepSeek 云端 API

### 2.4 系统盘
- 默认 40GB 即可（够放 torch + BGE 模型 + 依赖）

### 2.5 网络（VPC + 安全组）
- VPC：用默认创建的即可
- **安全组**：先选默认安全组，后面第 3 步再放行 7860 端口

### 2.6 弹性公网 IP（⚠️ 关键，漏了就没法公网访问）
- 在「网络」配置里，找到**弹性公网IP**，选择「**现在购买**」并**绑定**到该实例
- 带宽 1~5 Mbit/s 均可（演示够用）
- 不绑定公网 IP 的话，服务器只能内网访问，**外部打不开**

### 2.7 登录方式
- **密码**（简单）：设置一个 root 密码，之后 `ssh root@<公网IP>` 登录
- **密钥对**（更安全）：创建密钥对并下载 `.pem` 文件，登录用 `ssh -i xxx.pem root@<公网IP>`

### 2.8 确认购买
- 勾选同意协议 → **立即购买**，等 1~2 分钟实例创建完成
- 记下控制台显示的**弹性公网 IP**（形如 `123.60.x.x`）

---

## 3. 安全组放行 7860 端口（⚠️ 关键）

华为云默认安全组通常只放行 22（SSH），必须手动加 7860。

1. 控制台 → **弹性云服务器** → 找到刚买的实例 → 点实例名进入详情
2. 左侧/顶部找 **「安全组」** 标签（或：控制台 →「网络与安全」→「安全组」）
3. 点该安全组 → **「配置规则」** → **「入方向规则」** 页签 → **「添加规则」**，填：

   | 项 | 值 |
   |----|----|
   | 优先级 | 1（或默认） |
   | 策略 | 允许 |
   | 协议端口 | TCP / 7860 |
   | 类型 | IPv4 |
   | 源地址 | 0.0.0.0/0 |

4. 确定保存。

> ⚠️ `源地址 0.0.0.0/0` 表示任何人可访问（演示够用）。若要更安全，可改成你自己的办公/校园出口 IP。

---

## 4. 登录服务器

```bash
# 密码方式
ssh root@<弹性公网IP>
# 输入第 2.7 步设置的 root 密码

# 密钥对方式
ssh -i /path/to/你的密钥.pem root@<弹性公网IP>
```

登录成功后会看到 `root@xxx:~#` 提示符。

---

## 5. 本机打包「三件套」并上传

**在你的 Windows 开发机上**（不是服务器）：

```bash
cd scenic-ai-guide
python scripts/pack_offline.py
# 产出 releases/offline_resources.zip（约 100MB，含 BGE 模型 + 向量库 + 知识库）
```

然后传到服务器（用 Git Bash / PowerShell 的 scp 均可）：

```bash
scp releases/offline_resources.zip root@<公网IP>:~/
scp scripts/deploy_cloud.sh        root@<公网IP>:~/
```

> 或者登录服务器后直接用 curl 拉部署脚本：
> `curl -O https://raw.githubusercontent.com/zhangjiaxin13553-source/scenic-ai-guide/main/scripts/deploy_cloud.sh`

---

## 6. 服务器上执行部署

```bash
# 把 sk-xxx 换成真实 DeepSeek Key；脚本会自动 clone 代码、装依赖、放资源、启动
LLM_API_KEY=sk-xxx bash deploy_cloud.sh ~/offline_resources.zip
```

脚本会自动完成（全程约 3~6 分钟）：
1. 装 `python3 / git / unzip`
2. `git clone` 仓库到 `/root/scenic-ai-guide`
3. 建 venv → 装 CPU 版 torch + 依赖
4. 解压放置三件套（BGE 模型 → `scripts/`，向量库 + 知识库 → 项目根）
5. 生成 `.env` 并写入 `LLM_API_KEY`
6. 后台启动 `gradio_app.py`，并探活

看到 `✅ 部署完成` 即成功。

> 如果国内下载 pip / torch 慢，见第 9 节「常见问题」的镜像说明。

---

## 7. 验证

1. 服务器上探活：`curl http://127.0.0.1:7860` 返回网页即就绪
2. 本机浏览器打开 `http://<弹性公网IP>:7860`
3. 试问：
   - 「这个展厅主要展什么？」→ 讲解员模式
   - 「鲁迅先生，您为什么要弃医从文？」→ 数字人模式
4. 首次加载约 1 分钟（BGE 模型加载），之后秒回；右侧调试面板能看到意图/检索/守卫

---

## 8. 开机自启（可选，systemd · root 版）

华为云默认 root 用户，脚本把代码装在 `/root/scenic-ai-guide`，对应自启配置：

```bash
sudo tee /etc/systemd/system/luxun-demo.service >/dev/null <<'EOF'
[Unit]
Description=Luxun Digital Human Demo
After=network.target

[Service]
User=root
WorkingDirectory=/root/scenic-ai-guide
ExecStart=/root/scenic-ai-guide/venv/bin/python scripts/gradio_app.py --host 0.0.0.0 --port 7860
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now luxun-demo
sudo systemctl status luxun-demo
```

> 若你改用非 root 用户，把上面的 `root` 和 `/root/...` 换成对应用户和 `$HOME/...` 路径即可。

---

## 9. 常见问题（华为云 + 通用）

| 现象 | 原因 | 处理 |
|------|------|------|
| 公网打不开，服务器本地 curl 正常 | 安全组没放行 7860 | 回第 3 步，确认入方向规则有 TCP/7860、源 0.0.0.0/0 |
| 公网打不开，本地也连不上 | 没绑定弹性公网IP | 第 2.6 步，给实例绑定 EIP |
| 华为云默认登录用户是谁 | — | **root**（Linux 镜像），不是 ubuntu |
| `pip install` 卡住/超时 | 国内访问 PyPI 慢 | 脚本 `pip install` 前加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `torch` 下载失败 | 国内访问 pytorch.org 慢 | 用清华源：`pip install torch==2.12.0 -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 端口被占用 | 7860 被占 | `APP_PORT=7861 bash deploy_cloud.sh ...` 换端口，并同步放行新端口 |
| 重启服务器后 demo 没了 | nohup 不自启 | 用第 8 节 systemd 托管 |
| 想更新代码 | 改了主仓库 | 服务器 `git -C /root/scenic-ai-guide pull` 后重跑 `bash deploy_cloud.sh` |
| 首次提问很慢 | BGE 模型加载 | 正常，之后秒回 |

---

## 附：释放/省钱

演示结束后，按需计费的实例可在控制台「更多 → 释放」删掉实例（连同弹性公网IP一起释放），停止计费。
