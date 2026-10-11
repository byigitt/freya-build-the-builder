"""Generate out/brief-a.workflow.json from Brief A. Run: python3 out/build_brief_a.py"""
import json, pathlib

BASE = "https://freya-bank-mock.freyavoice.workers.dev/v1/"
HOLIDAYS = ["2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"]

# ---------------------------------------------------------------- helpers
def leaf(typ, default, desc="", enum=None):
    d = {"type": typ, "default": default}
    if desc: d["description"] = desc
    if enum: d["enum"] = enum
    return d

def api_fn(name, path, body, required, desc="", post="", pre=""):
    t = {
        "type": "function",
        "config": {"timeoutMs": 12000, "maxRetries": 0},
        "function": {
            "name": name, "handler": "__function__:api_call", "description": desc,
            "parameters": {"type": "object", "properties": {
                "url": leaf("string", BASE + path),
                "method": leaf("string", "POST"),
                "headers": {"type": "object", "properties": {"Content-Type": leaf("string", "application/json")}},
                "connect_retries": {"type": "number", "default": 2},
                "body": {"type": "object", "properties": body, "required": required},
            }},
        },
    }
    if post: t["post_process_code"] = post
    if pre: t["pre_process_code"] = pre
    return t

CID = leaf("string", "{{customer_id}}")

def bool_true(var):
    return [{"variable": var, "operator": "equals", "operand": "true"},
            {"variable": var, "operator": "equals", "operand": "True"}]

def cond_or(conds):
    return {"logic": "or", "conditions": conds}

def tool_transition(target, desc):
    return {"target_node": target, "description": desc, "is_tool_call": True,
            "condition": {"operator": "matches_intent", "description": desc}}

def conv(name, task, tools, transitions, on_enter=None):
    return {"name": name, "node_type": "conversation", "task_message": task,
            "on_enter": on_enter or {"type": "llm"}, "tools": tools, "transitions": transitions,
            "max_node_turns": 60, "extraction_schema": []}

POST_COMMON = """try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if isinstance(d, dict):
            ok = str(d.get('ok')).lower() == 'true'
%s
except Exception:
    pass
"""
def post(body):
    return POST_COMMON % "\n".join("            " + l for l in body.strip("\n").split("\n"))

# ---------------------------------------------------------------- close nodes
def close_node(key, outcome, reason, text):
    body = {"customer_id": CID, "outcome": leaf("string", outcome)}
    if reason: body["reason"] = leaf("string", reason)
    return key, {
        "name": key, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "end",
        "on_enter": {"type": "tts", "text": text}, "disable_inactivity_monitor": True,
        "pre_actions": [api_fn("close_call", "close_call", body, ["customer_id", "outcome"], "End the call.")],
        "response_mapping": [],
        "transitions": [{"target_node": "end", "description": "always", "condition": {"operator": "always"}}],
    }

BYE = "Thank you for your time, {{title}} {{last_name}}. Goodbye."
CLOSES = dict([
    close_node("close_unclear", "not_reached", "unclear", "I am sorry, I could not confirm who I am speaking with. " + BYE),
    close_node("close_wrong_number", "not_reached", "wrong_number", "I apologise for the disturbance. Thank you for your time. Goodbye."),
    close_node("close_deceased", "not_reached", "deceased", "I am sorry for your loss. Thank you for your time. Goodbye."),
    close_node("close_callback", "not_reached", "callback", "Thank you, we will call back at that time. Thank you for your time. Goodbye."),
    close_node("close_no_callback", "not_reached", "no_callback", "Thank you, we will try again another time. Thank you for your time. Goodbye."),
    close_node("close_declined", "not_verified", "declined", "I understand. Without the security check I cannot continue this call. " + BYE),
    close_node("close_failed", "not_verified", "failed", "I am sorry, I could not verify your identity. Please use the Freya Bank mobile app or visit a branch. " + BYE),
    close_node("close_promise", "promise", "", "Your promise is recorded. You will receive a text message confirming this promise. " + BYE),
    close_node("close_paid", "paid", "", "Thank you for letting me know. Payments can take one business day to appear on your account. " + BYE),
    close_node("close_refused", "no_promise", "refused", "I understand. " + BYE),
    close_node("close_hardship", "no_promise", "hardship", "I understand. " + BYE),
    close_node("close_dispute", "no_promise", "dispute", "I understand, thank you for telling me. " + BYE),
    close_node("close_service_error", "no_promise", "service_error", "I am sorry, I could not record your promise because of a technical problem. " + BYE),
    close_node("close_transfer_restructuring", "transferred", "restructuring", "You are being transferred to our restructuring team now. " + BYE),
    close_node("close_transfer_human", "transferred", "human", "You are being transferred to a colleague now. " + BYE),
    close_node("close_transfer_support", "transferred", "support", "You are being transferred to our customer support team now. " + BYE),
])

