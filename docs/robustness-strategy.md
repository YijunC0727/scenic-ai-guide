# 鲁棒性策略文档 — 阶段三

> **版本**: v1.0   
> **Owner**: 张嘉欣  

---

## 一、5层防护架构

```
用户输入
    │
    ▼
┌─ Layer 1: 意图分类器 ──────────────────────────────────┐
│  intent_classifier.py — 5分类 + Prompt注入检测           │
│  reject_irrelevant / reject_time → 直接拦截              │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─ Layer 2: 查询改写器 ──────────────────────────────────┐
│  query_rewriter.py — 50+现代概念映射 → 3种改写策略       │
│  将"鲁迅怎么看互联网" → "鲁迅对报纸/通讯媒介的看法"        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─ Layer 3: 多子查询检索合并 ────────────────────────────┐
│  rag_pipeline.py:_retrieve_multi() — 去重排序            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─ Layer 4: System Prompt 时间边界 ──────────────────────┐
│  "我只知道1936年10月之前的事"  —  prompt层约束           │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
                  LLM 生成回答
                       │
                       ▼
┌─ Layer 5: QualityGuard 回答后卫 ←  阶段三新增 ──────┐
│  quality_guard.py                                        │
│  ├─ HallucinationChecker: NER抽取 → 事实比对            │
│  ├─ ConsistencyChecker: 时间边界 + 口吻 + 风格           │
│  └─ 裁决: PASS → 输出 / AMEND → 追加声明 / RETRY → 重试  │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
                  文本输出 → TTS
```

---

## 二、核心模块设计

### 2.1 幻觉检测器 (`hallucination_checker.py`)

**设计原则**: 不引入新模型，用 jieba 分词 + 正则 + 复用 BGE embedding。

**流程**:
```
LLM回答 → Step 1: NER抽取（人名/地名/年份/日期/作品名/数字+量词）
        → Step 2: 过滤非事实声明（AI模板句/鲁迅风格句式）
        → Step 3: 上下文比对（精确匹配 → 语义相似度 @ BGE）
        → Step 4: 分类裁决
```

### 2.2 一致性校验器 (`consistency_checker.py`)

**三层规则引擎**:

#### Layer A: 时间边界检查

| 检查项 | 规则 | 严重度 |
|--------|------|--------|
| 1936年后具体年份 | 正则 `(194\d|195\d|...|202\d)年` | high |
| 现代关键词 | 50+关键词库（互联网/AI/微信/高铁/996…） | high |
| 后代人物 | 莫言/村上春树/余华/金庸… | high |
| 当代政治 | 习近平/邓小平/改革开放… | high |
| 时间穿越场景 | "如果鲁迅活在今天…" 且未拒绝 | high |

**豁免规则**: 如果回答中包含"我不知道""不是我所能知道的""属于另一个时代"等拒绝语，即使出现现代关键词也不处罚。

#### Layer B: 角色口吻检查

| 检查项 | 规则 | 严重度 |
|--------|------|--------|
| AI自称 | "作为AI""根据我的知识库""基于资料显示" | high |
| 网络用语 | yyds/绝绝子/躺平/内卷/get到… | high |
| 现代句式 | "首先…其次…最后""综上所述""值得一提的是" | medium |
| AI模板结尾 | "希望对您有帮助！""如有问题欢迎继续提问" | medium |
| 讲解员串词 | 讲解模式下鲁迅不该用第一人称"我" | medium |

#### Layer C: 风格合规检查

| 指标 | 阈值 | 意义 |
|------|------|------|
| 虚词密度 | < 2个/百字 → 偏低 | "大抵/大约/然而/却/竟/似乎"密度 |
| 平均句长 | > 40字 → 偏长 | 鲁迅风格应 < 30字 |
| 反讽标记 | 0个 → 太"平" | 缺少"自然是了""原是如此""好得很"等 |
| 风格句式 | < 2个 → 偏少 | "我想…""这大约…""却也未必…"等 |

**评分公式**:
```
score = 1.0 - (high时间违规 × 0.20 × 1.5) - (med时间违规 × 0.20 × 1.0)
            - (high口吻违规 × 0.15 × 1.5) - (med口吻违规 × 0.15 × 1.0)
最低为 0.0，最高为 1.0
```

### 2.3 质量守卫 (`quality_guard.py`)

**裁决矩阵**:

| 幻觉得分 | 一致性得分 | 裁决 | 动作 |
|----------|-----------|------|------|
| ≥ 0.70 | ≥ 0.80 | **PASS** | 直接输出 |
| 0.50~0.70 | ≥ 0.60 | **AMEND** | 末尾追加鲁迅口吻边界声明 |
| ≥ 0.50 | 0.60~0.80 | **AMEND** | 追加时间边界声明 |
| < 0.50 | 任意 | **RETRY** | temperature↓0.15 重试 |
| 任意 | < 0.60 | **RETRY** | temperature↓0.15 重试 |
| 重试后再RETRY | — | **FALLBACK** | 兜底话术 |

**边界声明模板**（鲁迅口吻）:

```
# 时间边界
"——写到这里，我倒要说明一下：你方才问的事物，大致是1936年我闭眼之后的事了。
我毕竟只知道1936年前的事，那些后起的概念，我是无从了解的。"

# 幻觉警告
"——不过上面这些话里，有些细节我的记忆未必准确。
倘若与你所知的有所不同，还望以可靠的史料为准。"
```

### 3.4 超时熔断与优雅降级 (`llm_client.py`)

**熔断器设计**:

```
连续失败计数: 0 → 1 → 2 → 3 → 4 → 5 → 熔断打开（冷却60s）
                          ↑ 每次成功则归零
```

**错误分级降级**:

