"""Policy engine that runs INSIDE the Freya workflow (code nodes and a code_exec tool).

The compiler embeds this file's source plus a JSON config (CFG) into every code step. The sandbox gives us a dict
named `vars` (the call's variable table); everything we compute goes back into `vars` as strings.
Rules for this file (the platform's templating and sandbox):
  - never write two opening or two closing curly braces next to each other anywhere in this file
  - only json, re and datetime are imported
  - nothing may raise out of an entry point
Entry points: run_setup(vars), run_prepare(vars), run_assess(vars, params), run_commit_check(vars), run_finalize(vars)
"""
import datetime
import json
import re

CFG = dict()  # replaced by the compiler

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
NUM_WORDS = dict(zero=0, one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9, ten=10, eleven=11, twelve=12,
                 thirteen=13, fourteen=14, fifteen=15, sixteen=16, seventeen=17, eighteen=18, nineteen=19, twenty=20, thirty=30,
                 forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90)
ORD_WORDS = dict(first=1, second=2, third=3, fourth=4, fifth=5, sixth=6, seventh=7, eighth=8, ninth=9, tenth=10, eleventh=11,
                 twelfth=12, thirteenth=13, fourteenth=14, fifteenth=15, sixteenth=16, seventeenth=17, eighteenth=18,
                 nineteenth=19, twentieth=20, thirtieth=30)


# ------------------------------------------------------------------ small helpers
def cfg(path, default=None):
    cur = CFG
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def to_float(x, default=None):
    try:
        if isinstance(x, str):
            x = x.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
        return float(x)
    except Exception:
        return default


def money(x):
    x = round(float(x), 2)
    if abs(x - int(x)) < 0.005:
        s = "%d" % int(x)
    else:
        s = "%.2f" % x
    word = cfg("texts.currency_word", "")
    return (s + " " + word).strip() if word else s


def say_date(d):
    return WEEKDAYS[d.weekday()].capitalize() + " " + str(d.day) + " " + MONTHS[d.month - 1].capitalize()


def say_date_year(d):
    return say_date(d) + " " + str(d.year)


def holidays():
    out = []
    for h in cfg("calendar.holidays", []) or []:
        out.append(str(h)[:10])
    return out


def is_bd(d):
    days = cfg("calendar.business_weekdays", [0, 1, 2, 3, 4])
    return d.weekday() in days and d.isoformat() not in holidays()


def next_bd_on_or_after(d):
    for _ in range(60):
        if is_bd(d):
            return d
        d = d + datetime.timedelta(days=1)
    return d


def prev_bd_on_or_before(d):
    for _ in range(60):
        if is_bd(d):
            return d
        d = d - datetime.timedelta(days=1)
    return d


def nth_bd_after(d, n):
    c = 0
    for _ in range(400):
        if c >= n:
            break
        d = d + datetime.timedelta(days=1)
        if is_bd(d):
            c += 1
    return d


def last_bd_of_week(any_day):
    monday = any_day - datetime.timedelta(days=any_day.weekday())
    best = None
    for i in range(7):
        x = monday + datetime.timedelta(days=i)
        if is_bd(x):
            best = x
    return best


def today_of(vars):
    raw = str(vars.get(cfg("variables.now", "now")) or "").strip()
    try:
        return datetime.datetime.fromisoformat(raw[:16])
    except Exception:
        try:
            return datetime.datetime.fromisoformat(raw[:10] + "T10:00")
        except Exception:
            return datetime.datetime(2026, 10, 14, 11, 0)


def week_table(today):
    monday = today - datetime.timedelta(days=today.weekday())
    lines = []
    for i in range(7):
        this_d = monday + datetime.timedelta(days=i)
        next_d = this_d + datetime.timedelta(days=7)
        t = "this " + WEEKDAYS[i].capitalize() + " = " + say_date(this_d) + " (" + this_d.isoformat() + ")"
        if this_d < today:
            t += " [already past]"
        if this_d == today:
            t += " [today]"
        lines.append("- " + t + "; next " + WEEKDAYS[i].capitalize() + " = " + say_date(next_d) + " (" + next_d.isoformat() + ")")
    return "\n".join(lines)


# ------------------------------------------------------------------ parsing what the customer said
def words_to_int(text):
    t = text.lower().replace("-", " ").replace(" and ", " ")
    total, cur, seen = 0, 0, False
    for w in t.split():
        if w in NUM_WORDS:
            cur += NUM_WORDS[w]
            seen = True
        elif w in ORD_WORDS:
            cur += ORD_WORDS[w]
            seen = True
        elif w == "hundred":
            cur = max(cur, 1) * 100
            seen = True
        elif w == "thousand":
            total += max(cur, 1) * 1000
            cur = 0
            seen = True
    return total + cur if seen else None