# ---------------------------------------------------------------- tools
def verify_post(what):
    return post("""
left = d.get('wrong_answers_left')
try:
    left = int(left)
except Exception:
    left = None
if d.get('hint') == 'day_month_swapped':
    n = 'The day and the month look swapped. This does NOT count as a wrong answer. Ask the customer to say their date of birth again, saying the month as a word (for example: the 5th of March 1980).'
elif str(d.get('verified')).lower() == 'true' or str(d.get('all_verified')).lower() == 'true':
    n = 'Correct.'
elif not ok:
    n = 'The answer could not be read (not counted as wrong). Ask the customer to repeat WHAT.'
elif left == 0:
    n = 'The identity check failed. Say nothing about any account.'
else:
    n = 'That answer does NOT match. Tell the customer it did not match and ask for WHAT again. Wrong answers left: ' + str(left) + '.'
d['what_to_do_next'] = n
""".replace("WHAT", what))

verify_dob = api_fn("verify_date_of_birth", "verify_identity", {
    "customer_id": CID,
    "field": leaf("string", "date_of_birth"),
    "answer": leaf("string", "{{answer}}", "The date of birth as YYYY-MM-DD. Convert spoken dates. A numbers-only date is day, then month, then year."),
}, ["customer_id", "field", "answer"],
    "Check the date of birth. CALL it every time the customer says a date with a day, a month and a year. Then follow what_to_do_next in the result.",
    post=verify_post("their date of birth (day, the month as a word, and year)"))

verify_phone = api_fn("verify_phone_last4", "verify_identity", {
    "customer_id": CID,
    "field": leaf("string", "phone_last4"),
    "answer": leaf("string", "{{answer}}", "Exactly four digits, for example 0457."),
}, ["customer_id", "field", "answer"],
    "Check the last four digits of the phone number on file. CALL it every time the customer has said four digits. Then follow what_to_do_next in the result.",
    post=verify_post("the last four digits of the phone number on file"))

def transfer_tool(name, queue, when):
    return api_fn(name, "transfer_to_agent", {"customer_id": CID, "queue": leaf("string", queue)}, ["customer_id", "queue"],
                  "Transfer the call to the " + queue + " queue. CALL it " + when,
                  post=post("""
if ok:
    d['what_to_do_next'] = 'Transferred.'
else:
    d['what_to_do_next'] = 'The transfer did NOT work. Do not say you transferred. Tell the customer the transfer is not possible right now and continue.'
"""))

transfer_human = transfer_tool("transfer_to_human", "general", "only when the customer insists on a human after you asked once whether you can help first.")
transfer_restr = transfer_tool("transfer_to_restructuring", "restructuring", "when the customer asks for a new payment plan or lower instalments.")
transfer_support = transfer_tool("transfer_to_support", "support", "only when a customer who mentioned illness, a death in the family or job loss accepts your offer to connect them with the customer support team.")

callback_tool = api_fn("schedule_callback", "schedule_callback", {
    "customer_id": CID,
    "date": leaf("string", "{{date}}", "Callback date as YYYY-MM-DD."),
    "time": leaf("string", "{{time}}", "Callback time as HH:MM, 24 hour."),
}, ["customer_id", "date", "time"],
    "Book a callback. CALL it as soon as the person names a day and time that is inside the allowed callback window.",
    post=post("""
if ok:
    d['what_to_do_next'] = 'Callback booked.'
else:
    d['what_to_do_next'] = 'The callback was NOT booked (' + str(d.get('error')) + '). Do not say it is booked. Ask for another time inside the allowed window.'
"""))

