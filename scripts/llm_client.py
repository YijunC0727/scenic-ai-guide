"""
LLM API 统一封装
================
支持 DeepSeek / GLM 等国产大模型（OpenAI 兼容协议）。

功能：
  - 统一接口：chat(system_prompt, context, user_query) → str
  - 指数退避重试（最多 3 次）
  - 调用间隔限流（防 API 超额）
  - 多轮对话历史管理（最近 5 轮）

环境变量（.env）：
  LLM_API_KEY    - API 密钥（必填）
  LLM_BASE_URL   - API 地址（必填）
  LLM_MODEL      - 模型名（必填）
  LLM_MAX_TOKENS - 最大输出 token（可选，默认 1024）
  LLM_TEMPERATURE- 温度（可选，默认 0.3）

用法：
  from scripts.llm_client import LLMClient, chat

  client = LLMClient()
  reply = client.chat(
      system_prompt="你是讲解员",
      context="广州鲁迅纪念馆位于文明路215号...",
      user_query="纪念馆在哪里？",
  )

  # 或便捷函数
  reply = chat("你是讲解员", "广州鲁迅纪念馆...", "纪念馆在哪里？")
"""

import os
import json
import time
import logging
from typing import Optional, List, Dict, Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_client")

# ============================================================
# 配置常量
# ============================================================

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0     # 秒，指数退避基数
DEFAULT_MIN_INTERVAL = 0.3          # 秒，两次调用最小间隔（简单限流）
DEFAULT_TIMEOUT = 30                # 秒
SAFE_MESSAGE_MAX_TOTAL_CHARS = 12000  # messages总字符安全上限，防止超长报错

# 常用 provider → base_url 映射
PROVIDER_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}


# ============================================================
# LLMClient
# ============================================================

