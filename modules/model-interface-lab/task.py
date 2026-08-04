"""One task, shared by every module in this lab: extract an event record from a
short Chinese news sentence.

Deliberately the same task as extraction-eval-sets/, so that a number produced
here can be read against a number produced there. What differs is the subject:
that lab studies the eval set, this one studies the interface to the model.

The schema below is a hand-written subset of JSON Schema and `validate` is a
hand-written validator, both about forty lines. That is on purpose -- a module
about structured outputs should not hide the constraint surface behind a
library, and the subset a provider actually supports is smaller than the spec.
"""

# Documents and the record a careful labeller would write for each. The fetch
# date is the same for all of them, which is what makes the date failure mode in
# provider.py plausible rather than contrived -- see ../deterministic-graders.md
# for the same trap measured on the extraction lab's fixture.
FETCH_DATE = "2026-03-11"

EVENT_TYPES = ["investment", "supply_agreement", "regulation", "sanction",
               "production_change", "personnel"]

DOCUMENTS = {
    "N01": ("中国石化宣布将于三月十日在深圳新建研发中心",
            {"event_type": "investment", "actors": ["中国石化"],
             "date": "2026-03-10", "location": "深圳", "confidence": 0.9}),
    "N02": ("宁德时代与宝马集团于三月九日签署长期供货协议",
            {"event_type": "supply_agreement", "actors": ["宁德时代", "宝马集团"],
             "date": "2026-03-09", "location": None, "confidence": 0.9}),
    "N03": ("工业和信息化部三月十一日就稀土出口管制召集企业会议",
            {"event_type": "regulation", "actors": ["工业和信息化部"],
             "date": "2026-03-11", "location": None, "confidence": 0.85}),
    "N04": ("美国商务部三月五日将中芯国际列入实体清单",
            {"event_type": "sanction", "actors": ["美国商务部", "中芯国际"],
             "date": "2026-03-05", "location": None, "confidence": 0.9}),
    "N05": ("长江存储三月八日起武汉部分产线停产检修",
            {"event_type": "production_change", "actors": ["长江存储"],
             "date": "2026-03-08", "location": "武汉", "confidence": 0.8}),
    "N06": ("华为技术有限公司三月一日完成轮值董事长换届",
            {"event_type": "personnel", "actors": ["华为技术有限公司"],
             "date": "2026-03-01", "location": None, "confidence": 0.85}),
    "N07": ("蔚来汽车三月七日获得合肥市政府新一轮投资",
            {"event_type": "investment", "actors": ["蔚来汽车", "合肥市政府"],
             "date": "2026-03-07", "location": "合肥", "confidence": 0.9}),
    "N08": ("隆基绿能与通威股份三月六日协调光伏减产",
            {"event_type": "production_change", "actors": ["隆基绿能", "通威股份"],
             "date": "2026-03-06", "location": None, "confidence": 0.75}),
}

SCHEMA = {
    "type": "object",
    "required": ["event_type", "actors", "date"],
    "additionalProperties": False,
    "properties": {
        "event_type": {"type": "string", "enum": EVENT_TYPES},
        "actors": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "date": {"type": "string", "pattern": "YYYY-MM-DD"},
        "location": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

_TYPES = {"string": str, "number": (int, float), "array": list,
          "object": dict, "boolean": bool, "null": type(None)}


def _type_ok(value, spec):
    names = spec if isinstance(spec, list) else [spec]
    return any(isinstance(value, _TYPES[n]) for n in names)


def validate(obj, schema=SCHEMA):
    """Return a list of violation codes. Empty means valid.

    Codes, not messages, because a violation code is countable and a message is
    only readable -- the same argument as the error taxonomy module.
    """
    if not isinstance(obj, dict):
        return ["root/not-an-object"]
    out = []
    for field in schema["required"]:
        if field not in obj:
            out.append(f"{field}/missing")
    for field, value in obj.items():
        spec = schema["properties"].get(field)
        if spec is None:
            out.append(f"{field}/unknown-property")
            continue
        if not _type_ok(value, spec["type"]):
            out.append(f"{field}/wrong-type")
            continue
        if "enum" in spec and value not in spec["enum"]:
            out.append(f"{field}/not-in-enum")
        if "minItems" in spec and len(value) < spec["minItems"]:
            out.append(f"{field}/too-short")
        if spec.get("pattern") == "YYYY-MM-DD" and not _is_iso_date(value):
            out.append(f"{field}/bad-format")
        if "minimum" in spec and isinstance(value, (int, float)):
            if not spec["minimum"] <= value <= spec["maximum"]:
                out.append(f"{field}/out-of-range")
        if spec.get("items") and isinstance(value, list):
            if any(not _type_ok(v, spec["items"]["type"]) for v in value):
                out.append(f"{field}/bad-item-type")
    return out


def _is_iso_date(value):
    parts = value.split("-") if isinstance(value, str) else []
    return (len(parts) == 3 and len(parts[0]) == 4
            and all(p.isdigit() for p in parts)
            and len(parts[1]) == 2 and len(parts[2]) == 2)


def field_match(predicted, gold, field):
    """One field, one judgment. Match policy is stated, not assumed."""
    if field not in predicted:
        return False
    p, g = predicted[field], gold[field]
    if field == "actors":
        return sorted(p) == sorted(g) if isinstance(p, list) else False
    if field == "confidence":
        return isinstance(p, (int, float))      # calibration is a separate cycle
    return p == g


SCORED_FIELDS = ["event_type", "actors", "date", "location"]


def record_correct(predicted, gold):
    return all(field_match(predicted, gold, f) for f in SCORED_FIELDS)