PROMISE_POST = post("""
if ok:
    d['what_to_do_next'] = 'Recorded.'
else:
    tries = 1
    try:
        tries = int(vars.get('promise_fail_count') or 0) + 1
        vars['promise_fail_count'] = tries
    except Exception:
        tries = 1
    if tries >= 2:
        d['what_to_do_next'] = 'The promise was NOT recorded, for the second time. Do not say it is recorded. Call transition_to_close_service_error now.'
    else:
        d['what_to_do_next'] = 'The promise was NOT recorded. Do not say it is recorded. Call create_promise once more right now with exactly the same amount and date. If you already called create_promise before and it failed then too, call transition_to_close_service_error instead.'
""")

promise_tool = api_fn("create_promise", "create_promise", {
    "customer_id": CID,
    "product_id": leaf("string", "{{product_id}}"),
    "amount": leaf("number", "{{amount}}", "The confirmed amount, a number such as 120.5."),
    "date": leaf("string", "{{date}}", "The confirmed payment date as YYYY-MM-DD, copied from the calendar in your instructions."),
}, ["customer_id", "product_id", "amount", "date"],
    "Record the payment promise. CALL it only right after the customer clearly said yes to your read-back of product, amount and date.",
    post=PROMISE_POST)

get_account_fn = api_fn("get_account", "get_account", {"customer_id": CID}, ["customer_id"], "Get the late products.")
get_account_fn["config"]["maxRetries"] = 2

# ---------------------------------------------------------------- code
SETUP_CODE = r'''
import datetime
HOL = HOLIDAYS_LIST
def bd(d):
    return d.weekday() < 5 and d.isoformat() not in HOL
def say(d):
    return d.strftime('%A ') + str(d.day) + d.strftime(' %B %Y')
try:
    raw = str(vars.get('now') or '').strip()
    try:
        nowdt = datetime.datetime.fromisoformat(raw[:16])
    except Exception:
        nowdt = datetime.datetime.fromisoformat(raw[:10] + 'T10:00')
    today = nowdt.date()
    nxt = today + datetime.timedelta(days=1)
    while not bd(nxt):
        nxt = nxt + datetime.timedelta(days=1)
    hm = nowdt.strftime('%H:%M')
    lines = []
    if nowdt.hour < 19:
        start = '10:00' if hm < '10:00' else 'later than ' + hm
        lines.append('- Today, ' + say(today) + ' (' + today.isoformat() + '): from ' + start + ' up to 19:00.')
    else:
        lines.append('- Today is no longer possible (it is after 19:00).')
    lines.append('- Next business day, ' + say(nxt) + ' (' + nxt.isoformat() + '): from 10:00 to 19:00, both included.')
    lines.append('- Every other day or time is OUTSIDE the window (for example 09:30, 19:30, the day after the next business day, a weekend, next week).')
    vars['callback_window'] = '\n'.join(lines)
    vars['today_say'] = say(today)
    vars['today_iso'] = today.isoformat()
    vars['now_time'] = hm
    vars['setup_state'] = 'ok'
except Exception as e:
    vars['callback_window'] = 'Today from later than now up to 19:00, or the next business day from 10:00 to 19:00.'
    vars['today_say'] = str(vars.get('now'))
    vars['today_iso'] = str(vars.get('now'))[:10]
    vars['now_time'] = ''
    vars['setup_state'] = 'error ' + str(e)
'''.replace("HOLIDAYS_LIST", repr(HOLIDAYS))

