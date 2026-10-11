"""Diff the decision-relevant fields of two specs.   python3 lab/diff_spec.py expected.json got.json"""
import json, sys

KEYS = ["variables", "address", "identity.questions", "identity.max_wrong_total", "identity.date_numeric_order", "account", "calendar", "bands", "dates",
        "persuasion", "multi", "reasons", "outcomes", "transfer_reasons", "early_closes", "callback", "opening.max_asks"]


def get(d, path):
    for p in path.split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


def norm(x):
    if isinstance(x, dict):
        return {k: norm(v) for k, v in sorted(x.items()) if k not in ("ask", "say_name", "floor_name", "words", "format")}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x


exp, got = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
bad = 0
for k in KEYS:
    a, b = norm(get(exp, k)), norm(get(got, k))
    if a != b:
        bad += 1
        print("DIFF", k, "\n  expected:", json.dumps(a)[:700], "\n  got:     ", json.dumps(b)[:700])
es, gs = exp.get("situations", {}), got.get("situations", {})
for k in sorted(set(es) | set(gs)):
    a = {x: es.get(k, {}).get(x) for x in ("effect", "queue", "reason", "outcome", "scope")}
    b = {x: gs.get(k, {}).get(x) for x in ("effect", "queue", "reason", "outcome", "scope")}
    if a != b:
        bad += 1
        print("DIFF situation", k, a, "|", b)
print(bad, "differences")
