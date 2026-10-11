"""Chat-completions client for the Vercel AI Gateway (OpenAI-compatible). Standard library only.

    export AI_GATEWAY_API_KEY=...        # or ANTHROPIC_API_KEY / OPENAI_API_KEY style keys via LLM_BASE_URL
    export LLM_BUDGET_USD=150            # hard cap on the summed cost of all calls recorded in .llm-spend.jsonl

Every call is appended to .llm-spend.jsonl (model, purpose, tokens, cost). When the recorded total reaches the
budget, call() raises instead of spending more.
"""
import json, os, pathlib, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("LLM_BASE_URL", "https://ai-gateway.vercel.sh/v1")
SPEND_FILE = pathlib.Path(os.environ.get("LLM_SPEND_FILE", ROOT / ".llm-spend.jsonl"))
BUDGET_USD = float(os.environ.get("LLM_BUDGET_USD", "150"))


class BudgetExceeded(RuntimeError):
    pass


def spent():
    if not SPEND_FILE.exists():
        return 0.0
    total = 0.0
    for line in SPEND_FILE.read_text().splitlines():
        try:
            total += float(json.loads(line).get("cost", 0))
        except ValueError:
            continue
    return total


def _cost(usage):
    for key in ("market_cost", "cost"):
        if usage.get(key):
            return float(usage[key])
    return float((usage.get("cost_details") or {}).get("upstream_inference_cost") or 0)


def call(messages, model="google/gemini-3-flash", purpose="", temperature=None, max_tokens=None, json_mode=False, timeout=300, retries=3, trace=None, stream=False, reasoning_effort=None):
    """Return assistant text; stream=True avoids idle gateway limits on long generations. Trace and spend include streamed usage."""
    if spent() >= BUDGET_USD:
        raise BudgetExceeded(f"LLM budget of ${BUDGET_USD:.0f} reached ({SPEND_FILE})")
    body = {"model": model, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if stream:
        body.update(stream=True, stream_options={"include_usage": True})
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("LLM_API_KEY", "")
    req = urllib.request.Request(BASE_URL + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if not stream:
                    out = json.load(r)
                else:
                    parts, usage = [], {}
                    finished = False
                    for line in r:
                        if not line.startswith(b"data:"):
                            continue
                        data = line[5:].strip()
                        if data == b"[DONE]":
                            finished = True
                            break
                        event = json.loads(data)
                        if event.get("error"):
                            raise RuntimeError(str(event["error"]))
                        if event.get("usage"):
                            usage = event["usage"]
                        for choice in event.get("choices", []):
                            if choice.get("index", 0) == 0:
                                text = choice.get("delta", {}).get("content")
                                if text:
                                    parts.append(text)
                    if not finished:
                        raise RuntimeError("completion stream ended before [DONE]")
                    out = {"choices": [{"message": {"content": "".join(parts)}}], "usage": usage}
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            detail = e.read().decode()[:500] if isinstance(e, urllib.error.HTTPError) else str(e)
            last = f"{model}: {detail}"
            if isinstance(e, urllib.error.HTTPError) and e.code in (400, 401, 403):
                raise RuntimeError(last) from None
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(last)
    usage = out.get("usage") or {}
    cost = _cost(usage)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "purpose": purpose[:120], "in": usage.get("prompt_tokens"),
           "out": usage.get("completion_tokens"), "cost": round(cost, 6), "seconds": round(time.time() - t0, 1)}
    with SPEND_FILE.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    if trace:
        trace(f"model call: {model} | {purpose} | {rec['in']} in / {rec['out']} out tokens | ${cost:.4f} | {rec['seconds']} s")
    return out["choices"][0]["message"].get("content") or ""


def parse_json(text):
    """Parse a JSON object from a model reply that may be wrapped in a code fence or prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except ValueError:
        start, end = t.find("{"), t.rfind("}")
        return json.loads(t[start:end + 1])


if __name__ == "__main__":
    print(f"spent ${spent():.4f} of ${BUDGET_USD:.0f}")
