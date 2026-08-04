# Failure log

Wrong predictions, in the order they happened. This is the highest-value file in
the repository: a generic flashcard tests a fact somebody else thought was
important, while an entry here tests the exact model that has already failed you
once.

Write the entry **at the moment of surprise**, before looking up the answer.
Retrospective entries lose the wrong model, which is the only part that matters.

## Format

```markdown
### YYYY-MM-DD -- one-line title

**Expected:** what I predicted would happen.

**Happened:** what actually happened, with the output or error.

**Wrong model:** the belief that produced the prediction. Not "I forgot X" --
name the thing I believed instead.

**Diagnosis:** how I found the real cause, including the dead ends.

**Rule:** what I will check first next time this shape appears.

**Propagate:** which card, lab, or module should change, or `none`.
```

The `Wrong model` line is the entry. An entry that says "I did not know about
this parameter" records a gap; an entry that says "I believed the lock was held
for the duration of the critical section, not the duration of the await" records
a model, and models are what fail again.

## Review

Read this file at the start of each cycle. Any entry that repeats a wrong model
already listed is a signal that the fix went into a card instead of into practice
-- promote it to a lab step or a project assertion.

---

<!-- newest entries at the top, below this line -->
