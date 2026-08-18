"""
查询改写器 — 越界方案第二层
=============================
当意图分类器检测到时间越界风险（time_aware=True）但置信度不足以直接拒绝时，
查询改写器将现代概念映射为1936年前可回答的永恒主题，拆解为1-3个时间安全子查询。

核心策略：
  1. 概念映射：现代词汇 → 永恒主题（如"996工作制" → "劳动与休息"）
  2. 问题拆解：复杂越界问题 → 多个时间安全子问题
  3. 抽象提升：将具体现代场景提升为鲁迅时代的哲学/社会议题
  4. LLM辅助：复杂语义映射由LLM完成（保留规则兜底）

用法：
  from scripts.query_rewriter import QueryRewriter
  rw = QueryRewriter()
  result = rw.rewrite("鲁迅怎么看现代的996工作制？")
  # → RewriteResult(sub_queries=["鲁迅如何看待劳动与休息？", ...], ...)

集成方式（在 rag_pipeline.py 中）：
  意图分类 time_aware=True + 中置信度 → 调 rewrite() → 多子查询分别检索 → 合并结果
"""

import re
import logging
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("query_rewriter")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RewriteResult:
    """改写结果"""
    original: str                                    # 原始问题
    sub_queries: List[str] = field(default_factory=list)   # 改写后的时间安全子查询
    modern_concepts: List[str] = field(default_factory=list)  # 检测到的现代概念
    rewrites: List[Dict[str, str]] = field(default_factory=list)  # [{"concept":..., "strategy":..., "rewrite":...}]
    can_rewrite: bool = True                         # 是否可改写（严重越界则 False）
    fallback_message: str = ""                       # 无法改写时的兜底话术


# ============================================================
# 概念映射表（现代概念 → 永恒主题）
# ============================================================

