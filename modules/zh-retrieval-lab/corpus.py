"""A small Chinese corpus, six queries, and graded relevance judgments.

Sixteen documents is a fixture, not a benchmark. It was authored to exercise
specific analyzer behaviours -- shared prefixes, cross-term false matches, and
an out-of-vocabulary compound -- not sampled from a corpus.

Graded relevance: 2 = answers the query, 1 = related and useful, absent = not
relevant. Judgments are over the whole corpus, so recall denominators are real.
"""

DOCS = {
    "D01": "中国石化宣布在深圳新建研发中心",
    "D02": "中国石油在新疆扩大天然气产能",
    "D03": "工业和信息化部就稀土出口管制召集企业会议",
    "D04": "宁德时代与宝马集团签署长期供货协议",
    "D05": "比亚迪郑州新工厂开始量产",
    "D06": "华为技术有限公司轮值董事长换届",
    "D07": "美国商务部将中芯国际列入实体清单",
    "D08": "长江存储武汉部分产线停产检修",
    "D09": "蔚来汽车获得合肥市政府新一轮投资",
    "D10": "国家发展和改革委员会就关税措施发表评论",
    "D11": "隆基绿能与通威股份协调光伏减产",
    "D12": "小米集团北京二期工厂落成",
    "D13": "中远海运与马士基航线运价争议进入仲裁",
    "D14": "稀土永磁材料出口价格上涨",
    # 管制 here means air traffic control. Contains both query terms of
    # "出口管制" in unrelated senses -- a cross-sense false match that no
    # analyzer scoring terms independently can avoid.
    "D15": "深圳机场空域管制调整影响出口货运",
    "D16": "中国稀土集团整合北方稀土资源",
    # Long, and legitimately repeats the query term five times while being only
    # marginally useful. The document term frequency was built to punish.
    "D17": "稀土市场周评稀土价格波动稀土库存变化稀土需求平稳稀土出口数据待发布",
}

QUERIES = {
    # 中石化 is the everyday abbreviation; the document says 中国石化. D02 shares
    # the characters 中 and 石 and is the distractor.
    "Q1 中石化深圳投资": {"D01": 2},
    # D15 contains both 出口 and 管制 in unrelated senses.
    "Q2 出口管制": {"D03": 2, "D14": 1},
    # Pure paraphrase: 动力电池 appears in no document. No lexical analyzer can
    # match this, and that is the honest argument for dense retrieval.
    "Q3 动力电池供应": {"D04": 2},
    "Q4 光伏减产": {"D11": 2},
    # 稀土永磁 is absent from the lab dictionary -- the out-of-vocabulary case.
    "Q5 稀土永磁": {"D14": 2, "D16": 1, "D03": 1, "D17": 1},
    # 芯片 appears nowhere, but 芯 appears inside 中芯国际. Watch which analyzer
    # benefits from that, and ask whether it deserved to.
    "Q6 芯片制裁": {"D07": 2},
}