class LLMClient:
    """
    LLM 统一调用客户端。

    自动从 .env 读取：
      LLM_API_KEY   API 密钥
      LLM_BASE_URL  API 地址（OpenAI 兼容）
      LLM_MODEL     模型名（默认 deepseek-chat）
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        # --- 从参数 / 环境变量读取 ---
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)

        self.max_tokens = (
            max_tokens if max_tokens is not None
            else int(os.getenv("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        )
        self.temperature = (
            temperature if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", DEFAULT_TEMPERATURE))
        )

        self.max_retries = max_retries
        self.timeout = timeout

        # 简单限流
        self._last_call_time = 0.0
        self._min_interval = DEFAULT_MIN_INTERVAL

        # 对话历史（多轮对话管理）
        self._history: List[Dict[str, str]] = []

        # Token 用量统计
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0

        # 熔断器：连续失败计数 + 冷却期
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_failure_threshold = 5    # 连续5次失败触发熔断
        self._circuit_cooldown_sec = 60.0      # 冷却60秒

        # --- 校验 ---
        if not self.api_key:
            raise ValueError(
                "LLM_API_KEY 未设置。请在 .env 中配置，或通过 api_key 参数传入。"
            )
        if not self.base_url:
            raise ValueError(
                "LLM_BASE_URL 未设置。请在 .env 中配置，或通过 base_url 参数传入。"
            )

        # 组装请求 URL 与 Headers
        self._endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "LLMClient 就绪 | model=%s | endpoint=%s | max_tokens=%d | temperature=%.2f",
            self.model, self._endpoint, self.max_tokens, self.temperature,
        )

    # ----------------------------------------------------------
    # 工具方法（来自 hjh PR#19 — 客户端加固）
    # ----------------------------------------------------------

    @staticmethod
    def _clean_llm_output(text: str) -> str:
        """清洗模型输出：剔除 markdown ``` 代码块标记、多余换行空格。"""
        if not text:
            return ""
        s = text.strip()
        if s.startswith("```"):
            lines = s.splitlines()
            filtered = [ln for ln in lines if not ln.strip().startswith("```")]
            s = "\n".join(filtered).strip()
        return s

    @staticmethod
    def _safe_truncate_messages(messages: List[Dict[str, str]], max_chars: int) -> List[Dict[str, str]]:
        """安全截断 messages 总字符数，避免请求 payload 过大。"""
        total = sum(len(m.get("content", "")) for m in messages)
        if total <= max_chars:
            return messages
        logger.warning(f"messages总字符 {total} 超过安全阈值{max_chars}，执行截断")
        system_msg = None
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m
            else:
                chat_msgs.append(m)
        while chat_msgs and sum(
            len(m.get("content", "")) for m in ([system_msg] if system_msg else []) + chat_msgs
        ) > max_chars:
            chat_msgs.pop(0)
        out = []
        if system_msg:
            out.append(system_msg)
        out.extend(chat_msgs)
        return out

    # ----------------------------------------------------------
    # 核心接口
    # ----------------------------------------------------------

    def call(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        底层调用：发送 messages，返回模型回复文本。
        自动处理重试、限流、熔断。

        参数：
          messages:    [{"role":"system","content":...}, ...]
          temperature: 覆盖实例默认值
          max_tokens:  覆盖实例默认值

        返回：
          模型回复字符串

        Raises:
          RuntimeError: 熔断器打开 或 重试耗尽
        """
        # 熔断检查
        if self._is_circuit_open():
            cooldown_remaining = int(self._circuit_open_until - time.time())
            raise RuntimeError(
                f"熔断器已打开（连续 {self._circuit_failure_threshold} 次失败），"
                f"请等待 {cooldown_remaining}s 后重试"
            )

        temp = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        payload = {
            "model": self.model,
            "messages": self._safe_truncate_messages(messages, SAFE_MESSAGE_MAX_TOTAL_CHARS),
            "temperature": temp,
            "max_tokens": mt,
            "stream": False,
        }

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            self._rate_limit()

            try:
                resp = requests.post(
                    self._endpoint,
                    headers=self._headers,
                    data=json.dumps(payload),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

                # 防御式解析：安全读取嵌套字段
                choices = data.get("choices") or []
                if not choices:
                    raise ValueError(f"API 返回空 choices: {json.dumps(data)[:200]}")

                message = choices[0].get("message") or {}
                content = message.get("content") or ""
                content = self._clean_llm_output(content)

                # 记录 token 用量
                self._record_usage(data)

                # 成功 → 重置熔断计数
                self._consecutive_failures = 0

                return content.strip() if content else ""

            except requests.exceptions.Timeout as e:
                last_error = e
                self._consecutive_failures += 1
                if attempt < self.max_retries:
                    delay = DEFAULT_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "API 超时 (第 %d/%d 次)，%.1fs 后重试",
                        attempt + 1, self.max_retries, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("API 超时，已达最大重试次数 (%d)", self.max_retries)

            except requests.exceptions.HTTPError as e:
                last_error = e
                self._consecutive_failures += 1
                status_code = getattr(e.response, "status_code", 0)

                # 4xx 错误不重试（客户端错误）
                if 400 <= status_code < 500:
                    logger.error("API 客户端错误 (HTTP %d): %s", status_code, e)
                    try:
                        error_body = e.response.json()
                        logger.error("  错误详情: %s", json.dumps(error_body, ensure_ascii=False)[:300])
                    except Exception:
                        pass
                    # 429 (Rate Limit) 仍然重试
                    if status_code == 429 and attempt < self.max_retries:
                        delay = DEFAULT_RETRY_BASE_DELAY * (2 ** (attempt + 1))  # 加倍等待
                        logger.warning("触发限流，%.1fs 后重试", delay)
                        time.sleep(delay)
                        continue
                    break  # 其他 4xx 不重试

                # 5xx 重试
                if attempt < self.max_retries:
                    delay = DEFAULT_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "API 服务端错误 HTTP %d (第 %d/%d 次)，%.1fs 后重试",
                        status_code, attempt + 1, self.max_retries, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("API 服务端错误，已达最大重试次数 (%d)", self.max_retries)

            except Exception as e:
                last_error = e
                self._consecutive_failures += 1
                if attempt < self.max_retries:
                    delay = DEFAULT_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "API 失败 (第 %d/%d 次)，%.1fs 后重试: %s",
                        attempt + 1, self.max_retries, delay, e,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "API 失败，已达最大重试次数 (%d): %s",
                        self.max_retries, e,
                    )

        # 检查是否触发熔断
        if self._consecutive_failures >= self._circuit_failure_threshold:
            self._circuit_open_until = time.time() + self._circuit_cooldown_sec
            logger.critical(
                "连续 %d 次失败，熔断器已打开，冷却 %ds",
                self._consecutive_failures, self._circuit_cooldown_sec,
            )

        raise RuntimeError(
            f"LLM 调用失败（已重试 {self.max_retries} 次）: {last_error}"
        )

    def chat(
        self,
        system_prompt: str,
        context: str = "",
        user_query: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        单轮对话（RAG 场景）。

        参数：
          system_prompt: 系统提示（角色设定 + 知识使用规则）
          context:       检索到的知识片段，会被拼入 user message
          user_query:    用户原始问题

        返回：
          模型回复文本
        """
        # 拼接上下文与用户问题
        if context:
            user_content = (
                f"【参考资料（请优先根据以下信息回答）】\n"
                f"{context}\n\n"
                f"【用户问题】\n"
                f"{user_query}"
            )
        else:
            user_content = user_query

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        return self.call(messages, temperature=temperature, max_tokens=max_tokens)

    def chat_with_history(
        self,
        system_prompt: str,
        context: str,
        user_query: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        多轮对话。

        参数：
          system_prompt: 系统提示
          context:       检索到的知识片段
          user_query:    用户当前问题
          history:       历史对话列表 [{"role":"user",...}, {"role":"assistant",...}]
                         若为 None，使用实例内置 _history

        返回：
          模型回复文本
        """
        msgs = history if history is not None else self._history

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(msgs)

        if context:
            user_content = (
                f"【参考资料】\n{context}\n\n"
                f"【用户问题】\n{user_query}"
            )
        else:
            user_content = user_query

        messages.append({"role": "user", "content": user_content})

        reply = self.call(messages)

        # 更新内置历史（只保留最近 5 轮 = 10 条消息）
        self._history.append({"role": "user", "content": user_query})
        self._history.append({"role": "assistant", "content": reply})
        if len(self._history) > 10:
            self._history = self._history[-10:]

        return reply

    # ----------------------------------------------------------
    # 辅助
    # ----------------------------------------------------------

    def _rate_limit(self):
        """简单限流：确保两次调用间隔不小于 _min_interval 秒。"""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def _is_circuit_open(self) -> bool:
        """检查熔断器是否打开。"""
        if self._circuit_open_until > time.time():
            return True
        # 冷却期已过，复位
        if self._circuit_open_until > 0:
            self._circuit_open_until = 0.0
            self._consecutive_failures = 0
            logger.info("熔断器已复位")
        return False

    def _record_usage(self, data: dict):
        """从 API 响应中提取并累加 token 用量。"""
        usage = data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or 0
        self._total_prompt_tokens += prompt_tokens
        self._total_completion_tokens += completion_tokens

    def clear_history(self):
        """清空多轮对话历史。"""
        self._history.clear()

    def reset_circuit(self):
        """手动复位熔断器。"""
        self._circuit_open_until = 0.0
        self._consecutive_failures = 0

    @property
    def history(self) -> List[Dict[str, str]]:
        """返回当前对话历史（只读副本）。"""
        return list(self._history)

    @property
    def token_usage(self) -> dict:
        """返回累计 token 用量统计。"""
        return {
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
        }

    @property
    def circuit_status(self) -> dict:
        """返回熔断器状态。"""
        return {
            "is_open": self._is_circuit_open(),
            "consecutive_failures": self._consecutive_failures,
            "cooldown_remaining_s": max(0, int(self._circuit_open_until - time.time())),
        }

    # ----------------------------------------------------------
    # 工厂方法
    # ----------------------------------------------------------

    @classmethod
    def from_provider(cls, provider: str, api_key: Optional[str] = None) -> "LLMClient":
        """
        按 provider 名称快速创建客户端。

        用法：
          client = LLMClient.from_provider("deepseek")
          client = LLMClient.from_provider("glm", api_key="xxx")
        """
        provider = provider.lower()
        if provider in PROVIDER_URLS:
            return cls(base_url=PROVIDER_URLS[provider], api_key=api_key)
        raise ValueError(
            f"不支持的 provider: '{provider}'，可选: {list(PROVIDER_URLS)}"
        )


# ============================================================
# 便捷函数
# ============================================================

_default_client: Optional[LLMClient] = None


def _get_client() -> LLMClient:
    """懒加载全局默认客户端。"""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def chat(
    system_prompt: str,
    context: str,
    user_query: str,
    temperature: Optional[float] = None,
) -> str:
    """
    便捷函数 —— 签名与执行方案一致：
        chat(system_prompt, context, user_query) → str

    使用全局默认客户端，适合快速调用。
    """
    return _get_client().chat(
        system_prompt=system_prompt,
        context=context,
        user_query=user_query,
        temperature=temperature,
    )


# ============================================================
# 自测
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-5s | %(message)s",
    )

    print("=" * 60)
    print("  LLM Client 自测")
    print("=" * 60)

    client = LLMClient()

    print(f"  model:      {client.model}")
    print(f"  endpoint:   {client._endpoint}")
    print(f"  max_tokens: {client.max_tokens}")
    print(f"  temperature:{client.temperature}")
    print()

    # 测试单轮对话
    system = "你是一个可靠的问答助手。请用一句话直接回答，不要多余解释。"
    context = "鲁迅（1881-1936），原名周树人，字豫才，浙江绍兴人，中国现代文学奠基人之一。"
    question = "鲁迅是谁？用一句话回答。"

    print(f"  Q: {question}")
    try:
        reply = client.chat(system, context, question)
        print(f"  A: {reply}")
        print()
        print("  OK 自测通过")
    except Exception as e:
        print(f"  FAIL 自测失败: {e}")