PREPARE_CODE = r'''
import datetime, json, re
HOL = HOLIDAYS_LIST
def bd(d):
    return d.weekday() < 5 and d.isoformat() not in HOL
def say(d):
    return d.strftime('%A ') + str(d.day) + d.strftime(' %B')
def money(x):
    x = round(float(x), 2)
    return ('%d' % x) if x == int(x) else ('%.2f' % x)
def nth_bd_after(d, n):
    c = 0
    while c < n:
        d = d + datetime.timedelta(days=1)
        if bd(d):
            c += 1
    return d
def next_bd_from(d):
    while not bd(d):
        d = d + datetime.timedelta(days=1)
    return d
def last_bd_of_week(monday):
    best = None
    for i in range(5):
        x = monday + datetime.timedelta(days=i)
        if bd(x):
            best = x
    return best
try:
    prods = vars.get('products')
    if isinstance(prods, str):
        try:
            prods = json.loads(prods)
        except Exception:
            try:
                import ast
                prods = ast.literal_eval(prods)
            except Exception:
                prods = None
    if isinstance(prods, dict):
        prods = [prods]
    if not isinstance(prods, list) or not prods:
        p = dict()
        for k, v in list(vars.items()):
            m = re.match(r'^(?:\w*_response\.data\.products|products)(?:\.|\[)0\]?\.(\w+)$', str(k))
            if m:
                p[m.group(1)] = v
        prods = [p] if p else []
    p = prods[0]
    typ = str(p.get('type'))
    past_due = float(p.get('past_due'))
    days_late = int(float(p.get('days_late')))
    if typ == 'credit_card':
        words = 'credit card ending ' + str(p.get('card_last4'))
        floor = float(p.get('minimum_payment'))
        floor_name = 'minimum payment'
    else:
        words = 'personal loan' if typ == 'personal_loan' else 'car loan'
        floor = float(p.get('instalment_amount'))
        floor_name = 'instalment amount'
    raw = str(vars.get('now') or '').strip()
    today = datetime.date.fromisoformat(raw[:10])
    if days_late <= 7:
        band = 'early'; n = 12; attempts = 1
    else:
        band = 'late'; n = 7; attempts = 2
    deadline = nth_bd_after(today, n)
    monday = today - datetime.timedelta(days=today.weekday())
    a1 = last_bd_of_week(monday)
    if a1 is None or a1 <= today:
        a1 = last_bd_of_week(monday + datetime.timedelta(days=7))
    if a1 > deadline:
        a1 = deadline
    allowed = []
    d = today
    while d <= deadline:
        if bd(d):
            allowed.append(d)
        d = d + datetime.timedelta(days=1)
    cal = []
    d = today
    end = deadline + datetime.timedelta(days=7)
    while d <= end:
        tag = d.isoformat() + ' ' + say(d)
        if d == today:
            tag += ' (TODAY)'
        if d == today + datetime.timedelta(days=1):
            tag += ' (tomorrow)'
        if d > deadline:
            cal.append(tag + ': AFTER the deadline. Not allowed. Say the latest date you can record is ' + say(deadline) + ' and offer it.')
        elif not bd(d):
            why = 'bank holiday' if d.weekday() < 5 else 'weekend'
            nb = next_bd_from(d)
            if nb > deadline:
                cal.append(tag + ': ' + why + '. Not allowed. Offer the deadline ' + say(deadline) + ' (' + deadline.isoformat() + ').')
            else:
                cal.append(tag + ': ' + why + '. Not allowed. Offer the next business day ' + say(nb) + ' (' + nb.isoformat() + ').')
        else:
            cal.append(tag + ': allowed' + (' (this is the DEADLINE)' if d == deadline else '') + '.')
        d = d + datetime.timedelta(days=1)
    cal.append('Any later date: AFTER the deadline. Not allowed. Say the latest date you can record is ' + say(deadline) + ' and offer it.')
    names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    wk = []
    for i in range(7):
        this_d = monday + datetime.timedelta(days=i)
        next_d = this_d + datetime.timedelta(days=7)
        t = 'this ' + names[i] + ' = ' + this_d.isoformat()
        if this_d < today:
            t += ' (already past)'
        wk.append(t + '; next ' + names[i] + ' = ' + next_d.isoformat())
    vars['product_id'] = str(p.get('product_id'))
    vars['product_words'] = words
    vars['past_due_say'] = money(past_due)
    vars['days_late'] = str(days_late)
    vars['floor_say'] = money(floor)
    vars['floor_name'] = floor_name
    vars['band'] = band
    vars['attempts_allowed'] = str(attempts)
    vars['deadline_say'] = say(deadline)
    vars['deadline_iso'] = deadline.isoformat()
    vars['attempt1_say'] = say(a1)
    vars['attempt1_iso'] = a1.isoformat()
    vars['today_is_business_day'] = 'yes' if bd(today) else 'no'
    vars['allowed_dates'] = ', '.join(x.isoformat() + ' ' + say(x) for x in allowed)
    vars['calendar'] = '\n'.join(cal)
    vars['weekdays'] = '\n'.join(wk)
    if band == 'late':
        vars['attempt2_text'] = 'Attempt 2: propose the floor amount ' + money(floor) + ' on the deadline ' + say(deadline) + ' (' + deadline.isoformat() + ').'
    else:
        vars['attempt2_text'] = 'There is NO attempt 2 for this customer (early band). After attempt 1 is refused, the attempts are used up.'
    vars['account_state'] = 'ok'
except Exception as e:
    for k in ['product_id', 'product_words', 'past_due_say', 'days_late', 'floor_say', 'floor_name', 'band', 'attempts_allowed', 'deadline_say', 'deadline_iso', 'attempt1_say', 'attempt1_iso', 'allowed_dates', 'calendar', 'weekdays', 'attempt2_text', 'today_is_business_day']:
        if vars.get(k) is None:
            vars[k] = 'unknown'
    vars['account_state'] = 'error ' + str(e)
'''.replace("HOLIDAYS_LIST", repr(HOLIDAYS))

