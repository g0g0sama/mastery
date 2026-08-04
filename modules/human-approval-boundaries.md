# Human approval boundaries and least privilege

**Micro module.** One mechanism, one experiment, three cards. Runs against
[agent-workflow-lab/](agent-workflow-lab/).

**Capabilities:** human approval boundaries (Layer 7, `-` -> Independent) and
least privilege / excessive agency (Layer 10, `-` -> Independent). Map evidence:
"A consequential action that cannot execute unapproved" and "Each tool's blast
radius written down and enforced."

---

## The problem

The agent has a `send_alert` tool. There is no API call that unsends an alert.

## The wrong model

**"Tell the model to ask before doing anything consequential."**

An instruction in a prompt is a request, and the previous two modules are about
why a request is not a control. Worse, the model's judgment of "consequential" is
exactly what an injected passage is in a position to move.

The boundary has to be in the **tool**:

```text
unapproved: awaiting-approval
approved:   sent
queue: [{'action': 'send_alert', 'payload': '稀土出口管制升级',
         'reason': 'irreversible external effect'}]
```

The model may **propose** and may not **perform**. That difference is enforced by
`send_alert` itself, not by anything upstream of it.

## The mechanism

The policy is a table, written before a tool is granted rather than after an
incident:

```text
tool            reads       writes         reversible        in-loop?
retrieve        corpus      nothing        n/a               yes
lookup_company  registry    nothing        n/a               yes
store           nothing     events table   yes, by key       yes, idempotent
send_alert      nothing     email/slack    NO                NEVER
delete_record   nothing     events table   no (audit only)   NEVER
```

The last two columns are the whole policy. **A tool that is irreversible and
in-loop is an incident with a schedule**, and the table makes that combination
visible while it is still a design choice.

Note what makes `store` acceptable inside a loop: not that writing is harmless,
but that it is keyed and therefore idempotent
([checkpoints-and-resumability.md](checkpoints-and-resumability.md)). Reversibility
is a property you can engineer, and doing so is often cheaper than an approval
queue.

## The experiment

```powershell
cd modules\agent-workflow-lab
python safety_lab.py     # sections 5 and 6
```

Look at what the queue entry carries: the action, the payload, and the reason.
That is the minimum for an approval to mean anything. **An approval UI that shows
a human "the agent wants to send an alert" with no payload trains them to click
yes**, and a reviewer trained to click yes is worse than no reviewer, because the
control now exists on the architecture diagram.

## Boundary

- **Approval fatigue is a real failure mode with a measurable rate.** If the
  queue is mostly noise, approvals become a formality -- the same arithmetic as
  the 0.074-precision heuristic in
  [deterministic-graders.md](deterministic-graders.md). Measure the fraction of
  requests a human actually rejects; if it is near zero, either the gate is on
  the wrong action or the action should be automated with a different control.
- **Prefer reversibility over approval where you can buy it.** An idempotent
  write with an audit trail and an undo path needs no human in the loop. Approval
  is the control of last resort, for effects that leave your system.
- **The approval is a checkpoint, so the run must survive waiting.** A pending
  approval that blocks a process holds a worker for hours; the state must be
  persisted and the run resumed on approval, which makes this a Layer 7 mechanism
  before it is a Layer 10 one.
- **Least privilege applies to the retrieval side too.** The tools table bounds
  what the agent can do; it says nothing about what it can *read*, which is
  [retrieval-freshness-deletion.md](retrieval-freshness-deletion.md)'s
  access-control filtering. An agent with a read tool that ignores ACLs has full
  privilege regardless of its write table.
- **Sub-agents inherit tools by default and should not.** A researcher sub-agent
  that can send alerts because its parent could is the most common way this table
  stops being true a month after it was written.

## Cards

### 1. [decision] Which tools may an agent call inside its loop without a human in the path?

**Answer:** Reversible ones, and irreversible ones only through an approval gate
enforced by the tool. Reversibility -- keyed idempotent writes, an undo path, an
audit trail -- is the property that decides it, not importance.

**Why:** A tool that is irreversible and in-loop will eventually be called on a
run nobody is watching, and the loop's action choice is a probability rather than
a guarantee.

**Boundary:** Engineering reversibility is usually cheaper than an approval
queue, and it does not decay. Approval is the control of last resort, for effects
that leave your system.

**Tags:** `agents` `security` `decision` `general-principle`

---

### 2. [failure] Your approval queue is approved 99% of the time. What has gone wrong, and why is it worse than having no gate?

**Answer:** The gate is on the wrong action. Reviewers have learned the answer is
yes, so the approval is a formality -- and the control now exists on the
architecture diagram, so nobody is looking for a replacement.

**Why:** The same arithmetic as an unmeasured heuristic: a signal that is almost
always benign trains its consumer to dismiss it, at which point it costs money
and catches nothing.

**Boundary:** Measure the rejection rate as a metric. Near zero means either
automate the action with a different control, or move the gate to the narrower
action that genuinely needs judgment.

**Tags:** `agents` `security` `failure` `general-principle`

---

### 3. [scenario] You are adding a tool to an agent. What do you write down before granting it?

**Answer:** What it reads, what it writes, whether the effect is reversible, and
whether it may be called inside a loop. The last two decide.

**Why:** The combination "irreversible and in-loop" is the one that becomes an
incident, and it is visible only when the four properties are written side by
side rather than inferred from the implementation.

**Boundary:** The table must also cover sub-agents, which inherit tools by
default and should not. That inheritance is the most common way a correct table
stops being true a month later.

**Tags:** `agents` `security` `scenario` `general-principle`
