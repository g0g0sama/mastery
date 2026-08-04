"""Generated claims with citations, and the gold that says what supports what.

The fixture for `grounding_lab.py`. Twelve claims over the three long documents
in `documents.py`, decomposed into fifteen ATOMS -- the smallest units that can
be independently true or false. Three atoms have no support in the document at
all; the other twelve carry the exact span that supports them.

Why atoms and not claims. A claim like "A signed with B, and the new line is
60 GWh" is two assertions welded together. Scored as one unit it is "supported"
the moment either half is, which is how a grounding number gets inflated without
anyone lying. The atom is the unit at which support is a yes or a no.

Authored, like `corpus.py`, to exercise specific behaviours, all marked below:

- K03 carries a FABRICATED citation -- a fluent paraphrase that does not occur
  in the document. Caught by string containment, at zero labelling cost.
- K08 changes one digit (百分之十 for the document's 百分之十五). Its citation
  resolves and is nearly identical to the claim in every string metric.
- K12 drops a hedge (可能 -> 将). Same shape: resolves, high overlap, false.
- K01, K06 and K11 are two-atom claims whose evidence sits in two spans. K06's
  two spans are in DIFFERENT sections, which a single-citation schema cannot
  express and a top-k retriever need not return together.

The two systems emit the SAME twelve claims and differ only in what they cite.
That isolates citation behaviour from generation quality -- any difference in
the numbers is attributable to the citations alone.
"""

from __future__ import annotations

# id -> doc, claim text, atoms. Each atom's `evidence` is the exact substring of
# the document that supports it, or None if the document does not support it.
CLAIMS: list[dict] = [
    {
        "id": "K01",
        "doc": "L1",
        "text": "稀土出口管制自二零二六年三月一日起实施，过渡期内已签订的合同可在四月三十日前完成交付",
        "atoms": [
            {"id": "K01a", "evidence": "自二零二六年三月一日起正式实施"},
            {"id": "K01b", "evidence": "过渡期内已签订的合同可在四月三十日前完成交付"},
        ],
    },
    {
        "id": "K02",
        "doc": "L1",
        "text": "管制范围涵盖稀土永磁材料及相关生产设备",
        "atoms": [{"id": "K02a", "evidence": "管制范围涵盖稀土永磁材料及相关生产设备"}],
    },
    {
        "id": "K03",
        "doc": "L1",
        "text": "上述企业需在三十日内完成合规备案",
        "atoms": [{"id": "K03a", "evidence": "上述企业需在三十日内完成合规备案"}],
    },
    {
        # Nothing in L1 mentions penalties. A clean fabrication, not a near-miss.
        "id": "K04",
        "doc": "L1",
        "text": "违反规定的企业将被处以罚款",
        "atoms": [{"id": "K04a", "evidence": None}],
    },
    {
        "id": "K05",
        "doc": "L1",
        "text": "出口经营者应当提交最终用户证明",
        "atoms": [{"id": "K05a", "evidence": "提交最终用户证明"}],
    },
    {
        # Two atoms, two sections. 【动力电池供货协议】and【产能安排】.
        "id": "K06",
        "doc": "L2",
        "text": "宁德时代与宝马集团签署长期供货协议，新产线年产能达到六十吉瓦时",
        "atoms": [
            {"id": "K06a", "evidence": "宁德时代与宝马集团签署长期供货协议"},
            {"id": "K06b", "evidence": "年产能达到六十吉瓦时"},
        ],
    },
    {
        "id": "K07",
        "doc": "L2",
        "text": "价格随碳酸锂市场价格按季度联动调整",
        "atoms": [{"id": "K07a", "evidence": "价格随碳酸锂市场价格按季度联动调整"}],
    },
    {
        # The document says 百分之十五. One character, and the claim is false.
        "id": "K08",
        "doc": "L2",
        "text": "任何一方均可在价格偏离超过百分之十时提出重新磋商",
        "atoms": [{"id": "K08a", "evidence": None}],
    },
    {
        "id": "K09",
        "doc": "L2",
        "text": "宁德时代将在福建宁德新建产线",
        "atoms": [{"id": "K09a", "evidence": "宁德时代将在福建宁德新建产线"}],
    },
    {
        "id": "K10",
        "doc": "L3",
        "text": "美国商务部将中芯国际列入实体清单",
        "atoms": [{"id": "K10a", "evidence": "将中芯国际等实体列入实体清单"}],
    },
    {
        # Two atoms, adjacent sentences inside 【影响评估】.
        "id": "K11",
        "doc": "L3",
        "text": "先进制程设备的采购受到最直接的限制，成熟制程产线短期内所受影响相对有限",
        "atoms": [
            {"id": "K11a", "evidence": "先进制程设备的采购将受到最直接的限制"},
            {"id": "K11b", "evidence": "成熟制程产线短期内所受影响相对有限"},
        ],
    },
    {
        # The document hedges: 部分产能可能转移. The claim asserts it.
        "id": "K12",
        "doc": "L3",
        "text": "部分产能将转移至已获得许可的合作方",
        "atoms": [{"id": "K12a", "evidence": None}],
    },
]