CONCEPT_MAP: Dict[str, Dict[str, str]] = {
    # ── 工作与劳动 ──
    "996": {
        "theme": "劳动与休息",
        "rewrite_hint": "鲁迅如何看待劳动与休息？他对工人的处境有什么看法？",
    },
    "加班": {
        "theme": "劳动与休息",
        "rewrite_hint": "鲁迅如何看待劳动与休息？他对工人的处境有什么看法？",
    },
    "工作制": {
        "theme": "劳动与休息",
        "rewrite_hint": "鲁迅如何看待劳动与休息？他对工人的处境有什么看法？",
    },
    "内卷": {
        "theme": "社会竞争",
        "rewrite_hint": "鲁迅如何看待社会竞争与人生态度？他对青年的奋斗有什么看法？",
    },
    "躺平": {
        "theme": "人生态度",
        "rewrite_hint": "鲁迅如何看待人生态度？他对'消极'与'积极'有什么论述？",
    },
    "打工人": {
        "theme": "劳动阶层",
        "rewrite_hint": "鲁迅如何看待劳动者和底层人民？他的作品如何描写普通人的处境？",
    },
    "社畜": {
        "theme": "劳动阶层",
        "rewrite_hint": "鲁迅如何看待劳动者和底层人民？他对社会底层有什么同情？",
    },

    # ── 社交媒体与通讯 ──
    "微信": {
        "theme": "通信与交流",
        "rewrite_hint": "鲁迅喜欢用什么方式与人通信？他如何看待书信往来？",
    },
    "微博": {
        "theme": "发表观点",
        "rewrite_hint": "鲁迅喜欢通过什么方式发表自己的观点？他如何看待公共舆论？",
    },
    "抖音": {
        "theme": "大众娱乐",
        "rewrite_hint": "鲁迅如何看待大众娱乐？他对通俗文化和艺术有什么看法？",
    },
    "社交媒体": {
        "theme": "公共舆论",
        "rewrite_hint": "鲁迅如何看待公共舆论和大众传播？他通过什么渠道影响社会？",
    },
    "朋友圈": {
        "theme": "社交与人际",
        "rewrite_hint": "鲁迅如何看待社交与人际关系？他与朋友如何保持联系？",
    },
    "网红": {
        "theme": "名声与影响力",
        "rewrite_hint": "鲁迅如何看待名声与影响力？他对'名人'有什么看法？",
    },
    "直播": {
        "theme": "大众娱乐",
        "rewrite_hint": "鲁迅如何看待大众娱乐？他对通俗文化和艺术有什么看法？",
    },
    "up主": {
        "theme": "创作与表达",
        "rewrite_hint": "鲁迅如何看待创作与自我表达？他为什么选择写作？",
    },
    "博主": {
        "theme": "创作与表达",
        "rewrite_hint": "鲁迅如何看待创作与自我表达？他为什么选择写作？",
    },
    "小红书": {
        "theme": "生活分享",
        "rewrite_hint": "鲁迅如何看待日常生活？他的日记中记录了哪些生活细节？",
    },

    # ── 科技与工具 ──
    "手机": {
        "theme": "通信工具",
        "rewrite_hint": "鲁迅使用什么工具写作和通信？他对技术发明有什么看法？",
    },
    "电脑": {
        "theme": "写作工具",
        "rewrite_hint": "鲁迅使用什么工具写作？他的写作习惯是怎样的？",
    },
    "计算机": {
        "theme": "写作工具",
        "rewrite_hint": "鲁迅使用什么工具写作？他的写作习惯是怎样的？",
    },
    "互联网": {
        "theme": "信息传播",
        "rewrite_hint": "鲁迅如何看待信息传播？他那个时代的新闻和出版物如何流通？",
    },
    "网络": {
        "theme": "信息传播",
        "rewrite_hint": "鲁迅如何看待信息传播？他那个时代的新闻和出版物如何流通？",
    },
    "人工智能": {
        "theme": "技术与人性",
        "rewrite_hint": "鲁迅如何看待技术与人性？他对科学和机械文明有什么看法？",
    },
    "AI": {
        "theme": "技术与人性",
        "rewrite_hint": "鲁迅如何看待技术与人性？他对科学和机械文明有什么看法？",
    },
    "机器人": {
        "theme": "技术与人性",
        "rewrite_hint": "鲁迅如何看待技术与人性？他对科学和机械文明有什么看法？",
    },
    "ChatGPT": {
        "theme": "写作与思考",
        "rewrite_hint": "鲁迅如何看待写作与思考的关系？他怎样看待'代笔'或'模仿'？",
    },
    "算法": {
        "theme": "规则与自由",
        "rewrite_hint": "鲁迅如何看待规则与个人自由？他对社会约束有什么看法？",
    },

    # ── 现代娱乐 ──
    "电影": {
        "theme": "艺术与娱乐",
        "rewrite_hint": "鲁迅如何看待艺术与娱乐？他对戏剧和文学以外的艺术形式有什么看法？",
    },
    "电影院": {
        "theme": "艺术与娱乐",
        "rewrite_hint": "鲁迅如何看待艺术与娱乐？他对戏剧和文学以外的艺术形式有什么看法？",
    },
    "电视剧": {
        "theme": "艺术与娱乐",
        "rewrite_hint": "鲁迅如何看待艺术与娱乐？他对戏剧和文学以外的艺术形式有什么看法？",
    },
    "综艺": {
        "theme": "大众娱乐",
        "rewrite_hint": "鲁迅如何看待大众娱乐？他对通俗文化有什么看法？",
    },
    "游戏": {
        "theme": "消遣与娱乐",
        "rewrite_hint": "鲁迅有什么消遣和娱乐方式？他如何看待'玩'与'学'的关系？",
    },
    "动漫": {
        "theme": "艺术形式",
        "rewrite_hint": "鲁迅如何看待不同的艺术形式？他对美术和插图有什么看法？",
    },
    "电竞": {
        "theme": "竞技与消遣",
        "rewrite_hint": "鲁迅如何看待竞技和消遣？他对体育和竞赛有什么看法？",
    },
    "漫威": {
        "theme": "西方文化",
        "rewrite_hint": "鲁迅如何看待西方文化？他对西方文学和艺术有什么评价？",
    },

    # ── 现代交通 ──
    "高铁": {
        "theme": "交通与旅行",
        "rewrite_hint": "鲁迅如何看待旅行和交通？他的旅行经历是怎样的？",
    },
    "地铁": {
        "theme": "交通与旅行",
        "rewrite_hint": "鲁迅如何看待旅行和交通？他的旅行经历是怎样的？",
    },
    "飞机": {
        "theme": "交通与旅行",
        "rewrite_hint": "鲁迅如何看待旅行和交通？他的旅行经历是怎样的？",
    },

    # ── 现代教育与社会 ──
    "高考": {
        "theme": "教育与考试",
        "rewrite_hint": "鲁迅如何看待教育和考试制度？他对科举和新式教育有什么看法？",
    },
    "考研": {
        "theme": "读书与求学",
        "rewrite_hint": "鲁迅如何看待读书和求学？他对深造和学术研究有什么看法？",
    },
    "留学": {
        "theme": "留学经历",
        "rewrite_hint": "鲁迅的留学经历是怎样的？他如何看待留学和东西方文化交流？",
    },
    "大学": {
        "theme": "教育",
        "rewrite_hint": "鲁迅如何看待大学教育？他在大学任教的经历是怎样的？",
    },

    # ── 经济与消费 ──
    "房价": {
        "theme": "居住与生活",
        "rewrite_hint": "鲁迅如何看待居住和生活条件？他在不同城市的居住经历是怎样的？",
    },
    "买房": {
        "theme": "居住与生活",
        "rewrite_hint": "鲁迅如何看待居住和生活条件？他在不同城市的居住经历是怎样的？",
    },
    "双十一": {
        "theme": "消费与物质",
        "rewrite_hint": "鲁迅如何看待消费和物质生活？他对金钱和物质有什么看法？",
    },
    "网购": {
        "theme": "消费与物质",
        "rewrite_hint": "鲁迅如何看待消费和物质生活？他对金钱和物质有什么看法？",
    },
    "快递": {
        "theme": "通信与物流",
        "rewrite_hint": "鲁迅如何看待书信和物品的传递？他与朋友如何互寄书稿？",
    },
    "外卖": {
        "theme": "日常生活",
        "rewrite_hint": "鲁迅的日常生活是怎样的？他的饮食习惯如何？",
    },

    # ── 当代概念 ──
    "现代年轻人": {
        "theme": "青年",
        "rewrite_hint": "鲁迅如何看待青年？他对青年有什么期望和建议？",
    },
    "年轻人": {
        "theme": "青年",
        "rewrite_hint": "鲁迅如何看待青年？他对青年有什么期望和建议？",
    },
    "当今社会": {
        "theme": "社会",
        "rewrite_hint": "鲁迅如何看待他那个时代的社会？他对社会问题有什么观察？",
    },
    "现代": {
        "theme": "时代变迁",
        "rewrite_hint": "鲁迅如何看待时代变迁？他对'新'与'旧'有什么看法？",
    },
    "当下": {
        "theme": "时代变迁",
        "rewrite_hint": "鲁迅如何看待时代变迁？他对'新'与'旧'有什么看法？",
    },
    "今天": {
        "theme": "时代变迁",
        "rewrite_hint": "鲁迅如何看待时代变迁？他对'新'与'旧'有什么看法？",
    },
    "现在的生活": {
        "theme": "生活",
        "rewrite_hint": "鲁迅如何看待日常生活？他对'如何生活'有什么看法？",
    },
    "奥运会": {
        "theme": "体育与竞技",
        "rewrite_hint": "鲁迅如何看待体育和竞技？他对身体健康有什么看法？",
    },
    "世界杯": {
        "theme": "体育与竞技",
        "rewrite_hint": "鲁迅如何看待体育和竞技？他对身体健康有什么看法？",
    },
    "联合国": {
        "theme": "国际关系",
        "rewrite_hint": "鲁迅如何看待国际关系和世界格局？他对中国在世界上的位置有什么看法？",
    },
    "二战": {
        "theme": "战争与和平",
        "rewrite_hint": "鲁迅如何看待战争与和平？他对日本侵华有什么看法？",
    },
    "原子弹": {
        "theme": "战争与武器",
        "rewrite_hint": "鲁迅如何看待战争与武器？他对暴力与和平有什么看法？",
    },
    "核武器": {
        "theme": "战争与武器",
        "rewrite_hint": "鲁迅如何看待战争与武器？他对暴力与和平有什么看法？",
    },
}


