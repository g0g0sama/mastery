"""Three systems' output over the same 12 documents.

`rules`    a regex + gazetteer + dictionary baseline. No model call. It is very
           good at the fields that have a grammar (dates, place names) and
           useless at the one that does not (event_type). It also emits raw
           Chinese into `event_type` twice, which is a schema violation.

`model_a`  the confabulator. Never leaves a field empty. When it does not know,
           it produces something plausible.

`model_b`  the abstainer. Emits None or drops list items when unsure.

model_a and model_b were constructed so that their headline numbers nearly
coincide. If your scorer reports them as roughly equivalent systems, your scorer
is working and your metric set is incomplete. That is the point of the lab.

COST_PER_RECORD is illustrative, not measured. Replace it with your provider's
real per-document cost before this number decides anything.
"""

from __future__ import annotations

RULES: dict[str, dict] = {
    "R01": {
        "actors": ["中国石化"],
        "event_type": None,
        "time": "2026-01-12",
        "location": "深圳市",
        "confidence": None,
    },
    "R02": {
        "actors": ["宁德时代"],
        "event_type": None,
        "time": "2026-01-20",
        "location": "宁德",
        "confidence": None,
    },
    "R03": {
        # The dictionary was built from headline names. It covers two of the
        # seven actors in the one document that has a long tail.
        "actors": ["工业和信息化部", "中国稀土集团"],
        "event_type": None,
        "time": "2026-02-03",
        "location": "北京",
        "confidence": None,
    },
    "R04": {
        "actors": ["比亚迪"],
        "event_type": None,
        "time": "2026-02-11",
        "location": "郑州市",
        "confidence": None,
    },
    "R05": {
        "actors": ["华为技术有限公司"],
        "event_type": None,
        "time": "2026-02-18",
        "location": "深圳",
        "confidence": None,
    },
    # Schema violation: the keyword rule wrote a Chinese label into a field whose
    # vocabulary is an English closed set. Nothing downstream can store this.
    "R06": {
        "actors": ["中芯国际"],
        "event_type": "制裁",
        "time": "2026-03-02",
        "location": None,
        "confidence": None,
    },
    "R07": {
        "actors": [],
        "event_type": None,
        "time": "2026-03-14",
        "location": "武汉市",
        "confidence": None,
    },
    # Second schema violation.
    "R08": {
        "actors": [],
        "event_type": "投资",
        "time": "2026-03-21",
        "location": "安徽省",
        "confidence": None,
    },
    # The regex found the publication date and called it the event date.
    "R09": {
        "actors": ["国家发展和改革委员会"],
        "event_type": None,
        "time": "2026-04-05",
        "location": "北京市",
        "confidence": None,
    },
    "R10": {
        "actors": ["隆基绿能"],
        "event_type": None,
        "time": "2026-04-17",
        "location": "西安",
        "confidence": None,
    },
    # The dictionary matched a company named only in the page footer.
    "R11": {
        "actors": ["小米集团", "中国石化"],
        "event_type": None,
        "time": "2026-05-06",
        "location": "北京",
        "confidence": None,
    },
    "R12": {
        "actors": ["中远海运"],
        "event_type": None,
        "time": "2026-05-19",
        "location": "上海市",
        "confidence": None,
    },
}

