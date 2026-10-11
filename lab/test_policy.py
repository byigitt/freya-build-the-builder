"""Exercise builder/runtime/policy.py locally with the practice cases' event sequences."""
import importlib.util, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = json.load(open(sys.argv[1] if len(sys.argv) > 1 else ROOT / "specs/brief-ab.json"))
src = (ROOT / "builder/runtime/policy.py").read_text()
assert "{{" not in src and "}}" not in src, "policy source contains doubled braces"


def fresh():
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("pol", loader=None))
    exec(src, m.__dict__)
    m.CFG = spec
    return m


def flat(products):
    v = {"now": "2026-10-14T11:00"}
    for i, p in enumerate(products):
        for k, val in dict(product_id="p%d" % (i + 1), **p).items():
            v["load_account_response.data.products.%d.%s" % (i, k)] = str(val)
    return v


cases = {c["id"]: c for c in json.load(open(ROOT / "public-test-set.json"))}
SCEN = {
    "PUB-01": [("pay_today", "p1", None, None)],
    "PUB-04": [("propose", "p1", None, "2026-11-06"), ("accept_offer", "p1", None, None)],
    "PUB-06": [("too_much", "p1", None, None), ("propose", "p1", None, "this Friday")],
    "PUB-06b": [("too_much", "p1", None, None), ("accept_offer", "p1", None, None)],
    "PUB-07": [("refuse", "p1", None, None), ("vague", "p1", None, "the week after next"), ("propose", "p1", None, "Monday the 26th"), ("accept_offer", "p1", None, None)],
    "PUB-07b": [("propose", "p1", None, "the week after next"), ("propose", "p1", None, "Monday the 26th"), ("accept_offer", "p1", None, None)],
    "PUB-10": [("refuse", "p1", None, None), ("accept_offer", "p1", None, None)],
    "PUB-11": [("propose", "all", None, "this Friday")],
    "PUB-11b": [("refuse", "all", None, None), ("accept_offer", "p1", None, None), ("accept_offer", "p2", None, None), ("accept_offer", "p3", None, None)],
    "PUB-12": [("propose", "p1", None, "tomorrow"), ("refuse", "p2", None, None), ("refuse", "p2", None, None), ("refuse", "p3", None, None)],
    "PUB-13": [("propose", "all", None, "30 October")],
    "PUB-05": [("hardship_declined", "all", None, None), ("refuse", "all", None, None)],
}
for name, events in SCEN.items():
    case = cases[name.rstrip("b")]
    m = fresh()
    v = flat(case["products"])
    m.run_prepare(v)
    print("=" * 100, "\n", name, case["title"], "\nDEBT:", v.get("debt_statement"))
    for ev in events:
        m.run_assess(v, dict(event=ev[0], product=ev[1], amount=ev[2], date=ev[3]))
        print("  ", ev, "->", v["next_instruction"], "| phase", v.get("policy_phase"))
    m.run_commit_check(v)
    print("  commit_ready", v.get("commit_ready"), [(v.get("c%d_product" % k), v.get("c%d_amount" % k), v.get("c%d_date" % k)) for k in (1, 2, 3) if v.get("c%d_go" % k) == "yes"])
    m.run_finalize(v)
    print("  finalize", v.get("final_outcome"), v.get("final_reason"), "notes", [(v.get("n%d_product" % k), v.get("n%d_reason" % k)) for k in (1, 2, 3) if v.get("n%d_go" % k) == "yes"], "| expected", case["expected"]["outcome"], case["expected"]["reason"], case["expected"]["promises"], case["expected"]["notes"])
    if v.get("finalize_error"):
        print("  FINALIZE ERROR", v["finalize_error"])
