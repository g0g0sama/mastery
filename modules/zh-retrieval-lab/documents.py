"""Three long structured Chinese documents, and answer-span judgments.

A chunk counts as relevant for a query if it CONTAINS the answer span. That
makes the judgments independent of the chunking strategy, which is the only way
to compare strategies on the same footing -- chunk ids differ between them, so
chunk-id judgments would be uncomparable by construction.

Section headings are marked 【...】 so a structure-aware chunker has something
real to key on, as a Markdown heading or an HTML tag would supply.
"""

LONG_DOCS = {
    "L1": (
        "【稀土出口管制通知】"
        "工业和信息化部会同海关总署发布关于稀土相关物项出口管制的公告。"
        "公告明确管制范围涵盖稀土永磁材料及相关生产设备。"
        "出口经营者应当依照规定向主管部门提出许可申请并提交最终用户证明。"
        "【实施时间】"
        "本公告自二零二六年三月一日起正式实施。"
        "过渡期内已签订的合同可在四月三十日前完成交付。"
        "【企业范围】"
        "首批纳入名单的企业包括中国稀土集团北方稀土盛和资源广晟有色五矿稀土厦门钨业。"
        "上述企业需在三十日内完成合规备案并建立台账。"
    ),
    "L2": (
        "【动力电池供货协议】"
        "宁德时代与宝马集团签署长期供货协议。"
        "协议约定自二零二六年起分阶段供应新一代电池产品。"
        "【产能安排】"
        "宁德时代将在福建宁德新建产线以满足该协议的交付需求。"
        "新产线预计年产能达到六十吉瓦时。"
        "【价格机制】"
        "双方约定价格随碳酸锂市场价格按季度联动调整。"
        "任何一方均可在价格偏离超过百分之十五时提出重新磋商。"
    ),
    "L3": (
        "【实体清单更新】"
        "美国商务部工业与安全局将中芯国际等实体列入实体清单。"
        "被列入实体的采购行为需要事先取得出口许可。"
        "【影响评估】"
        "分析认为先进制程设备的采购将受到最直接的限制。"
        "成熟制程产线短期内所受影响相对有限。"
        "【应对措施】"
        "相关企业表示将加快国产设备验证并调整供应链布局。"
        "部分产能可能转移至已获得许可的合作方。"
    ),
}

# query -> (document, answer span that must appear in a retrieved chunk)
ANSWERS = {
    "稀土管制何时实施": ("L1", "自二零二六年三月一日起正式实施"),
    "稀土管制过渡期交付期限": ("L1", "四月三十日前完成交付"),
    "首批纳入名单的企业": ("L1", "中国稀土集团北方稀土盛和资源"),
    "宁德时代新产线年产能": ("L2", "年产能达到六十吉瓦时"),
    "电池价格如何调整": ("L2", "随碳酸锂市场价格按季度联动调整"),
    "实体清单对成熟制程的影响": ("L3", "成熟制程产线短期内所受影响相对有限"),
    # Phrased in the SECTION HEADING's vocabulary (【实施时间】), which the body
    # sentence does not contain. Only a chunker that carries the heading into
    # the chunk can match this.
    "稀土管制实施时间": ("L1", "自二零二六年三月一日起正式实施"),
}