| 级别 | 场景 | 用户看到 |
|------|------|---------|
| L1 | 检索为空 | "关于此事，我手头的资料有限，恐怕难以给出确切的回答。" |
| L2 | LLM 超时(30s) | "这问题我得想想……（系统暂时繁忙，请稍后再问）" |
| L3 | LLM 不可用 | "这大约是什么缘故呢——我此刻竟想不起来了。你先问些别的罢。" |
| L4 | QualityGuard RETRY 耗尽 | 兜底话术（按意图选择鲁迅/讲解员口吻） |

**API调用改进**:
- 超时阈值从60s降至30s
- 防御式响应解析: `data.get("choices",[{}])[0].get("message",{}).get("content","")`
- Token用量追踪: `total_prompt_tokens`, `total_completion_tokens`
- HTTP状态码区分: 4xx(除429)不重试，5xx重试3次，429(Rate Limit)加倍等待
- 熔断器: 连续5次失败 → 60s冷却 → 自动复位

---

## 四、自动化评估 (`eval_runner.py`)

**评估流程**:
```
加载 tests/robustness_cases.json (40条)
    │
    ▼
逐条 → RAGPipeline.ask(question, return_retrieval=True)
    │
    ├─→ HallucinationChecker.check(response, chunks)
    ├─→ ConsistencyChecker.check(response, intent, question)
    │
    ▼
综合评分: auto_score = hallucination_score × 0.5 + consistency_score × 0.5
    │
    ▼
输出: CSV详情 + Markdown汇总报告
```

**自动评分维度**:

| 维度 | 自动判定项 | 方法 |
|------|-----------|------|
| 幻觉检测 | 标记数量 | HallucinationChecker |
| 一致性 | 时间违规+口吻违规 | ConsistencyChecker |
| 综合 | 加权平均 | auto_score |
| 判定 | auto_score ≥ 0.75 → PASS, ≥ 0.50 → WARN, < 0.50 → FAIL | — |

**输出**:
- `docs/eval-results-YYYYMMDD-HHMM.csv` — 含自动评分 + 人工评分空列
- `docs/eval-results-YYYYMMDD-HHMM.md` — 汇总统计 + 按类别/严重度分析

---

## 五、测试用例体系

| 文件 | 数量 | 类别 | 贡献者 |
|------|------|------|--------|
| `tests/robustness_cases.json` | 40 | 幻觉诱导(H001-015) + 时间边界(T001-015) + 知识盲区(K001-010) | 窦一禾 |
| `tests/luxun_questions.txt` | 30 | 数字人模式问题 | 杜佳琳 |
| `tests/venue_questions.txt` | 25 | 讲解模式问题 | 杜佳琳 |
| `tests/edge_cases.txt` | 26 | 模糊/混合/恶意输入 | 杜佳琳 |
| `tests/adversarial_cases.txt` | 🟡 待扩展 | Prompt注入变体 | 窦一禾 |
| `tests/fact_check_cases.txt` | 🟡 待扩展 | 事实核查用例 | 窦一禾 |
| `tests/multi_turn_cases.txt` | 🟡 待扩展 | 多轮对话场景 | 窦一禾 |

---

## 六、阈值配置汇总

| 参数 | 默认值 | 位置 | 说明 |
|------|--------|------|------|
| `SIM_THRESHOLD_VERIFIED` | 0.82 | `hallucination_checker.py` | ≥此值→事实已验证 |
| `SIM_THRESHOLD_PLAUSIBLE` | 0.65 | `hallucination_checker.py` | ≥此值→基本可信 |
| `WEIGHT_UNSUPPORTED` | 0.25 | `hallucination_checker.py` | 每个无支撑声明的扣分 |
| `WEIGHT_CONTRADICTED` | 0.40 | `hallucination_checker.py` | 每个矛盾声明的扣分 |
| `THRESHOLD_HALLUCINATION` | 0.50 | `quality_guard.py` | 低于此→RETRY |
| `THRESHOLD_CONSISTENCY` | 0.60 | `quality_guard.py` | 低于此→RETRY |
| `THRESHOLD_AMEND_H` | 0.70 | `quality_guard.py` | 低于此→AMEND |
| `THRESHOLD_AMEND_C` | 0.80 | `quality_guard.py` | 低于此→AMEND |
| `DEFAULT_TIMEOUT` | 30s | `llm_client.py` | API调用超时 |
| `_circuit_failure_threshold` | 5 | `llm_client.py` | 连续失败触发熔断 |
| `_circuit_cooldown_sec` | 60s | `llm_client.py` | 熔断冷却时间 |
| `THRESHOLD_PASS` | 0.75 | `eval_runner.py` | 综合评分≥此→PASS |
| `THRESHOLD_WARN` | 0.50 | `eval_runner.py` | 综合评分≥此→WARN |

---

## 七、已知局限与后续改进

| 局限 | 说明 | 改进方向 |
|------|------|---------|
| NER依赖jieba | 对人名/地名的识别受jieba词表限制 | 引入专用NER模型（如hanlp）或LLM辅助实体抽取 |
| 语义比对精度 | BGE small模型对细粒度事实比对有局限 | 可升级为BGE-large或引入cross-encoder重排序 |
| 缺少多语言支持 | 仅支持中文输入 | 增加英文/日文关键词库（针对国际游客场景） |
| 风格检查不阻塞 | Layer C仅记录，不影响裁决 | 积累足够数据后可将风格指标纳入AMEND判断 |
| 无主动学习机制 | 阈值固定，不随使用数据自适应 | 引入人工反馈循环（human-in-the-loop）校准阈值 |
| 兜底话术有限 | 仅有5种兜底话术 | 扩展为按子场景（时间越界/知识盲区/技术故障等）细分 |

---

-