MODEL_A: dict[str, dict] = {
    # Full legal form where the gold holds the short form. Under this lab's
    # policy that is a miss, and the fix is entity linking, not normalization.
    "R01": {
        "actors": ["中国石油化工集团有限公司"],
        "event_type": "investment",
        "time": "2026-01-12",
        "location": "深圳",
        "confidence": 0.95,
    },
    # Full-width latin inside a parenthetical, and a location carrying its
    # province prefix. Both are normalization's job, not the model's.
    "R02": {
        "actors": ["宁德时代（ＣＡＴＬ）", "宝马集团"],
        "event_type": "investment",
        "time": "2026-01-20",
        "location": "福建省宁德市",
        "confidence": 0.92,
    },
    "R03": {
        "actors": [
            "工业和信息化部",
            "中国稀土集团",
            "北方稀土",
            "盛和资源",
            "广晟有色",
            "五矿稀土",
            "中国铝业",
        ],
        "event_type": "trade_dispute",
        "time": "2026-02-03",
        "location": "北京",
        "confidence": 0.88,
    },
    "R04": {
        "actors": ["比亚迪"],
        "event_type": "plant_opening",
        "time": "2026-02-11",
        "location": "郑州",
        "confidence": 0.94,
    },
    "R05": {
        "actors": ["华为"],
        "event_type": "leadership_change",
        "time": "2026-02-18",
        "location": "深圳",
        "confidence": 0.91,
    },
    "R06": {
        "actors": ["美国商务部", "中芯国际"],
        "event_type": "sanction",
        "time": "2026-03-02",
        "location": "华盛顿",
        "confidence": 0.96,
    },
    "R07": {
        "actors": ["长江存储"],
        "event_type": "production_halt",
        "time": "2026-03-14",
        "location": "武汉",
        "confidence": 0.9,
    },
    "R08": {
        "actors": ["蔚来汽车", "合肥市政府"],
        "event_type": "investment",
        "time": "2026-03-21",
        "location": "合肥",
        "confidence": 0.89,
    },
    # The source gave a month. The model produced a day anyway, confidently.
    "R09": {
        "actors": ["国家发展和改革委员会"],
        "event_type": "trade_dispute",
        "time": "2026-04-05",
        "location": "北京",
        "confidence": 0.93,
    },
    "R10": {
        "actors": ["隆基绿能", "通威股份"],
        "event_type": "production_halt",
        "time": "2026-04-16",
        "location": "西安",
        "confidence": 0.87,
    },
    "R11": {
        "actors": ["小米集团"],
        "event_type": "plant_opening",
        "time": "2026-05-06",
        "location": "北京",
        "confidence": 0.95,
    },
    "R12": {
        "actors": ["中远海运", "马士基"],
        "event_type": "sanction",
        "time": "2026-05-19",
        "location": "上海",
        "confidence": 0.9,
    },
}

MODEL_B: dict[str, dict] = {
    "R01": {
        "actors": ["中国石化"],
        "event_type": "investment",
        "time": "2026-01-12",
        "location": "深圳",
        "confidence": 0.88,
    },
    "R02": {
        "actors": ["宁德时代", "宝马集团"],
        "event_type": "investment",
        "time": "2026-01-20",
        "location": "宁德",
        "confidence": 0.85,
    },
    # Dropped the three actors it was least sure of. Silent, and invisible to
    # any metric that only watches precision.
    "R03": {
        "actors": ["工业和信息化部", "中国稀土集团", "北方稀土", "五矿稀土"],
        "event_type": "trade_dispute",
        "time": "2026-02-03",
        "location": "北京",
        "confidence": 0.62,
    },
    "R04": {
        "actors": ["比亚迪"],
        "event_type": "plant_opening",
        "time": "2026-02-11",
        "location": "郑州市",
        "confidence": 0.9,
    },
    "R05": {
        "actors": [],
        "event_type": "leadership_change",
        "time": "2026-02-18",
        "location": "深圳",
        "confidence": 0.55,
    },
    "R06": {
        "actors": ["美国商务部", "中芯国际"],
        "event_type": "sanction",
        "time": "2026-03-02",
        "location": None,
        "confidence": 0.71,
    },
    "R07": {
        "actors": ["长江存储"],
        "event_type": "production_halt",
        "time": "2026-03-14",
        "location": "武汉市",
        "confidence": 0.83,
    },
    "R08": {
        "actors": ["蔚来汽车"],
        "event_type": "investment",
        "time": "2026-03-21",
        "location": "合肥",
        "confidence": 0.6,
    },
    # Correctly declined to invent a day. Both sides empty.
    "R09": {
        "actors": ["国家发展和改革委员会"],
        "event_type": "trade_dispute",
        "time": None,
        "location": "北京市",
        "confidence": 0.58,
    },
    "R10": {
        "actors": ["隆基绿能", "通威股份"],
        "event_type": "production_halt",
        "time": None,
        "location": "西安",
        "confidence": 0.64,
    },
    "R11": {
        "actors": ["小米集团"],
        "event_type": "plant_opening",
        "time": "2026-05-06",
        "location": "北京",
        "confidence": 0.92,
    },
    "R12": {
        "actors": ["中远海运", "马士基"],
        "event_type": None,
        "time": "2026-05-19",
        "location": "上海",
        "confidence": 0.66,
    },
}

SYSTEMS: dict[str, dict[str, dict]] = {
    "rules": RULES,
    "model_a": MODEL_A,
    "model_b": MODEL_B,
}

# USD per document processed. Illustrative.
COST_PER_RECORD: dict[str, float] = {
    "rules": 0.0,
    "model_a": 0.0042,
    "model_b": 0.0038,
}
