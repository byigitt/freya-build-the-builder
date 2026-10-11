"""Compile a collections spec (JSON, see specs/) plus the bank's tool OpenAPI file into a Freya workflow.

The graph is fixed and tested; everything brief-specific comes from the spec:

  opening -> (third party: third_party code -> third_party_call) | identity questions identity, identity_2.. -> load_account -> prepare -> negotiate
  negotiate --transition_to_confirm_promises--> confirm_promises -> commit_k (+ retry) -> finalize -> note_k -> close_final -> end
  early exits: close_<situation> (fixed outcome and reason) -> end

Arithmetic, dates, persuasion steps, outcomes and notes are computed by builder/runtime/policy.py, which is embedded in
code steps. The phone agent's model only talks and reports what the customer said through the `assess` tool.
"""
import json, pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
POLICY_SRC = (HERE / "runtime" / "policy.py").read_text()
TOOLS = ["verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call"]


# ------------------------------------------------------------------ openapi
class Api:
    def __init__(self, openapi):
        self.doc = openapi
        self.base = (openapi.get("servers") or [{"url": ""}])[0]["url"].rstrip("/")
        self.ops = {}
        for path, item in openapi.get("paths", {}).items():
            for method, op in item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"} or not isinstance(op, dict):
                    continue
                name = op.get("operationId") or path.strip("/").split("/")[-1]
                schema = self._resolve(((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema") or {})
                resp = self._resolve((((op.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json", {}).get("schema") or {})
                key = path.strip("/").split("/")[-1]
                self.ops[key] = dict(path=path, method=method.upper(), schema=schema, response=resp, name=name, summary=op.get("summary", ""))
                if op.get("x-role") in TOOLS:
                    self.ops[op["x-role"]] = self.ops[key]

    def _resolve(self, s):
        if isinstance(s, dict) and "$ref" in s:
            ref = s["$ref"].split("/")[-1]
            return self._resolve(self.doc.get("components", {}).get("schemas", {}).get(ref, {}))
        return s

    def has(self, tool):
        return tool in self.ops

    def url(self, tool):
        return self.base + self.ops[tool]["path"]

    def method(self, tool):
        return self.ops[tool]["method"]

    def props(self, tool):
        return (self.ops[tool]["schema"] or {}).get("properties", {}) if tool in self.ops else {}

    def required(self, tool):
        return (self.ops[tool]["schema"] or {}).get("required", []) if tool in self.ops else []

    def enum(self, tool, field):
        return self.props(tool).get(field, {}).get("enum") or []

    overrides = dict()
    HINTS = {
        "customer_id": (lambda k, v: "customer" in k or k.endswith("_id") and "product" not in k),
        "product_id": (lambda k, v: "product" in k or "account" in k or "loan" in k),
        "amount": (lambda k, v: v.get("type") in ("number", "integer") or "amount" in k or "sum" in k),
        "date": (lambda k, v: v.get("format") == "date" or "date" in k or "day" in k),
        "time": (lambda k, v: "time" in k or "hour" in k),
        "reason": (lambda k, v: "reason" in k or "code" in k),
        "outcome": (lambda k, v: "outcome" in k or "result" in k or "status" in k),
        "queue": (lambda k, v: "queue" in k or "team" in k or "department" in k),
        "field": (lambda k, v: bool(v.get("enum"))),
        "answer": (lambda k, v: "answer" in k or "value" in k),
        "text": (lambda k, v: "text" in k or "note" in k or "comment" in k),
    }

    def field(self, tool, role, fallbacks=()):
        """Find the request field that plays `role`: the spec's tool_fields first, then the exact name, then by keyword and type."""
        props = self.props(tool)
        mapped = (self.overrides.get(tool) or {}).get(role)
        if mapped and mapped in props:
            return mapped
        for cand in (role,) + tuple(fallbacks):
            if cand in props:
                return cand
        taken = set((self.overrides.get(tool) or {}).values())
        hint = self.HINTS.get(role)
        if hint:
            for k, v in props.items():
                if k not in taken and hint(k.lower(), v or {}):
                    return k
        for k in props:
            if role.split("_")[-1] in k:
                return k
        return role

    def resp_props(self, tool):
        r = self.ops.get(tool, {}).get("response") or {}
        return r.get("properties", {})


# ------------------------------------------------------------------ small builders
def leaf(typ, default, desc="", enum=None):
    d = {"type": typ, "default": default}
    if desc:
        d["description"] = desc
    if enum:
        d["enum"] = enum
    return d


def api_fn(api, tool, body, name=None, desc="", pre="", post="", retries=0):
    t = {
        "type": "function",
        "config": {"timeoutMs": 12000, "maxRetries": retries},
        "function": {
            "name": name or tool, "handler": "__function__:api_call", "description": desc or tool,
            "parameters": {"type": "object", "properties": {
                "url": leaf("string", api.url(tool)),
                "method": leaf("string", api.method(tool)),
                "headers": {"type": "object", "properties": {"Content-Type": leaf("string", "application/json")}},
                "connect_retries": {"type": "number", "default": 2},
                "body": {"type": "object", "properties": body, "required": [k for k in api.required(tool) if k in body]},
            }},
        },
    }
    if pre:
        t["pre_process_code"] = check_code(pre)
    if post:
        t["post_process_code"] = check_code(post)
    return t


def check_code(code):
    if "{{" in code or "}}" in code:
        raise ValueError("generated code contains doubled braces")
    return code


def py_literal(text):
    """A Python string literal for `text` that contains no curly braces at all."""
    return repr(text).replace("{", "\\x7b").replace("}", "\\x7d")


def strip_source(src):
    out = []
    in_doc = False
    for line in src.split("\n"):
        s = line.strip()
        if s.startswith('"""') and (s.count('"""') == 1):
            in_doc = not in_doc
            continue
        if in_doc or (s.startswith('"""') and s.endswith('"""') and len(s) > 5):
            continue
        if not s or s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


POLICY_KEYS = ("bank_name", "agent_identity", "variables", "texts", "calendar", "bands", "dates", "persuasion", "multi", "reasons", "outcomes", "transfer_reasons",
               "account", "callback", "situations", "closing", "promise_reasons", "language", "locale")


def _prune(src, entry):
    """Keep only the top-level definitions the entry code can reach (smaller code steps run faster and more reliably)."""
    import ast
    tree = ast.parse(src)
    defs, other = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            defs[node.targets[0].id] = node
        else:
            other.append(node)
    def names(n):
        return {x.id for x in ast.walk(n) if isinstance(x, ast.Name)} | {x.attr for x in ast.walk(n) if isinstance(x, ast.Attribute)}
    need, todo = set(), list(names(ast.parse(entry)) | {"CFG"})
    while todo:
        k = todo.pop()
        if k in defs and k not in need:
            need.add(k)
            todo.extend(names(defs[k]))
    keep = [n for n in tree.body if n in other or any(defs.get(k) is n for k in need)]
    for n in keep:
        if isinstance(n, ast.FunctionDef) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str) and len(n.body) > 1:
            n.body = n.body[1:]                               # drop docstrings
    return ast.unparse(ast.Module(body=keep, type_ignores=[]))


def policy_code(spec, entry):
    cfg = json.dumps({k: spec[k] for k in POLICY_KEYS if k in spec}, separators=(",", ":"))
    src = strip_source(POLICY_SRC)
    try:
        src = _prune(src, entry)                         # the config is injected after pruning: unparse would decode its escapes
    except Exception:
        pass
    src = src.replace("CFG = dict()  # replaced by the compiler", "CFG = dict()").replace("CFG = dict()", "CFG = json.loads(" + py_literal(cfg) + ")", 1)
    return check_code(src + "\n" + entry + "\n")


def code_node(key, code, nxt, transitions=None):
    return {"name": key, "node_type": "code", "passthrough": True, "passthrough_default_transition": nxt,
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [{"type": "function", "config": {"timeoutMs": 20000, "maxRetries": 2},
                             "function": {"name": "code_exec", "handler": "__function__:code_exec",
                             "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code},
                                                                             "timeout_ms": {"type": "number", "default": 15000}}}}}],
            "transitions": (transitions or []) + [always(nxt)]}


def add_retry(nodes, key):
    """If the code sandbox fails (seen: 'Failed to reach snekbox'), run the same code step once more before moving on."""
    node = nodes[key]
    twin = json.loads(json.dumps(node))
    twin["name"] = key + "_again"
    nodes[key + "_again"] = twin
    node["transitions"] = [{"target_node": key + "_again", "description": "the code step failed", "condition": {"logic": "or", "conditions": [
        {"variable": key + "_failure_count", "operator": "greater_than", "operand": 0},
        {"variable": key + "_response.status", "operator": "equals", "operand": "error"}]}}] + node["transitions"]


def always(target):
    return {"target_node": target, "description": "always", "condition": {"operator": "always"}}


def eq_any(var, values, target, desc):
    return {"target_node": target, "description": desc, "condition": {"logic": "or", "conditions": [{"variable": var, "operator": "equals", "operand": v} for v in values]}}


def is_true(var, target, desc):
    return eq_any(var, ["true", "True"], target, desc)


def tool_transition(target, desc):
    return {"target_node": target, "description": desc, "is_tool_call": True, "condition": {"operator": "matches_intent", "description": desc}}


def conv(name, task, tools, transitions, on_enter=None, first_only=True):
    n = {"name": name, "node_type": "conversation", "task_message": task, "on_enter": on_enter or {"type": "llm"},
         "tools": tools, "transitions": transitions, "max_node_turns": 60, "extraction_schema": []}
    if first_only:
        n["on_enter_first_entry_only"] = True
    return n


def bullets(items):
    return "\n".join("- " + s for s in items if s)


# ------------------------------------------------------------------ hooks
POST_HEAD = "try:\n    if isinstance(result, dict):\n        result.pop('header', None)\n        d = result.get('data')\n        if not isinstance(d, dict):\n            d = dict()\n            result['data'] = d\n        ok = (str(d.get('ok')).lower() == 'true' if 'ok' in d else True) and str(result.get('status', 'success')) != 'error'\n"
POST_TAIL = "except Exception:\n    pass\n"


def post(body):
    return POST_HEAD + "\n".join("        " + l for l in body.strip("\n").split("\n")) + "\n" + POST_TAIL


def side_snippet(spec):
    """Python (no braces) that turns the extracted side_question into qa_prefix, the answer spoken before the next fixed line."""
    T = spec.get("texts", {})
    robot = T.get("robot_reply") or ("I am " + spec.get("agent_identity", "the bank's digital assistant") + ".")
    scam = T.get("scam_reply") or ("You can verify this call by phoning " + spec.get("bank_name", "the bank") + "'s customer service number.")
    why = T.get("identity_why") or ""
    return check_code(
        "k = str(vars.get('side_question') or '').strip().lower()\nvars['side_question'] = 'none'\n"
        "r = dict(robot=" + py_literal(robot) + ", scam=" + py_literal(scam) + ", purpose=" + py_literal(why) + ").get(k, '')\n"
        "vars['qa_prefix'] = (r + ' ') if r else ''\n")


def verify_post(what, hints, tool_name, side=""):
    """Turn whatever the identity tool returns into what_to_do_next plus a stable `<tool>_state` variable for routing."""
    hint_lines = ""
    for h, txt in (hints or {}).items():
        hint_lines += "if str(d.get('hint') or '') == " + repr(h) + ":\n    n = " + repr(txt) + "\n    s = 'hint'\nel"
    return post("""def tv(keys):
    for k in keys:
        if k in d:
            return str(d.get(k)).lower() == 'true'
    return None
ver = tv(['verified', 'match', 'matched', 'correct', 'passed', 'is_verified', 'valid'])
allv = tv(['all_verified', 'fully_verified', 'identity_verified', 'all_passed'])
left = None
for k in ['wrong_answers_left', 'attempts_left', 'attempts_remaining', 'remaining_attempts', 'tries_left', 'wrong_left']:
    if k in d:
        try:
            left = int(d.get(k))
        except Exception:
            left = None
        break
""" + hint_lines + """if ver or allv:
    n = 'Correct. Move on now.'
    s = 'verified'
elif not ok:
    n = 'The answer could not be checked (this does not count as wrong). Ask the customer to repeat WHAT.'
    s = 'unreadable'
elif left == 0 or str(d.get('locked')).lower() == 'true':
    n = 'The identity check has failed. Say nothing about any account or amount.'
    s = 'failed'
else:
    n = 'That answer does NOT match. Say it did not match and ask for WHAT again.'
    s = 'wrong'
d['what_to_do_next'] = n
vars['TOOL_state'] = s
""".replace("WHAT", what).replace("TOOL", tool_name) + side)


def verify_pre(kind, order, digits):
    if kind == "date":
        return ("import re, datetime\ntry:\n    b = config.get('body') or dict()\n    raw = str(b.get('ANSWER') or '').strip()\n"
                "    out = raw\n    m = re.match(r'^(\\d{4})-(\\d{1,2})-(\\d{1,2})$', raw)\n"
                "    if m:\n        out = '%04d-%02d-%02d' % (int(m.group(1)), int(m.group(2)), int(m.group(3)))\n"
                "    else:\n        m = re.match(r'^(\\d{1,2})[./ -](\\d{1,2})[./ -](\\d{2,4})$', raw)\n"
                "        if m:\n            a, c, y = int(m.group(1)), int(m.group(2)), int(m.group(3))\n            if y < 100:\n                y = y + (1900 if y > 30 else 2000)\n"
                "            day, mon = (a, c) if ORDER == 'DMY' else (c, a)\n            out = '%04d-%02d-%02d' % (y, mon, day)\n"
                "    b['ANSWER'] = out\n    config['body'] = b\nexcept Exception:\n    pass\n").replace("ORDER", repr(order))
    if kind == "digits":
        return ("import re\ntry:\n    b = config.get('body') or dict()\n    raw = str(b.get('ANSWER') or '')\n    dg = re.sub(r'\\D', '', raw)\n"
                "    if dg:\n        b['ANSWER'] = dg\n        config['body'] = b\nexcept Exception:\n    pass\n")
    return ""


# ------------------------------------------------------------------ compile
def compile_workflow(spec, openapi):
    api = Api(openapi)
    api.overrides = spec.get("tool_fields") or dict()
    T = spec.get("texts", {})
    V = spec.get("variables", {})
    cid_var = V.get("customer_id", "customer_id")
    addr = spec.get("address", "{{title}} {{last_name}}")
    full = spec.get("customer_full_name", "{{first_name}} {{last_name}}")
    agent_id = spec.get("agent_identity", "the bank's digital assistant")
    bye = T.get("goodbye", "Thank you for your time. Goodbye.")
    cid_field = api.field("close_call", "customer_id")
    CID = leaf("string", "{{" + cid_var + "}}")
    outcomes = spec.get("outcomes", {})
    closes_spec = spec.get("early_closes", {})
    tr_reason = spec.get("transfer_reasons", {"restructuring": "restructuring", "general": "human", "support": "support"})
    nodes = {}

    # ---------------- close nodes with a fixed outcome
    def close_node(key, outcome, reason, text):
        f_out = api.field("close_call", "outcome")
        f_rea = api.field("close_call", "reason")
        body = {cid_field: CID, f_out: leaf("string", outcome)}
        if reason:
            body[f_rea] = leaf("string", reason)
        nodes[key] = {"name": key, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "end",
                      "on_enter": {"type": "tts", "text": text}, "disable_inactivity_monitor": True,
                      "pre_actions": [api_fn(api, "close_call", body, desc="End the call.")], "response_mapping": [], "transitions": [always("end")]}
        return key

    early_text = {
        "unclear": T.get("close_unclear", "I am sorry, I could not confirm who I am speaking with. " + bye),
        "callback": T.get("close_callback", "Thank you, we will call back then. Goodbye."),
        "no_callback": T.get("close_no_callback", "Thank you, we will try again another time. Goodbye."),
        "wrong_number": T.get("close_wrong_number", "I apologise for the disturbance. Goodbye."),
        "deceased": T.get("close_deceased", T.get("condolence", "I am sorry for your loss.") + " " + T.get("goodbye_short", "Goodbye.")),
        "id_failed": T.get("close_id_failed", T.get("identity_failed", "I could not verify your identity.") + " " + bye),
        "id_declined": T.get("close_id_declined", "I understand. Without the security check I cannot continue this call. " + bye),
    }
    for key, (oc, rs) in closes_spec.items():
        close_node("close_" + key, oc, rs, spec.get("close_texts", {}).get(key) or early_text.get(key, bye))
    if "close_id_declined" not in nodes:
        close_node("close_id_declined", outcomes.get("not_verified", "not_verified"), "declined", early_text["id_declined"])
    nodes["close_transfer_human_early"] = None  # placeholder, replaced below

    # ---------------- tools shared by several steps
    q_field = api.field("transfer_to_agent", "queue")
    queues = api.enum("transfer_to_agent", q_field) or list(tr_reason)

    def transfer_tool(queue, when):
        return api_fn(api, "transfer_to_agent", {cid_field: CID, q_field: leaf("string", queue)}, name="transfer_" + queue,
                      desc="Transfer the call to the " + queue + " team. CALL it " + when,
                      post=post("if ok:\n    vars['transfer_queue_done'] = " + repr(queue) + "\n    d['what_to_do_next'] = 'Transferred. Say one short sentence that you are transferring them now.'\nelse:\n    d['what_to_do_next'] = 'The transfer did NOT work. Do not say you transferred. Say the transfer is not possible right now and continue.'"))

    situations = spec.get("situations", {})
    human_q = (situations.get("human") or {}).get("queue", "general")
    human_tr = transfer_tool(human_q, "only when the person insists on a human after you asked once whether you can help first.") if human_q in queues else None
    oc_tr = outcomes.get("transferred", "transferred")
    close_node("close_transfer_early", oc_tr, tr_reason.get(human_q, "human"), T.get("close_transfer_early", "I am transferring you to a colleague now. " + bye))
    del nodes["close_transfer_human_early"]

    def human_exit():
        return [is_true("transfer_" + human_q + "_response.data.ok", "close_transfer_early", "the transfer to a human worked")] if human_tr else []

    # ---------------- system prompt
    forbidden = ", ".join(spec.get("forbidden_before_verification", []))
    system = (
        "You are " + agent_id + " on an outbound phone call from " + spec.get("bank_name", "the bank") + " to " + addr + " (" + full + "). "
        "Speak " + spec.get("language", "English") + ". Keep every turn to one or two short sentences. Address the customer as " + addr + ".\n"
        "The current date and time is {{" + V.get("now", "now") + "}}. Never use any other clock. Never compute dates or amounts yourself: use the facts in your current task.\n\n"
        "Rules at every step:\n" + bullets(spec.get("global_rules", [])) + "\n"
        "- Until both security answers are verified, never say why you are calling and never mention: " + forbidden + ".\n"
        "- Tools: when a rule says to call a tool, CALL it. Saying you did something is not doing it. Call at most one tool per message. "
        "After every tool result, speak to the customer or call the next tool. Never end a turn with nothing. If a tool result has what_to_do_next, follow it.\n"
        "- Never say that something is recorded, booked or transferred unless a tool result says so. If a tool call fails with an error, never invent its result: say you could not check it and ask again.\n"
        "- When you call a transition_to_... tool, the closing words are spoken automatically right after. Do not say goodbye yourself."
    )

    # ---------------- opening
    op = spec.get("opening", {})
    first_line = T.get("opening", "Hello, this is " + agent_id + ".") + " " + T.get("identity_question", "Am I speaking with " + addr + "?")
    max_asks = max(1, int(op.get("max_asks", 2) or 2))
    idq_text = T.get("identity_question", "Am I speaking with " + addr + "?")
    # Who is on the line is extracted before the reply and routed in code, and the asks are counted in code: a model
    # tool-call transition in the same turn as a reply does not reliably move the call on.
    who_extract = [
        {"name": "who_answer", "type": "string", "min_confidence": 0.4,
         "enum_values": ["confirmed", "someone_else", "not_confirmed"],
         "description": "How the person's LATEST message answers whether they are " + full + ". "
                        "confirmed: a clear yes, 'that's me', 'speaking', or their own name (" + op.get("confirmation", "") + "). "
                        "someone_else: they say they are someone else (a relative, flatmate, colleague), the customer is not there or not available, "
                        "the number is not the customer's, they do not know the customer, or the customer has died. "
                        "not_confirmed: anything else ('hello', 'who is this?', 'why?', 'what is this about?', a question, a refusal to say)."},
        {"name": "other_kind", "type": "string", "min_confidence": 0.4,
         "enum_values": ["deceased", "wrong_number", "other"],
         "description": "Only when someone else answers: deceased if they say the customer has died; wrong_number if they say the number does not belong to the customer or they do not know the customer; otherwise other."},
    ]
    side_q = [{"name": "side_question", "type": "string", "min_confidence": 0.4, "enum_values": ["none", "robot", "scam", "purpose"],
               "description": "Did the person's LATEST message also ask a question? robot: whether they talk to a robot, an AI or a real person; "
                              "scam: whether this is a scam or a real call from the bank; purpose: why you need this or what the call is about; none: no such question."}]
    who_extract.append(side_q[0])
    who_trans = [
        eq_any("who_answer", ["confirmed"], "to_identity", "the person confirmed they are the customer"),
        {"target_node": "close_deceased", "description": "the customer has died", "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
            {"variable": "who_answer", "operator": "equals", "operand": "someone_else"}, {"variable": "other_kind", "operator": "equals", "operand": "deceased"}]}]}},
        {"target_node": "close_wrong_number", "description": "wrong number", "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
            {"variable": "who_answer", "operator": "equals", "operand": "someone_else"}, {"variable": "other_kind", "operator": "equals", "operand": "wrong_number"}]}]}},
        eq_any("who_answer", ["someone_else"], "third_party", "someone else is on the line"),
        eq_any("who_answer", ["not_confirmed"], "opening_count", "not a confirmation"),
    ]
    open_task = (
        "The opening line was already said: \"" + first_line + "\"\n"
        "Your only job in this step: find out whether " + addr + " is the person on the line. Never say why you are calling. "
        "If asked what it is about, say you can only discuss it with " + addr + " personally. If asked whether you are a robot or whether this is a scam, answer per the rules.\n"
        "If the person asks for a human: the first time, ask whether you can help first. If they insist, call transfer_" + human_q + ".\n"
        "If the person says for the second time that they do not want to talk, call transition_to_close_id_declined.\n"
        "Otherwise: if they clearly confirmed, call transition_to_to_identity; if someone else is on the line, call transition_to_third_party; "
        "if it is not a confirmation, call transition_to_opening_count. Say nothing yourself in those cases.\n"
        + bullets(op.get("rules", [])) + "\nALWAYS:\n" + bullets(spec.get("global_rules", []))
    )
    extra_open = human_exit() + [
        # fallbacks the model can use if the deterministic routing above did not run for this message
        tool_transition("to_identity", "The person clearly confirmed they are the customer."),
        tool_transition("third_party", "Someone other than the customer is on the line, the customer is not available or not known, or has died."),
        tool_transition("opening_count", "The latest answer is not a confirmation and not someone else."),
        tool_transition("close_id_declined", "The person said twice that they do not want to talk.")]
    nodes["opening"] = conv("opening", open_task, [human_tr] if human_tr else [], who_trans + extra_open, on_enter={"type": "tts", "text": first_line})
    nodes["opening"]["extraction_schema"] = list(who_extract)
    nodes["to_identity"] = code_node("to_identity", policy_code(spec, "side_answer(vars)"), "identity")
    nodes["opening_count"] = code_node("opening_count", check_code(
        "try:\n    n = int(float(vars.get('opening_asks') or 1)) + 1\nexcept Exception:\n    n = 2\n"
        "vars['opening_asks'] = str(n)\nvars['who_answer'] = ''\nvars['other_kind'] = ''\n"
        "vars['opening_state'] = 'close' if n > " + str(max_asks) + " else 'ask'\n"), "opening_retry",
        [eq_any("opening_state", ["close"], "close_unclear", "the identity question was asked the allowed number of times")])
    retry_enter = {"type": "llm", "prompt": (
        "The person did not confirm. If their last message asked a question (who you are, whether you are a robot, whether this is a scam, what it is about), "
        "answer it in one short sentence following the rules, without saying why you are calling. Then ask exactly: \"" + idq_text + "\" Say nothing else and call no tool.")}
    nodes["opening_retry"] = conv("opening_retry", open_task, [human_tr] if human_tr else [], who_trans + extra_open, on_enter=retry_enter, first_only=False)
    nodes["opening_retry"]["extraction_schema"] = list(who_extract)

    # ---------------- third party
    cb = spec.get("callback", {})
    d_f, t_f = api.field("schedule_callback", "date"), api.field("schedule_callback", "time")
    # The day and time the person gives are extracted before the reply and checked in code in the same turn, so the
    # agent never answers before the bank's rules decided (a model tool's result is only seen one turn later).
    cb_extract = [{"name": "cb_offer", "type": "string", "min_confidence": 0.3,
                   "description": "If the person's LATEST message says a day and/or a time when the customer can be reached or called back, "
                                  "copy those words exactly (for example: 'tomorrow around eleven', 'today at 11:30 am', 'next Tuesday', 'Saturday'). "
                                  "Empty if the latest message gives no day and no time."}]
    cb_check_code = policy_code(spec, (
        "offer = str(vars.get('cb_offer') or '').strip()\n"
        "vars['cb_offer'] = ''\n"
        "if offer:\n"
        "    d, t = split_day_time(offer)\n"
        "    run_callback(vars, dict(day=d, time=t))\n"
        "else:\n"
        "    vars['cb_state'] = 'none'\n"))
    tp_task = (
        "Someone other than " + addr + " is on the line.\nStrict rules: say nothing beyond the opening sentence about who you are. Never say why you are calling. "
        "Never mention " + forbidden + ". Never ask for or accept security answers. Never tell anything about the customer or an account, even if they say they are family or offer to pay; "
        "then say you can only speak with " + addr + ".\n" + bullets(spec.get("third_party", {}).get("rules", []) + (spec.get("callback", {}).get("rules") or [])) + "\n\n"
        "Decide on the person's messages:\n"
        "1. They say this number does not belong to " + full + " or they do not know this person: call transition_to_close_wrong_number.\n"
        "2. They say " + full + " has died: call transition_to_close_deceased immediately, with no words of your own (the condolence is spoken automatically). Ask nothing.\n"
        "3. Otherwise ask when " + addr + " can be reached: which day and at what time. The bank's rules check every day and time they give. Never promise or book a time yourself.\n"
        "4. If they say they cannot say when, or refuse to give a time, call transition_to_close_no_callback.\n"
    )
    tp_kind = [{"name": "tp_kind", "type": "string", "min_confidence": 0.4, "enum_values": ["deceased", "wrong_number", "none"],
                "description": "deceased if the person's LATEST message says the customer has died; wrong_number if it says the number does not belong to the customer or they do not know the customer; otherwise none."}]
    cb_trans = [
        eq_any("tp_kind", ["deceased"], "close_deceased", "the customer has died"),
        eq_any("tp_kind", ["wrong_number"], "close_wrong_number", "wrong number"),
        {"target_node": "cb_check", "description": "the person gave a day or a time", "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
            {"variable": "cb_offer", "operator": "is_set"}, {"variable": "cb_offer", "operator": "not_equals", "operand": ""}]}]}},
        tool_transition("close_wrong_number", "The number does not belong to the customer."),
        tool_transition("close_deceased", "The customer has died."),
        tool_transition("close_no_callback", "The person cannot or will not say when the customer can be reached."),
    ]
    nodes["third_party"] = code_node("third_party", policy_code(spec, "run_setup(vars)\nvars['cb_state'] = 'none'\n"), "third_party_call", [
        {"target_node": "cb_check", "description": "a day or time was already given", "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
            {"variable": "cb_offer", "operator": "is_set"}, {"variable": "cb_offer", "operator": "not_equals", "operand": ""}]}]}}])
    nodes["third_party_call"] = conv("third_party_call", tp_task, [], cb_trans)
    nodes["third_party_call"]["extraction_schema"] = cb_extract + tp_kind
    for k in list(nodes):
        if k in ("opening", "opening_retry"):
            nodes[k]["extraction_schema"] = nodes[k]["extraction_schema"] + cb_extract   # a day or time said in the first answer is not lost
    nodes["cb_check"] = code_node("cb_check", cb_check_code, "third_party_ask", [
        eq_any("cb_state", ["book"], "cb_book", "a callback time inside the window was given"),
        eq_any("cb_state", ["give_up"], "close_no_callback", "no callback inside the window"),
    ])
    nodes["third_party_ask"] = conv("third_party_ask", tp_task, [], cb_trans, on_enter={"type": "tts", "text": "{{cb_say}}"}, first_only=False)
    nodes["third_party_ask"]["extraction_schema"] = cb_extract + tp_kind
    nodes["cb_book"] = {"name": "cb_book", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "close_no_callback",
                        "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                        "pre_actions": [api_fn(api, "schedule_callback", {cid_field: CID, d_f: leaf("string", "{{cb_date}}"), t_f: leaf("string", "{{cb_time}}")}, desc="Book the callback.")],
                        "response_mapping": [], "transitions": [
                            is_true("cb_book_response.data.ok", "close_callback", "the callback was booked"),
                            {"target_node": "close_callback", "description": "booked", "condition": {"logic": "or", "conditions": [{"variable": "cb_book_success_count", "operator": "greater_than", "operand": 0}]}},
                            always("close_no_callback")]}

    # ---------------- identity
    idq = spec.get("identity", {}).get("questions", [])
    f_field, a_field = api.field("verify_identity", "field"), api.field("verify_identity", "answer")
    decline_rule = spec.get("identity", {}).get("decline_rule", "")
    id_common = (
        "\nNever say why you are calling and never mention " + forbidden + " until every security answer is verified.\n" + decline_rule + "\n"
        "Refusals to answer are counted by the bank's rules, which explain the purpose and end the call when needed: never end the call yourself. "
        "A question that only asks why you need the information is not a refusal: answer it every time it is asked, with the reason given below, and wait for the answer.\n"
        "If the customer asks for a human: the first time, ask whether you can help first. If they insist, call transfer_" + human_q + ".\n"
        + bullets(spec.get("identity", {}).get("rules", [])) + "\nIf the customer asked a question earlier in the call that has not been answered yet (for example whether this is a scam or whether you are a robot), answer it in one sentence before your next question.\nALWAYS (also while asking security questions):\n" + bullets(spec.get("global_rules", [])) + "\nDo not call any other tool."
    )
    hints = spec.get("identity", {}).get("hints", {})
    order = spec.get("identity", {}).get("date_numeric_order", "DMY")
    fail_conds = []
    for i, q in enumerate(idq):
        tool_name = "verify_" + re.sub(r"\W", "_", q["field"])
        fail_conds.append({"variable": tool_name + "_response.data.wrong_answers_left", "operator": "equals", "operand": "0"})
        fail_conds.append({"variable": tool_name + "_state", "operator": "equals", "operand": "failed"})
    failed_tr = {"target_node": "close_id_failed", "description": "no wrong answers left", "condition": {"logic": "or", "conditions": fail_conds}}
    refusal_x = [{"name": "id_reply", "type": "string", "min_confidence": 0.5,
                  "enum_values": ["answer", "refuses", "why_needed", "call_purpose", "asks_if_genuine", "wants_human", "other"],
                  "description": "What the person's LATEST message does with the security question. "
                                 "answer: it gives the answer (or part of it). "
                                 "refuses: it says they will not give it, are not comfortable giving it, or want to skip it (even if it also asks a question). "
                                 "why_needed: it ONLY asks why you need this information, without refusing (for example 'Why do you need that?'). "
                                 "call_purpose: it asks what the call is about instead of answering. "
                                 "asks_if_genuine: it asks whether this is a scam, a real call from the bank, or whether you are a robot or an AI. "
                                 "wants_human: it asks for a human or a real person. "
                                 "other: anything else."}]
    max_decl = int(spec.get("identity", {}).get("max_declines", 2) or 2)
    decline_kinds = ["refuses"] + (["call_purpose"] if spec.get("identity", {}).get("call_purpose_counts_as_decline", True) else [])

    def add_refusal(key):
        """Refusals are counted in code; the first one gets the purpose explained once, the last one closes the call."""
        nodes[key]["extraction_schema"] = nodes[key].get("extraction_schema", []) + refusal_x
        nodes[key]["transitions"].insert(0, {"target_node": key + "_decl", "description": "the customer refused to answer", "condition": {"logic": "or", "conditions": [
            {"logic": "and", "conditions": [{"variable": "id_reply", "operator": "equals", "operand": k},
                                            {"variable": "side_question", "operator": "not_equals", "operand": "scam"},
                                            {"variable": "side_question", "operator": "not_equals", "operand": "robot"}]} for k in decline_kinds]}})
        nodes[key + "_decl"] = code_node(key + "_decl", check_code(
            "try:\n    n = int(float(vars.get('identity_declines') or 0)) + 1\nexcept Exception:\n    n = 1\n"
            "vars['identity_declines'] = str(n)\nvars['id_reply'] = 'other'\n"
            "vars['identity_decline_state'] = 'close' if n >= " + str(max_decl) + " else 'explain'\n"), key + "_re",
            [eq_any("identity_decline_state", ["close"], "close_id_declined", "refused too often")])
        twin = json.loads(json.dumps(nodes[key]))
        twin["name"] = key + "_re"
        twin["on_enter"] = {"type": "tts", "text": T.get("identity_why", "These questions protect your account.") + " " + reask[key]}
        twin["on_enter_first_entry_only"] = False
        nodes[key + "_re"] = twin

    reask = dict()
    declined_tr = eq_any("identity_decline_state", ["close"], "close_id_declined", "second refusal of the security questions")
    decline_tool = {"type": "function", "function": {
        "name": "record_decline", "handler": "__function__:code_exec",
        "description": "CALL it only when the customer clearly refuses to answer a security question ('I won't tell you that', 'skip it'), or asks what the call is about instead of answering. "
                       "A question about the security question itself ('why do you need that?', 'which number?') is NOT a refusal when it comes alone. If the same message also refuses ('I won't give it, why do you need it?'), it IS a refusal: call record_decline.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": check_code(
            "try:\n    n = int(float(vars.get('identity_declines') or 0)) + 1\nexcept Exception:\n    n = 1\n"
            "vars['identity_declines'] = str(n)\nvars['identity_decline_state'] = 'close' if n >= " + str(int(spec.get("identity", {}).get("max_declines", 2) or 2)) + " else 'explain'\n")}}, "required": []}}}
    vprops = api.props("verify_identity")
    per_question = f_field in vprops and a_field in vprops
    if not per_question and idq:
        # The tool takes every answer in one call: one step collects them all.
        body = {cid_field: CID}
        for q in idq:
            fld = q["field"] if q["field"] in vprops else api.field("verify_identity", q["field"])
            body[fld] = leaf((vprops.get(fld) or {}).get("type", "string"), "{{ans_" + re.sub(r"\W", "_", fld) + "}}",
                             ("The date as YYYY-MM-DD. " if q.get("kind") == "date" else "") + q.get("say_name", fld))
        asks = " Then ".join(q.get("ask", "") for q in idq)
        task = ("Security questions, one at a time, in this order: " + asks + "\nWhen you have every answer, call verify_identity with all of them. "
                "Convert spoken dates to YYYY-MM-DD (a numbers-only date is " + ("day, month, year" if order == "DMY" else "month, day, year") + "). "
                "If an answer is incomplete, ask for the missing part first. After the result, follow what_to_do_next exactly." + id_common)
        tool = api_fn(api, "verify_identity", body, desc="Check the security answers. CALL it once you have every answer. Then follow what_to_do_next.",
                      post=verify_post("the answers", hints, "verify_identity", side_snippet(spec)))
        failed_tr["condition"]["conditions"].append({"variable": "verify_identity_state", "operator": "equals", "operand": "failed"})
        nodes["identity"] = conv("identity", task, [tool] + ([human_tr] if human_tr else []), [
            eq_any("verify_identity_state", ["verified"], "load_account", "answers verified"), failed_tr] + human_exit() + [declined_tr],
            on_enter={"type": "tts", "text": "{{qa_prefix}}" + T.get("thanks_address", "Thank you, " + addr + ".") + " " + idq[0].get("ask", "")})
        nodes["identity"]["extraction_schema"] = list(side_q)
        reask["identity"] = idq[0].get("ask", "")
        add_refusal("identity")
        idq = []
    for i, q in enumerate(idq):
        key = "identity" if i == 0 else "identity_" + str(i + 1)
        nxt = "identity_" + str(i + 2) if i + 1 < len(idq) else "load_account"
        tool_name = "verify_" + re.sub(r"\W", "_", q["field"])
        kind = q.get("kind", "text")
        if kind == "year":
            kind, q = "digits", dict(q, digits=q.get("digits") or 4)
        if kind == "date":
            how = ("As soon as the customer has said a day, a month and a year, call " + tool_name + " with the date as YYYY-MM-DD. Do this even if the sentence trails off: "
                   "a day, a month and a year is a complete answer. Convert spoken dates (\"twelfth of July nineteen ninety\" -> 1990-07-12). "
                   + ("A date said only in numbers is day, then month, then year (\"05/03/1980\" -> 1980-03-05). " if order == "DMY" else "A date said only in numbers is month, then day, then year. ")
                   + "If the day, the month or the year is missing, ask for the missing part first.")
            adesc = "The date as YYYY-MM-DD."
        elif kind == "digits":
            n = q.get("digits")
            how = ("As soon as the customer has said all " + (str(n) + " " if n else "") + "digits, call " + tool_name + " with the digits only. "
                   "If they gave only part of it (for example two digits, then a pause), ask for the rest first and join the parts.")
            adesc = "Digits only" + (", exactly " + str(n) if n else "") + "."
        else:
            how = "As soon as the customer has given the complete answer, call " + tool_name + " with the answer exactly as given (normalized: no extra words)."
            adesc = q.get("format", "The answer.")
        thanks = (T.get("thanks_address", "Thank you, " + addr + ".") if i == 0 else T.get("thanks", "Thank you.")) + " "
        why = T.get("identity_why", "These questions protect your account.")
        robot = T.get("robot_reply") or ("I am " + agent_id + ".")
        scam = T.get("scam_reply") or ("You can verify this call by phoning " + spec.get("bank_name", "the bank") + "'s customer service number.")
        task = ("Security question " + str(i + 1) + " of " + str(len(idq)) + ": you asked for the " + q.get("say_name", q["field"].replace("_", " ")) + ".\n"
                "If the latest message asks whether you are a robot, an AI or a real person, your reply MUST begin with: \"" + robot + "\" "
                "If it asks whether this is a scam or a real call, your reply MUST begin with: \"" + scam + "\" Then continue.\n"
                "If the customer asks why you need it (instead of answering), reply with exactly this and nothing more: \"" + why + "\" Do not ask the question again in that reply.\n" + how +
                "\nIf the customer's message is cut off or has no answer in it, say something short like '" + T.get("listening", "Go on, I am listening.") + "' If you already said that and their next message is cut off again, briefly repeat the question.\nIf a message contains an answer together with a question or a complaint, FIRST call " + tool_name + " with the answer, then reply to the rest. Every answer given counts and must be checked.\n"
                "After each result, follow what_to_do_next exactly. A wrong answer is asked again; the check counts wrong answers itself. "
                "Never ask a question that was already verified again." + id_common)
        tool = api_fn(api, "verify_identity", {cid_field: CID, f_field: leaf("string", q["field"]), a_field: leaf("string", "{{answer}}", adesc)}, name=tool_name,
                      desc="Check the " + q.get("say_name", q["field"]) + ". CALL it every time the customer gives a complete answer. Then follow what_to_do_next.",
                      pre=verify_pre(kind, order, q.get("digits")).replace("ANSWER", a_field),
                      post=verify_post("the " + q.get("say_name", q["field"]), hints, tool_name, side_snippet(spec)))
        ok_var = tool_name + "_response.data."
        nodes[key] = conv(key, task, [tool] + ([human_tr] if human_tr else []), [
            {"target_node": nxt, "description": "answer verified", "condition": {"logic": "or", "conditions": [
                {"variable": tool_name + "_state", "operator": "equals", "operand": "verified"},
                {"variable": ok_var + "verified", "operator": "equals", "operand": "true"},
                {"variable": ok_var + "verified", "operator": "equals", "operand": "True"},
                {"variable": ok_var + "all_verified", "operator": "equals", "operand": "true"},
                {"variable": ok_var + "all_verified", "operator": "equals", "operand": "True"}]}},
            failed_tr,
        ] + human_exit() + [declined_tr], on_enter={"type": "tts", "text": "{{qa_prefix}}" + thanks + q.get("ask", "")})
        nodes[key]["extraction_schema"] = list(side_q)
        reask[key] = q.get("ask", "")
        add_refusal(key)

    # ---------------- account
    products_field = spec.get("account", {}).get("products_field", "products") or ""   # empty: the account itself is the one product
    nodes["load_account"] = {
        "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "prepare",
        "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
        "pre_actions": [api_fn(api, "get_account", {cid_field: CID}, desc="Get the late products.", retries=2)],
        "response_mapping": [{"path": ("data." + products_field) if products_field else "data", "variable": "account_products"}],
        "transitions": [always("prepare")],
    }
    nodes["prepare"] = code_node("prepare", policy_code(spec, "run_prepare(vars)"), "negotiate")

    # ---------------- negotiation
    events = {
        "pay_today": "they clearly agree to pay TODAY / right now ('yes, today'). Only when they say today or now. A named day (Friday, tomorrow, the 20th) is propose; 'I will pay' without a day is not pay_today, ask which day",
        "propose": "they name a day and/or an amount themselves (pass what they said in date and amount)",
        "accept_offer": "they accept the offer you just made",
        "too_much": "they explicitly say the AMOUNT itself is too high for them or ask to pay a smaller part, without naming an amount. Not 'I cannot pay today' and not 'I cannot pay all of that today'",
        "refuse": "a clear no with no day and no amount: 'no', 'I can't pay', 'not today', 'I cannot pay all of that today', 'not that day'. These are refusals, not too_much",
        "vague": "they give a vague period (next week, end of the month, when my salary comes) instead of a day",
        "cut_off": "their message breaks off in the middle of a sentence (it is clearly unfinished, for example 'I can pay the')",
        "question": "they ask you something instead of answering (a question back, 'which account?', 'is that acceptable?', 'are you still there?')",
        "no_answer": "a complete reply that avoids your question without asking anything ('hmm', 'I don't know', only talk about something else). Not for unfinished messages and not for questions",
        "situation": "one of the PRIORITY SITUATIONS below (give its name in situation)",
    }
    sit_ids = list(situations)
    # `assess` is a read-only bank call (get_account): its pre-hook runs the policy and rewrites the request to a plain
    # account read, its post-hook puts the policy's next step into the tool result, where the model reliably reads it.
    assess_body = {
        cid_field: CID,
        "a_event": {"type": "string", "enum": list(events), "default": "{{a_event}}", "description": "; ".join(k + " = " + v for k, v in events.items())},
        "a_product": {"type": "string", "default": "{{a_product}}", "description": "The product id (p1, p2, ...), or several ids separated by commas (p1,p2) when the same answer applies to exactly those products, or all ONLY when it explicitly applies to every remaining product. Never include a product the customer did not mention."},
        "a_date": {"type": "string", "default": "{{a_date}}", "description": "The day the customer said, as YYYY-MM-DD if you are sure, otherwise their exact words (for example: next Friday, the 26th). Empty if none."},
        "a_amount": {"type": "string", "default": "{{a_amount}}", "description": "Only an explicit amount for this one product, as a number. Empty if none, if they say 'the full amount', or if they give one total for several products."},
    }
    if sit_ids:
        assess_body["a_situation"] = {"type": "string", "enum": sit_ids, "default": "{{a_situation}}", "description": "Only with event situation: the name of the PRIORITY SITUATION."}
        assess_body["b_situation"] = {"type": "string", "enum": sit_ids + ["none"], "default": "{{b_situation}}",
                                      "description": "Only when the SAME message ALSO describes a PRIORITY SITUATION for OTHER products than a_product "
                                                     "(for example: 'I can pay the card on Friday, but I lost my job and cannot pay the loan'): its name. Otherwise none."}
        assess_body["b_product"] = {"type": "string", "default": "{{b_product}}", "description": "Only with b_situation: the product id(s) that situation is about. Empty otherwise."}
    assess_pre = policy_code(spec, (
        "try:\n    b = config.get('body') or dict()\n    prm = dict()\n"
        "    for k in ('event', 'product', 'date', 'amount', 'situation'):\n        v = b.get('a_' + k)\n"
        "        if v is not None and str(v).strip().startswith('{'):\n            v = None\n        prm[k] = v\n"
        "    vars['assess_last_args'] = json.dumps(prm)\n    run_assess(vars, prm)\n"
        "    bs = str(b.get('b_situation') or '').strip().lower()\n    bp = str(b.get('b_product') or '').strip().lower()\n"
        "    first = [x.strip() for x in str(prm.get('product') or '').lower().split(',')]\n"
        "    if bs and bs != 'none' and not bs.startswith('{') and bp and not bp.startswith('{') and bp != 'all' and str(prm.get('event') or '') != 'situation' and not any(x in first for x in bp.split(',')):\n"
        "        run_assess(vars, dict(event='situation', situation=bs, product=bp))\n"
        "    config['body'] = dict([(" + repr(cid_field) + ", b.get(" + repr(cid_field) + "))])\n"
        "except Exception as e:\n    vars['next_instruction'] = 'Continue carefully. (policy error ' + str(e)[:60] + ')'\n"))
    assess_post = ("try:\n    if isinstance(result, dict):\n        result.pop('header', None)\n"
                   "        result['data'] = dict(next_step=str(vars.get('next_instruction') or 'Continue.'), say_it=" + py_literal("Now reply out loud with at least one short sentence: what next_step says, in your own words. If you already said it in this turn, say something short like " + T.get("take_your_time", "Take your time.") + " Never reply with nothing, and do not add other offers.") + ")\n"
                   "except Exception:\n    pass\n")
    assess_tool = api_fn(api, "get_account", assess_body, name="assess",
                         desc="Report what the customer just said. CALL it after EVERY customer answer about paying, a day, an amount, your offer, the debt or a PRIORITY SITUATION, BEFORE you reply. The result tells you exactly what to say next (next_step).",
                         pre=assess_pre, post=assess_post)
    assess_tool["function"]["parameters"]["properties"]["body"]["required"] = [cid_field, "a_event", "a_product"]
    sit_lines = []
    for key, s in situations.items():
        how = " -> call assess with a_event situation, a_situation " + key + (", a_product all" if s.get("scope") == "all" or s.get("effect") in ("call", "transfer") else ", and a_product the product it is about (or all)") + ". The result's next_step tells you what to say."
        if s.get("offer_queue"):
            how += (" When they answer your offer (yes or no, even together with another question), FIRST call assess with a_event accept_offer or refuse. "
                    "After this situation, never ask about a payment, a day or an amount yourself; only the customer may bring one up.")
        sit_lines.append(key.upper() + ": " + s.get("trigger", "") + how)
    tr_tools = []
    neg_task = (
        "The customer is verified. You already stated the debt: \"{{debt_statement}}\"\n\n"
        "LAST INSTRUCTION FROM THE BANK'S RULES: {{next_instruction}}\n\n"
        "FACTS (computed for you; trust them):\n- Today: {{today_say}}.\n{{facts}}\n- Weekday words:\n{{week_table}}\n\n"
        "HOW TO WORK\n"
        "1. After EVERY customer message, whatever it says, FIRST call assess (a_event, a_product, a_date, a_amount as they said it). "
        "The result's next_step is what you say next, in your own short words. Say only that: never decide dates, amounts or offers yourself, never add an offer of your own, and never skip assess.\n"
        "   A PRIORITY SITUATION is reported every time it comes up, also when the customer repeats it (for example a second request for a human). "
        "Call assess ONCE per customer message, never several at the same time. Products are handled one at a time: report the answer for the product the last instruction is about "
        "(now: {{current_product}}), or a_product all when the answer covers every product. What they say about later products is taken up when their turn comes. "
        "A PRIORITY SITUATION about any product may be reported at once: if the same message also answers about other products, put the situation in b_situation and its product in b_product of the same assess call. When one message says different things about different products "
        "(for example 'I paid the card this morning, and the loan was closed years ago'), report each product separately, one assess call after the other "
        "(wait for each result), each with its own event or situation. A recent payment of the past-due amount is paid; a claim that a product was closed or paid off in the past is a dispute.\n"
        "2. A day or an amount the customer names is never a refusal: use a_event propose. A message that breaks off mid-sentence: use a_event cut_off. "
        "A complete message that does not answer the question: use a_event no_answer.\n"
        "   A cut-off message is not lost: read it together with the next one, and report what both say (a cut-off 'I lost my job in...' followed by 'I cannot pay anything' is that PRIORITY SITUATION). "
        "Report a PRIORITY SITUATION only when the words match its description; a request for something no situation describes (for example a discount) is answered by the rules, not reported as a situation. "
        "If the messages match several PRIORITY SITUATIONS, report the one listed first.\n"
        "3. When next_step says to read back, read it back exactly and ask \"" + T.get("confirm_question", "Do you confirm?") + "\". "
        "When the customer clearly says yes to the read-back, call transition_to_confirm_promises. If the yes comes with a question, first answer it in one sentence "
        "(for example: a recorded promise can be changed later in the mobile app), then call transition_to_confirm_promises. If they change a day or an amount instead, call assess with a_event propose.\n"
        "4. Never say a promise is recorded: that is said for you after it is recorded.\n"
        "5. People talk loosely. If a number or a date sounds unfinished (\"four hundred and...\", \"the twenty...\"), ask them to finish it before you call assess, and join the parts. "
        "If they correct themselves (\"the 21st, sorry, the 20th\"), use the corrected value. Amounts and dates said in words are normal: convert them. "
        "Dates they mention that are not about paying (a wedding, a birthday) are not proposals. If they ask a question back, answer it briefly, then continue.\n"
        "6. Say a sentence of sympathy at most once in the whole call.\n\n"
        "PRIORITY SITUATIONS (check these first on every customer message):\n" + bullets(sit_lines) + "\n\n"
        "RULES\n" + bullets(spec.get("negotiation_rules", [])) + "\n\nALWAYS:\n" + bullets(spec.get("global_rules", []))
    )
    neg_trans = [
        {"target_node": "finalize", "description": "the call was already transferred", "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
            {"variable": "transfer_queue_done", "operator": "is_set"}, {"variable": "transfer_queue_done", "operator": "not_equals", "operand": ""}]}]}},
        eq_any("policy_phase", ["offer"], "offer_decision", "an offer to connect the customer was made"),
        eq_any("policy_phase", ["transfer"], "transfer_exec", "the policy asks for a transfer"),
        eq_any("policy_phase", ["done"], "finalize", "nothing left to agree"),
        tool_transition("confirm_promises", "The customer clearly said yes to the read-back of every agreed promise."),
    ]
    nodes["negotiate"] = conv("negotiate", neg_task, [assess_tool], neg_trans,
                              on_enter={"type": "tts", "text": "{{qa_prefix}}" + T.get("thanks_address", "Thank you, " + addr + ".") + " {{debt_statement}}"})
    # An offer (for example to connect a customer in hardship with a support team) gets its own step: the model only decides yes or no.
    offer_task = (
        "The customer is verified and told you about their situation. Do this now, in one or two short sentences: {{next_instruction}}\n"
        "Then wait for their answer and decide:\n"
        "- They accept being connected or transferred: call transition_to_offer_accept.\n"
        "- They decline, or answer with anything else without accepting (for example they ask for a discount, or say they cannot pay): "
        "if they asked a question, answer it in one short sentence (never offer a discount, a plan or any other term), then call transition_to_offer_decline.\n"
        "- They name a day or an amount to pay themselves: call assess with a_event propose (a_date, a_amount as they said it), "
        "with a_product the products they named (for example p1,p2; all only if they clearly mean every product).\n"
        "- They ask for a different person or team instead (for example a human): call assess with a_event situation and that PRIORITY SITUATION's name.\n"
        "Never ask about a payment, a day or an amount yourself. Never repeat the offer.\n\nALWAYS:\n" + bullets(spec.get("global_rules", []))
    )
    nodes["offer_decision"] = conv("offer_decision", offer_task, [assess_tool], [
        eq_any("policy_phase", ["transfer"], "transfer_exec", "transfer requested"),
        eq_any("policy_phase", ["done"], "finalize", "nothing left to agree"),
        eq_any("policy_phase", ["negotiating", "readback"], "negotiate", "the customer proposed a payment"),
        tool_transition("offer_accept", "The customer accepts the offer to be connected."),
        tool_transition("offer_decline", "The customer declines the offer or answers without accepting it."),
    ], first_only=False)
    nodes["offer_decision"]["max_node_turns"] = 3
    nodes["offer_decision"]["max_turn_transition"] = "offer_decline"
    route_after = [eq_any("policy_phase", ["transfer"], "transfer_exec", "transfer"), eq_any("policy_phase", ["negotiating", "readback"], "negotiate", "more to agree")]
    nodes["offer_accept"] = code_node("offer_accept", policy_code(spec, "run_assess(vars, dict(event='accept_offer', product='all'))"), "finalize", route_after)
    nodes["offer_decline"] = code_node("offer_decline", policy_code(spec, "run_assess(vars, dict(event='refuse', product='all'))"), "finalize", route_after)
    transfer_post = post("if ok:\n    vars['transfer_queue_done'] = str(vars.get('transfer_now') or '')")
    nodes["transfer_exec"] = {"name": "transfer_exec", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "finalize",
                              "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                              "pre_actions": [api_fn(api, "transfer_to_agent", {cid_field: CID, q_field: leaf("string", "{{transfer_now}}")}, desc="Transfer the call.", post=transfer_post)],
                              "response_mapping": [], "transitions": [always("finalize")]}

    # ---------------- commit pipeline
    pid_f, amt_f, date_f = api.field("create_promise", "product_id"), api.field("create_promise", "amount"), api.field("create_promise", "date")
    amount_pre = ("try:\n    b = config.get('body') or dict()\n    v = str(b.get(" + repr(amt_f) + ") or '').replace(',', '')\n    b[" + repr(amt_f) + "] = round(float(v), 2)\n    config['body'] = b\nexcept Exception:\n    pass\n")

    def commit_node(k, retry):
        key = "commit_" + str(k) + ("_retry" if retry else "")
        nxt_go = "commit_" + str(k + 1) if k < 3 else "finalize"
        body = {cid_field: CID, pid_f: leaf("string", "{{c" + str(k) + "_product}}"), amt_f: leaf("number", "{{c" + str(k) + "_amount}}"), date_f: leaf("string", "{{c" + str(k) + "_date}}")}
        if api.props("create_promise") and pid_f not in api.props("create_promise"):
            body.pop(pid_f)                              # a single-account API has no product field
        trans = []
        if not retry:
            trans.append({"target_node": key + "_retry", "description": "the promise call failed", "condition": {"logic": "or", "conditions": [
                {"variable": key + "_failure_count", "operator": "greater_than", "operand": 0},
                {"variable": key + "_response.data.ok", "operator": "equals", "operand": "false"},
                {"variable": key + "_response.data.ok", "operator": "equals", "operand": "False"},
                {"variable": key + "_response.status", "operator": "equals", "operand": "error"}]}})
        if k < 3:
            trans.append(eq_any("c" + str(k + 1) + "_go", ["yes"], nxt_go, "next promise"))
        trans.append(always("finalize"))
        nodes[key] = {"name": key, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "finalize",
                      "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                      "pre_actions": [api_fn(api, "create_promise", body, desc="Record a promise.", pre=amount_pre)],
                      "response_mapping": [], "transitions": trans}
    for k in (1, 2, 3):
        commit_node(k, False)
        commit_node(k, True)
    nodes["confirm_promises"] = code_node("confirm_promises", policy_code(spec, "run_commit_check(vars)"), "negotiate",
                                      [eq_any("commit_ready", ["yes"], "commit_1", "ready to record"),
                                       eq_any("commit_ready", ["done"], "finalize", "already recorded")])

    # ---------------- finalize, notes, close
    nodes["finalize"] = code_node("finalize", policy_code(spec, "run_finalize(vars)"), "close_final",
                                  [eq_any("n1_go", ["yes"], "note_1", "notes to add")] if api.has("add_note") and spec.get("multi", {}).get("notes") else [])
    if api.has("add_note") and spec.get("multi", {}).get("notes"):
        npid, nrea = api.field("add_note", "product_id"), api.field("add_note", "reason")
        ntext = api.field("add_note", "text") if "text" in api.props("add_note") else None
        for k in (1, 2, 3):
            body = {cid_field: CID, npid: leaf("string", "{{n" + str(k) + "_product}}"), nrea: leaf("string", "{{n" + str(k) + "_reason}}")}
            if api.props("add_note") and npid not in api.props("add_note"):
                body.pop(npid)
            if ntext:
                body[ntext] = leaf("string", "{{n" + str(k) + "_reason}}")
            trans = [eq_any("n" + str(k + 1) + "_go", ["yes"], "note_" + str(k + 1), "next note")] if k < 3 else []
            nodes["note_" + str(k)] = {"name": "note_" + str(k), "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "close_final",
                                       "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                                       "pre_actions": [api_fn(api, "add_note", body, desc="Add a note.")], "response_mapping": [], "transitions": trans + [always("close_final")]}
    f_out, f_rea = api.field("close_call", "outcome"), api.field("close_call", "reason")
    reason_pre = ("try:\n    b = config.get('body') or dict()\n    if not str(b.get(" + repr(f_rea) + ") or '').strip() or '{' in str(b.get(" + repr(f_rea) + ")):\n        b.pop(" + repr(f_rea) + ", None)\n    config['body'] = b\nexcept Exception:\n    pass\n")
    nodes["close_final"] = {"name": "close_final", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "end",
                            "on_enter": {"type": "tts", "text": "{{final_say}} " + bye}, "disable_inactivity_monitor": True,
                            "pre_actions": [api_fn(api, "close_call", {cid_field: CID, f_out: leaf("string", "{{final_outcome}}"), f_rea: leaf("string", "{{final_reason}}")},
                                                   desc="End the call.", pre=reason_pre)],
                            "response_mapping": [], "transitions": [always("end")]}
    nodes["end"] = {"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                    "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
                                 "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}

    # every early close the graph references must exist
    for need in ("close_unclear", "close_callback", "close_no_callback", "close_wrong_number", "close_deceased", "close_id_failed"):
        if need not in nodes:
            close_node(need, outcomes.get("not_reached", "not_reached"), need[len("close_"):], bye)

    language = str(spec.get("language", "English"))
    if language.lower() not in ("en", "english", "en-us", "en-gb"):
        language_name = spec.get("locale", {}).get("language_name") or {"tr": "Turkish"}.get(language.lower(), language)
        language_rule = "Speak only " + language_name + ". Speak numbers, amounts and dates naturally in that language. Instructions may be in English; never read those instructions aloud.\n"
        system += "\n" + language_rule
        cb_extract[0]["description"] = ("If the latest message gives a callback day or time, normalize the day to YYYY-MM-DD and the time to HH:MM, separated by a space when both are given. "
                                        "Use the call's now for relative days. Preserve only the supplied parts; never invent a missing day or time. Empty if neither is given.")
        assess_body["a_date"]["description"] = "The customer's proposed payment day as YYYY-MM-DD, using the call's now for relative days. If no exact day can be determined, preserve their words. Empty if none."
        assess_body["a_amount"]["description"] = "Only an explicit amount for this one product, normalized to digits with a dot decimal separator and no thousands separator or currency. Empty if none, full amount, or one total for several products."
        for node in nodes.values():
            if node.get("node_type") == "conversation":
                node["task_message"] = language_rule + node["task_message"]
                if node["on_enter"].get("type") == "llm" and node["on_enter"].get("prompt"):
                    node["on_enter"]["prompt"] = language_rule + node["on_enter"]["prompt"]

    for key in [k for k, n in list(nodes.items()) if n.get("node_type") == "code"]:
        add_retry(nodes, key)

    # No test_variables: in a chat they override the call's own variables (customer_id included).
    wf = {"initial_node": "opening", "system_prompt": system, "nodes": nodes, "global_nodes": {}}
    return wf


def audit(wf, openapi):
    """Every bank call in the workflow must send each field the tool API marks as required. Returns a list of problems."""
    api = Api(openapi)
    by_url = {api.url(t): t for t in api.ops}
    problems = []
    for key, node in wf["nodes"].items():
        for fn in (node.get("tools") or []) + (node.get("pre_actions") or []):
            f = fn.get("function", {})
            if f.get("handler") != "__function__:api_call":
                continue
            props = f["parameters"]["properties"]
            tool = by_url.get(props.get("url", {}).get("default"))
            if not tool:
                problems.append(key + ": " + f.get("name", "?") + " calls an URL that is not in the tool API")
                continue
            body = props.get("body", {}).get("properties", {})
            for req in api.required(tool):
                if req not in body:
                    problems.append(key + ": " + tool + " misses required field " + req)
            for name in body:
                if name not in api.props(tool) and not name.startswith(("a_", "b_")):   # assess-only fields, stripped by its pre-hook
                    problems.append(key + ": " + tool + " sends a field the API does not declare: " + name)
    return problems


if __name__ == "__main__":
    import sys
    spec = json.load(open(sys.argv[1]))
    oa = json.load(open(sys.argv[2]))
    wf = compile_workflow(spec, oa)
    out = sys.argv[3] if len(sys.argv) > 3 else "out/workflow.json"
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps(wf, indent=1))
    print("wrote", out, len(wf["nodes"]), "nodes", len(json.dumps(wf)), "bytes")
