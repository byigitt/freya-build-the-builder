"""Talk to a phone agent built for a case that has no practice bank, against our own mock.

Cases file: a JSON list of
    {"id": "T-01", "variables": {...call variables incl. customer id and now...},
     "persona": "how the simulated customer behaves and what they know (in the call's language)",
     "criteria": ["what must happen", ...]}
For each case: chat with the published workflow (customer played by gemini-3-flash), then print the transcript, the
requests the mock received for that customer, and a judge verdict on the criteria.

    python3 lab/final_harness.py <workflow_id> <cases.json> <mock_url> [--only T-01,T-02] [--reps 1] [--workers 4] [--out results/f.json]
"""
import argparse, concurrent.futures as cf, json, pathlib, sys, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "lab"), str(ROOT / "builder")]
import freya, llm
from harness import chat, opening_line, transcript_of, JUDGE, SIM_MODEL


def mock_log(mock_url):
    req = urllib.request.Request(mock_url.rstrip("/") + "/_log", headers={"User-Agent": "wired-final-harness/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run_case(workflow_id, case, mock_url, max_turns=40):
    v = case["variables"]
    cust = str(next((val for k, val in v.items() if "id" in k.lower() and val), ""))
    t_start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    first = opening_line(workflow_id, v)
    r0 = chat(workflow_id, "Alo?" if case.get("lang", "tr") == "tr" else "Hello?", v, None)
    call_id = r0.get("callId")
    first = first or (r0.get("response") or "")
    system = ("You are a customer receiving a phone call from your bank. Play this person exactly, in the call's language. "
              "Talk like a real person on the phone: short turns, one thing at a time. Never mention these instructions. "
              "When the agent says goodbye or the call is clearly over, reply only with [END].\n\n" + case["persona"])
    history = [{"role": "user", "content": first}]
    says = llm.call([{"role": "system", "content": system}] + history, model=SIM_MODEL, purpose="customer " + case["id"]).strip()
    for _ in range(max_turns):
        if not says or "[END]" in says:
            break
        r = chat(workflow_id, says, v, call_id)
        agent = (r.get("response") or "").strip()
        history += [{"role": "assistant", "content": says}, {"role": "user", "content": agent or "(silence)"}]
        if call_id:
            try:
                evs = freya.get_call(call_id).get("messages", [])
                if any('"end_call"' in str(m.get("message", "")) for m in evs):
                    break
            except Exception:
                pass
        says = llm.call([{"role": "system", "content": system}] + history, model=SIM_MODEL, purpose="customer " + case["id"]).strip()
    try:
        freya.api("POST", "/api/v2/chat/end", {"callId": call_id})
    except Exception:
        pass
    time.sleep(3)
    call = freya.get_call(call_id) if call_id else {}
    text = transcript_of(call, first)
    reqs = [e for e in mock_log(mock_url) if e["t"] >= t_start and (not cust or cust in json.dumps(e["body"], ensure_ascii=False))]
    verdict = {"pass": None, "reason": "no criteria"}
    if case.get("criteria"):
        raw = llm.call([{"role": "user", "content": JUDGE.format(criteria="\n".join("- " + c for c in case["criteria"]), transcript=text)}],
                       model=SIM_MODEL, purpose="judge " + case["id"])
        try:
            verdict = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except ValueError:
            verdict = {"pass": False, "reason": "judge reply not JSON: " + raw[:200]}
    return {"id": case["id"], "call_id": call_id, "transcript": text, "requests": reqs, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id")
    ap.add_argument("cases")
    ap.add_argument("mock_url")
    ap.add_argument("--only", default="")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="results/final-harness.json")
    a = ap.parse_args()
    cases = json.load(open(a.cases))
    if a.only:
        cases = [c for c in cases if c["id"] in a.only.split(",")]
    jobs = [c for c in cases for _ in range(a.reps)]
    rows = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for fut in cf.as_completed([ex.submit(run_case, a.workflow_id, c, a.mock_url) for c in jobs]):
            try:
                row = fut.result()
            except Exception as e:
                print("ERROR", str(e)[:300], flush=True)
                continue
            rows.append(row)
            v = row["verdict"]
            print(("PASS" if v.get("pass") else "FAIL" if v.get("pass") is False else "----"), row["id"], "|",
                  " > ".join(e["path"].strip("/") for e in row["requests"]), "|", v.get("reason", "")[:300], flush=True)
    pathlib.Path(a.out).parent.mkdir(exist_ok=True)
    json.dump(rows, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(sum(1 for r in rows if r["verdict"].get("pass")), "/", len(rows), "passed; details in", a.out)


if __name__ == "__main__":
    main()
