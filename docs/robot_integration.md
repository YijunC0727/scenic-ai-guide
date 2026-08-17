# 实验室机器人对话系统 API 对接说明 (Robot Integration Guide)
## 1. 概述与系统架构
本文档旨在为机器人控制层开发提供标准的 HTTP 接口对接指南。目前我们的对话系统已封装为运行在 Jetson 上的 FastAPI 服务，以替代原有的 Gradio 人机交互界面，从而支持机器人硬件层的程序化调用。
### 1.1 核心数据流向
在语音交互链路中，我们的 FastAPI 服务处于中枢位置，负责接收 ASR 识别后的文本，进行意图理解与生成，并将结果返回给 TTS 模块。数据流向如下：
![](image-1.png)
## 2. 接口清单
以下是当前版本提供的核心 RESTful API 列表：

| 接口 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康检查（机器人启动时探活 + 预热） |
| `/chat` | POST | 单轮对话（机器人主调用） |
| `/reset` | POST | 清空对话历史（切游客 / 结束一轮） |
## 3. 核心接口详情与示例
### 3.1 `GET /health` — 健康检查

用于机器人启动时探活，也用于预热。会尝试加载 pipeline 并返回真实状态。

#### 响应示例（就绪）：

```json
{
  "status": "ok",
  "model_loaded": true,
  "error": null,
  "circuit": { "is_open": false, "fail_count": 0, "fail_threshold": 5, "reset_timeout": 60 }
}
```

#### 响应示例（加载失败）：

```json
{ "status": "error", "model_loaded": false, "error": "<具体异常信息>", "circuit": null }
```

- `status` 为 `ok` 才可正常对话；为 `error` 时机器人应提示「服务不可用」并重试。
- `circuit.is_open == true` 表示 LLM 熔断器已打开（连续失败触发的冷却中），此时对话会走兜底话术。
#### cURL测试示例:
1. 快速查看完整返回（人工排查）
```bash
{curl -s http://<Jetson_IP>:8000/health | jq .}
```
2. 判断服务是否真正就绪（核心逻辑）
```bash
{curl -s http://<Jetson_IP>:8000/health | jq -e '.status == "ok" and .model_loaded == true'}
```
返回 `true`：说明服务完全就绪。
返回 `false`：说明模型还在加载或加载失败。
命令报错（退出码非0）：说明请求失败或 JSON 解析出错。
3. 检查 LLM 熔断器状态
如果你想单独确认 LLM 是否处于熔断冷却中（走兜底话术），可以检查 `circuit.is_open`：
```bash
{curl -s http://<Jetson_IP>:8000/health | jq '.circuit.is_open'}
```
返回 `false`：正常状态。
返回 `true`：熔断器已打开，连续失败冷却中
4. 获取具体的错误信息（排查问题）
当服务不可用时，直接提取 error 字段看具体原因：
```bash
{curl -s http://<Jetson_IP>:8000/health | jq -r '.error'}
```
### 3.2 `POST /chat` — 单轮对话（核心）

#### 请求：

```jsonc
{
  "text": "鲁迅先生，您为什么弃医从文？",   // 必填，ASR 识别出的文本
  "session_id": "tourist-001",              // 可选，多轮对话隔离用
  "force_mode": null,                       // 可选，"narrator" | "luxun" | null(自动)
  "include_debug": false                    // 可选，是否返回调试信息
}
```

#### 响应（成功）：

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

#### 响应（兜底——接口不抛 5xx，永远返回可播报文本）：

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

#### 字段说明：

| 字段 | 含义 |
|------|------|
| `success` | 只要返回了可播报文本就为 `true`（兜底也算成功）。为 `false` 仅表示**服务级异常**，但 `reply` 仍是可播文本 |
| `reply` | **唯一必须交给 TTS 的字段**。任何情况下都非空 |
| `intent` | `narrator` / `luxun` / `ambiguous` / `reject_time` / `reject_irrelevant` |
| `mode` | 中文标签（给人看，机器人可忽略） |
| `guard_status` | 质量守卫判定：`PASS` / `WARN` / `AMEND` / `FALLBACK` / `N/A` / `ERROR` |
| `latency_ms` | 本问耗时，供延迟监控 |
| `error` | 仅 `success=false` 时非空 |

