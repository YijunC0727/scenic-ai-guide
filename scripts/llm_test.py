"""
LLM API 快速测试脚本（薄封装 LLMClient）
=======================================
用法:
  python scripts/llm_test.py                              # 默认测试
  python scripts/llm_test.py --question "鲁迅的原名是什么？"  # 自定义问题
  python scripts/llm_test.py --multi-turn                  # 多轮对话测试
  python scripts/llm_test.py --stress 10                   # 压力测试（N次调用）
"""

import os
import sys
import time
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from llm_client import LLMClient


def main():
    parser = argparse.ArgumentParser(description="LLM API 快速测试")
    parser.add_argument("--question", "-q", type=str, default="鲁迅是谁？用一句话回答。",
                        help="测试问题")
    parser.add_argument("--model", type=str, default=None, help="模型名（覆盖 .env）")
    parser.add_argument("--multi-turn", action="store_true", help="多轮对话测试")
    parser.add_argument("--stress", type=int, default=0, help="压力测试（连续N次调用）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    args = parser.parse_args()

    try:
        client = LLMClient(model=args.model)
    except ValueError as e:
        print(f"❌ 初始化失败: {e}")
        print("请检查 .env 文件中的 LLM_API_KEY, LLM_BASE_URL, LLM_MODEL 配置")
        return

    print(f"LLM 客户端就绪 | model={client.model} | endpoint={client._endpoint}")

    # 单次测试
    system = "你是一个可靠的问答助手。请直接回答，不要输出多余解释。"
    context = ""
    try:
        reply = client.chat(system, context, args.question)
        print(f"\nQ: {args.question}")
        print(f"A: {reply}")
        if args.verbose:
            print(f"\nToken 用量: {client.token_usage}")
    except Exception as e:
        print(f"❌ 单次测试失败: {e}")
        return

    # 多轮对话测试
    if args.multi_turn:
        print("\n--- 多轮对话测试 ---")
        questions = [
            "鲁迅是谁？",
            "他为什么弃医从文？",
            "他最喜欢的作品是什么？",
        ]
        for i, q in enumerate(questions, 1):
            try:
                reply = client.chat_with_history(
                    system_prompt="你是一位鲁迅研究专家，请使用鲁迅的口吻回答问题。",
                    context="",
                    user_query=q,
                )
                print(f"[{i}] Q: {q}")
                print(f"[{i}] A: {reply[:100]}...")
            except Exception as e:
                print(f"[{i}] ❌ 失败: {e}")
                break

    # 压力测试
    if args.stress > 0:
        print(f"\n--- 压力测试 ({args.stress} 次) ---")
        success = 0
        times = []
        for i in range(args.stress):
            t0 = time.time()
            try:
                client.chat(system, context, f"测试 #{i+1}: {args.question}")
                success += 1
                times.append(time.time() - t0)
                print(f"  #{i+1}: OK ({times[-1]:.1f}s)")
            except Exception as e:
                print(f"  #{i+1}: FAIL ({e})")
        avg_time = sum(times) / len(times) if times else 0
        print(f"\n结果: {success}/{args.stress} 成功, 平均耗时 {avg_time:.1f}s")
        if args.verbose:
            print(f"Token 用量: {client.token_usage}")
            print(f"熔断器状态: {client.circuit_status}")


if __name__ == "__main__":
    main()
