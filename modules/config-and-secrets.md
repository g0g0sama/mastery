# Config and secret management

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Config and secret management (Layer 9, Working -> Independent).
Map evidence: "No provider key reachable from application code paths."

---

## The problem

The map row is written as a reachability claim, and reachability is the right
frame: a key is not safe because of where it is stored, it is safe because of
how few places it can get to. This module counts those places instead of
arguing about them, and then spends its second half on the other 95% of
configuration, which is where the outages actually come from.

## The mechanism

**Eight ways out, four defence levels, measured.** Each channel is exercised for
real — a real exception frame, a real subprocess, a real zip, real
serialization — and searched for the literal key:

```text
channel                         plain str   +Secret     +redact     +allowlist
repr() in an error page         LEAK        -           -           -
crash reporter frame locals     LEAK        LEAK        LEAK        LEAK
structured request log          LEAK        LEAK        -           -
subprocess environment          LEAK        LEAK        LEAK        LEAK
provider error body             LEAK        LEAK        LEAK        LEAK
/debug/config dump              LEAK        -           -           -
build artifact                  LEAK        LEAK        LEAK        -
cached response entry           LEAK        -           -           -
TOTAL                           8 of 8      5 of 8      4 of 8      3 of 8
```

The `Secret` wrapper — a masked `__repr__`, a `get()` you have to call — closes
three of eight, and they are precisely the three whose leak went through a
`repr` or a serializer: the error page, the config dump, the cache entry. Every
*accidental* path. It closes nothing where the value was deliberately unwrapped,
because unwrapping is the point of holding a key.

The residue after all three defences is the part worth memorizing, because each
of the three needs a different kind of fix and none of them is a type:

- **frame locals** — a setting on the crash reporter, not on your code. Any
  frame between the unwrap and the call holds the plaintext, and a reporter
  that attaches locals ships it to an incident channel with no logging
  statement anywhere naming the key.
- **subprocess environment** — scope. A child inherits the parent's environment
  because that is what an environment *is*. The fix is passing the credential
  to the one call that needs it, or a broker issuing a short-lived one per call.
- **the provider's error body** — written by someone else's server, landing in
  your logs. You cannot redact what you did not format.

Note what this does to the usual advice. "Use an environment variable, not a
config file" moves the key from a channel that a `.gitignore` and a build
allowlist can close into one that neither can.

**And after one incident, rotation is not one action:**

```text
  CONTAINS KEY  app.log (request logging)
  CONTAINS KEY  crash-report.json (frame locals)
  CONTAINS KEY  svc.zip (build artifact)
  CONTAINS KEY  provider-error.log
  CONTAINS KEY  child process environment
  CONTAINS KEY  /debug/config response body

6 of 6 persisted artifacts contain the key.
```

Issue the new key, deploy it everywhere it is read, revoke the old one, and then
expire six artifacts — including ones already shipped to a log aggregator you do
not control and the provider's own request logs, which you cannot delete at all.
That list is the argument for the measure that sounds like overkill until you
generate the list: short-lived credentials, so "leaked" has an expiry date, and
a canary key whose use anywhere is an alert.

**The other 95%.** Six entirely ordinary configuration scenarios, against the
three-line resolver everyone writes (`env.get(x) or file.get(x) or default`) and
against a strict one:

```text
scenario                    loose result          strict result         intended
env set normally            'large-1'             'large-1'             'large-1'
env absent, file wins       '30'  <-              30.0                  30.0
env declared but empty      '30'  <-              'ConfigError'         raise
bool from string 'false'    'false'  <-           False                 False
numeric from env            '5'  <-               5                     5
value with trailing space   'large-1 '            'large-1 '            'large-1 '

loose resolver correct: 2 of 6   strict: 6 of 6
```

Two of these are the failures that are always the failures. `or` treats the
empty string as absent, so a CI system that declares a variable without
populating it silently serves the previous environment's value. And
`bool('false')` is `True`, so the flag is *on* in every environment that
carefully set it to `"false"`. The trailing space passes both resolvers: it is a
valid string, and only validation against a known set catches it.

**The variables nobody reads:**

```text
  read by the app   APP_MODEL='large-1'
  read by the app   APP_REGION='cn-north'
  IGNORED SILENTLY  APP_STRICT_SCHEME='true'
  IGNORED SILENTLY  APP_TIMEOUT='60'
```