#### cURL测试示例:
1.基础测试（发送标准对话）
这是最常用的测试命令，发送一段 ASR 识别出的文本，并开启调试信息以便排查：
```bash
{
curl -X POST "http://<Jetson_IP>:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "鲁迅先生，您为什么弃医从文？",
    "session_id": "tourist-001",
    "include_debug": true
  }' | jq .
}
```
(注：加上 `| jq .` 可以格式化输出，方便阅读长文本的 `reply`)
2.测试兜底话术（模拟异常）
```bash
{
# 比如故意不传必填的 text 字段
curl -X POST "http://<Jetson_IP>:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "tourist-001"}' | jq .
}
```
预期结果：HTTP 状态码应为 200，但 JSON 中 `success` 为 `false`，且 `reply` 是类似“这大约是什么缘故呢……”的兜底文本。
#### 测试建议：
针对这个接口，建议重点测试以下 3 个边界场景：
多轮对话隔离：连续发两次带相同 `session_id` 的请求，看上下文是否连贯。
质量守卫触发：构造一些敏感或违规文本，测试 `guard_status` 是否能正确返回 `WARN`、`AMEND` 或 `FALLBACK`。
超长文本：发送一段极长的 ASR 文本，测试 `latency_ms` 是否在合理范围内，以及是否会被截断。

### 3.3 `POST /reset` — 清空历史

##### 查询参数：`session_id`（可选）。

```
POST /reset                    → 清空全局单会话
POST /reset?session_id=tourist-001  → 清空指定会话
```

#### 响应：
`{ "success": true, "reset": "global" }` 或 `{ "success": true, "reset": "tourist-001", "existed": true }`

建议机器人**每接待一位新游客时调用一次**，避免上一游客的对话污染下一游客的上下文。
#### cURL测试示例:
清空全局单会话（无参数）
```bash
{curl -X POST "http://localhost:8080/reset" | jq .}
```
预期响应：
```json
{
  "success": true,
  "reset": "global"
}
```
### Python调用示例
```python
import requests
import json

class LuxunRobotClient:
    def __init__(self, jetson_ip):
        self.base_url = f"http://{jetson_ip}:8000"
        self.session = requests.Session()  # 使用 Session 复用 TCP 连接，提升性能
        self.session.headers.update({"Content-Type": "application/json"})

    def check_health(self):
        """3.1 健康检查"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[健康检查失败] {e}")
            return None

    def reset_session(self, session_id=None):
        """3.3 清空历史"""
        try:
            url = f"{self.base_url}/reset"
            params = {"session_id": session_id} if session_id else {}
            response = self.session.post(url, params=params, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[重置会话失败] {e}")
            return None

    def chat(self, text, session_id=None, force_mode=None, include_debug=False):
        """3.2 对话接口"""
        try:
            payload = {
                "text": text,
                "include_debug": include_debug
            }
            if session_id:
                payload["session_id"] = session_id
            if force_mode:
                payload["force_mode"] = force_mode

            response = self.session.post(f"{self.base_url}/chat", json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[对话请求失败] {e}")
            return None

# ================= 测试运行 =================
if __name__ == "__main__":
    # 1. 初始化客户端（请替换为真实的 Jetson IP）
    robot = LuxunRobotClient("192.168.1.100") 

    # 2. 检查服务是否就绪
    health = robot.check_health()
    if not health or health.get("status") != "ok":
        print("服务未就绪，退出测试。")
        exit(1)
    print("✅ 服务已就绪，模型加载状态:", health.get("model_loaded"))

    # 3. 模拟新游客接入，清空历史
    SID = "tourist-001"
    robot.reset_session(session_id=SID)

    # 4. 进行多轮对话测试
    questions = [
        "鲁迅先生，您为什么弃医从文？",
        "您觉得现在的年轻人怎么样？"
    ]

    for q in questions:
        print(f"\n🙋 游客: {q}")
        result = robot.chat(text=q, session_id=SID)
        
        if result:
            # 提取核心播报文本
            reply = result.get("reply", "")
            latency = result.get("latency_ms", 0)
            success = result.get("success", False)
            
            print(f"🎭 鲁迅 ({latency}ms): {reply}")
            if not success:
                print(f"⚠️ 触发兜底逻辑，错误信息: {result.get('error')}")
```
## 4. 错误处理与稳定性约定
为确保机器人现场运行的稳定性，API 遵循以下兜底策略：
1. 
超时时间：建议客户端设置请求超时时间为 30秒。
2. 
异常兜底：服务端承诺永不返回 5xx 空响应。若内部发生任何异常（如 ASR/TTS 模块超时、大模型推理失败），将始终返回标准的 HTTP 200 状态码，并在 `reply` 字段中返回兜底文本
3. 
会话隔离：请严格遵守`session_id`规则，不同机器人或不同房间的对话务必使用不同的`session_id`，避免上下文串扰
## 5. 常见问题排查
● 无法连接：请确认 Jetson 的 IP 地址是否正确，以及防火墙是否放行了 8000 端口。
● 响应缓慢：首次调用可能因模型加载需要数秒，后续调用将保持低延迟。可通过 /health 接口提前预热服务。
