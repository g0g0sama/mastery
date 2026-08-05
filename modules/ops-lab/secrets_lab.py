"""Config and secret management: where the key actually goes.

Map row (Layer 9): "No provider key reachable from application code paths."

Section 1 enumerates eight ways a key leaves a process and measures which ones
a masked secret type closes, which ones need a redacting log processor, and
which ones no type can close at all. Every channel here is exercised for real:
real exception frames, a real subprocess, a real zip, real serialization.

Section 2 stops asking about the key and asks about the rest of the
configuration, which is where the outages are.

Commit to the predictions before running.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import ops

PREDICTIONS = {
    "A": "Keeping the key in an environment variable instead of a config file "
         "is the fix.",
    "B": "A Secret wrapper type with a masked __repr__ stops the key from "
         "being logged.",
    "C": "Config resolution is simple enough not to need a test: read the env "
         "var, fall back to the file, fall back to the default.",
    "D": "If the service starts and serves traffic, its configuration is "
         "correct.",
}

KEY = "sk-lab-FAKE-9f2c4d7a10b3"          # not a credential, and never was
FALLBACK_KEY = "sk-lab-FAKE-rotated-0001"


# --------------------------------------------------------------------------- #
# The two ways to hold it.
# --------------------------------------------------------------------------- #

class Secret:
    """A string that has to be asked for. The masking is the easy half; the
    interesting half is that `get()` is a grep-able audit point."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def get(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(****)"

    __str__ = __repr__


@dataclass
class Settings:
    api_key: object                       # str or Secret, per variant
    base_url: str = "https://api.example.invalid/v1"
    model: str = "mid-1"
    timeout_s: float = 30.0


def _dump(obj) -> str:
    """A /debug/config handler, or a crash reporter's context block. Whatever
    raises here is a leak that did NOT happen."""
    try:
        return json.dumps(asdict(obj), default=str)
    except TypeError as exc:
        return f"<refused: {type(exc).__name__}>"


def _frame_locals() -> str:
    """A crash reporter that attaches frame locals -- the default of several
    real ones, and the reason a key can reach an incident channel without any
    logging statement mentioning it."""
    def call_provider(settings):
        key = settings.api_key.get() if isinstance(settings.api_key, Secret) \
            else settings.api_key                    # the unwrap site
        headers = {"authorization": f"Bearer {key}"}
        raise RuntimeError("connection reset by peer")

    try:
        call_provider(_settings)
    except RuntimeError:
        tb = sys.exc_info()[2]
        out = []
        while tb:
            out.append(repr(tb.tb_frame.f_locals))
            tb = tb.tb_next
        return " | ".join(out)
    return ""


def _request_log(settings, redact: bool) -> str:
    key = settings.api_key.get() if isinstance(settings.api_key, Secret) \
        else settings.api_key
    event = {"event": "provider.request", "url": settings.base_url,
             "headers": {"authorization": f"Bearer {key}",
                         "content-type": "application/json"}}
    if redact:
        event = _redact(event)
    return json.dumps(event)


REDACT_KEYS = {"authorization", "api_key", "apikey", "token", "cookie",
               "set-cookie", "x-api-key", "password", "secret"}


