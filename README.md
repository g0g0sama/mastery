# Mastery

The state of one learning system. Not a notes folder -- the files here decide
what gets studied next and whether it counts as learned.

## The unit of progress

The unit is not a document. It is:

```text
capability -> primary source read -> prediction -> implementation -> broken on
purpose -> measured -> used in a real project -> recalled cold a month later
```

A module that produced files but no project change and no cold recall is an
unfinished module, regardless of how good the files are.

## Files

| File | Holds | Written by |
|---|---|---|
| [capability-map.md](capability-map.md) | Every capability, current level, target level, gate, evidence | `/curriculum` |
| [current-cycle.md](current-cycle.md) | The one capability in progress and its evidence contract | `/curriculum` opens it, you close it |
| [failure-log.md](failure-log.md) | Wrong predictions and the mental model behind each | You, at the moment of surprise |
| [decisions/](decisions/) | ADRs -- what was chosen for a real project, and on what measurement | `/eval-coach` |
| [modules/](modules/) | Explainers, labs, and cards produced along the way | `/technical-mastery` |

## The three skills

- **`/curriculum`** -- what should I learn next? Reads the map, checks gates,
  proposes one capability, opens a cycle. Also closes cycles and moves levels.
- **`/technical-mastery`** -- how does this mechanism work? Produces a micro,
  standard, or deep module into `modules/`.
- **`/eval-coach`** -- can I use it reliably in reality? Turns the capability
  into a measured change in a real project, with an eval set, a baseline, and an
  ADR.

They run in that order and each one refuses to skip the previous. `/curriculum`
will not open a cycle whose gate is unmet. `/eval-coach` will not accept a change
with no before/after on a fixed set.

## Rules that keep this from becoming a documentation project

1. **One open cycle.** Two is a signal that the first one stalled; say so in the
   cycle file and close it as abandoned rather than quietly starting a third.
2. **Micro by default.** A concept earns a standard module only when it is
   foundational, actively confusing, or expensive to get wrong.
3. **The primary source is read first.** The generated module is a companion to
   the documentation or paper, never a replacement for it.
4. **Evidence, not artifacts.** A cycle closes on the five conditions in its
   evidence contract. Producing `explainer.md` is not one of them.
5. **Every cycle touches a real project.** If no project can use it, either the
   capability was chosen wrongly or the project transfer is a benchmark you build
   deliberately -- decide which, in writing.
6. **The map is updated at close, not at start.** Levels move on demonstrated
   evidence.

## Level definitions

| Level | Evidence |
|---|---|
| Aware | Can define it and recognize where it is used. |
| Working | Can implement it with the documentation open. |
| Independent | Can design, test, and debug it without a tutorial. |
| Deep | Can explain the trade-offs, read the papers, and improve the implementation. |

Most capabilities should stop at Working or Independent. Deep is for the few that
differentiate the work -- currently multilingual retrieval and structured
extraction.
