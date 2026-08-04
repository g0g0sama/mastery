"""Prediction prompts. Answer all five in writing before running verify.py.

An answer you did not write down is an answer you will revise after seeing the
number. That revision feels like understanding and leaves nothing behind. When
one of these misses, the entry goes in ../../failure-log.md at the moment of
surprise, before you work out why.
"""

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # boilerplate

print(__doc__)
print("1. The rules baseline never predicts event_type at all: every prediction")
print("   for that field is None. State two numbers -- its event_type MICRO")
print("   precision and its MACRO precision -- and explain the gap before you")
print("   look. One of them is a number you would not want on a slide.")
print()
print("2. model_a invents actors it cannot find. model_b silently drops them.")
print("   Their actors F1 scores differ by less than 0.01 and their record")
print("   accuracies are identical. Name the specific number in the report that")
print("   separates them, and say which system you would rather ship into a")
print("   database that analysts query.")
print()
print("3. The rules baseline emits schema-invalid output on R06 and R08, so both")
print("   records are dropped before scoring. Its location micro F1 then comes")
print("   out at exactly 1.0000. Say what is wrong with reporting that number,")
print("   and what you would have to print beside it to make it honest.")
print()
print("4. Four fields, each around 0.9 F1. Predict the fraction of records where")
print("   ALL FOUR fields are exactly right. Write the arithmetic you used.")
print()
print("5. The rules baseline costs $0.00 per document -- no model call. Predict")
print("   its cost per ACCEPTED record. Then say why cost per call would have")
print("   ranked the three systems in a different order.")
print()
print("Now: implement the five tasks, then run  python verify.py")