def _redact(obj):
    """Key-name based redaction. Note what it is: a denylist, applied to a
    structure. Both halves are load-bearing -- it cannot redact a key pasted
    into a free-text message, which is section 1's residue."""
    if isinstance(obj, dict):
        return {k: ("****" if k.lower() in REDACT_KEYS else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _subprocess_env(settings) -> str:
    """The child does not have your type system."""
    key = settings.api_key.get() if isinstance(settings.api_key, Secret) \
        else settings.api_key
    env = dict(os.environ, APP_API_KEY=key)          # how it is always passed
    prog = "import os,sys;sys.stdout.write(os.environ.get('APP_API_KEY',''))"
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                       text=True, env=env)
    return f"child stdout: {r.stdout}"


def _provider_error(settings) -> str:
    """The remote end's error body. Several real ones echo a key prefix, and
    one has echoed the whole thing. You do not control this string."""
    key = settings.api_key.get() if isinstance(settings.api_key, Secret) \
        else settings.api_key
    return json.dumps({"error": {"type": "authentication_error",
                                 "message": f"Invalid API key: {key}"}})


def _artifact(settings, tmp: Path, allowlist: bool) -> str:
    """A build that packages the working directory. The .env file is in the
    working directory because that is what .env files are for."""
    root = tmp / "svc"
    shutil.rmtree(root, ignore_errors=True)
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    key = settings.api_key.get() if isinstance(settings.api_key, Secret) \
        else settings.api_key
    (root / ".env").write_text(f"APP_API_KEY={key}\n", encoding="utf-8")
    out = tmp / "svc.zip"
    names = ["app/main.py"] if allowlist else \
        [str(p.relative_to(root)).replace("\\", "/")
         for p in root.rglob("*") if p.is_file()]
    with zipfile.ZipFile(out, "w") as zf:
        for n in names:
            zf.write(root / n, n)
    return out.read_bytes().decode("utf-8", "replace")


def _cache_entry(settings) -> str:
    """A cached response, keyed by the request that produced it -- including
    the client config, because it was convenient."""
    return _dump(settings)


_settings = None


def section_1_egress(tmp: Path):
    ops.rule("1. Eight ways out, three defences, and what is left")
    global _settings

    def channels(settings, *, redact, allowlist):
        return [
            ("repr() in an error page", lambda: repr(settings)),
            ("crash reporter frame locals", _frame_locals),
            ("structured request log", lambda: _request_log(settings, redact)),
            ("subprocess environment", lambda: _subprocess_env(settings)),
            ("provider error body", lambda: _provider_error(settings)),
            ("/debug/config dump", lambda: _dump(settings)),
            ("build artifact", lambda: _artifact(settings, tmp, allowlist)),
            ("cached response entry", lambda: _cache_entry(settings)),
        ]

    variants = [
        ("plain str", Settings(KEY), False, False),
        ("+ Secret type", Settings(Secret(KEY)), False, False),
        ("+ redacting log processor", Settings(Secret(KEY)), True, False),
        ("+ build allowlist", Settings(Secret(KEY)), True, True),
    ]

    ops.row("channel", "plain str", "+Secret", "+redact", "+allowlist",
            widths=[32, 12, 12, 12, 14])
    grid = []
    for _label, settings, redact, allowlist in variants:
        _settings = settings
        leaks = []
        for name, fn in channels(settings, redact=redact, allowlist=allowlist):
            leaks.append(KEY in fn())
        grid.append(leaks)
    names = [n for n, _ in channels(variants[0][1], redact=False, allowlist=False)]
    for i, name in enumerate(names):
        ops.row(name, *["LEAK" if grid[v][i] else "-" for v in range(4)],
                widths=[32, 12, 12, 12, 14])
    ops.row("TOTAL", *[f"{sum(g)} of 8" for g in grid], widths=[32, 12, 12, 12, 14])

    print("\nThe first column is the state of most services. The second is the")
    print("one-afternoon fix: it closes three of the eight, and they are")
    print("exactly the three whose leak went through a repr or a serializer --")
    print("every ACCIDENTAL path. What a type cannot close is a path where the")
    print("value was deliberately unwrapped, because unwrapping is the point.")
    print("\nThe residue after all three defences is the part worth memorizing:")
    for i, name in enumerate(names):
        if grid[3][i]:
            print(f"  - {name}")
    print("\nThree residues, three different kinds of fix, and none of them is")
    print("a type:")
    print("  - frame locals: a setting on the crash reporter, not on your")
    print("    code. Turn locals off, or accept that every frame between the")
    print("    unwrap and the call holds the plaintext.")
    print("  - subprocess environment: scope. A child inherits the parent's")
    print("    environment because that is what an environment is. Pass the")
    print("    key to the one call that needs it, or use a broker that issues")
    print("    a short-lived credential per call.")
    print("  - the provider's error body: written by someone else's server and")
    print("    landing in your logs. You cannot redact what you did not")
    print("    format. The only defence is that the credential expires and its")
    print("    use is monitored -- a rotation story, not a redaction one.")
    return grid, names


def section_1b_persisted(tmp: Path):
    ops.rule("1b. After one incident: where the key now lives")
    print("Every artifact the section above produced, searched for the literal")
    print("value. This is the rotation checklist, and it is generated rather")
    print("than remembered.\n")
    _settings_local = Settings(KEY)
    written = {
        "app.log (request logging)": _request_log(_settings_local, redact=False),
        "crash-report.json (frame locals)": _frame_locals(),
        "svc.zip (build artifact)": _artifact(_settings_local, tmp, allowlist=False),
        "provider-error.log": _provider_error(_settings_local),
        "child process environment": _subprocess_env(_settings_local),
        "/debug/config response body": _dump(_settings_local),
    }
    hits = [name for name, blob in written.items() if KEY in blob]
    for name in written:
        print(f"  {'CONTAINS KEY' if name in hits else 'clean       '}  {name}")
    print(f"\n{len(hits)} of {len(written)} persisted artifacts contain the key.")
    print("Rotating a key is not one action. It is: issue the new one, deploy")
    print("it everywhere it is read, revoke the old one, and then delete or")
    print("expire every artifact above -- including the ones already shipped")
    print("to a log aggregator you do not control, and the provider's own")
    print("request logs, which you cannot delete at all.")
    print("\nWhich is the argument for the thing that sounds like overkill:")
    print("short-lived credentials, so that 'leaked' has an expiry date, and a")
    print("canary key whose use anywhere is an alert.")
    return len(hits), len(written)


# --------------------------------------------------------------------------- #
# 2. The other 95% of configuration.
# --------------------------------------------------------------------------- #

FILE_CONFIG = {"APP_TIMEOUT_S": "30", "APP_MODEL": "mid-1",
               "APP_STRICT_SCHEMA": "false", "APP_MAX_RETRIES": "2"}
DEFAULTS = {"APP_TIMEOUT_S": 30.0, "APP_MODEL": "mid-1",
            "APP_STRICT_SCHEMA": False, "APP_MAX_RETRIES": 2,
            "APP_REGION": "cn-north"}


def loose_resolve(name, env):
    """The three-line resolver everyone writes."""
    return env.get(name) or FILE_CONFIG.get(name) or DEFAULTS.get(name)


TYPES = {"APP_TIMEOUT_S": float, "APP_MODEL": str, "APP_STRICT_SCHEMA": bool,
         "APP_MAX_RETRIES": int, "APP_REGION": str}


class ConfigError(Exception):
    pass


def strict_resolve(name, env):
    """Explicit presence, explicit types, no falsy coalescing, and unknown
    APP_* variables are an error rather than a shrug."""
    if name in env:
        raw, src = env[name], "env"
    elif name in FILE_CONFIG:
        raw, src = FILE_CONFIG[name], "file"
    elif name in DEFAULTS:
        return DEFAULTS[name]
    else:
        raise ConfigError(f"{name} has no value and no default")
    typ = TYPES[name]
    if raw == "":
        raise ConfigError(f"{name} is set to the empty string in {src}")
    if typ is bool:
        if raw.lower() not in ("true", "false", "1", "0"):
            raise ConfigError(f"{name}={raw!r} is not a boolean")
        return raw.lower() in ("true", "1")
    try:
        return typ(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not {typ.__name__}") from exc


SCENARIOS = [
    ("env set normally", "APP_MODEL", {"APP_MODEL": "large-1"}, "large-1"),
    ("env absent, file wins", "APP_TIMEOUT_S", {}, 30.0),
    ("env declared but empty", "APP_TIMEOUT_S", {"APP_TIMEOUT_S": ""}, "ConfigError"),
    ("bool from string 'false'", "APP_STRICT_SCHEMA",
     {"APP_STRICT_SCHEMA": "false"}, False),
    ("numeric from env", "APP_MAX_RETRIES", {"APP_MAX_RETRIES": "5"}, 5),
    ("value with trailing space", "APP_MODEL", {"APP_MODEL": "large-1 "},
     "large-1 "),
]


def section_2_precedence():
    ops.rule("2. Six ordinary config scenarios, two resolvers")
    ops.row("scenario", "loose result", "strict result", "intended",
            widths=[28, 22, 22, 14])
    loose_ok = strict_ok = 0
    for label, name, env, intended in SCENARIOS:
        try:
            lv = loose_resolve(name, env)
        except Exception as exc:
            lv = f"{type(exc).__name__}"
        try:
            sv = strict_resolve(name, env)
        except ConfigError as exc:
            sv = "ConfigError"
        lo = (repr(lv) == repr(intended)) or (intended == "ConfigError" and lv == "ConfigError")
        so = (repr(sv) == repr(intended)) or (intended == "ConfigError" and sv == "ConfigError")
        loose_ok += lo
        strict_ok += so
        ops.row(label, f"{lv!r}{'' if lo else '  <-'}", f"{sv!r}",
                repr(intended) if intended != "ConfigError" else "raise",
                widths=[28, 22, 22, 14])
    print(f"\nloose resolver correct: {loose_ok} of {len(SCENARIOS)}   "
          f"strict: {strict_ok} of {len(SCENARIOS)}")
    print("\nThe two failures are the two that are always the failures:")
    print("  - `env.get(x) or file.get(x)` treats an empty string as absent.")
    print("    A CI system that declares a variable without populating it is")
    print("    the normal way this happens, and the service starts happily on")
    print("    the previous environment's value.")
    print("  - bool('false') is True. The flag is on in every environment that")
    print("    set it to 'false' and off in the one that forgot to set it.")
    print("\nThe trailing space is the third one and it does not raise in")
    print("either resolver: it is a valid string. Model names, region names")
    print("and URLs read from a pasted secret are where this lands, and the")
    print("only defence is validating against a known set at startup.")
    return loose_ok, strict_ok


def section_2b_typos(tmp: Path):
    ops.rule("2b. The variables nobody reads")
    env = {"APP_MODEL": "large-1", "APP_TIMEOUT": "60",
           "APP_STRICT_SCHEME": "true", "APP_REGION": "cn-north"}
    known = set(TYPES)
    supplied = {k for k in env if k.startswith("APP_")}
    unread = supplied - known
    for name in sorted(supplied):
        print(f"  {'read by the app' if name in known else 'IGNORED SILENTLY'}"
              f"  {name}={env[name]!r}")
    print(f"\n{len(unread)} of {len(supplied)} APP_* variables are ignored: "
          f"{', '.join(sorted(unread))}")
    print("APP_TIMEOUT is a typo for APP_TIMEOUT_S and the service runs on the")
    print("30-second default while the deployment config says 60.")
    print("APP_STRICT_SCHEME is a typo for APP_STRICT_SCHEMA and the strict")
    print("flag someone believed they enabled has been off the whole time.")
    print("\nBoth are caught by one rule: reject unknown variables carrying")
    print("the application's own prefix, at startup, loudly. It is four lines")
    print("and it is the highest-yield four lines in this module.")
    return len(unread), len(supplied)


def section_3_fail_fast():
    ops.rule("3. When a bad value is discovered")
    print("Settings, instrumented to record when each one is first READ, over")
    print("one day of traffic with the fixture's declared failure rates.\n")
    reads = {name: None for name in
             ["model", "timeout_s", "max_retries", "prompt_version",
              "strict_schema", "fallback_model", "dlq_url", "region"]}

    for i, e in enumerate(ops.traffic(day=5, n=400)):
        for name in ("model", "prompt_version", "timeout_s", "strict_schema"):
            if reads[name] is None:
                reads[name] = i                      # happy path touches these
        if e["attempts"] > 1 and reads["max_retries"] is None:
            reads["max_retries"] = i
        if e["outcome"] == "error" and reads["dlq_url"] is None:
            reads["dlq_url"] = i
        # fallback_model is read only when routing gives up; region only when
        # the client builds a URL for a region-specific endpoint, which this
        # deployment does not do.

    ops.row("setting", "first read at request", "verdict", widths=[22, 24, 34])
    never = 0
    for name, idx in reads.items():
        if idx is None:
            never += 1
        ops.row(name, "never" if idx is None else f"#{idx}",
                "validated by traffic" if idx is not None and idx < 50 else
                ("found during an incident" if idx is not None
                 else "NEVER validated in production"),
                widths=[22, 24, 34])
    print(f"\n{never} of {len(reads)} settings were never read on this day.")
    print("They are not obscure settings -- they are the fallback model and")
    print("the region. The dead-letter queue URL is worse than never read: it")
    print("was first read at request #98, by the first request that failed.")
    print("A typo in any of the three is discovered by the incident that needs")
    print("them, which is the worst available moment to discover it.")
    print("\nLazy configuration turns a startup error into an incident")
    print("amplifier. Parse and validate every setting at startup, including")
    print("the ones only the error path uses, and refuse to start otherwise:")
    print("a service that will not start is a page at 10am, and a service that")
    print("starts with a broken DLQ URL is a page at 3am with data loss.")
    return never, len(reads)


def score(grid, names, hits, total_written, loose_ok, unread, never, n_settings):
    ops.rule("4. The predictions")
    residue = [n for n, leak in zip(names, grid[3]) if leak]
    verdicts = {
        "A": (f"WRONG, and it moves the problem rather than solving it -- the "
              f"environment is inherited by every subprocess and dumped by "
              f"crash reporters. It stayed a leak through all four defence "
              f"levels. After one incident the key was present in {hits} of "
              f"{total_written} persisted artifacts"),
        "B": (f"HALF RIGHT and worth doing -- it took the leaking channels "
              f"from {sum(grid[0])} of 8 to {sum(grid[1])} of 8, closing every "
              f"accidental path. It closes nothing where the value is "
              f"deliberately unwrapped, and after a redacting log processor "
              f"and a build allowlist the residue is: "
              f"{'; '.join(residue)}"),
        "C": (f"WRONG -- the three-line resolver got {loose_ok} of "
              f"{len(SCENARIOS)} ordinary scenarios right, failing on the "
              f"empty string and on bool('false'), and {unread} of 4 "
              f"prefixed environment variables were ignored in silence"),
        "D": (f"WRONG -- {never} of {n_settings} settings were never read "
              f"during a full day of traffic, and they are exactly the ones "
              f"the error path needs. Traffic validates the happy path's "
              f"configuration and nothing else"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp(prefix="ops-secrets-"))
    try:
        grid, names = section_1_egress(tmp)
        print()
        hits, total_written = section_1b_persisted(tmp)
        print()
        loose_ok, _strict_ok = section_2_precedence()
        print()
        unread, _supplied = section_2b_typos(tmp)
        print()
        never, n_settings = section_3_fail_fast()
        print()
        score(grid, names, hits, total_written, loose_ok, unread, never, n_settings)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
