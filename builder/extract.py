"""Brief (+ tool API) -> spec JSON, with a strong model, then a deterministic check and one review pass."""
import json, os, pathlib, re

import llm
from compile import Api

HERE = pathlib.Path(__file__).resolve().parent
GUIDE = (HERE / "spec_guide.md").read_text()
EXAMPLE = (HERE / "example_spec.json").read_text()
MODEL = os.environ.get("BUILDER_MODEL", "anthropic/claude-opus-5.5")

DEADLINE_KINDS = {"business_days_after_today", "business_days_after_today_inclusive", "calendar_days_after_today", "end_of_month"}
LADDER_DATES = {"today", "next_business_day", "last_business_day_this_week", "last_business_day_next_week", "deadline"}


def tool_summary(openapi):
    """Compact view of the tool API: request fields with enums, and response fields."""
    lines = ["Base URL: " + (openapi.get("servers") or [{"url": "?"}])[0]["url"]]
    comps = openapi.get("components", {}).get("schemas", {})

    def res(s):
        if isinstance(s, dict) and "$ref" in s:
            return res(comps.get(s["$ref"].split("/")[-1], {}))
        return s or {}

    def fields(schema, depth=0):
        out = []
        schema = res(schema)
        for k, v in (schema.get("properties") or {}).items():
            v = res(v)
            t = v.get("type")
            extra = ""
            if v.get("enum"):
                extra += " enum=" + json.dumps(v["enum"])
            if v.get("format"):
                extra += " format=" + v["format"]
            if v.get("description"):
                extra += " -- " + v["description"]
            out.append("  " * (depth + 1) + "- " + k + ": " + str(t) + extra)
            if t == "array":
                out += fields(v.get("items") or {}, depth + 1)
            elif t == "object":
                out += fields(v, depth + 1)
        return out

    for path, item in openapi.get("paths", {}).items():
        for method, op in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"} or not isinstance(op, dict):
                continue
            lines.append(method.upper() + " " + path + ": " + op.get("summary", "") + " " + op.get("description", ""))
            if op.get("x-role"):
                lines.append(" compiler tool role: " + op["x-role"])
            req = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")
            if req:
                lines.append(" request (required: " + ", ".join(res(req).get("required", [])) + "):")
                lines += fields(req)
            resp = (((op.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json", {}).get("schema")
            if resp:
                lines.append(" response:")
                lines += fields(resp)
    return "\n".join(lines)


def system_prompt():
    return GUIDE.replace("EXAMPLE_SPEC", EXAMPLE)


FALLBACK_MODELS = [m for m in os.environ.get("BUILDER_FALLBACK_MODELS", "anthropic/claude-opus-5,anthropic/claude-sonnet-5.5").split(",") if m]


def ask_json(messages, purpose, trace):
    """Call the builder model (then the fallbacks) until a reply parses as a JSON object."""
    last = None
    for model in [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]:
        for attempt in range(2):
            try:
                raw = llm.call(messages, model=model, purpose=purpose + ("" if attempt == 0 else " (retry)"), max_tokens=16000, trace=trace)
                out = llm.parse_json(raw)
                if isinstance(out, dict):
                    return out
                last = "reply is not a JSON object"
            except llm.BudgetExceeded:
                raise
            except Exception as e:
                last = str(e)[:300]
                trace("model call failed (" + model + "): " + last)
    raise RuntimeError("no model produced a spec: " + str(last))


def extract(brief_text, openapi, trace=print):
    tools = tool_summary(openapi)
    user = ("THE BRIEF (read all of it):\n<<<\n" + brief_text + "\n>>>\n\nTHE TOOL API:\n<<<\n" + tools + "\n>>>\n\n"
            "Write the spec JSON for this brief. Detect its conversation language and fill language, the complete locale (all templates), "
            "and ALL texts in that language, including thanks, listening, callback and closing sentences. Preserve prescribed wording verbatim; "
            "otherwise use natural polite phrasing. Product display words, security questions and quoted speech must use that language too. "
            "Never translate API identifiers or placeholders. Reply with the JSON object only.")
    spec = ask_json([{"role": "system", "content": system_prompt()}, {"role": "user", "content": user}], "extract the spec from the brief", trace)
    problems = validate(spec, openapi)
    trace("spec check after extraction: " + (("; ".join(problems)) if problems else "no problems"))
    review = ("THE BRIEF:\n<<<\n" + brief_text + "\n>>>\n\nTHE TOOL API:\n<<<\n" + tools + "\n>>>\n\nA DRAFT SPEC:\n" + json.dumps(spec, indent=1) +
              "\n\nAUTOMATIC CHECK FOUND: " + ("; ".join(problems) if problems else "nothing") +
              "\n\nReview the draft against the brief, rule by rule. For every rule, check the spec holds it with the brief's exact values "
              "(numbers, dates, holidays, codes, sentences, order of questions, bands, attempts, persuasion steps, callback window, what counts as confirmation). "
              "Check that no value was copied from the guide's example when the brief says something else. Fix every problem the check found. "
              "Check language and locale, including every sentence template and every fixed spoken text: no English fallback in a non-English call. "
              "Check product display words, dates, amounts, identity questions, side answers, callback speech and all closings. "
              "Reply with the complete corrected spec JSON only (include the coverage list).")
    try:
        spec2 = ask_json([{"role": "system", "content": system_prompt()}, {"role": "user", "content": review}],
                         "review the spec rule by rule against the brief and fix it", trace)
        if spec2.get("identity") and spec2.get("bands"):
            spec = spec2
    except Exception as e:
        trace("review pass failed, keeping the first spec: " + str(e)[:200])
    problems = validate(spec, openapi)
    spec = repair(spec, openapi, problems, trace)
    return spec


def enum_of(openapi, tool, field):
    return Api(openapi).enum(tool, field)


def validate(spec, openapi):
    p = []
    for key in ("texts", "identity", "account", "calendar", "bands", "persuasion", "outcomes", "early_closes", "situations"):
        if key not in spec:
            p.append("missing " + key)
    fields = enum_of(openapi, "verify_identity", "field")
    for q in (spec.get("identity") or {}).get("questions", []):
        if fields and q.get("field") not in fields:
            p.append("identity field " + str(q.get("field")) + " not in verify_identity enum " + str(fields))
        if q.get("kind") not in ("date", "digits", "year", "text"):
            p.append("identity kind " + str(q.get("kind")) + " unknown")
    outs = enum_of(openapi, "close_call", "outcome")
    for k, v in (spec.get("outcomes") or {}).items():
        if outs and v not in outs:
            p.append("outcome " + k + " -> " + str(v) + " not in close_call enum " + str(outs))
    for k, v in (spec.get("early_closes") or {}).items():
        if outs and (not isinstance(v, list) or v[0] not in outs):
            p.append("early_close " + k + " outcome " + str(v) + " not in close_call enum")
    queues = enum_of(openapi, "transfer_to_agent", "queue")
    for k, s in (spec.get("situations") or {}).items():
        for qk in ("queue", "offer_queue"):
            if s.get(qk) and queues and s[qk] not in queues:
                p.append("situation " + k + " " + qk + " " + s[qk] + " not in " + str(queues))
        if s.get("effect") == "transfer" and not s.get("queue"):
            p.append("situation " + k + " has effect transfer but no queue")
        if s.get("effect") not in ("transfer", "product", "call", "none"):
            p.append("situation " + k + " effect " + str(s.get("effect")) + " unknown")
    for q in (spec.get("transfer_reasons") or {}):
        if queues and q not in queues:
            p.append("transfer_reasons key " + q + " not a queue " + str(queues))
    reasons = enum_of(openapi, "add_note", "reason")
    if reasons and (spec.get("multi") or {}).get("notes"):
        for k, v in (spec.get("reasons") or {}).items():
            if v not in reasons:
                p.append("reason " + k + " -> " + str(v) + " not in add_note enum " + str(reasons))
    for b in spec.get("bands") or []:
        if (b.get("deadline") or {}).get("kind") not in DEADLINE_KINDS:
            p.append("band " + str(b.get("name")) + " deadline kind unknown: " + str(b.get("deadline")))
    for s in spec.get("persuasion") or []:
        d = str(s.get("date"))
        if d not in LADDER_DATES and not re.match(r"^business_days_after_today:\d+$", d):
            p.append("persuasion date kind unknown: " + d)
        if s.get("amount") not in ("current", "full", "floor"):
            p.append("persuasion amount kind unknown: " + str(s.get("amount")))
    for h in (spec.get("calendar") or {}).get("holidays", []):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(h)):
            p.append("holiday not YYYY-MM-DD: " + str(h))
    types = enum_of_response(openapi)
    for t in types:
        if t not in ((spec.get("account") or {}).get("types") or {}):
            p.append("product type " + t + " missing in account.types")
    return p


def enum_of_response(openapi):
    s = json.dumps(Api(openapi).ops.get("get_account", {}).get("response", {}))
    m = re.search(r'"type":\s*\{"type":\s*"string",\s*"enum":\s*(\[[^\]]*\])', s)
    return json.loads(m.group(1)) if m else []


def repair(spec, openapi, problems, trace):
    """Last-resort deterministic fixes so the compiler always gets a usable spec."""
    if problems:
        trace("spec problems left after review (repairing what can be repaired): " + "; ".join(problems))
    spec.setdefault("texts", {})
    spec.setdefault("calendar", {"business_weekdays": [0, 1, 2, 3, 4], "holidays": []})
    for b in spec.get("bands", []):
        if (b.get("deadline") or {}).get("kind") not in DEADLINE_KINDS:
            b["deadline"] = {"kind": "business_days_after_today", "n": int((b.get("deadline") or {}).get("n") or 7)}
    spec["persuasion"] = [s for s in spec.get("persuasion", []) if s.get("amount") in ("current", "full", "floor")]
    outs = enum_of(openapi, "close_call", "outcome")
    if outs:
        for k, v in list(spec.get("outcomes", {}).items()):
            if v not in outs:
                spec["outcomes"][k] = k if k in outs else outs[0]
    queues = enum_of(openapi, "transfer_to_agent", "queue")
    for k, s in spec.get("situations", {}).items():
        if s.get("queue") and queues and s["queue"] not in queues:
            s.pop("queue")
            if s.get("effect") == "transfer":
                s["effect"] = "none"
    return spec
