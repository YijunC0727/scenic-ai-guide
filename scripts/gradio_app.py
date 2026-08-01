"""
Gradio 聊天界面
==============
对接 rag_pipeline.py，提供双模式（讲解/数字人）对话界面。

用法：
  cd scenic-ai-guide
  python scripts/gradio_app.py

功能：
  - 输入框 + 对话区
  - 实时显示当前模式（讲解员 / 鲁迅数字人）
  - 重置对话按钮
  - 自动意图识别，无需手动切换模式
"""

import sys
import os

import gr

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

# ---------- 延迟导入：启动时给用户友好的加载提示 ----------

_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        print("正在加载 RAG 全链路（BGE 模型 + ChromaDB + LLM 客户端）...")
        from rag_pipeline import RAGPipeline, ConversationState
        _pipeline = RAGPipeline()
        print("加载完成。")
    return _pipeline


def reset_pipeline():
    global _pipeline
    if _pipeline is not None:
        from rag_pipeline import ConversationState
        _pipeline.state = ConversationState()


# ---------- 意图 → 中文标签 ----------

INTENT_LABELS = {
    "narrator":  "🏛️ 讲解员模式",
    "luxun":     "🎭 鲁迅数字人",
    "ambiguous": "🎭 鲁迅数字人（自动）",
    "reject_time":        "⚠️ 时间越界·已拦截",
    "reject_irrelevant":  "🚫 无关内容·已拒绝",
}


def current_mode_label():
    pipeline = get_pipeline()
    intent = pipeline.state.current_intent
    return INTENT_LABELS.get(intent, f"❓ {intent}")


# ---------- 核心回调 ----------

def respond(message, history):
    """处理用户输入，调用 RAG 管线，返回聊天记录和模式标签。"""
    if not message or not message.strip():
        return history, current_mode_label()

    pipeline = get_pipeline()

    try:
        reply = pipeline.ask(message.strip())
    except Exception as e:
        reply = f"（生成回答时出错：{e}）"

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})

    return history, current_mode_label()


def reset_chat():
    """清空对话历史和管线状态。"""
    reset_pipeline()
    return [], "🔄 对话已重置"


# ---------- Gradio UI ----------

def create_ui():
    import gradio as gr

    css = """
    .mode-display textarea {
        font-size: 16px !important;
        font-weight: 600 !important;
        text-align: center !important;
        background: #f0f4f8 !important;
        border: 1px solid #d0d7de !important;
    }
    .guide-box {
        font-size: 13px;
        color: #57606a;
        line-height: 1.7;
    }
    footer { display: none !important; }
    """

    with gr.Blocks(title="鲁迅数字人 · 双模式对话") as demo:
        # ---- 标题 ----
        gr.Markdown(
            """
            # 🏛️ 鲁迅数字人 · 双模式对话系统
            **讲解员模式** · 回答场馆、展品、参观信息 ｜ **数字人模式** · 以鲁迅口吻与你对话
            """
        )

        with gr.Row():
            # ---- 左侧：聊天区 ----
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[],
                    height=520,
                    label="对话",
                    placeholder="输入你的问题开始对话...",
                )

                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="输入问题，如「鲁迅先生，您为什么要弃医从文？」",
                        label="",
                        scale=5,
                        container=False,
                    )
                    submit_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Row():
                    reset_btn = gr.Button("🔄 重置对话", variant="secondary", size="sm")
                    gr.Markdown(
                        "直接输入即可 · 系统自动识别讲解/数字人模式",
                        elem_classes="guide-box",
                    )

            # ---- 右侧：信息栏 ----
            with gr.Column(scale=1):
                gr.Markdown("### 当前模式")
                mode_display = gr.Textbox(
                    value="⏳ 正在加载模型...",
                    label="",
                    interactive=False,
                    elem_classes="mode-display",
                    container=True,
                )

                gr.Markdown("---")
                gr.Markdown(
                    """
                    **💡 使用提示**

                    系统会根据你的问题
                    自动判断应该用哪种
                    模式回答你：

                    - 问场馆/展品/参观
                      → 讲解员模式
                    - 问鲁迅生平/作品/
                      思想 → 数字人模式
                    - 既有场馆又有对话
                      → 自动选择

                    **🗣️ 试试这样问**
                    - 这个展厅主要展什么？
                    - 鲁迅先生，您怎么看
                      现在的年轻人？
                    - 您和许广平是怎么
                      认识的？
                    """,
                    elem_classes="guide-box",
                )

        # ---- 事件绑定 ----
        msg.submit(respond, [msg, chatbot], [chatbot, mode_display]).then(
            lambda: "", None, [msg]
        )
        submit_btn.click(respond, [msg, chatbot], [chatbot, mode_display]).then(
            lambda: "", None, [msg]
        )
        reset_btn.click(reset_chat, None, [chatbot, mode_display])

        # ---- 页面加载回调：更新模式标签 ----
        demo.load(lambda: "✅ 就绪 · 等待输入", None, [mode_display])

    return demo


# ---------- 入口 ----------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="鲁迅数字人 Gradio 聊天界面")
    parser.add_argument("--port", type=int, default=7860, help="服务端口（默认 7860）")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="绑定地址")
    parser.add_argument("--share", action="store_true", help="生成公网链接")
    args = parser.parse_args()

    # 启动时预加载管线
    print("正在初始化 RAG 管线...")
    get_pipeline()
    print(f"启动 Gradio 服务 → http://{args.host}:{args.port}")

    demo = create_ui()
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        inbrowser=True
    )
