"""The gold set: 12 hand-labelled records, Sinoscope shape.

This is NOT an eval set. Twelve records is a test fixture for a scorer -- it has
no statistical power and it was written to exercise specific metric behaviours.
The 50 records in the cycle's evidence contract have to come from your own
documents, labelled under your own policy. What this file gives you is something
to point the scorer at while you are still writing the scorer.

Labelling conventions used here, all of which are policy choices you would
otherwise have to make yourself:

- `actors` is stored as the labeller wrote it, including full-width characters
  and stray spacing. Normalization is applied at scoring time, to both sides.
  Storing normalized gold makes the set unusable the day the policy changes.
- `time` is the event's date, not the article's publication date, as ISO
  `YYYY-MM-DD`. Where the source only gives a month, the field is None rather
  than a guessed day.
- `location` is stored at the granularity the source actually supplies.
- `claims` and `source` are present but NOT scored -- see policy.py.
- `confidence` here is the labeller's, on a 3-point scale mapped to
  1.0 / 0.7 / 0.4. The model's own confidence lives in the prediction records.

Fields are Chinese text. Nothing in this lab prints raw field values, because a
redirected stdout on Windows can fall back to the ANSI codepage and raise
UnicodeEncodeError. Record ids are the currency of every report.
"""

from __future__ import annotations

GOLD: list[dict] = [
    {
        "id": "R01",
        "actors": ["中国石化"],
        "event_type": "investment",
        "time": "2026-01-12",
        "location": "深圳市",
        "claims": ["公司宣布在当地新建研发中心"],
        "source": {"url": "https://example.test/a/1", "fetched_at": "2026-01-13T02:10:00Z"},
        "confidence": 1.0,
    },
    {
        "id": "R02",
        "actors": ["宁德时代", "宝马集团"],
        "event_type": "investment",
        "time": "2026-01-20",
        "location": "宁德",
        "claims": ["双方签署长期供货协议"],
        "source": {"url": "https://example.test/a/2", "fetched_at": "2026-01-20T09:00:00Z"},
        "confidence": 1.0,
    },
    {
        # The long-tail record. Seven actors in one document. Watch what this
        # single row does to a micro average.
        "id": "R03",
        "actors": [
            "工业和信息化部",
            "中国稀土集团",
            "北方稀土",
            "盛和资源",
            "广晟有色",
            "五矿稀土",
            "厦门钨业",
        ],
        "event_type": "trade_dispute",
        "time": "2026-02-03",
        "location": "北京",
        "claims": ["主管部门就出口管制召集六家企业开会"],
        "source": {"url": "https://example.test/a/3", "fetched_at": "2026-02-03T11:30:00Z"},
        "confidence": 0.7,
    },
    {
        "id": "R04",
        "actors": ["比亚迪"],
        "event_type": "plant_opening",
        "time": "2026-02-11",
        "location": "郑州市",
        "claims": ["新工厂开始量产"],
        "source": {"url": "https://example.test/a/4", "fetched_at": "2026-02-11T06:45:00Z"},
        "confidence": 1.0,
    },
    {
        "id": "R05",
        "actors": ["华为技术有限公司"],
        "event_type": "leadership_change",
        "time": "2026-02-18",
        "location": "深圳",
        "claims": ["轮值董事长换届"],
        "source": {"url": "https://example.test/a/5", "fetched_at": "2026-02-18T13:05:00Z"},
        "confidence": 1.0,
    },
    {
        "id": "R06",
        "actors": ["美国商务部", "中芯国际"],
        "event_type": "sanction",
        "time": "2026-03-02",
        "location": "华盛顿",
        "claims": ["新增实体清单条目"],
        "source": {"url": "https://example.test/a/6", "fetched_at": "2026-03-02T21:15:00Z"},
        "confidence": 1.0,
    },
    {
        "id": "R07",
        "actors": ["长江存储"],
        "event_type": "production_halt",
        "time": "2026-03-14",
        "location": "武汉市",
        "claims": ["部分产线停产检修"],
        "source": {"url": "https://example.test/a/7", "fetched_at": "2026-03-15T01:00:00Z"},
        "confidence": 0.7,
    },
    {
        "id": "R08",
        "actors": ["蔚来汽车", "合肥市政府"],
        "event_type": "investment",
        "time": "2026-03-21",
        "location": "合肥",
        "claims": ["地方政府参与新一轮融资"],
        "source": {"url": "https://example.test/a/8", "fetched_at": "2026-03-21T08:20:00Z"},
        "confidence": 0.7,
    },
    {
        # The source gives a month only. The labeller refused to invent a day.
        # An extractor that emits a day here is wrong, not merely more precise.
        "id": "R09",
        "actors": ["国家发展和改革委员会"],
        "event_type": "trade_dispute",
        "time": None,
        "location": "北京市",
        "claims": ["就关税措施发表评论"],
        "source": {"url": "https://example.test/a/9", "fetched_at": "2026-04-05T10:00:00Z"},
        "confidence": 0.4,
    },
    {
        "id": "R10",
        "actors": ["隆基绿能", "通威股份"],
        "event_type": "production_halt",
        "time": "2026-04-17",
        "location": "西安",
        "claims": ["行业协会协调减产"],
        "source": {"url": "https://example.test/a/10", "fetched_at": "2026-04-17T15:40:00Z"},
        "confidence": 0.7,
    },
    {
        "id": "R11",
        "actors": ["小米集团"],
        "event_type": "plant_opening",
        "time": "2026-05-06",
        "location": "北京",
        "claims": ["二期工厂落成"],
        "source": {"url": "https://example.test/a/11", "fetched_at": "2026-05-06T03:30:00Z"},
        "confidence": 1.0,
    },
    {
        "id": "R12",
        "actors": ["中远海运", "马士基"],
        "event_type": "trade_dispute",
        "time": "2026-05-19",
        "location": "上海市",
        "claims": ["航线运价争议进入仲裁"],
        "source": {"url": "https://example.test/a/12", "fetched_at": "2026-05-19T19:00:00Z"},
        "confidence": 0.4,
    },
]

GOLD_BY_ID: dict[str, dict] = {record["id"]: record for record in GOLD}
