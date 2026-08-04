"""A fake provider that fails the way real ones do.

No network, no key, no cost, and no pretence that this is a model. What it
reproduces is the INTERFACE and its failure surface: token usage and price,
transient versus terminal errors, streaming with mid-stream failure,
free-form versus schema-constrained output, and tool calls whose arguments do
not match the tool's own schema.

Everything is deterministic. The same request returns the same response on every
run and on every machine, because a lab whose numbers move between runs teaches
nothing you can predict against. The seed is derived from the request itself, so
changing the temperature changes the outcome the way it would in reality --
without any of the reality.
"""
import hashlib
import json
import random
import re

from task import DOCUMENTS, FETCH_DATE
from tokenizer import count


class ProviderError(Exception):
    """Base. `transient` is the only field that a retry policy may consult."""

    transient = False
    status = None
    retry_after = None


class RateLimitError(ProviderError):
    transient, status = True, 429

    def __init__(self, retry_after=2.0):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class OverloadedError(ProviderError):
    transient, status = True, 529


class ServerError(ProviderError):
    transient, status = True, 500


class APITimeoutError(ProviderError):
    """Transient in the sense that retrying may work, and the one error where
    retrying is unsafe by default: the first request may have succeeded."""
    transient, status = True, None


class BadRequestError(ProviderError):
    """Terminal. Retrying a malformed request produces the same malformed
    request, at the same price, forever."""
    transient, status = False, 400


class ContentFilterError(ProviderError):
    """Terminal, and not actually an error -- it is a result about the input.
    Counting it as a failure hides a data problem inside a reliability metric."""
    transient, status = False, 400


class Model:
    def __init__(self, name, price_in, price_out, latency_ms, skill):
        self.name = name
        self.price_in = price_in          # USD per 1k input tokens
        self.price_out = price_out
        self.latency_ms = latency_ms
        self.skill = skill                # P(semantically correct record)

    def cost(self, usage):
        return (usage["input"] * self.price_in
                + usage["output"] * self.price_out) / 1000


MODELS = {
    "tiny-1":  Model("tiny-1",  0.00025, 0.00125,  240, skill=0.55),
    "mid-1":   Model("mid-1",   0.00300, 0.01500,  900, skill=0.80),
    "large-1": Model("large-1", 0.01500, 0.07500, 2600, skill=0.93),
}

PROMPT = ("Extract one event record from the news sentence. "
          "Return JSON with keys event_type, actors, date, location, confidence. "
          "event_type must be one of: investment, supply_agreement, regulation, "
          "sanction, production_change, personnel. Sentence: ")

# Two prompt versions, so a prompt change can be gated by an eval run rather
# than by reading it and agreeing with it. v2 is a real-shaped edit: it adds a
# date instruction that helps overall and, like most added instructions, costs
# something on a slice nobody was looking at.
PROMPT_VARIANTS = {
    "v1": {"text": PROMPT, "skill_delta": 0.0, "slice_delta": {}},
    "v2": {"text": PROMPT.replace(
               "Sentence: ",
               "The date must be the one stated in the sentence, not today's "
               "date. Sentence: "),
           "skill_delta": 0.10,
           "slice_delta": {"regulation": -0.35}},
}


def _rng(*parts):
    digest = hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:12], 16))


def _pick(rng, weights):
    total = sum(weights.values())
    x = rng.random() * total
    for name, w in weights.items():
        x -= w
        if x <= 0:
            return name
    return next(iter(weights))


def _mutate(record, mode, rng):
    """Turn the correct record into one of the failure modes, semantic first."""
    r = json.loads(json.dumps(record))
    if mode == "date_is_fetch_date":
        r["date"] = FETCH_DATE
    elif mode == "hallucinated_actor":
        r["actors"] = r["actors"] + ["国家发展和改革委员会"]
    elif mode == "plausible_wrong_enum":
        alt = [e for e in ("investment", "regulation", "supply_agreement",
                           "production_change") if e != r["event_type"]]
        r["event_type"] = rng.choice(alt)
    elif mode == "location_filled":
        r["location"] = r["location"] or "北京"
    elif mode == "missing_date":
        r.pop("date")
    elif mode == "wrong_type":
        r["confidence"] = str(r["confidence"])
    elif mode == "enum_drift":
        r["event_type"] = "投资"
    return r


def _serialize(record, mode):
    """Then break the SYNTAX, which is a different kind of failure entirely."""
    body = json.dumps(record, ensure_ascii=False)
    if mode == "fenced":
        return f"```json\n{body}\n```"
    if mode == "prose":
        return f"Here is the extracted record:\n\n{body}\n\nLet me know if..."
    if mode == "trailing_comma":
        return body[:-1] + ",}"
    return body


SYNTAX_MODES = ("fenced", "prose", "trailing_comma")
SHAPE_MODES = ("missing_date", "wrong_type", "enum_drift")
SEMANTIC_MODES = ("date_is_fetch_date", "hallucinated_actor",
                  "plausible_wrong_enum", "location_filled")


