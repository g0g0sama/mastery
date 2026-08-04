"""Four adversarial records, and what they do to a set that could not fail.

    python adversarial.py

Each record was chosen because of a hypothesis about a specific failure, not
because it looked hard. Requires all five lab tasks.
"""
import copy
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import gold as gold_module
import scoring
from predictions import SYSTEMS

SRC = {"url": "https://example.test/adv", "fetched_at": "2026-06-20T00:00:00Z"}

# N1 negative: market commentary. The correct output is nothing at all.
# N2 confusable: 中国石油 and 中国石化 differ by one character.
# N3 distractor: the article cites a 2019 precedent before the 2026 event.
# N4 out-of-vocabulary: a product recall, which EVENT_TYPES does not contain.
ADVERSARIAL = [
    {"id": "N1", "actors": [], "event_type": None, "time": None, "location": None,
     "claims": [], "source": SRC, "confidence": 1.0},
    {"id": "N2", "actors": ["中国石油"], "event_type": "investment",
     "time": "2026-06-05", "location": "北京", "claims": [], "source": SRC,
     "confidence": 1.0},
    {"id": "N3", "actors": ["中远海运"], "event_type": "trade_dispute",
     "time": "2026-06-09", "location": "上海", "claims": [], "source": SRC,
     "confidence": 1.0},
    {"id": "N4", "actors": ["比亚迪"], "event_type": None, "time": "2026-06-12",
     "location": "深圳", "claims": [], "source": SRC, "confidence": 0.7},
]

ADV_PREDS = {
    "rules": {
        "N1": {"actors": ["中国石化"], "event_type": None, "time": "2026-06-02",
               "location": "北京", "confidence": None},
        "N2": {"actors": ["中国石化"], "event_type": None, "time": "2026-06-05",
               "location": "北京", "confidence": None},
        "N3": {"actors": ["中远海运"], "event_type": None, "time": "2019-05-14",
               "location": "上海", "confidence": None},
        "N4": {"actors": ["比亚迪"], "event_type": None, "time": "2026-06-12",
               "location": "深圳", "confidence": None},
    },
    "model_a": {
        "N1": {"actors": ["中国石化"], "event_type": "investment",
               "time": "2026-06-02", "location": "北京", "confidence": 0.86},
        "N2": {"actors": ["中国石化"], "event_type": "investment",
               "time": "2026-06-05", "location": "北京", "confidence": 0.91},
        "N3": {"actors": ["中远海运"], "event_type": "trade_dispute",
               "time": "2019-05-14", "location": "上海", "confidence": 0.88},
        "N4": {"actors": ["比亚迪"], "event_type": "production_halt",
               "time": "2026-06-12", "location": "深圳", "confidence": 0.84},
    },
    "model_b": {
        "N1": {"actors": [], "event_type": None, "time": None, "location": None,
               "confidence": 0.41},
        "N2": {"actors": ["中国石油"], "event_type": "investment",
               "time": "2026-06-05", "location": "北京", "confidence": 0.79},
        "N3": {"actors": ["中远海运"], "event_type": "trade_dispute",
               "time": "2026-06-09", "location": "上海", "confidence": 0.72},
        "N4": {"actors": ["比亚迪"], "event_type": None, "time": "2026-06-12",
               "location": "深圳", "confidence": 0.58},
    },
}

before = {name: scoring.score(name) for name in SYSTEMS}
saved_gold = list(gold_module.GOLD)
saved_preds = copy.deepcopy(SYSTEMS)
try:
    gold_module.GOLD.extend(ADVERSARIAL)
    for name, extra in ADV_PREDS.items():
        SYSTEMS[name].update(extra)
    after = {name: scoring.score(name) for name in SYSTEMS}
finally:
    gold_module.GOLD[:] = saved_gold
    for name in SYSTEMS:
        SYSTEMS[name].clear()
        SYSTEMS[name].update(saved_preds[name])

hdr = f"{'system':<9}{'metric':<16}{'12 typical':>12}{'+4 adversarial':>16}{'delta':>9}"
print(hdr)
print("-" * len(hdr))
for name in SYSTEMS:
    b, a = before[name], after[name]
    rows = [("actors F1", b["fields"]["actors"]["micro"][2], a["fields"]["actors"]["micro"][2]),
            ("event_type F1", b["fields"]["event_type"]["micro"][2], a["fields"]["event_type"]["micro"][2]),
            ("time F1", b["fields"]["time"]["micro"][2], a["fields"]["time"]["micro"][2]),
            ("record accuracy", b["record_accuracy"], a["record_accuracy"])]
    for label, x, y in rows:
        print(f"{name:<9}{label:<16}{x:>12.4f}{y:>16.4f}{y - x:>+9.4f}")
    print()

print("Per-record result on the four adversarial cases:")
print(f"{'':<9}{'N1 negative':>14}{'N2 confusable':>16}{'N3 distractor':>15}{'N4 out-of-vocab':>17}")
gold_module.GOLD.extend(ADVERSARIAL)
for name, extra in ADV_PREDS.items():
    SYSTEMS[name].update(extra)
try:
    by_id = {g["id"]: g for g in ADVERSARIAL}
    for name in SYSTEMS:
        cells = []
        for rid in ("N1", "N2", "N3", "N4"):
            ok = scoring.record_accepted(by_id[rid], SYSTEMS[name][rid])
            cells.append("accepted" if ok else "REJECTED")
        print(f"{name:<9}{cells[0]:>14}{cells[1]:>16}{cells[2]:>15}{cells[3]:>17}")
finally:
    gold_module.GOLD[:] = saved_gold
    for name in SYSTEMS:
        SYSTEMS[name].clear()
        SYSTEMS[name].update(saved_preds[name])