def parse_amount(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().lower()
    if not s or s in ("none", "null", "nan"):
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if m:
        return to_float(m.group(0))
    cents = 0.0
    if " point " in s:
        a, b = s.split(" point ", 1)
        s = a
        cv = words_to_int(b)
        if cv is not None:
            cents = cv / (10.0 ** len(str(cv)))
    v = words_to_int(s)
    return None if v is None else v + cents


def parse_date(x, today):
    """Return a date or None. Accepts ISO, '16 October', 'October 16th', 'the twenty-third', weekdays with this/next, today, tomorrow."""
    if x is None:
        return None
    s = str(x).strip().lower()
    if not s or s in ("none", "null"):
        return None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    if re.search(r"next (business|working|bank) day", s):
        return nth_bd_after(today, 1)
    if "day after tomorrow" in s:
        return today + datetime.timedelta(days=2)
    if "tomorrow" in s:
        return today + datetime.timedelta(days=1)
    if "today" in s or "now" == s:
        return today
    month = None
    for i, name in enumerate(MONTHS):
        if name in s or re.search(r"\b" + name[:3] + r"\b", s):
            month = i + 1
            break
    day = None
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", s)
    if m:
        day = int(m.group(1))
    else:
        dv = words_to_int(re.sub(r"\b(" + "|".join(MONTHS) + r")\b", " ", s))
        if dv and 1 <= dv <= 31:
            day = dv
    if day:
        if month is None:
            month = today.month
            try:
                cand = datetime.date(today.year, month, day)
            except Exception:
                cand = None
            if cand is None or cand < today:
                month = month + 1
                year = today.year + (1 if month > 12 else 0)
                month = 1 if month > 12 else month
                try:
                    return datetime.date(year, month, day)
                except Exception:
                    return None
            return cand
        year = today.year
        try:
            cand = datetime.date(year, month, day)
        except Exception:
            return None
        if cand < today - datetime.timedelta(days=60):
            try:
                cand = datetime.date(year + 1, month, day)
            except Exception:
                return None
        return cand
    for i, name in enumerate(WEEKDAYS):
        if name in s:
            monday = today - datetime.timedelta(days=today.weekday())
            this_d = monday + datetime.timedelta(days=i)
            if "next" in s or "following" in s:
                return this_d + datetime.timedelta(days=7)
            if "this" in s:
                return this_d
            return this_d if this_d >= today else this_d + datetime.timedelta(days=7)
    return None


# ------------------------------------------------------------------ products and bands
def find_products(vars):
    field = cfg("account.products_field", "products")
    prods = vars.get(field) if field != "products" else vars.get("products")
    if prods is None:
        prods = vars.get("account_products")
    if isinstance(prods, str):
        try:
            prods = json.loads(prods)
        except Exception:
            try:
                prods = json.loads(prods.replace("'", '"').replace("True", "true").replace("False", "false").replace("None", "null"))
            except Exception:
                prods = None
    if isinstance(prods, dict):
        prods = [prods]
    if isinstance(prods, list) and prods and isinstance(prods[0], dict):
        return prods
    found = dict()
    pat = re.compile(r"(?:^|\.)" + re.escape(field) + r"\.(\d+)\.(\w+)$")
    for k, v in list(vars.items()):
        m = pat.search(str(k))
        if m and "_response.data." in str(k):
            found.setdefault(int(m.group(1)), dict())[m.group(2)] = v
    return [found[i] for i in sorted(found)]


def product_words(p):
    types = cfg("account.types", dict())
    t = str(p.get(cfg("account.type_field", "type")) or "")
    spec = types.get(t) or dict()
    tpl = spec.get("words") or t.replace("_", " ")
    out = tpl
    for k, v in p.items():
        out = out.replace("<" + str(k) + ">", str(v))
    return out


def product_floor(p):
    types = cfg("account.types", dict())
    t = str(p.get(cfg("account.type_field", "type")) or "")
    spec = types.get(t) or dict()
    fld = spec.get("floor_field")
    val = to_float(p.get(fld)) if fld else None
    if val is None and spec.get("floor_percent") is not None:
        raw = to_float(p.get(cfg("account.amount_field", "past_due")), 0.0) * to_float(spec.get("floor_percent"), 0) / 100.0
        mode = str(spec.get("floor_rounding") or "round").lower()
        cents = raw * 100
        exact = abs(cents - round(cents)) < 1e-6
        if exact:
            val = round(cents) / 100.0
        elif "ceil" in mode or "up" in mode:
            val = (int(cents) + 1) / 100.0
        elif "floor" in mode or "down" in mode:
            val = int(cents) / 100.0
        else:
            val = round(raw, 2)
    if val is not None and spec.get("floor_min") is not None:
        val = max(val, to_float(spec.get("floor_min"), 0))
    if val is None:
        for alt in cfg("account.floor_fields", ["minimum_payment", "instalment_amount", "installment_amount"]):
            if p.get(alt) is not None:
                val = to_float(p.get(alt))
                break
    return val, spec.get("floor_name") or cfg("texts.floor_name", "minimum amount")


def band_for(days_late):
    bands = cfg("bands", [])
    for b in bands:
        lo = to_float(b.get("min_days"), -1e9)
        hi = to_float(b.get("max_days"), 1e9)
        if lo <= days_late <= hi:
            return b
    return bands[-1] if bands else dict(name="default", deadline=dict(kind="business_days_after_today", n=7), attempts=1)


def deadline_for(band, today, p):
    dl = band.get("deadline") or dict(kind="business_days_after_today", n=7)
    kind = dl.get("kind", "business_days_after_today")
    n = int(to_float(dl.get("n"), 7))
    if kind == "calendar_days_after_today":
        d = today + datetime.timedelta(days=n)
        return prev_bd_on_or_before(d) if dl.get("adjust", "previous_business_day") == "previous_business_day" else next_bd_on_or_after(d)
    if kind == "end_of_month":
        nm = datetime.date(today.year + (today.month // 12), today.month % 12 + 1, 1)
        return prev_bd_on_or_before(nm - datetime.timedelta(days=1))
    if kind == "business_days_after_today_inclusive":
        return nth_bd_after(today - datetime.timedelta(days=1), n)
    return nth_bd_after(today, n)


def ladder_date(kind, today, deadline):
    kind = str(kind or "deadline")
    if kind == "today":
        d = today
    elif kind == "next_business_day":
        d = nth_bd_after(today, 1)
    elif kind.startswith("business_days_after_today:"):
        d = nth_bd_after(today, int(kind.split(":")[1]))
    elif kind == "last_business_day_this_week":
        d = last_bd_of_week(today)
        if d is None or d < today:
            d = nth_bd_after(today, 1)
        elif d == today:
            d = last_bd_of_week(today + datetime.timedelta(days=7))
    elif kind == "last_business_day_next_week":
        d = last_bd_of_week(today + datetime.timedelta(days=7))
    else:
        d = deadline
    if d is None or d > deadline:
        d = deadline
    if not is_bd(d):
        d = next_bd_on_or_after(d)
        if d > deadline:
            d = deadline
    return d


# ------------------------------------------------------------------ state
def load_state(vars):
    raw = vars.get("pol_state")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return None


def save_state(vars, st):
    vars["pol_state"] = json.dumps(st)


def prod_by_id(st, pid):
    pid = str(pid or "").strip().lower()
    for p in st["products"]:
        if p["id"].lower() == pid:
            return p
    m = re.search(r"(\d+)", pid)
    if m:
        i = int(m.group(1)) - 1
        if 0 <= i < len(st["products"]):
            return st["products"][i]
    for p in st["products"]:
        if pid and pid in p["words"].lower():
            return p
    for p in st["products"]:
        if p["status"] in ("open", "offered"):
            return p
    return None


def open_products(st):
    return [p for p in st["products"] if p["status"] in ("open", "offered")]


def current_product(st):
    ops = open_products(st)
    return ops[0] if ops else None


def target_amount(p):
    if p.get("agreed_amount") is not None:
        return p["agreed_amount"]
    if p.get("too_much") and p.get("floor") is not None:
        return p["floor"]
    return p["full"]


def offer_text(p, amount, d):
    return money(amount) + " for your " + p["words"] + " on " + say_date(d)


# ------------------------------------------------------------------ texts the model must say
def facts_text(st):
    lines = []
    for p in st["products"]:
        lines.append("- " + p["id"] + ": " + p["words"] + ". Past due " + money(p["full"]) + ", " + str(p["days_late"]) + " days late. "
                     + "Floor (" + p["floor_name"] + "): " + (money(p["floor"]) if p["floor"] is not None else "none") + ". "
                     + "Latest allowed promise date (deadline): " + say_date(datetime.date.fromisoformat(p["deadline"])) + " (" + p["deadline"] + "). "
                     + "Persuasion attempts allowed: " + str(p["attempts_allowed"]) + ". Status: " + status_words(p) + ".")
    return "\n".join(lines)


def status_words(p):
    s = p["status"]
    if s == "agreed":
        return "AGREED " + money(p["agreed_amount"]) + " on " + p["agreed_date"]
    if s == "offered":
        return "waiting for an answer to your offer of " + money(p["offer_amount"]) + " on " + p["offer_date"]
    if s == "open":
        return "open"
    return "closed without promise (" + str(p.get("reason")) + ")"


def debt_statement(st):
    intro = cfg("texts.debt_intro", "I am calling about a late payment.")
    parts = []
    for p in st["products"]:
        parts.append("Your " + p["words"] + " has " + money(p["full"]) + " past due and is " + str(p["days_late"]) + " days late.")
    if len(st["products"]) > 1:
        ask = cfg("texts.ask_today_all", "Can you pay all of them today?")
    else:
        ask = cfg("texts.ask_today", "Can you make this payment today?")
    return intro + " " + " ".join(parts) + " " + ask


def readback_text(st):
    agreed = [p for p in st["products"] if p["status"] == "agreed"]
    if not agreed:
        return ""
    bits = []
    for p in agreed:
        b = money(p["agreed_amount"]) + " for your " + p["words"] + " on " + say_date(datetime.date.fromisoformat(p["agreed_date"]))
        if p.get("clamped"):
            b += " (that is the latest date I can record for it)"
        bits.append(b)
    if len(bits) == 1:
        body = bits[0]
    else:
        body = ", ".join(bits[:-1]) + " and " + bits[-1]
    return cfg("texts.readback_prefix", "So that is") + " " + body + ". " + cfg("texts.confirm_question", "Do you confirm?")


def start_transfer(vars, st, queue):
    """Ask the workflow to transfer the call now (an engine step calls the bank's transfer tool)."""
    for p in st["products"]:
        if p["status"] == "agreed":
            p["status"] = "closed"
            p["agreed_amount"] = None
            p["agreed_date"] = None
    st["transfer_queue"] = str(queue or "")
    vars["transfer_now"] = str(queue or "")
    return cfg("texts.transfer_say", "Say that you are transferring them now.")


def set_outputs(vars, st, instruction):
    st["instruction"] = instruction
    vars["next_instruction"] = instruction
    vars["facts"] = facts_text(st)
    vars["readback"] = readback_text(st)
    cur = current_product(st)
    vars["current_product"] = (cur["id"] + " (" + cur["words"] + ")") if cur else "none"
    if st.get("transfer_queue"):
        vars["policy_phase"] = "transfer"
    elif st.get("pending_offer"):
        vars["policy_phase"] = "offer"
    elif open_products(st):
        vars["policy_phase"] = "negotiating"
    elif any(p["status"] == "agreed" for p in st["products"]):
        vars["policy_phase"] = "readback"
    else:
        vars["policy_phase"] = "done"
    save_state(vars, st)


def ask(p, text):
    """The instruction asks the customer something about this product: wait for the answer."""
    p["pending_q"] = True
    return text


def next_step_instruction(st):
    """What to do once the last event is handled: move to the next open product, or read back, or close."""
    cur = current_product(st)
    if cur is not None:
        if cur["status"] == "offered":
            return "Wait for the customer's answer to your offer of " + offer_text(cur, cur["offer_amount"], datetime.date.fromisoformat(cur["offer_date"])) + "."
        if len(st["products"]) > 1 and cur.get("asked") is not True:
            cur["asked"] = True
            today = datetime.date.fromisoformat(st["today"])
            offer = refusal(cur, st, today)
            if offer is None:
                return next_step_instruction(st)
            return "Now the " + cur["words"] + " (" + cur["id"] + "). Do NOT ask about paying today again. " + offer
        return "Continue with the " + cur["words"] + " (" + cur["id"] + ")."
    if any(p["status"] == "agreed" for p in st["products"]):
        return "Every product is settled. Read back exactly this and wait for the answer: \"" + readback_text(st) + "\" When the customer clearly says yes, call transition_to_confirm_promises."
    return "Every product is settled and no promise was agreed. Say one short polite sentence. Do not offer anything else."


# ------------------------------------------------------------------ entry points
def run_setup(vars):
    try:
        now = today_of(vars)
        today = now.date()
        cb = cfg("callback", dict())
        start = str(cb.get("start", "10:00"))
        end = str(cb.get("end", "19:00"))
        hm = now.strftime("%H:%M")
        days = []
        if (is_bd(today) or not cb.get("today_requires_business_day", True)) and hm < end and cb.get("allow_today", True):
            days.append((today, max(start, hm), True))
        nxt = nth_bd_after(today, 1)
        for i in range(int(to_float(cb.get("business_days_ahead"), 1))):
            days.append((nxt, start, False))
            nxt = nth_bd_after(nxt, 1)
        lines = []
        for d, s, is_today in days:
            if is_today and hm < start:
                lines.append("- TODAY " + say_date(d) + " (" + d.isoformat() + "): from " + start + " to " + end + ", both included.")
            elif is_today:
                lines.append("- TODAY " + say_date(d) + " (" + d.isoformat() + "): a time later than " + hm + " and up to " + end + " (" + end + " included).")
            else:
                lines.append("- " + say_date(d) + " (" + d.isoformat() + "): from " + start + " to " + end + ", both included.")
        lines.append("- Anything else is OUTSIDE the window (another day, a weekend, earlier than " + start + ", later than " + end + ").")
        vars["callback_window"] = "\n".join(lines)
        vars["callback_dates"] = ", ".join(d.isoformat() for d, s, t in days)
        vars["today_say"] = say_date_year(today)
        vars["today_iso"] = today.isoformat()
        vars["now_time"] = hm
        vars["week_table"] = week_table(today)
        vars["setup_state"] = "ok"
    except Exception as e:
        vars["callback_window"] = "Today later than now and up to 19:00, or the next business day from 10:00 to 19:00."
        vars["today_say"] = str(vars.get("now"))
        vars["setup_state"] = "error " + str(e)


def parse_time(x):
    """'11', '11:30', 'eleven', 'around eleven', '2pm', 'half past two', 'quarter to three' -> 'HH:MM' or None."""
    if x is None:
        return None
    s = str(x).strip().lower()
    if not s or s in ("none", "null"):
        return None
    pm = "pm" in s or "p.m" in s or "afternoon" in s or "evening" in s
    am = "am" in s or "a.m" in s or "morning" in s
    if re.search(r"\bnoon\b", s) or "midday" in s:
        return "12:00"
    h, mnt = None, 0
    m = re.search(r"(\d{1,2})[:.h](\d{2})", s)
    if m:
        h, mnt = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(?<!\d)(\d{1,2})(?!\d)", s)
        if m:
            h = int(m.group(1))
        else:
            words = s.replace("-", " ")
            for w, v in sorted(NUM_WORDS.items(), key=lambda kv: -len(kv[0])):
                if re.search(r"\b" + w + r"\b", words) and 1 <= v <= 12:
                    h = v
                    break
        if h is not None:
            if "half past" in s:
                mnt = 30
            elif "quarter past" in s:
                mnt = 15
            elif "quarter to" in s:
                h, mnt = h - 1, 45
            elif re.search(r"\bthirty\b", s):
                mnt = 30
    if h is None:
        return None
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    if not pm and not am and 1 <= h <= 7:
        h += 12                               # "at three" on a business call means the afternoon
    if not (0 <= h <= 23 and 0 <= mnt <= 59):
        return None
    return "%02d:%02d" % (h, mnt)


TIME_RE = re.compile(
    r"(?:\b(?:at|around|about|by)\s+)?"
    r"(?:\d{1,2}[:.]\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?"
    r"|\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.|o'clock|in the morning|in the afternoon|in the evening)"
    r"|(?<=at )\d{1,2}(?![\d/])|(?<=around )\d{1,2}(?![\d/])|(?<=about )\d{1,2}(?![\d/])"
    r"|\bnoon\b|\bmidday\b|half past [a-z]+|quarter (?:past|to) [a-z]+"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b(?:[ -](?:thirty|fifteen|forty-five|o'clock))?"
    r"(?:\s*(?:am|pm|in the morning|in the afternoon|in the evening))?)")


def split_day_time(text):
    """'Thursday at 11:30 am' -> ('thursday', 'at 11:30 am'). Day numbers ('the 15th') are never taken as times."""
    low = " " + str(text or "").lower() + " "
    m = TIME_RE.search(low)
    if not m:
        return low.strip(), None
    t = m.group(0).strip()
    rest = (low[:m.start()] + " " + low[m.end():]).strip()
    for w in ("in the morning", "in the afternoon", "in the evening", "morning", "afternoon", "evening"):
        if w in rest and w not in t:
            t = t + " " + w
            break
    return rest, t


def callback_days(vars):
    now = today_of(vars)
    today = now.date()
    cb = cfg("callback", dict())
    out = []
    if (is_bd(today) or not cb.get("today_requires_business_day", True)) and cb.get("allow_today", True):
        out.append(today)
    nxt = today
    for i in range(int(to_float(cb.get("business_days_ahead"), 1))):
        nxt = nth_bd_after(nxt, 1)
        out.append(nxt)
    return now, out


def run_callback(vars, params):
    """Check a proposed callback day and time against the window. Sets cb_state (book / ask / give_up), cb_say, cb_date, cb_time."""
    try:
        cb = cfg("callback", dict())
        start, end = str(cb.get("start", "10:00")), str(cb.get("end", "19:00"))
        now, days = callback_days(vars)
        today = now.date()
        d = parse_date(params.get("day"), today)
        t = parse_time(params.get("time"))
        if d is None and str(params.get("day") or "").strip() == "" and t is not None:
            d = None
        prev_d = vars.get("cb_day_seen")
        if d is None and prev_d:
            try:
                d = datetime.date.fromisoformat(str(prev_d))
            except Exception:
                d = None
        asks = int(to_float(vars.get("cb_asks"), 0) or 0) + 1
        vars["cb_asks"] = str(asks)
        window = " or ".join(("today until " + end) if x == today else (say_date(x) + " between " + start + " and " + end) for x in days)
        outside = int(to_float(vars.get("cb_outside"), 0) or 0)

        def is_out(day, tm):
            if day is not None and day not in days:
                return True
            if tm is not None and not (start <= tm <= end):
                return True
            if day == today and tm is not None and tm <= now.strftime("%H:%M"):
                return True
            return False

        if (d is not None or t is not None) and is_out(d, t):
            outside += 1
            vars["cb_outside"] = str(outside)
            vars["cb_day_seen"] = ""
            if outside >= 2 or not cb.get("reask_once", True):
                vars["cb_state"] = "give_up"
                vars["cb_say"] = ""
                return
            vars["cb_state"] = "ask"
            vars["cb_say"] = "I am sorry, I can only call back " + window + ". Is there another day and time that works?"
            return
        if outside >= 1 and cb.get("incomplete_second_offer") == "give_up" and not (d is not None and t is not None):
            vars["cb_state"] = "give_up"     # the brief closes when the second offer is still incomplete
            vars["cb_say"] = ""
            return
        if asks > 4 and not (d is not None and t is not None):
            vars["cb_state"] = "give_up"     # no usable day and time after several tries
            vars["cb_say"] = ""
            return
        if d is None and t is not None and len(days) == 1:
            d = days[0]                       # only one day is possible: a time alone is enough
        if d is not None and t is not None:
            vars["cb_state"] = "book"
            vars["cb_date"] = d.isoformat()
            vars["cb_time"] = t
            return
        if d is not None:
            vars["cb_day_seen"] = d.isoformat()
            vars["cb_state"] = "ask"
            vars["cb_say"] = "At what time on " + say_date(d) + "? I can call between " + (now.strftime("%H:%M") if d == today else start) + " and " + end + "."
            return
        vars["cb_state"] = "ask"
        vars["cb_say"] = "When can I reach them? I can call back " + window + "."
    except Exception as e:
        vars["cb_state"] = "ask"
        vars["cb_say"] = "When can I reach them, which day and at what time?"
        vars["cb_error"] = str(e)[:120]


def run_prepare(vars):
    try:
        run_setup(vars)
        now = today_of(vars)
        today = now.date()
        prods = find_products(vars)
        st = dict(products=[], today=today.isoformat(), events=[], transfer_queue="", notes_enabled=bool(cfg("multi.notes", False)))
        idf = cfg("account.id_field", "product_id")
        amt_f = cfg("account.amount_field", "past_due")
        late_f = cfg("account.days_late_field", "days_late")
        for i, p in enumerate(prods):
            full = to_float(p.get(amt_f), 0.0)
            late = int(to_float(p.get(late_f), 0))
            band = band_for(late)
            dl = deadline_for(band, today, p)
            floor, floor_name = product_floor(p)
            st["products"].append(dict(id=str(p.get(idf) or ("p" + str(i + 1))), words=product_words(p), full=full, days_late=late,
                                       floor=floor, floor_name=floor_name, band=band.get("name", ""), deadline=dl.isoformat(),
                                       attempts_allowed=int(to_float(band.get("attempts"), 1)), attempts_used=0, floor_offered=False,
                                       too_much=False, vague_asked=False, status="open", agreed_amount=None, agreed_date=None,
                                       offer_amount=None, offer_date=None, reason=None, clamped=False, asked=(i == 0)))
        vars["products_count"] = str(len(st["products"]))
        vars["debt_statement"] = debt_statement(st)
        vars["account_state"] = "ok" if st["products"] else "empty"
        set_outputs(vars, st, "You just stated the debt and asked the first question about paying. Wait for the answer.")
    except Exception as e:
        vars["account_state"] = "error " + str(e)
        vars["debt_statement"] = cfg("texts.debt_intro", "I am calling about a late payment.")
        vars["next_instruction"] = "Something went wrong reading the account. Say you do not have that information right now."
        vars["facts"] = "unknown"


def decide_date(p, d, today, single_date_for_all=False):
    """Return (ok_date, offer_date, why). ok_date set when d is acceptable as is."""
    deadline = datetime.date.fromisoformat(p["deadline"])
    if d < today:
        earliest = today if cfg("dates.today_allowed", True) and is_bd(today) else nth_bd_after(today, 1)
        return None, earliest, "past"
    if d > deadline:
        if single_date_for_all and cfg("multi.single_date_after_deadline", "offer_deadline") == "use_product_deadline":
            return deadline, None, "clamped"
        return None, deadline, "after_deadline"
    if not is_bd(d):
        nb = next_bd_on_or_after(d)
        if nb > deadline:
            return None, deadline, "not_business_after"
        return None, nb, "not_business"
    if d == today and not cfg("dates.today_allowed", True):
        nb = nth_bd_after(today, 1)
        return None, nb, "today_not_allowed"
    return d, None, "ok"


def refusal(p, st, today):
    """One persuasion attempt used. Returns the instruction."""
    ladder = cfg("persuasion", [])
    steps = []
    for s in ladder:
        bands = s.get("bands")
        if bands and p["band"] not in bands:
            continue
        steps.append(s)
    used = p["attempts_used"]
    if p.get("no_persuasion"):
        p["status"] = "closed"
        p["reason"] = cfg("reasons.hardship", "hardship")
        return None
    if used < p["attempts_allowed"] and used < len(steps):
        s = steps[used]
        p["attempts_used"] = used + 1
        deadline = datetime.date.fromisoformat(p["deadline"])
        amt_kind = s.get("amount", "current")
        if amt_kind == "floor" and p["floor"] is not None:
            amount = p["floor"]
        elif amt_kind == "full":
            amount = p["full"]
        else:
            amount = target_amount(p)
        d = ladder_date(s.get("date"), today, deadline)
        p["status"] = "offered"
        p["offer_amount"] = amount
        p["offer_date"] = d.isoformat()
        p["offer_kind"] = "persuasion"
        extra = ""
        if amount == p["floor"] and amount < p["full"]:
            extra = " " + cfg("texts.rest_overdue", "Say that the rest stays overdue.")
        return ("Persuasion attempt " + str(used + 1) + " of " + str(p["attempts_allowed"]) + ": propose exactly " + offer_text(p, amount, d)
                + " (" + d.isoformat() + ")." + extra + " Ask if they can do that.")
    p["status"] = "closed"
    p["reason"] = cfg("reasons.refused", "refused")
    return None


def run_assess(vars, params):
    try:
        st = load_state(vars)
        if not st:
            run_prepare(vars)
            st = load_state(vars)
        today = datetime.date.fromisoformat(st["today"])
        ev = str(params.get("event") or "").strip().lower()
        target = str(params.get("product") or "").strip().lower()
        amt = parse_amount(params.get("amount"))
        dt = parse_date(params.get("date"), today)
        sid = str(params.get("situation") or "").strip().lower()
        legacy = dict(paid="paid", already_paid="paid", dispute="dispute", not_mine="dispute", hardship_declined="hardship", stop_talking="stop_talking")
        sits = cfg("situations", dict())
        if ev in legacy and legacy[ev] in sits:
            sid = legacy[ev]
            ev = "situation"
        st["events"].append([ev, target, params.get("amount"), params.get("date"), sid])
        pend = st.get("pending_offer")
        accepting = ev in ("accept_offer", "accept", "yes")
        if pend and ev == "situation" and sid != pend and (sits.get(sid) or dict()).get("effect") == "transfer":
            if (sits.get(sid) or dict()).get("queue") == (sits.get(pend) or dict()).get("offer_queue"):
                accepting = True        # "yes, connect me" reported as a transfer request to the offered team
            else:
                st["pending_offer"] = ""  # they want a different team: handle that situation on its own
                pend = None
        if pend and ev in ("propose", "propose_date", "propose_amount", "pay_today") and pend in sits:
            # The offer is not accepted, but the customer names a payment themselves: products the proposal does not
            # cover get no persuasion, then the proposal is handled.
            st["pending_offer"] = ""
            st["offer_done_" + pend] = True
            named = [x.strip().lower() for x in str(target).split(",") if x.strip()]
            s0 = sits.get(st.get("offer_sid") or "") or dict()
            for p in st["products"]:
                if p["status"] in ("open", "offered") and named and "all" not in named and p["id"].lower() not in named:
                    p["status"] = "closed"           # declined the offer and names no payment for this product
                    p["reason"] = s0.get("reason") or cfg("reasons.hardship", "hardship")
            pend = None
        if pend and accepting and pend in sits:
            st["pending_offer"] = ""
            set_outputs(vars, st, start_transfer(vars, st, sits[pend].get("offer_queue")))
            return
        if pend and ev in ("refuse", "refused", "no", "non_answer") and pend in sits:
            st["pending_offer"] = ""
            ev = "situation"
            sid = pend
            st["offer_done_" + sid] = True
        elif pend and ev in ("cut_off", "no_answer"):
            set_outputs(vars, st, "Their answer was cut off or did not answer your offer. Do not repeat the offer: just say something short like 'Go on, I am listening.'")
            return
        elif pend and ev not in ("situation", "no_answer", "cut_off"):
            st["pending_offer"] = ""
        if ev == "situation":
            s = sits.get(sid) or dict()
            effect = s.get("effect", "product")
            if s.get("ask_first") and not st.get("asked_" + sid):
                st["asked_" + sid] = True
                set_outputs(vars, st, s.get("say") or "Ask once whether you can help them first.")
                return
            if s.get("offer_queue") and not st.get("offer_done_" + sid):
                st["offer_done_" + sid] = True
                st["pending_offer"] = sid
                st["offer_sid"] = sid
                for p in st["products"]:
                    if p["status"] in ("open", "offered"):
                        p["no_persuasion"] = True
                        if p["status"] == "offered" and p.get("offer_kind") == "persuasion":
                            p["status"] = "open"      # the persuasion offer is withdrawn: no persuasion in a hardship
                            p["offer_amount"] = None
                            p["offer_date"] = None
                set_outputs(vars, st, (s.get("action") or "") + " Offer it once and wait for the answer. Make no persuasion attempt.")
                return
            if effect == "transfer":
                set_outputs(vars, st, start_transfer(vars, st, s.get("queue")))
                return
            if effect == "call" or s.get("scope") == "call":
                targets = open_products(st)
                if s.get("outcome"):
                    st["forced"] = [s.get("outcome"), s.get("reason") or ""]
            elif target in ("all", "every", "both", "everything", "") and (len(st["products"]) > 1 or s.get("scope") == "all"):
                targets = open_products(st)
            elif s.get("scope") == "all":
                targets = open_products(st)
            else:
                p0 = prod_by_id(st, target)
                targets = [p0] if p0 is not None else []
            if effect == "none":
                set_outputs(vars, st, (s.get("say") or s.get("action") or "") + " " + next_step_instruction(st))
                return
            named_one = target not in ("all", "every", "both", "everything", "")
            targets = [p for p in targets if p["status"] in ("open", "offered") or (p["status"] == "agreed" and named_one)]
            for p in targets:
                p["status"] = "closed"
                p["reason"] = s.get("reason") or sid
            say = s.get("say") or ""
            if s.get("close_say"):
                st.setdefault("close_say", []).append(s.get("close_say"))
            instr = (say + " Take no promise for " + (", ".join("the " + p["words"] for p in targets) if targets else "it") + ".").strip()
            set_outputs(vars, st, instr + " " + next_step_instruction(st))
            return
        all_events = ("pay_today", "propose_date", "propose", "accept_offer")
        listed = [x.strip() for x in re.split(r"[,;/ ]+(?:and )?", target) if x.strip() and x.strip() not in ("and",)]
        if len(listed) > 1 and all(prod_by_id(st, x) is not None and re.match(r"^p?\d+$", x) for x in listed):
            seen = []
            for x in listed:
                q = prod_by_id(st, x)
                if q not in seen:
                    seen.append(q)
            msgs = []
            for p in seen:
                p["pending_q"] = False
                m = assess_one(p, st, ev, None if len(seen) > 1 else amt, dt, today, multi=True, raw_date=params.get("date"))
                if m:
                    msgs.append(m)
            waiting = any(p["status"] == "offered" or p.get("pending_q") for p in seen)
            instr = " ".join(msgs)
            if not waiting:
                instr = (instr + " " + next_step_instruction(st)).strip()
            set_outputs(vars, st, instr)
            return
        if target in ("all", "every", "both", "everything", "") and len(st["products"]) > 1 and ev in all_events:
            if ev == "accept_offer":
                targets = [p for p in st["products"] if p["status"] == "offered"]
            else:
                targets = [p for p in st["products"] if p["status"] in ("open", "offered", "agreed") or (p["status"] == "closed" and p.get("reason") in (cfg("reasons.refused", "refused"), cfg("reasons.hardship", "hardship")))]
        else:
            p0 = prod_by_id(st, target)
            targets = [p0] if p0 is not None else []
            cur = current_product(st)
            if p0 is not None and cur is not None and p0 is not cur and p0["status"] in ("open", "offered") and len(st["products"]) > 1:
                # Products are handled one by one. An answer about a later product is taken up when its turn comes.
                # Do not write anything: a parallel call for the current product must not be overwritten.
                return
        if not targets:
            set_outputs(vars, st, next_step_instruction(st))
            return
        if len(targets) > 1:
            amt = None                       # one amount said for several products is a total, never one product's amount
        msgs = []
        for p in targets:
            p["pending_q"] = False
            m = assess_one(p, st, ev, amt, dt, today, multi=len(targets) > 1, raw_date=params.get("date"))
            if m:
                msgs.append(m)
        waiting = any(p["status"] == "offered" or p.get("pending_q") for p in targets)
        instr = " ".join(msgs)
        if not waiting:
            instr = (instr + " " + next_step_instruction(st)).strip()
        set_outputs(vars, st, instr)
    except Exception as e:
        vars["next_instruction"] = "Continue the conversation carefully. (policy error " + str(e)[:80] + ")"


def assess_one(p, st, ev, amt, dt, today, multi=False, raw_date=None):
    if p["status"] not in ("open", "offered"):
        hardship = cfg("reasons.hardship", "hardship")
        if p["status"] == "agreed" and ev in ("refuse", "refused", "no", "too_much", "vague", "propose", "propose_date", "propose_amount", "pay_today"):
            p["status"] = "open"             # they take back or change an agreement that is not recorded yet
            p["agreed_amount"] = None
            p["agreed_date"] = None
        elif ev in ("propose", "propose_date", "propose_amount", "pay_today") and p["status"] == "closed" and p.get("reason") == cfg("reasons.refused", "refused"):
            p["status"] = "open"             # they refused earlier but now name a day or an amount themselves
            p["reason"] = None
        elif ev in ("propose", "propose_date", "propose_amount", "pay_today") and p["status"] == "closed" and p.get("reason") == hardship:
            p["status"] = "open"             # the customer still names a day or an amount: handle it, but never persuade
            p["no_persuasion"] = True
            p["reason"] = None
        else:
            return ""
    if ev in ("stop_talking",):
        p["status"] = "closed"
        p["reason"] = cfg("reasons.refused", "refused")
        return "The customer does not want to talk. Thank them politely."
    if ev in ("paid", "already_paid"):
        p["status"] = "closed"
        p["reason"] = cfg("reasons.paid", "paid")
        return cfg("texts.paid_response", "Say that payments can take one business day to appear.") + " Take no promise for the " + p["words"] + "."
    if ev in ("dispute", "not_mine"):
        p["status"] = "closed"
        p["reason"] = cfg("reasons.dispute", "dispute")
        return "Do not argue. Take no promise for the " + p["words"] + "."
    if ev in ("hardship_declined",):
        p["status"] = "closed"
        p["reason"] = cfg("reasons.hardship", "hardship")
        return "Acknowledge kindly. Take no promise for the " + p["words"] + "."
    if ev == "no_answer" and cfg("negotiation.non_answer_is_refusal", True):
        p["noans"] = 0
        return refused_or_next(p, st, today)      # the brief counts a non-answer like a flat refusal
    if ev in ("cut_off", "no_answer"):
        # A message that breaks off is not an answer yet: alternate a short prompt to go on with a brief repeat of the question.
        p["noans"] = int(p.get("noans") or 0) + 1
        if p["noans"] % 2 == 1:
            return ask(p, "Their answer was cut off or did not answer. Do not repeat your question: just say something short like 'Go on, I am listening.'")
        return ask(p, "They still have not answered. Briefly repeat your last question once, in different words.")
    p["noans"] = 0
    if ev in ("accept_offer", "accept", "yes"):
        if p["status"] == "offered":
            return handle_amount_then_agree(p, p["offer_amount"], datetime.date.fromisoformat(p["offer_date"]), st, today)
        ev = "propose" if (dt is not None or amt is not None) else "pay_today"
    if ev == "pay_today":
        # "Yes" to the first ask: the first ask is about today, or about the earliest allowed day when today is not allowed.
        d = today if cfg("dates.today_allowed", True) else next_bd_on_or_after(today + datetime.timedelta(days=1))
        ok, offer, why = decide_date(p, d, today)
        if ok is None:
            return make_offer(p, target_amount(p) if amt is None else amt, offer, "today is not a business day")
        return handle_amount_then_agree(p, amt, ok, st, today)
    if ev in ("too_much", "cannot_pay_full"):
        p["too_much"] = True
        if p["floor"] is not None and not p["floor_offered"] and p["floor"] < p["full"]:
            p["floor_offered"] = True
            d = None
            if dt is not None:
                ok, offer, why = decide_date(p, dt, today)
                d = ok or offer
            if d is None and p.get("offer_date"):
                d = datetime.date.fromisoformat(p["offer_date"])
            if d is None:
                p["status"] = "open"
                p["agreed_amount"] = None
                p["pending_floor"] = True
                return ask(p, "Offer the " + p["floor_name"] + " of " + money(p["floor"]) + " instead, once. " + cfg("texts.rest_overdue", "Say that the rest stays overdue.")
                           + " Ask on which day they can pay " + money(p["floor"]) + ".")
            p["status"] = "offered"
            p["offer_amount"] = p["floor"]
            p["offer_date"] = d.isoformat()
            return ("Offer the " + p["floor_name"] + " of " + money(p["floor"]) + " instead, once, on " + say_date(d) + ". "
                    + cfg("texts.rest_overdue", "Say that the rest stays overdue.") + " Ask if they can do that.")
        return refused_or_next(p, st, today)
    if ev in ("refuse", "refused", "no", "non_answer"):
        if p.get("pending_floor"):
            p["pending_floor"] = False
        return refused_or_next(p, st, today)
    if ev in ("vague_date", "vague"):
        if not p["vague_asked"]:
            p["vague_asked"] = True
            return ask(p, "Ask once for the exact day they can pay.")
        d = datetime.date.fromisoformat(p["deadline"])
        return make_offer(p, target_amount(p) if amt is None else amt, d, "no exact day")
    if ev in ("propose", "propose_date", "propose_amount"):
        if (p["status"] == "offered" and p.get("offer_date") == p["deadline"] and dt is not None
                and dt > datetime.date.fromisoformat(p["deadline"])):
            return refused_or_next(p, st, today)     # they refuse the latest possible date and insist on a later one
        if amt is not None and dt is None and p.get("pending_floor") and abs(amt - (p["floor"] or -1)) < 0.01:
            dt = today
        if dt is None and amt is not None:
            res = check_amount(p, amt, st, today, datetime.date.fromisoformat(p["offer_date"]) if p["status"] == "offered" and p.get("offer_date") else None)
            if res is not None:
                return res
            p["agreed_amount"] = amt if amt <= p["full"] else p["full"]
            if p["status"] == "offered" and p.get("offer_date"):
                return agree(p, p["agreed_amount"], datetime.date.fromisoformat(p["offer_date"]))
            return ask(p, "The amount " + money(p["agreed_amount"]) + " is fine. Ask on which day they will pay it.")
        if dt is None:
            if raw_date and not p["vague_asked"]:
                p["vague_asked"] = True
                return ask(p, "That is not an exact day. Ask once for the exact day they can pay.")
            if raw_date:
                return make_offer(p, target_amount(p) if amt is None else amt, datetime.date.fromisoformat(p["deadline"]), "no exact day")
            return ask(p, "Ask which exact day they can pay.")
        ok, offer, why = decide_date(p, dt, today, single_date_for_all=multi)
        if ok is None:
            reason = dict(past="that day is in the past", after_deadline="that day is after the deadline",
                          not_business="that day is not a business day", not_business_after="that day is not a business day",
                          today_not_allowed="today is not possible").get(why, "that day is not possible")
            a = target_amount(p) if amt is None else amt
            res = check_amount(p, a, st, today, offer)
            if res is not None:
                return res
            if why == "past":
                return make_offer(p, a, offer, "that day is in the past")
            if why in ("after_deadline", "not_business_after"):
                return make_offer(p, a, offer, reason, latest=True)
            return make_offer(p, a, offer, reason)
        if why == "clamped":
            p["clamped"] = True
        a = target_amount(p) if amt is None else amt
        return handle_amount_then_agree(p, a, ok, st, today)
    return ""


def check_amount(p, amt, st, today, d=None):
    """None when the amount can be used. Otherwise the instruction (floor offer once, then a flat refusal)."""
    if amt is None:
        return None
    if p["floor"] is not None and amt < p["floor"] - 0.005:
        if not p["floor_offered"]:
            p["floor_offered"] = True
            p["too_much"] = True
            lead = "Say that " + money(amt) + " cannot be recorded. Offer the " + p["floor_name"] + " of " + money(p["floor"]) + " instead, once. " + cfg("texts.rest_overdue", "Say that the rest stays overdue.")
            if d is not None:
                p["status"] = "offered"
                p["offer_amount"] = p["floor"]
                p["offer_date"] = d.isoformat()
                p["offer_kind"] = "floor"
                return lead + " Offer it on " + say_date(d) + " and ask if they can do that."
            p["pending_floor"] = True
            p["status"] = "open"
            return ask(p, lead + " Ask on which day they can pay " + money(p["floor"]) + ".")
        return refused_or_next(p, st, today)
    return None


def handle_amount_then_agree(p, amt, d, st, today):
    a = target_amount(p) if amt is None else amt
    res = check_amount(p, a, st, today, d)
    if res is not None:
        return res
    if a > p["full"] + 0.005:
        return make_offer(p, p["full"], d, "only the full past-due amount of " + money(p["full"]) + " can be recorded")
    return agree(p, a, d)


def make_offer(p, amount, d, reason, latest=False):
    amount = min(float(amount), p["full"])
    p["status"] = "offered"
    p["offer_amount"] = amount
    p["offer_date"] = d.isoformat()
    p["offer_kind"] = "correction"
    if latest:
        return "Say the latest date you can record is " + say_date(d) + ", and offer " + offer_text(p, amount, d) + " (" + d.isoformat() + "). Ask if they can do that."
    return "Say " + reason + ", and offer " + offer_text(p, amount, d) + " (" + d.isoformat() + "). Ask if they can do that."


def agree(p, amount, d):
    p["status"] = "agreed"
    p["agreed_amount"] = round(float(amount), 2)
    p["agreed_date"] = d.isoformat()
    p["pending_floor"] = False
    return "Agreed (not recorded yet: never say it is recorded) for the " + p["words"] + ": " + money(amount) + " on " + say_date(d) + "."


def refused_or_next(p, st, today):
    if p["status"] == "offered" and p.get("offer_kind") == "correction" and p.get("offer_date") == p["deadline"] and p.get("latest_refused") is not True:
        p["latest_refused"] = True
    instr = refusal(p, st, today)
    if instr is None:
        return "The persuasion attempts for the " + p["words"] + " are used up. Do not make another offer for it."
    return instr


def run_commit_check(vars):
    try:
        st = load_state(vars)
        if st and (st.get("transfer_queue") or vars.get("transfer_now")):
            vars["commit_ready"] = "no"
            for i in range(3):
                vars["c" + str(i + 1) + "_go"] = "no"
            return
        agreed = [p for p in st["products"] if p["status"] == "agreed"] if st else []
        if not st or not agreed or open_products(st):
            vars["commit_ready"] = "no"
            vars["next_instruction"] = ("Not everything is settled yet. " + next_step_instruction(st)) if st else "Continue."
            if st:
                save_state(vars, st)
            return
        vars["commit_ready"] = "yes"
        for i in range(3):
            k = str(i + 1)
            if i < len(agreed):
                vars["c" + k + "_product"] = agreed[i]["id"]
                vars["c" + k + "_amount"] = str(agreed[i]["agreed_amount"])
                vars["c" + k + "_date"] = agreed[i]["agreed_date"]
                vars["c" + k + "_go"] = "yes"
            else:
                vars["c" + k + "_go"] = "no"
        save_state(vars, st)
    except Exception as e:
        vars["commit_ready"] = "no"
        vars["next_instruction"] = "Continue. (error " + str(e)[:60] + ")"


def ok_of(vars, node):
    sc = to_float(vars.get(node + "_success_count"), 0) or 0
    okv = str(vars.get(node + "_response.data.ok") or "").lower()
    if okv == "true":
        return True
    if okv == "false":
        return False
    return sc > 0 and okv == ""


def run_after_promise(vars, k):
    """After create_promise attempt k: decide whether to retry."""
    try:
        node = "commit_" + str(k)
        vars["c" + str(k) + "_ok"] = "yes" if ok_of(vars, node) else "no"
    except Exception:
        vars["c" + str(k) + "_ok"] = "no"


def run_finalize(vars):
    try:
        st = load_state(vars) or dict(products=[], transfer_queue="")
        rec = []
        failed = []
        for i in range(3):
            k = str(i + 1)
            if vars.get("c" + k + "_go") != "yes":
                continue
            pid = vars.get("c" + k + "_product")
            okd = ok_of(vars, "commit_" + k) or ok_of(vars, "commit_" + k + "_retry")
            for p in st["products"]:
                if p["id"] == pid:
                    if okd:
                        p["status"] = "recorded"
                        rec.append(p)
                    else:
                        p["status"] = "closed"
                        p["reason"] = cfg("reasons.service_error", "service_error")
                        failed.append(p)
        q = str(vars.get("transfer_queue_done") or "")
        if not q and str(vars.get("transfer_exec_response.data.ok") or "").lower() == "true":
            q = str(vars.get("transfer_now") or "")
        oc = cfg("outcomes", dict())
        notes = []
        if q:
            outcome, reason = oc.get("transferred", "transferred"), cfg("transfer_reasons", dict()).get(q, q)
        else:
            for p in st["products"]:
                if p["status"] in ("open", "offered", "agreed"):
                    p["status"] = "closed"
                    p["reason"] = p.get("reason") or cfg("reasons.refused", "refused")
            unp = [p for p in st["products"] if p["status"] == "closed"]
            if st.get("notes_enabled"):
                notes = [(p["id"], p.get("reason") or cfg("reasons.refused", "refused")) for p in unp]
            if st.get("forced") and not rec:
                outcome, reason = st["forced"][0], st["forced"][1]
            elif rec:
                outcome, reason = oc.get("promise", "promise"), cfg("promise_reasons.full", "")
                if any(p.get("agreed_amount") is not None and p["agreed_amount"] < p["full"] - 0.005 for p in rec):
                    outcome = oc.get("partial_promise", outcome)
                    reason = cfg("promise_reasons.partial", reason)
            elif st["products"] and all(p.get("reason") == cfg("reasons.paid", "paid") for p in unp) and unp:
                outcome, reason = oc.get("paid", "paid"), ""
            else:
                first = unp[0] if unp else None
                outcome = oc.get("no_promise", "no_promise")
                reason = (first.get("reason") if first else cfg("reasons.refused", "refused")) or "refused"
                if first and first.get("reason") == cfg("reasons.paid", "paid"):
                    for p in unp:
                        if p.get("reason") != cfg("reasons.paid", "paid"):
                            reason = p.get("reason")
                            break
                prio = cfg("closing.no_promise_reason_priority", [])
                if prio:
                    present = [p.get("reason") for p in unp if p.get("reason") != cfg("reasons.paid", "paid")] or [p.get("reason") for p in unp]
                    ranked = [r for r in prio if r in present]
                    if ranked:
                        reason = ranked[0]
        vars["final_outcome"] = outcome
        vars["final_reason"] = reason
        for i in range(3):
            k = str(i + 1)
            if i < len(notes):
                vars["n" + k + "_go"] = "yes"
                vars["n" + k + "_product"] = notes[i][0]
                vars["n" + k + "_reason"] = notes[i][1]
            else:
                vars["n" + k + "_go"] = "no"
        say = list(st.get("close_say") or [])
        if q:
            say.append(cfg("texts.transfer_say", "I am transferring you now."))
        if rec:
            say.append(cfg("texts.recorded", "Your promise is recorded.") + " " + cfg("texts.after_promise", ""))
        if failed:
            say.append(cfg("texts.service_error", "I am sorry, I could not record your promise because of a technical problem.")
                       + (" (" + ", ".join(p["words"] for p in failed) + ")" if rec else ""))
        vars["final_say"] = " ".join(s.strip() for s in say if s.strip())
        save_state(vars, st)
    except Exception as e:
        vars["final_outcome"] = cfg("outcomes.no_promise", "no_promise")
        vars["final_reason"] = cfg("reasons.refused", "refused")
        vars["final_say"] = ""
        vars["finalize_error"] = str(e)[:200]