`APP_TIMEOUT` is a typo for `APP_TIMEOUT_S`; the service runs on the 30-second
default while the deployment config says 60. `APP_STRICT_SCHEME` is a typo for
`APP_STRICT_SCHEMA`; the strict flag someone believed they enabled has been off
the entire time. One rule catches both: reject unknown variables carrying the
application's own prefix, at startup, loudly. Four lines, and the
highest-yield four lines in this module.

**When a bad value is discovered.** Settings instrumented to record their first
read, over a day of traffic:

```text
setting               first read at request   verdict
model                 #0                      validated by traffic
timeout_s             #0                      validated by traffic
max_retries           #7                      validated by traffic
prompt_version        #0                      validated by traffic
strict_schema         #0                      validated by traffic
fallback_model        never                   NEVER validated in production
dlq_url               #98                     found during an incident
region                never                   NEVER validated in production
```

Traffic validates the happy path's configuration and nothing else. The three
settings it does not validate are the fallback model, the region and the
dead-letter queue URL — read for the first time by the first request that fails.
A typo in any of them is discovered by the incident that needed them. Parse and
validate every setting at startup, including the ones only the error path uses:
a service that refuses to start is a page at 10am, and a service that starts
with a broken DLQ URL is a page at 3am with data loss.

## The experiment

```powershell
cd modules\ops-lab
python secrets_lab.py    # ~2 s; spawns subprocesses, writes and deletes a temp tree
```

## Boundary

- **The key is fake and no network exists.** What is measured is which
  *channels* carry a value out of a process, which is a property of Python and
  of the filesystem, not of the credential.
- **The channel list is not exhaustive.** Core dumps, memory scraping, an
  editor's swap file, a screen share, and a model's own context window (a key
  pasted into a prompt) are all real and none is measured here.
- **The redaction processor is a denylist over a structure.** It is defeated by
  a key inside a free-text message — which is exactly the provider-error-body
  row. Denylists are the wrong shape; the reason they persist is that the
  allowlist version has to know every field's name.
- **This module does not cover authorization.** "Which caller may invoke this
  tool" is [untrusted-content-isolation.md](untrusted-content-isolation.md) and
  the Layer 10 rows, not this one.

## Cards

### 1. [decision] Where should the provider key live: a file, an env var, or a secret manager?

**Answer:** Ask which channels each choice opens rather than which sounds safer.
In the lab, moving the key to the environment closed the "swept into the build
artifact" path and opened "inherited by every subprocess", which no type or
redactor can close. A secret manager with short-lived credentials is the only
option that changes the *shape* of the problem, because it puts an expiry on
every leak you have not found yet.

**Why:** A secret's exposure is the union of the channels it can reach, and
storage location only changes some of them.

**Boundary:** A broker adds an availability dependency on the credential path
and a cache that is itself a channel. Where it is not justified, the fallback
that pays for itself is a canary key: unused, valid, and alerting on any use.

**Tags:** `secrets` `decision` `general-principle`

---

### 2. [failure] The key leaked. It was never logged — you checked every logging call.

**Answer:** Check the paths that format objects without being asked to: a
crash reporter attaching frame locals, a `/debug/config` handler, an error page
rendering `repr(settings)`, a cached entry serializing the client config, and
the provider's own 401 body echoing the key into your logs. In the lab those
accounted for five of the eight channels, and a `Secret` type with a masked
repr closed exactly the three that went through a repr or a serializer.

**Why:** Leaks travel through serialization, not through logging statements.

**Boundary:** After the type, a redacting processor and a build allowlist, three
channels remained: frame locals, subprocess environment, and the remote error
body. Two of those are somebody else's code, which is why the residual control
is rotation rather than prevention.

**Tags:** `secrets` `failure` `general-principle`

---

### 3. [misconception] The service started and is serving traffic, so the config is fine.

**Answer:** Traffic exercises the happy path's settings only. In the lab, two of
eight settings were never read at all during a full day — the fallback model and
the region — and a third, the DLQ URL, was first read at request #98, the first
one that failed. Separately, two of four supplied `APP_*` variables were typos
that the service ignored in silence while the deployment config claimed
otherwise.

**Why:** Lazy resolution means a bad value is discovered by the code path that
needs it, and the error-path settings are needed exactly during incidents.

**Boundary:** Fail-fast at startup makes a config typo a deploy failure instead
of an incident, which is the trade you want — but only if the validation covers
value *shape* too. `bool('false')` was `True` and an empty environment variable
silently fell through to the previous environment's value; both parse fine and
neither is caught by "is it set?".

**Tags:** `config` `misconception` `general-principle`