def code_node(key, code, nxt):
    return {"name": key, "node_type": "code", "passthrough": True, "passthrough_default_transition": nxt,
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code},
                                                                "timeout_ms": {"type": "number", "default": 10000}}}}}],
            "transitions": [{"target_node": nxt, "description": "always", "condition": {"operator": "always"}}]}

# ---------------------------------------------------------------- prompts
SYSTEM = """You are Freya Bank's digital assistant on an outbound phone call to {{title}} {{first_name}} {{last_name}}. Speak English. Keep every turn to one or two short sentences. Address the customer as {{title}} {{last_name}}.
The current date and time of this call is {{now}} ({{today_say}}). Use only this, never any other clock. Never compute dates yourself: use the date facts given in your current task.

General rules, at every step:
- If asked whether you are a robot or an AI: say you are Freya Bank's digital assistant, then continue.
- If asked whether this is a scam: say they can verify this call by phoning Freya Bank's customer service number, then continue.
- If asked something you cannot answer from the facts you were given: say you do not have that information. Never invent figures, dates or reasons.
- Never offer a discount, a waiver, an instalment plan or any term that is not in your instructions. Never ask the customer how much they can pay.
- Tools: when a rule says to call a tool, CALL it. Saying you did something is not doing it. Call at most one tool per message. After every tool result, speak to the customer or call the next tool. Never end a turn with nothing. If a tool result has what_to_do_next, follow it.
- Never say that something is recorded, booked or transferred unless the tool result says so.
- When you call a transition_to_close_... tool, the goodbye and the closing words are spoken automatically right after. Do not say goodbye yourself; write at most a very short acknowledgement or nothing."""

OPENING_TEXT = "Hello, this is the digital assistant of Freya Bank calling, and this call is recorded. Am I speaking with {{title}} {{last_name}}?"

OPENING = """The opening line was already said: you introduced yourself as Freya Bank's digital assistant, said that the call is recorded, and asked "Am I speaking with {{title}} {{last_name}}?". That was ask number 1.

Your only job in this step: find out whether {{title}} {{last_name}} ({{first_name}} {{last_name}}) is the person on the line.
Never say why you are calling. Never say the words collections, debt, payment, loan, card, account or any product. If asked what it is about, say you can only discuss it with {{title}} {{last_name}} personally.

Decide on the person's latest message:
1. CONFIRMED only when the person says "yes", "that's me", "speaking", "it is", or says their own name ({{first_name}} or {{last_name}}). Then call transition_to_identity_dob. Say nothing else.
2. Someone else is on the line (they say they are not {{title}} {{last_name}}, they are a relative or colleague, the customer is not here or not available, the number belongs to someone else, they never heard of the customer, or the customer has died): call transition_to_third_party. Say nothing else.
3. Anything else is NOT a confirmation: "hello", "go ahead", "who is this?", "what is this about?", "who's calling?", silence, a vague or unrelated answer. First answer a question if there was one (who you are: Freya Bank's digital assistant), then ask exactly once more: "Am I speaking with {{title}} {{last_name}}?" That is ask number 2. You never ask it a third time: if after ask number 2 the answer is still not a confirmation and not case 2, call transition_to_close_unclear.
4. If the person asks for a human: the first time, ask whether you can help first. If they insist, call transfer_to_human.
5. If the person says they do not want to talk: the first time, ask again politely. The second time, call transition_to_close_declined."""

