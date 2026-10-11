"""Print a call's transcript with node changes, tool calls, results and errors.   python3 lab/show_call.py <call_id> [--vars]"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]
import freya

call = freya.get_call(sys.argv[1])
show_vars = "--vars" in sys.argv
print("ended:", call.get("endedReason"))
for m in call.get("messages", []):
    role, text = m.get("role"), m.get("message") or ""
    if role in ("assistant", "user"):
        print(f"{'AGENT' if role == 'assistant' else 'USER '} [{m.get('nodeId')}] {text}")
        continue
    try:
        ev = json.loads(text)
    except ValueError:
        print("SYS", text[:300]); continue
    e = ev.get("event")
    if e == "node_enter":
        print(f"   -> node {ev.get('node')} (from {ev.get('from_node')}: {str(ev.get('reason'))[:80]})")
    elif e == "function_call_start":
        a = ev.get("args") or {}
        body = a.get("body") if isinstance(a, dict) and "body" in a else (a.get("params") if isinstance(a, dict) else a)
        print(f"   CALL {ev.get('function')} {json.dumps(body)[:300]}")
    elif e == "function_call_complete":
        r = ev.get("result")
        print(f"   RESULT {ev.get('function')} {json.dumps(r)[:400]}")
    elif e == "error":
        print(f"   ERROR {json.dumps(ev)[:600]}")
    elif e == "route_evaluated" and show_vars:
        vt = ev.get("variable_table") or {}
        print(f"   ROUTE {ev.get('from_node')} -> {ev.get('target')} matched={ev.get('matched')}")
        for k, v in vt.items():
            if any(s in k for s in ("next_instruction", "policy_phase", "commit", "final_", "c1_", "pol_state", "account", "facts")):
                print(f"       {k} = {str(v)[:300]}")
    elif e not in ("route_evaluated",):
        print("   EV", e, json.dumps(ev)[:200])