CLAIMS_BY_ID: dict[str, dict] = {c["id"]: c for c in CLAIMS}

# system -> claim id -> list of quoted spans. A claim id absent from the mapping
# was emitted UNCITED. Every quote here is what the system claims the document
# says; whether it does is what gate 1 checks.
SYSTEMS: dict[str, dict[str, list[str]]] = {
    # Cites every claim it emits, including the three it should not have made,
    # and quotes the first span it finds rather than every span it needs.
    "A cite-everything": {
        "K01": ["本公告自二零二六年三月一日起正式实施。"],
        "K02": ["公告明确管制范围涵盖稀土永磁材料及相关生产设备。"],
        "K03": ["上述企业须于三十日内完成备案登记"],          # FABRICATED
        "K04": ["出口经营者应当依照规定向主管部门提出许可申请"],  # resolves, unrelated
        "K05": ["出口经营者应当依照规定向主管部门提出许可申请并提交最终用户证明。"],
        "K06": ["宁德时代与宝马集团签署长期供货协议。"],        # atom a only
        "K07": ["双方约定价格随碳酸锂市场价格按季度联动调整。"],
        "K08": ["任何一方均可在价格偏离超过百分之十五时提出重新磋商。"],  # resolves, false
        "K09": ["宁德时代将在福建宁德新建产线以满足该协议的交付需求。"],
        "K10": ["美国商务部工业与安全局将中芯国际等实体列入实体清单。"],
        "K11": ["分析认为先进制程设备的采购将受到最直接的限制。"],  # atom a only
        "K12": ["部分产能可能转移至已获得许可的合作方。"],        # resolves, hedge dropped
    },
    # Cites only where it located the evidence, and quotes every span the claim
    # needs. Silent on the other six -- including two it could have supported.
    "B cite-conservatively": {
        "K01": ["本公告自二零二六年三月一日起正式实施。",
                "过渡期内已签订的合同可在四月三十日前完成交付。"],
        "K02": ["公告明确管制范围涵盖稀土永磁材料及相关生产设备。"],
        "K06": ["宁德时代与宝马集团签署长期供货协议。",
                "新产线预计年产能达到六十吉瓦时。"],
        "K09": ["宁德时代将在福建宁德新建产线以满足该协议的交付需求。"],
        "K10": ["美国商务部工业与安全局将中芯国际等实体列入实体清单。"],
        "K11": ["分析认为先进制程设备的采购将受到最直接的限制。"
                "成熟制程产线短期内所受影响相对有限。"],
    },
}

# One query per document, for the retrieval-composition part.
QUERIES: dict[str, str] = {
    "L1": "稀土出口管制",
    "L2": "动力电池供货协议",
    "L3": "实体清单",
}