class Provider:
    """One provider, one model. `script` injects errors for the retry module."""

    def __init__(self, model="mid-1", script=(), latency_scale=1.0):
        self.model = MODELS[model]
        self.script = list(script)
        self.calls = 0
        self.latency_scale = latency_scale

    # -- the failure distribution, in one place so it can be read -----------
    def _modes(self, temperature, constrained, skill=None):
        skill = self.model.skill if skill is None else skill
        semantic = (1 - skill) * 0.85
        if constrained:
            # Constrained decoding removes every syntax and shape failure by
            # construction. It also has to emit a value for each required
            # field, so the model fills instead of omitting -- confabulation
            # replaces abstention. That trade is the whole structured-output
            # module and it is asserted here, not discovered.
            semantic *= 1.3
            weights = {m: semantic / len(SEMANTIC_MODES) for m in SEMANTIC_MODES}
        else:
            syntax = 0.08 + 0.55 * temperature
            weights = {m: syntax / len(SYNTAX_MODES) for m in SYNTAX_MODES}
            shape = (0.05 + 0.25 * temperature) * (1 - skill) * 2
            weights |= {m: shape / len(SHAPE_MODES) for m in SHAPE_MODES}
            weights |= {m: semantic / len(SEMANTIC_MODES) for m in SEMANTIC_MODES}
        weights["clean"] = max(0.02, 1.0 - sum(weights.values()))
        return weights

    def _raise_scripted(self):
        if self.calls <= len(self.script):
            err = self.script[self.calls - 1]
            if err is not None:
                raise err() if isinstance(err, type) else err

    def complete(self, doc_id, *, temperature=0.0, constrained=False,
                 max_tokens=256, attempt=0, prompt_version="v1"):
        self.calls += 1
        self._raise_scripted()
        text, gold = DOCUMENTS[doc_id]
        variant = PROMPT_VARIANTS[prompt_version]
        skill = min(0.99, self.model.skill + variant["skill_delta"]
                    + variant["slice_delta"].get(gold["event_type"], 0.0))
        rng = _rng(self.model.name, doc_id, temperature, constrained, attempt,
                   prompt_version)
        mode = _pick(rng, self._modes(temperature, constrained, skill))
        record = _mutate(gold, mode, rng) if mode != "clean" else gold
        body = _serialize(record, mode if mode in SYNTAX_MODES else "plain")
        usage = {"input": count(variant["text"] + text), "output": count(body)}
        truncated = usage["output"] > max_tokens
        if truncated:
            body = body[: int(len(body) * max_tokens / usage["output"])]
            usage["output"] = max_tokens
        return Response(body, usage, self.model, mode,
                        "max_tokens" if truncated else "stop")

    def stream(self, doc_id, *, temperature=0.0, constrained=False,
               fail_at=None, chunk=12):
        """Yields ('delta', str) then ('usage', dict). Closing the generator
        early is a cancellation, and the `finally` is where the only correct
        place to handle one lives."""
        self.calls += 1
        response = self.complete(doc_id, temperature=temperature,
                                 constrained=constrained)
        self.calls -= 1
        emitted = 0
        try:
            for i in range(0, len(response.text), chunk):
                piece = response.text[i:i + chunk]
                if fail_at is not None and emitted >= fail_at:
                    raise OverloadedError("stream failed mid-response")
                emitted += len(piece)
                yield "delta", piece
            yield "usage", response.usage
        finally:
            self.emitted = emitted


class Response:
    def __init__(self, text, usage, model, mode, stop_reason):
        self.text = text
        self.usage = usage
        self.model = model
        self.mode = mode                 # ground truth about how it failed
        self.stop_reason = stop_reason

    @property
    def cost(self):
        return self.model.cost(self.usage)

    def parse(self):
        """What the caller has to do, and where half the failures land."""
        try:
            return json.loads(self.text), None
        except json.JSONDecodeError as exc:
            return None, f"json/{exc.msg.split(':')[0].replace(' ', '-').lower()}"


def repair(text):
    """The cheap fix everyone writes before reaching for a schema.

    Packaging only. It must never change a VALUE -- a repair pass that edits
    content is an undocumented model of its own, and it will be blamed for the
    model's errors and credited with its successes.
    """
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return text
    return re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])


# --- tool calling ---------------------------------------------------------
TOOLS = {
    "lookup_company": {
        "description": "Resolve a company name to a registry id.",
        "parameters": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {"name": {"type": "string"},
                           "year": {"type": "number",
                                    "minimum": 1990, "maximum": 2030}},
        },
    },
}

REGISTRY = {"中国石化": "CN-0001", "宁德时代": "CN-0002", "华为技术有限公司": "CN-0003",
            "蔚来汽车": "CN-0004", "长江存储": "CN-0005"}


def tool_call(doc_id, *, temperature=0.0, validated=False):
    """A single tool-use block, with arguments that may not match the schema.

    `validated` stands for the provider-side guarantee some APIs offer. Note
    what it does and does not cover -- that is the module.
    """
    text, gold = DOCUMENTS[doc_id]
    rng = _rng("tool", doc_id, temperature, validated)
    actor = gold["actors"][0]
    modes = {"clean": 0.62, "unknown_arg": 0.10, "wrong_type": 0.10,
             "missing_required": 0.08, "out_of_range": 0.10}
    if validated:
        modes = {"clean": 0.72, "not_in_registry": 0.28}
    mode = _pick(rng, modes)
    args = {"name": actor, "year": 2026}
    if mode == "unknown_arg":
        args["company"] = args.pop("name")
    elif mode == "wrong_type":
        args["year"] = "2026"
    elif mode == "missing_required":
        args.pop("name")
    elif mode == "out_of_range":
        args["year"] = 20260
    elif mode == "not_in_registry":
        args["name"] = actor + "集团"
    return {"name": "lookup_company", "arguments": args, "_mode": mode}