ID_COMMON = """
Never say why you are calling and never mention collections, debt, payment or any product until both security answers are verified.
If the customer refuses to answer, or asks what the call is about instead of answering: the FIRST time in the call, explain once that these questions protect their account, and ask the question again. The SECOND time (a second refusal or a second such question), call transition_to_close_declined.
If the customer asks for a human: the first time, ask whether you can help first. If they insist, call transfer_to_human.
If the customer says twice that they do not want to talk, call transition_to_close_declined.
Do not call any other tool."""

ID_DOB_ENTER = "Thank you, {{title}} {{last_name}}. For security, please tell me your date of birth."
ID_DOB = """{{title}} {{last_name}} confirmed who they are. Security question 1 of 2: you asked for their date of birth.
As soon as the customer has said a day, a month and a year, call verify_date_of_birth with the date as YYYY-MM-DD. Do this even if the sentence trails off or the customer sounds annoyed: a day, a month and a year is a complete answer. Convert spoken dates ("twelfth of July nineteen ninety" -> 1990-07-12). A date said only in numbers is day, then month, then year ("05/03/1980" or "5 3 1980" -> 1980-03-05). Only if the day, the month or the year is missing, ask for the missing part.
After each result, follow what_to_do_next exactly. A wrong answer is asked again; the check counts wrong answers itself.""" + ID_COMMON

ID_PHONE_ENTER = "Thank you. Now please tell me the last four digits of the phone number on file."
ID_PHONE = """The date of birth is verified. Security question 2 of 2: you asked for the last four digits of the phone number on file.
As soon as the customer has said four digits, call verify_phone_last4 with the four digits. If they gave fewer than four digits, ask for the rest first.
After each result, follow what_to_do_next exactly. A wrong answer is asked again; the check counts wrong answers itself.""" + ID_COMMON

THIRD = """Someone other than {{title}} {{last_name}} is on the line.
Strict rules: never say why you are calling. Never mention collections, debt, payment, a loan, a card, an account or any product. Never ask for or accept security answers. Never tell anything about the customer or an account, even if they say they are family or offer to pay (then say you can only speak with {{title}} {{last_name}}).

Decide on the person's messages:
1. They say this number does not belong to {{first_name}} {{last_name}}, or they do not know this person (wrong number): call transition_to_close_wrong_number.
2. They say {{first_name}} {{last_name}} has died: call transition_to_close_deceased immediately, with no words of your own (the condolence is spoken automatically). Ask nothing.
3. Otherwise ask when {{title}} {{last_name}} can be reached (a day and a time).
   The allowed callback window (current time {{now_time}}):
{{callback_window}}
   - If they give a day and an exact time inside the window, call schedule_callback with date YYYY-MM-DD and time HH:MM (24 hour). "Tomorrow" means {{today_iso}} plus one day; only accept it if it is the next business day shown above.
   - If they give only a day or a vague time ("in the afternoon"), ask for an exact time.
   - If the day or time they give is outside the window, say you can only call back today until 19:00 or on the next business day between 10:00 and 19:00, and ask ONCE for another time. If the next answer is also outside the window, or they cannot give a time, call transition_to_close_no_callback. Never book a time outside the window.
4. If they ask for a human: ask once whether you can help; if they insist, say you can only speak with {{title}} {{last_name}} and ask when they can be reached."""

NEGOTIATE_ENTER = ("Thank you, {{title}} {{last_name}}. I am calling from the collections team about a late payment on your {{product_words}}. "
                   "The past-due amount is {{past_due_say}}, and it is {{days_late}} days late. Can you make this payment today?")