# ============================================================
# 不可改写的模式（严重越界，直接拒绝）
# ============================================================

UNCAN_REWRITE_PATTERNS = [
    # 要求鲁迅提供具体的现代物品/账号信息（无法改写）
    r"(鲁迅|您|你).*(有|有没有).*(手机|微信|QQ|抖音).*(号码|账号|多少|是什么|给.*我|告诉.*我)",
    r"(鲁迅|您|你).*(手机|微信|QQ|抖音).*(账号|号码).*(多少|是什么|哪|给|告诉)",
    # 询问完全不存在的关联（鲁迅 + 现代虚构角色/游戏）
    r"(鲁迅|您|你).*(玩过|打过|通关).*(王者荣耀|原神|吃鸡|LOL|英雄联盟)",
    # 要求生成现代格式的内容（最离谱的越界）
    r"(帮我|给我|替我).*(写.*代码|写.*程序|发.*朋友圈|发.*微博|拍.*视频|做.*直播)",
]


# ============================================================
# LLM 改写提示词
# ============================================================

LLM_REWRITE_SYSTEM_PROMPT = """你是一个查询改写专家，专门处理"时间越界"的用户问题。

背景：用户在向"鲁迅数字人"（模拟1936年去世的鲁迅）提问，但问题中包含了1936年后的现代概念。
你的任务：将越界问题改写为鲁迅可以回答的、基于他生前知识和经验的问题。

规则：
1. 识别问题中的现代概念（如"996"、"微信"、"手机"、"现代年轻人"等）
2. 提取问题的核心意图——用户到底想知道什么？
3. 将现代概念映射为鲁迅时代就存在的永恒主题（如"996"→"劳动与休息"，"微信"→"通信方式"）
4. 生成1-3个改写后的子问题，每个子问题必须：
   - 不包含1936年后的概念
   - 基于鲁迅的知识和经验可以回答
   - 保持原问题的核心关切
5. 如果问题完全无法改写（如问鲁迅手机号码），标记为不可改写

输出格式（严格JSON）：
{
  "can_rewrite": true/false,
  "modern_concepts": ["检测到的现代概念"],
  "sub_queries": ["改写后的子问题1", "改写后的子问题2"],
  "reasoning": "改写思路简述"
}

示例：
用户问："鲁迅怎么看现在的996工作制？"
输出：
{
  "can_rewrite": true,
  "modern_concepts": ["996", "工作制"],
  "sub_queries": [
    "鲁迅如何看待劳动与休息的关系？",
    "鲁迅对工人阶级的处境有什么看法？",
    "鲁迅认为人应该怎样对待工作？"
  ],
  "reasoning": "将'996工作制'映射为永恒主题'劳动与休息'，从鲁迅的社会关怀和劳动观念角度改写"
}

用户问："鲁迅的手机号码是多少？"
输出：
{
  "can_rewrite": false,
  "modern_concepts": ["手机", "号码"],
  "sub_queries": [],
  "reasoning": "问题核心是获取鲁迅的联系方式，完全无时间安全的等价问题"
}
"""

