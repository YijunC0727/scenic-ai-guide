"""
e2e 端到端测试脚本
==================
读取 tests/ 下的题目文件，批量调用 RAG 全链路，输出带回答的 CSV。

用法：
  cd scenic-ai-guide
  python scripts/run_e2e.py                     # 全部 75 题
  python scripts/run_e2e.py --start 1 --end 10  # 前 10 题
  python scripts/run_e2e.py --mode venue        # 只跑场馆题
  python scripts/run_e2e.py --mode luxun        # 只跑数字人题
  python scripts/run_e2e.py --mode edge         # 只跑边缘题

产出：
  docs/e2e-scores.csv   带回答的评分表（分数栏留空，手动填）
"""

import csv
import os
import sys
import re
import time
import logging
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from rag_pipeline import RAGPipeline, ConversationState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("e2e")

TESTS_DIR = os.path.join(ROOT_DIR, "tests")
CSV_OUT = os.path.join(ROOT_DIR, "docs", "e2e-scores.csv")

CSV_COLUMNS = [
    "序号", "问题ID", "问题", "模式",
    "回答", "准确性(1-5)", "鲁味(1-5)", "流畅度(1-5)", "安全性(1-5)",
    "综合分", "备注",
]


def parse_venue_questions():
    """解析 tests/venue_questions.txt，格式 V001|问题"""
    path = os.path.join(TESTS_DIR, "venue_questions.txt")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "|" not in line:
                continue
            qid, question = line.split("|", 1)
            rows.append((qid.strip(), question.strip(), "讲解"))
    return rows


def parse_luxun_questions():
    """解析 tests/luxun_questions.txt，格式 L001|问题"""
    path = os.path.join(TESTS_DIR, "luxun_questions.txt")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "|" not in line:
                continue
            qid, question = line.split("|", 1)
            rows.append((qid.strip(), question.strip(), "数字人"))
    return rows


def parse_edge_questions():
    """解析 tests/edge_cases.txt，带 # 注释和分类标题"""
    path = os.path.join(TESTS_DIR, "edge_cases.txt")
    rows = []
    mode = "模糊"
    count = 0

    # 分类标题下方的说明文字（不是题目）
    skip_patterns = ["游客问题在", "同一句话同时包含", "测试系统对有害"]

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 跳过注释行和分隔线
            if line.startswith("#") or line.startswith("="):
                continue
            # 跳过说明文字
            if any(line.startswith(p) for p in skip_patterns):
                continue
            # 检测分类标题
            if "模糊意图" in line:
                mode = "模糊"
                continue
            elif "混合意图" in line:
                mode = "混合"
                continue
            elif "恶意输入" in line or "鲁棒性" in line:
                mode = "恶意"
                continue
            # 问题行
            count += 1
            qid = f"E{count:03d}"
            rows.append((qid, line, mode))

    return rows


def build_question_list(mode_filter=None):
    """合并三类题目"""
    all_rows = []

    if mode_filter is None or mode_filter == "venue":
        all_rows.extend(parse_venue_questions())

    if mode_filter is None or mode_filter == "luxun":
        all_rows.extend(parse_luxun_questions())

    if mode_filter is None or mode_filter == "edge":
        all_rows.extend(parse_edge_questions())

    return all_rows


def run(start_idx=1, end_idx=None, mode_filter=None):
    """执行端到端测试"""
    all_q = build_question_list(mode_filter)
    total = len(all_q)

    if end_idx is None:
        end_idx = total
    end_idx = min(end_idx, total)
    start_idx = max(1, start_idx)

    os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)

    logger.info("初始化 RAG 管线...")
    pipeline = RAGPipeline()
    logger.info("管线就绪。范围：%d-%d / %d 题\n", start_idx, end_idx, total)

    results = []

    for idx in range(start_idx - 1, end_idx):
        qid, question, mode = all_q[idx]
        seq = idx + 1

        logger.info("[%d/%d] %s | %s", seq, total, qid, question[:60])

        # 每题独立，重置对话状态
        pipeline.state = ConversationState()

        start = time.time()
        try:
            reply = pipeline.ask(question)
        except Exception as e:
            reply = f"[ERROR] {e}"
            logger.error("  失败: %s", e)

        elapsed = time.time() - start
        intent = pipeline.state.current_intent
        logger.info("  intent=%s  time=%.1fs  reply=%s...", intent, elapsed, reply[:80])

        results.append({
            "序号": seq,
            "问题ID": qid,
            "问题": question,
            "模式": mode,
            "回答": reply,
            "准确性(1-5)": "",
            "鲁味(1-5)": "",
            "流畅度(1-5)": "",
            "安全性(1-5)": "",
            "综合分": "",
            "备注": f"intent={intent} time={elapsed:.1f}s",
        })

    # 写出 CSV
    with open(CSV_OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(results)

    logger.info("\n✅ 完成。结果: %s", CSV_OUT)
    logger.info("回答已填充，评分栏请手动填写（准确性/鲁味/流畅度/安全性 1-5）")
    logger.info("综合分 = 准确性×0.35 + 鲁味×0.30 + 流畅度×0.20 + 安全性×0.15")

    return results


def main():
    parser = argparse.ArgumentParser(description="e2e 端到端测试")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--mode", choices=["venue", "luxun", "edge"], default=None)
    args = parser.parse_args()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\ne2e 测试 " + now_str)
    mode_label = "全部" if args.mode is None else args.mode
    end_label = args.end or "末尾"
    print("范围: " + mode_label + " (" + str(args.start) + "-" + str(end_label) + ")\n")

    run(start_idx=args.start, end_idx=args.end, mode_filter=args.mode)


if __name__ == "__main__":
    main()
