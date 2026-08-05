# 意图分类设计文档

> 阶段二 | 张嘉欣 

## 一、分类体系

### 五分类定义

| 标签 | 含义 | 触发条件 | 后续处理 |
|------|------|---------|---------|
| `narrator` | 讲解模式 | 场馆/展品/参观类问题 | 检索 venue+bio，用讲解员 Prompt |
| `luxun` | 数字人模式 | 向鲁迅提问/作品/思想类 | 检索 work+quote+persona+bio，用鲁迅 Prompt |
| `ambiguous` | 模糊意图 | 无法确定，或两种模式都沾边 | 全量检索，默认数字人 Prompt |
| `reject_time` | 时间越界 | 涉及 1936 年后事物/概念 | 不检索，数字人 Prompt 时间边界拒绝 |
| `reject_irrelevant` | 无关/恶意 | 与鲁迅/纪念馆完全无关 | 不检索，简短拒绝，引导回正题 |

### 置信度等级

| 置信度 | 含义 | 处理 |
|--------|------|------|
| ≥0.9 | 高置信 | 直接采用 |
| 0.7-0.9 | 中置信 | 采用但标记 `time_aware=True` |
| <0.7 | 低置信 | 降级为 `ambiguous` |

---

## 二、分类规则

### 2.1 优先级链

```
reject_irrelevant → reject_time → narrator → luxun → ambiguous
    (最先匹配)                                    (兜底)
```

### 2.2 narrator 判定（讲解模式）

**关键词**（强信号，≥1个命中 → narrator）：
`纪念馆`, `展区`, `展品`, `展厅`, `展览`, `文物`, `参观`, `游览`, `开放时间`, `预约`, `门票`, `地址`, `在哪里`, `怎么去`, `钟楼`, `白云楼`

**句式**（弱信号，≥2个命中 → narrator）：
- `有没有.*(展|收藏|陈列)`
- `(展示|介绍).*什么`
- `(怎么|如何).*(参观|游览|预约)`
- `(适合|推荐).*(参观|游览)`

### 2.3 luxun 判定（数字人模式）

**关键词**（强信号）：
`鲁迅先生`, `您`, `你的.*(作品|文章|小说|思想)`, `弃医从文`, `代表作`, `写作`

**句式**（弱信号）：
- `(鲁迅|他).*(为什么|为何|如何看待|认为)`
- `(请用|用).*(鲁迅|你).*(口吻|风格|语气)`
- `(鲁迅|你).*(喜欢|讨厌|觉得|想)`
- `(什么|哪些).*(作品|文章|小说|书)`

### 2.4 reject_time 判定（时间越界）

**现代科技词**（≥1个 → reject_time, confidence 0.85+）：
```
手机, 电脑, 计算机, 网络, 互联网, 电视, 电视机, 收音机, 广播电台,
飞机, 高铁, 地铁, 汽车, 电话, 
微信, 微博, 抖音, B站, bilibili, QQ, 小红书, 快手,
人工智能, AI, ChatGPT, 机器人, 大模型, 机器学习, 深度学习,
原子弹, 核弹, 核武器, 卫星, 火箭, 登月, 航天,
电影, 电影院, 视频, 直播, 综艺,
```

**未来时间锚点**（≥1个 → reject_time, confidence 0.80+）：
```
新中国成立, 解放后, 建国后, 改革开放,
文革, 文化大革命, 大跃进,
1949, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020,
二战, 第二次世界大战, 抗日战争全面爆发,
```

**跨越句式**（≥1个 → reject_time, confidence 0.90+）：
```
(鲁迅|您|你).*(用过|见过|参加|玩过|看过|有没有).*(手机|电脑|网络|电视|电影|汽车|飞机|人工智能|机器人)
(鲁迅|您|你).*(是否).*(参加|用过|看过|写过|得过|获得)
(如果|假如).*(鲁迅|你).*(活在|生活在|在).*(今天|现代|当代|现在|当下)
请用鲁迅的.*(评价|看待|谈谈).*(现代|当今|现在|当下|年轻人)
```

**陷阱问题模式**（≥1个 → reject_time, confidence 0.85+）：
```
鲁迅.*(手机|电脑|网络|电视|人工智能|机器人)
纪念馆.*(手机|人工智能|机器人|夜间讲解|100个展厅)
鲁迅.*获得.*诺贝尔
纪念馆.*(扩大到|扩建).*展厅
```

### 2.5 reject_irrelevant 判定（无关/恶意）

**恶意模式**（≥1个 → reject_irrelevant, confidence 0.95+）：
```
脏话: 操|fuck|shit|傻逼|他妈|你妈|日你|滚|去死
```

**完全无关**（≥1个 → reject_irrelevant, confidence 0.85+）：
```
政治敏感: 习近平|特朗普|拜登|共产党|国民党(非历史语境)
娱乐: 明星|综艺|追星|饭圈|游戏|王者荣耀|原神
```

---

## 三、分类流程

```python
def classify(text: str) -> dict:
    """
    输入: 用户原始文本
    输出: {"intent": str, "confidence": float, "reason": str, "matched": list}
    """
    # Step 1: 无关/恶意检测（最先）
    result = check_irrelevant(text)
    if result: return result
    
    # Step 2: 时间越界检测
    result = check_time_clash(text)
    if result: return result
    
    # Step 3: 正常意图分类
    narrator_score = score_narrator(text)
    luxun_score = score_luxun(text)
    
    if narrator_score > luxun_score and narrator_score >= 2:
        return {"intent": "narrator", "confidence": min(narrator_score/5, 0.95)}
    elif luxun_score > narrator_score and luxun_score >= 2:
        return {"intent": "luxun", "confidence": min(luxun_score/5, 0.95)}
    else:
        return {"intent": "ambiguous", "confidence": 0.5}
```

---

## 四、测试用例覆盖

以杜佳琳 55 条问题为基准：

| 类别 | 编号 | 期望分类 | 数量 |
|------|------|---------|------|
| 基础事实 | L001-L005 | `luxun` | 5 |
| 生平思想 | L006-L010 | `luxun` | 5 |
| 作品相关 | L011-L015 | `luxun` | 5 |
| 文学思想 | L016-L020 | `luxun` | 5 |
| 检核题 | L026-L028 | `luxun`（知识库应能回答） | 3 |
| 越界题 | L021-L023, L029-L030 | `reject_time` | 5 |
| 场馆事实 | V001-V005 | `narrator` | 5 |
| 展品展区 | V006-V010 | `narrator` | 5 |
| 参观指引 | V011-V015 | `narrator` | 5 |
| 深度问题 | V016-V020 | `narrator` | 5 |
| 陷阱题 | V021-V025 | `reject_time` | 5 |

> 目标：55 条分类准确率 ≥ 90%（即最多 5 条分类错误）