LLM_REWRITE_USER_TEMPLATE = """用户原始问题：{query}

意图分类结果：{intent_info}

请将上述问题改写为鲁迅（1881-1936）可以回答的时间安全子问题。"""


# ============================================================
# QueryRewriter
# ============================================================

class QueryRewriter:
    """查询改写器 —— 越界方案第二层核心"""

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLMClient 实例，用于复杂改写。为 None 时仅使用规则改写。
        """
        self._llm = llm_client

        # 编译不可改写模式
        self._uncant_rewrite_res = [
            re.compile(p) for p in UNCAN_REWRITE_PATTERNS
        ]

    # ---- 主入口 ----

    def rewrite(
        self,
        query: str,
        intent_result: Optional[dict] = None,
        use_llm: bool = True,
    ) -> RewriteResult:
        """
        对时间越界查询进行改写。

        Args:
            query:         用户原始问题
            intent_result: 意图分类器输出（可选，用于获取 matched 信息）
            use_llm:       是否启用 LLM 辅助改写

        Returns:
            RewriteResult
        """
        query = query.strip()

        # Step 0: 检查是否完全不可改写
        uncan_check = self._check_uncant_rewrite(query)
        if uncan_check:
            return uncan_check

        # Step 1: 规则提取现代概念
        modern_concepts = self._extract_modern_concepts(query, intent_result)

        if not modern_concepts:
            # 没有检测到明确的现代概念，可能不需要改写
            return RewriteResult(
                original=query,
                sub_queries=[query],
                modern_concepts=[],
                can_rewrite=True,
            )

        # Step 2: 规则改写（基于概念映射表）
        rule_result = self._rule_based_rewrite(query, modern_concepts)

        # Step 3: 如果规则改写不够（子查询太少或为空），尝试 LLM 改写
        if use_llm and self._llm and (
            len(rule_result.sub_queries) < 2 or not rule_result.can_rewrite
        ):
            try:
                llm_result = self._llm_based_rewrite(query, modern_concepts, intent_result)
                if llm_result and llm_result.sub_queries:
                    # 合并规则和LLM结果，去重
                    merged = list(dict.fromkeys(
                        rule_result.sub_queries + llm_result.sub_queries
                    ))
                    rule_result.sub_queries = merged[:5]  # 最多5个子查询
                    rule_result.rewrites.extend(llm_result.rewrites)
                    if llm_result.fallback_message:
                        rule_result.fallback_message = llm_result.fallback_message
            except Exception as e:
                logger.warning("LLM 改写失败，使用规则结果: %s", e)

        # Step 4: 确保至少一个子查询
        if not rule_result.sub_queries:
            # 最后兜底：尝试提取问句中的人/事/观点核心
            fallback = self._extract_core_question(query)
            if fallback:
                rule_result.sub_queries = [fallback]
            else:
                rule_result.can_rewrite = False
                rule_result.fallback_message = (
                    "这个问题涉及太多我无法理解的概念。"
                    "我生于光绪七年（1881年），殁于民国二十五年（1936年），"
                    "怕是无法回答关于这些后来事物的问题。"
                )

        return rule_result

    # ---- 不可改写检测 ----

    def _check_uncant_rewrite(self, query: str) -> Optional[RewriteResult]:
        """检查是否为完全不可改写的越界问题"""
        for pat in self._uncant_rewrite_res:
            if pat.search(query):
                return RewriteResult(
                    original=query,
                    sub_queries=[],
                    modern_concepts=[],
                    can_rewrite=False,
                    fallback_message=(
                        "这大约是什么新奇的东西罢。"
                        "我生于光绪七年，殁于民国二十五年，怕是未曾见过。"
                        "大抵是我所不能知道的事了。"
                    ),
                )
        return None

    # ---- 现代概念提取 ----

    def _extract_modern_concepts(
        self, query: str, intent_result: Optional[dict] = None
    ) -> List[str]:
        """从查询中提取现代概念词"""
        found = []

        # 从意图分类结果获取 matched
        if intent_result and intent_result.get("matched"):
            matched = intent_result["matched"]
            # 过滤出概念映射表中存在的
            for item in matched:
                # item 可能是关键词或正则模式
                for concept in CONCEPT_MAP:
                    if concept in item or concept in query:
                        if concept not in found:
                            found.append(concept)

        # 扫描概念映射表
        for concept in CONCEPT_MAP:
            if concept in query and concept not in found:
                found.append(concept)

        # 长概念优先（如"社交媒体"优先于"媒体"）
        found.sort(key=lambda x: -len(x))

        return found

    # ---- 规则改写 ----

    def _rule_based_rewrite(
        self, query: str, modern_concepts: List[str]
    ) -> RewriteResult:
        """基于概念映射表的规则改写"""
        sub_queries = []
        rewrites = []
        themes_seen = set()

        for concept in modern_concepts:
            mapping = CONCEPT_MAP.get(concept)
            if not mapping:
                continue

            theme = mapping["theme"]
            rewrite_hint = mapping["rewrite_hint"]

            # 同一主题不重复
            if theme in themes_seen:
                continue
            themes_seen.add(theme)

            # 提取改写提示中的问句
            questions = self._parse_rewrite_hint(rewrite_hint, query)

            for q in questions:
                if q not in sub_queries:
                    sub_queries.append(q)

            rewrites.append({
                "concept": concept,
                "strategy": f"概念映射 → {theme}",
                "theme": theme,
                "rewrite": " | ".join(questions),
            })

        # 如果没有提取到问句，尝试模式改写
        if not sub_queries:
            fallback_qs = self._pattern_based_rewrite(query, modern_concepts)
            sub_queries.extend(fallback_qs)

        return RewriteResult(
            original=query,
            sub_queries=sub_queries,
            modern_concepts=modern_concepts,
            rewrites=rewrites,
            can_rewrite=len(sub_queries) > 0,
        )

    def _parse_rewrite_hint(self, hint: str, original_query: str) -> List[str]:
        """从改写提示中提取独立的问句"""
        questions = []
        # 按中文问号或句号分割
        parts = re.split(r'[？?。；;]', hint)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 确保是完整的问句
            if "鲁迅" in part and ("什么" in part or "如何" in part or
                                    "怎样" in part or "为什么" in part or
                                    "是否" in part or "哪" in part):
                questions.append(part + "？")
            elif "鲁迅" in part and ("看法" in part or "态度" in part or
                                      "评价" in part or "观点" in part):
                questions.append(part + "？")

        # 如果 hint 本身就是一个完整的改写提示，直接使用
        if not questions and hint:
            questions.append(hint.strip().rstrip("。；;") + "？")

        return questions[:3]

    def _pattern_based_rewrite(
        self, query: str, modern_concepts: List[str]
    ) -> List[str]:
        """基于句式的通用改写模式"""

        results = []

        # 模式1: "如果/假如...活在今天/现代..." → 提取核心关切
        pattern_hypothesis = re.compile(
            r'(如果|假如|假设|倘若).*(鲁迅|你).*(活在|生活在|来到|穿越到).*(今天|现代|当代|现在|当下)'
        )
        if pattern_hypothesis.search(query):
            # 尝试提取"会怎样/会如何/会怎么"后面的内容
            core_match = re.search(
                r'(会|将会|可能).*(如何看待|如何评价|怎样|怎么|做什么|成为|选择|面对)',
                query
            )
            if core_match:
                topic = query[core_match.start():]
                # 泛化为永恒主题
                results.append(f"鲁迅{topic.replace('现代', '').replace('今天', '').replace('当下', '')}？")

        # 模式2: "用鲁迅的口吻/语言/风格评价..." → 提取评价对象
        pattern_comment = re.compile(
            r'(用|请用|请你用).*(鲁迅|你).*(口吻|语言|风格|语气).*(评价|谈谈|说说|看待)'
        )
        if pattern_comment.search(query):
            # 提取评价对象
            after = query.split("评价")[-1] if "评价" in query else \
                   query.split("谈谈")[-1] if "谈谈" in query else \
                   query.split("说说")[-1] if "说说" in query else \
                   query.split("看待")[-1] if "看待" in query else ""
            after = after.strip().rstrip("。！!？?")
            if after:
                # 去掉明确现代标记
                cleaned = after
                for c in modern_concepts:
                    cleaned = cleaned.replace(c, "")
                cleaned = cleaned.strip("的的了呢吗吧啊")
                if cleaned:
                    results.append(f"鲁迅对{cleaned}有什么看法？")

        # 模式3: "...会不会/会...吗" → 转为他那个时代可回答的形式
        pattern_would = re.compile(r'(鲁迅|你).*(会不会|会|可能).*(喜欢|讨厌|用|玩|看|参加)')
        if pattern_would.search(query):
            verb_match = re.search(r'(喜欢|讨厌|用|玩|看|参加|做)(.+)', query)
            if verb_match:
                activity = verb_match.group(2).strip().rstrip("？?。！!")
                # 去掉现代概念
                for c in modern_concepts:
                    activity = activity.replace(c, "")
                activity = activity.strip("的的了呢吗吧啊？?！!。")
                if activity:
                    verb = verb_match.group(1)
                    verb_map = {
                        "喜欢": "喜好与态度",
                        "讨厌": "喜好与态度",
                        "用": "工具与习惯",
                        "玩": "消遣与娱乐",
                        "看": "阅读与欣赏",
                        "参加": "社会活动",
                        "做": "行为与选择",
                    }
                    theme = verb_map.get(verb, "看法")
                    results.append(f"鲁迅对{activity}有什么{theme}？")

        # 去重
        return list(dict.fromkeys(results))

    # ---- 核心问题提取（兜底） ----

    def _extract_core_question(self, query: str) -> Optional[str]:
        """从越界问题中提取核心问句（最保守的兜底策略）"""
        # 移除明确的时间越界标记
        cleaned = query
        time_markers = [
            "现代", "当今", "现在", "当下", "今天", "目前",
            "如果.*活在", "假如.*来到", "假设.*穿越",
        ]
        for tm in time_markers:
            cleaned = re.sub(tm, "", cleaned)

        # 提取"鲁迅...?"的核心部分
        core_match = re.search(
            r'(鲁迅|他).*(如何看待|如何评价|有什么|是怎样|为什么|是否|是什么|怎么|怎样|什么|哪)',
            cleaned
        )
        if core_match:
            return cleaned.strip().rstrip("，,。！!？?") + "？"

        return None

    # ---- LLM 改写 ----

    def _llm_based_rewrite(
        self,
        query: str,
        modern_concepts: List[str],
        intent_result: Optional[dict] = None,
    ) -> Optional[RewriteResult]:
        """使用 LLM 进行语义改写"""
        if not self._llm:
            return None

        intent_info = ""
        if intent_result:
            intent_info = (
                f"intent={intent_result.get('intent')}, "
                f"confidence={intent_result.get('confidence')}, "
                f"matched={intent_result.get('matched', [])}"
            )

        user_prompt = LLM_REWRITE_USER_TEMPLATE.format(
            query=query,
            intent_info=intent_info or "无",
        )

        try:
            response = self._llm.chat(
                system_prompt=LLM_REWRITE_SYSTEM_PROMPT,
                context="",
                user_query=user_prompt,
                temperature=0.2,
            )
        except Exception as e:
            logger.error("LLM 改写调用失败: %s", e)
            return None

        # 解析 JSON 响应
        import json
        try:
            # 尝试提取 JSON 块
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
            else:
                logger.warning("LLM 未返回有效 JSON: %s", response[:200])
                return None

            return RewriteResult(
                original=query,
                sub_queries=data.get("sub_queries", []),
                modern_concepts=data.get("modern_concepts", modern_concepts),
                rewrites=[{
                    "concept": ", ".join(data.get("modern_concepts", [])),
                    "strategy": f"LLM改写 → {data.get('reasoning', '')}",
                }],
                can_rewrite=data.get("can_rewrite", True),
                fallback_message=data.get("fallback_message", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("LLM 返回解析失败: %s\n%s", e, response[:300])
            return None


# ============================================================
# 便捷函数
# ============================================================

def rewrite_query(
    query: str,
    intent_result: Optional[dict] = None,
    llm_client=None,
) -> RewriteResult:
    """便捷函数：对时间越界查询进行改写"""
    rw = QueryRewriter(llm_client=llm_client)
    return rw.rewrite(query, intent_result)


# ============================================================
# 自测
# ============================================================

def _run_tests():
    """内置测试用例"""
    test_cases = [
        # (输入, 预期是否可改写, 预期子查询数>=)
        ("鲁迅怎么看现在的996工作制？", True, 1),
        ("如果鲁迅活在今天，他会用微信吗？", True, 1),
        ("请用鲁迅的口吻评价一下现代年轻人的压力", True, 1),
        ("鲁迅会喜欢看漫威电影吗？", True, 1),
        ("鲁迅如何看待社交媒体对舆论的影响？", True, 1),
        ("如果鲁迅活在当代，他会如何评价中国的教育？", True, 1),
        ("鲁迅平时刷抖音吗？", True, 1),
        ("鲁迅先生，您的手机号码是多少？", False, 0),
        ("鲁迅有没有微信账号？", False, 0),
        ("鲁迅如何看待人工智能对未来社会的影响？", True, 1),
        ("鲁迅对当今社会的内卷现象有什么看法？", True, 1),
        ("鲁迅如果参加奥运会能拿什么项目？", True, 1),
        ("鲁迅如何看待现代年轻人的躺平文化？", True, 1),
    ]

    rw = QueryRewriter()

    print("=" * 70)
    print("Query Rewriter Self-Test")
    print("=" * 70)

    passed = 0
    failed = 0

    for query, expected_can_rewrite, min_sub_queries in test_cases:
        result = rw.rewrite(query, use_llm=False)

        ok = True
        issues = []

        if result.can_rewrite != expected_can_rewrite:
            ok = False
            issues.append(f"can_rewrite: expected {expected_can_rewrite}, got {result.can_rewrite}")

        if expected_can_rewrite and len(result.sub_queries) < min_sub_queries:
            ok = False
            issues.append(f"not enough sub_queries: {len(result.sub_queries)} < {min_sub_queries}")

        if ok:
            passed += 1
        else:
            failed += 1

        status = "PASS" if ok else "FAIL"
        print(f"\n[{status}] Q: {query}")
        print(f"   can_rewrite: {result.can_rewrite} | concepts: {result.modern_concepts}")
        if result.sub_queries:
            for i, sq in enumerate(result.sub_queries, 1):
                print(f"   [{i}] {sq}")
        if issues:
            print(f"   *** {'; '.join(issues)}")
        if result.fallback_message:
            print(f"   fallback: {result.fallback_message[:80]}...")

    print(f"\n{'=' * 70}")
    print(f"Result: {passed} pass / {failed} fail (total {len(test_cases)})")
    print(f"Accuracy: {passed / len(test_cases) * 100:.1f}%")
    print()

    return passed, failed


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-5s | %(message)s",
    )
    _run_tests()