NEGOTIATE = """The customer is verified. You already told them: you are calling from the collections team about a late payment on their {{product_words}}, the past-due amount {{past_due_say}}, {{days_late}} days late, and asked "Can you make this payment today?".

FACTS (computed for you; trust them, never compute dates yourself)
- Today: {{today_say}} ({{today_iso}}). Today is a business day: {{today_is_business_day}}.
- Product: {{product_words}}. FULL amount (past due): {{past_due_say}}.
- FLOOR ({{floor_name}}): {{floor_say}}. The lowest amount you may record.
- DEADLINE (latest promise date): {{deadline_say}} ({{deadline_iso}}).
- Allowed promise dates (business days from today to the deadline): {{allowed_dates}}
- Persuasion attempts allowed for this customer: {{attempts_allowed}}.
- Attempt 1: propose the amount (FULL, or FLOOR if the customer already said the full amount is too much) on {{attempt1_say}} ({{attempt1_iso}}).
- {{attempt2_text}}
- Weekday words: {{weekdays}}
- Calendar, day by day:
{{calendar}}

PRIORITY CASES (check these first on every customer message)
A. Illness, a death in the family, or job loss: say one short sentence of sympathy, make NO persuasion attempt, and offer to connect them with the customer support team. If they accept, call transfer_to_support. If they decline, call transition_to_close_hardship. (If they still name a date or amount themselves, handle it as a proposal below.)
B. "I already paid" (this past-due amount): call transition_to_close_paid. Take no promise.
C. "This debt is not mine", "I never had this product", or the product was closed or paid off in the past: do not argue, take no promise, call transition_to_close_dispute.
D. They ask for a new payment plan, a restructuring or lower instalments: do not describe any plan. Call transfer_to_restructuring.
E. They ask for a human: the first time, ask whether you can help first. If they insist, call transfer_to_human.
F. They say they do not want to talk: the first time, acknowledge and ask your question once more. The second time, call transition_to_close_refused.

GETTING THE PROMISE
1. Amount: always ask for the FULL amount first. You propose every amount; never ask how much they can pay.
2. "Yes" to paying today: the promise is the FULL amount (or the amount already agreed) on today {{today_iso}}. Go to the read-back.
3. The customer proposes a DATE (never a refusal): look it up in the calendar and do what it says.
   - allowed: use it, with the FULL amount unless another amount was agreed.
   - weekend or holiday on or before the deadline: offer the next business day the calendar names.
   - after the deadline: say the latest date you can record is {{deadline_say}}, and offer it. If they refuse the deadline, that is a flat refusal (rule 6).
   - before today: not allowed; ask for a date from today on.
   - vague ("next week", "end of the month", "when my salary comes", "in a few days"): ask ONCE for the exact day. If they still give no exact day, propose the deadline {{deadline_say}}.
   "Next <weekday>" and "this <weekday>": use the Weekday words line.
4. The customer proposes an AMOUNT (never a refusal):
   - from {{floor_say}} up to {{past_due_say}}, both included: accept it.
   - below {{floor_say}}: say that amount cannot be recorded and offer the floor {{floor_say}} once. If they do not accept the floor, that is a flat refusal (rule 6).
   - above {{past_due_say}}: say the amount due is {{past_due_say}} and use that.
5. The customer says the full amount is too much: offer the floor {{floor_say}} once, and say that the rest stays overdue. If they refuse the floor, that is a flat refusal (rule 6).
6. FLAT REFUSAL or non-answer (for example a "no" to paying today with no date and no amount, or refusing an offer): this uses one persuasion attempt.
   - First flat refusal: Attempt 1. Propose the FULL amount (or the FLOOR if they already said the full amount is too much) on {{attempt1_say}}.
   - Second flat refusal: {{attempt2_text}}
   - When the allowed attempts ({{attempts_allowed}}) are used up and they refuse again: call transition_to_close_refused. Never repeat an offer the customer already refused.
7. Never offer a discount, a waiver, an instalment plan or any other term.

READ-BACK AND RECORDING
8. When an amount and a date are agreed, read them back: "That is <amount> for your {{product_words}}, on <weekday day month>. Do you confirm?"
9. Only after a clear yes, call create_promise with that amount and the date as YYYY-MM-DD. If the customer changes the date or the amount instead, check the new value with rules 3 and 4 and read back again.
10. If create_promise fails, follow what_to_do_next: try once more with the same values; if it fails again, call transition_to_close_service_error. Never say the promise is recorded unless the result says ok.
11. A recorded promise cannot be changed in this call. If asked, say they can change it in the mobile app."""

# ---------------------------------------------------------------- nodes
def to_end(var):
    return {"target_node": var[0], "description": var[1], "condition": cond_or(bool_true(var[2]))}

