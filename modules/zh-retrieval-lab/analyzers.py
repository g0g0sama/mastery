"""Three ways to turn Chinese text into terms. Chinese has no spaces, so this
choice is not a detail -- it decides what can be matched at all.
"""

# Deliberately incomplete, as every real dictionary is. 稀土永磁 is absent.
DICTIONARY = {
    "中国石化", "中国石油", "工业和信息化部", "稀土", "出口", "管制", "宁德时代",
    "宝马集团", "供货", "协议", "比亚迪", "新工厂", "量产", "华为技术有限公司",
    "董事长", "美国商务部", "中芯国际", "实体清单", "长江存储", "武汉", "停产",
    "蔚来汽车", "合肥市政府", "投资", "国家发展和改革委员会", "关税", "隆基绿能",
    "通威股份", "光伏", "减产", "小米集团", "北京", "工厂", "中远海运", "马士基",
    "运价", "仲裁", "深圳", "港口", "货物", "中国稀土集团", "北方稀土", "资源",
    "新疆", "天然气", "产能", "研发中心", "价格", "上涨", "材料", "措施", "调整",
    "整合", "会议", "企业", "签署", "长期", "换届", "轮值", "列入", "部分",
    "产线", "检修", "获得", "新一轮", "发表", "评论", "协调", "二期", "落成",
    "航线", "争议", "进入", "扩大", "宣布", "新建", "开始", "郑州", "召集", "将",
}
MAX_WORD = max(len(w) for w in DICTIONARY)


def unigram(text):
    """Every character is a term. Maximum recall, no notion of a word."""
    return [c for c in text if c.strip()]


def bigram(text):
    """Overlapping character bigrams. The standard CJK baseline."""
    chars = [c for c in text if c.strip()]
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def dictmatch(text):
    """Forward maximum matching. Out-of-vocabulary spans fall back to characters."""
    chars = [c for c in text if c.strip()]
    terms, i = [], 0
    while i < len(chars):
        for size in range(min(MAX_WORD, len(chars) - i), 1, -1):
            candidate = "".join(chars[i:i + size])
            if candidate in DICTIONARY:
                terms.append(candidate)
                i += size
                break
        else:
            terms.append(chars[i])
            i += 1
    return terms


ANALYZERS = {"unigram": unigram, "bigram": bigram, "dictmatch": dictmatch}