nodes = {}
nodes["setup"] = code_node("setup", SETUP_CODE, "opening")
nodes["opening"] = conv("opening", OPENING, [transfer_human], [
    to_end(("close_transfer_human", "the transfer to a human worked", "transfer_to_human_response.data.ok")),
    tool_transition("identity_dob", "The person clearly confirmed they are the customer (yes, that's me, speaking, or their own name)."),
    tool_transition("third_party", "Someone other than the customer is on the line, or the customer cannot come to the phone, or the number is not the customer's, or the customer died."),
    tool_transition("close_unclear", "After asking twice, it is still unclear who is on the line."),
    tool_transition("close_declined", "The person said twice that they do not want to talk."),
], on_enter={"type": "tts", "text": OPENING_TEXT})
nodes["third_party"] = conv("third_party", THIRD, [callback_tool], [
    to_end(("close_callback", "the callback was booked", "schedule_callback_response.data.ok")),
    tool_transition("close_wrong_number", "The person says the number does not belong to the customer."),
    tool_transition("close_deceased", "The person says the customer has died."),
    tool_transition("close_no_callback", "No callback time inside the allowed window could be agreed after asking once more."),
])
DECLINE_ID = tool_transition("close_declined", "The customer refused the security questions a second time, or asked a second time what the call is about instead of answering, or said twice they do not want to talk.")
FAILED_ID = {"target_node": "close_failed", "description": "three wrong answers in total",
             "condition": cond_or([{"variable": "verify_date_of_birth_response.data.wrong_answers_left", "operator": "equals", "operand": "0"},
                                   {"variable": "verify_phone_last4_response.data.wrong_answers_left", "operator": "equals", "operand": "0"}])}
nodes["identity_dob"] = conv("identity_dob", ID_DOB, [verify_dob, transfer_human], [
    {"target_node": "identity_phone", "description": "date of birth verified",
     "condition": cond_or(bool_true("verify_date_of_birth_response.data.verified"))},
    FAILED_ID,
    to_end(("close_transfer_human", "the transfer to a human worked", "transfer_to_human_response.data.ok")),
    DECLINE_ID,
], on_enter={"type": "tts", "text": ID_DOB_ENTER})
nodes["identity_phone"] = conv("identity_phone", ID_PHONE, [verify_phone, transfer_human], [
    {"target_node": "load_account", "description": "phone digits verified",
     "condition": cond_or(bool_true("verify_phone_last4_response.data.verified") + bool_true("verify_phone_last4_response.data.all_verified"))},
    FAILED_ID,
    to_end(("close_transfer_human", "the transfer to a human worked", "transfer_to_human_response.data.ok")),
    DECLINE_ID,
], on_enter={"type": "tts", "text": ID_PHONE_ENTER})
nodes["load_account"] = {
    "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "prepare",
    "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "pre_actions": [get_account_fn],
    "response_mapping": [{"path": "data.products", "variable": "products"}],
    "transitions": [{"target_node": "prepare", "description": "always", "condition": {"operator": "always"}}],
}
nodes["prepare"] = code_node("prepare", PREPARE_CODE, "negotiate")
nodes["negotiate"] = conv("negotiate", NEGOTIATE, [promise_tool, transfer_restr, transfer_human, transfer_support], [
    to_end(("close_promise", "the promise was recorded", "create_promise_response.data.ok")),
    to_end(("close_transfer_restructuring", "transfer to restructuring worked", "transfer_to_restructuring_response.data.ok")),
    to_end(("close_transfer_support", "transfer to support worked", "transfer_to_support_response.data.ok")),
    to_end(("close_transfer_human", "transfer to a human worked", "transfer_to_human_response.data.ok")),
    tool_transition("close_paid", "The customer says they already paid this past-due amount."),
    tool_transition("close_dispute", "The customer says the debt is not theirs, they never had the product, or it was closed or paid off in the past."),
    tool_transition("close_hardship", "A customer who mentioned illness, a death in the family or job loss declined the transfer to customer support."),
    tool_transition("close_refused", "All allowed persuasion attempts are used up and the customer still refuses, or the customer said twice they do not want to talk."),
    tool_transition("close_service_error", "create_promise failed twice."),
], on_enter={"type": "tts", "text": NEGOTIATE_ENTER})
nodes.update(CLOSES)
nodes["end"] = {"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                "transitions": [], "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
                "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}

wf = {
    "initial_node": "setup",
    "system_prompt": SYSTEM,
    "nodes": nodes,
    "global_nodes": {},
    "test_variables": {"customer_id": "c_test", "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"},
}
out = pathlib.Path(__file__).resolve().parent / "brief-a.workflow.json"
out.write_text(json.dumps(wf, indent=1))
print("wrote", out, len(nodes), "nodes")
