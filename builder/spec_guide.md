# Collections call spec: what to extract from a bank's brief

You turn a bank's brief for outbound collections phone calls into ONE JSON object (the spec). A compiler turns the spec
into a phone agent. The compiler already implements this call shape:

1. Opening: the agent introduces itself, asks "Am I speaking with <customer>?" (asks at most `opening.max_asks` times).
2. Someone else on the line: no disclosure, try to book a callback inside a window, or close (wrong number, deceased, no callback).
3. Identity: security questions one at a time, each checked with the `verify_identity` tool. Wrong answers are counted by the bank.
4. `get_account` returns 1 to 3 late products. The agent states every product, then makes the brief's first payment ask (about today, or about the earliest allowed day when the brief forbids a promise for today).
5. Negotiation per product: dates, amounts, floors, persuasion attempts, special situations. Python code computes every date and amount.
6. One read-back for all agreed promises, one confirmation, then `create_promise` per product (retry once on failure), `add_note` per product without a promise (only if the brief uses notes), `close_call` with an outcome and reason.

Your job: fill every field from the brief. Values (holidays, limits, names, sentences, codes) MUST come from the brief and the
tool API you are given. Never copy a value from the example below unless the brief says the same thing. When the brief
is raw material (mails, policy extracts, memos, code lists), read every part first. Order the policy versions and amendments by
their stated dates, then apply each amendment field by field: a later memo overrides only what it names, a partial rollback restores
only the named fields, and unrevoked earlier changes (for example an added holiday) stay. A code list tells you what each code means;
the exact spelling and case of a code is the one in the tool API's enum.

`{{var}}` placeholders in texts refer to call variables (the variables every call starts with, listed in the brief), for example `{{title}} {{last_name}}`.
Use only variables the brief lists. Texts are spoken on the phone: plain words, short sentences.

## Fields

- `bank_name`: the bank's name.
- `agent_identity`: how the agent describes itself when asked if it is a robot (e.g. "Freya Bank's digital assistant").
- `language`: language of the call.
- `variables`: map of role -> call variable name. Roles: `customer_id` (passed to every tool), `now` (current date-time of the call), and any name fields (`first_name`, `last_name`, `title`, ...). Use the brief's names.
- `address`: how to address the customer, with placeholders (e.g. "{{title}} {{last_name}}").
- `customer_full_name`: full name with placeholders (e.g. "{{first_name}} {{last_name}}"), or the company/contact name if the brief calls companies.
- `texts`: exact sentences. Keep the brief's own wording where it gives one.
  - `opening`: the first sentence (who is calling, recording notice, whatever the brief requires) WITHOUT the identity question. Do not use the word "recorded" in it (that word is kept for payment promises): say for example "we are recording this call".
  - `identity_question`: the question asking whether the right person is on the line.
  - `condolence`: what to say when told the customer died (if the brief gives it).
  - `identity_failed`: what to say when the identity check failed (e.g. where to go instead).
  - `identity_why`: the explanation given once when the customer does not want to answer security questions.
  - `debt_intro`: the sentence before the products are stated (e.g. "I am calling from the collections team about a late payment.").
  - `ask_today`, `ask_today_all`: the brief's exact FIRST payment question for one product / for several products. If a promise for today is not allowed, this question asks about the earliest allowed day, not today.
  - `rest_overdue`: instruction when a floor amount is offered (e.g. "Say that the rest stays overdue."). Empty string if the brief says nothing.
  - `readback_prefix` (e.g. "So that is"), `confirm_question` (e.g. "Do you confirm?").
  - `robot_reply`, `scam_reply`: the exact sentence to say when asked whether this is a robot/AI, or whether the call is a scam.
  - `recorded`: sentence after a successful recording (e.g. "Your promise is recorded."), `after_promise`: any sentence the brief requires after a recorded promise.
  - `service_error`: what to say when recording failed for good.
  - `transfer_say`: what to say when transferring.
  - `goodbye`: thanks and goodbye at the end of every call.
  - `currency_word`: how amounts are spoken ("dollars", "euros", "pounds", ...).
  - `floor_name`: generic name of the lowest acceptable amount.
- `forbidden_before_verification`: words/topics the agent must not say before identity is verified.
- `opening`: `max_asks` (how many times the identity question may be asked in total), `confirmation` (what counts as confirmation, in one sentence), `rules` (other opening rules, sentences).
- `third_party.rules`: rules for when someone else answers (sentences).
- `callback`: the callback window: `start`, `end` (HH:MM, inclusive), `allow_today` (true if today later than now is allowed), `today_requires_business_day` (false only if today is allowed even when it is not a business day), `business_days_ahead` (how many following business days are allowed, e.g. 1 = next business day), `incomplete_second_offer` (`give_up` only if the brief says that a second offer that is still incomplete, for example a day without a time, ends the attempt; otherwise `ask`).
- `identity`:
  - `questions`: ordered list. Each: `field` (EXACT value of the `field` enum of `verify_identity` in the tool API), `ask` (the spoken question), `kind` (`date`, `digits`, `year`, or `text`), `digits` (count, for `digits`/`year`), `say_name` (short name, e.g. "date of birth").
  - `date_numeric_order`: how to read numeric dates: "DMY" or "MDY".
  - `max_wrong_total`: wrong answers allowed in total.
  - `hints`: map of a `hint` value the tool may return -> the instruction for the agent (e.g. "day_month_swapped": "...ask for the month as a word. This does not count as a wrong answer.").
  - `decline_rule`: what to do when the customer refuses to answer (in full).
  - `max_declines`: refusals to answer that end the call (for example 2 when the second refusal closes it).
  - `call_purpose_counts_as_decline`: true if asking what the call is about instead of answering counts as a refusal.
  - `rules`: other identity rules.
- `account`: how to read `get_account`'s response (field names from the tool API response schema): `products_field` (the array), `id_field`, `type_field`, `amount_field` (the past-due amount), `days_late_field`, and `types`: map of each product type value -> `words` (how to name it on the phone; `<field>` inserts a product field, e.g. "credit card ending <card_last4>"), `floor_field` (the field holding the lowest acceptable amount for this type, or null), `floor_percent` (percentage points, e.g. 22.5 for 22.5%, of the past-due amount, when the floor is a percentage instead of a field), `floor_rounding` (`round`, `ceil` or `floor` to the cent; only if the brief says), `floor_min` (a minimum floor amount, if any), `floor_name` (spoken name, e.g. "minimum payment").
- `tool_fields`: only when a tool's request field names differ from the usual ones: map of tool name -> {role: exact request field name}. Roles: `customer_id`, `product_id`, `amount`, `date`, `time`, `reason`, `outcome`, `queue`, `field`, `answer`, `text`. Example: `{"create_promise": {"amount": "promised_sum", "date": "settlement_day"}}`.
- `calendar`: `business_weekdays` (0=Monday ... 6=Sunday) and `holidays` (YYYY-MM-DD list).
- `bands`: list of bands by days late: `name`, `min_days`, `max_days` (inclusive), `deadline` (`kind` one of `business_days_after_today` with `n`; `business_days_after_today_inclusive` with `n` (today counts as day 1); `calendar_days_after_today` with `n` and `adjust` = `previous_business_day` or `next_business_day`; `end_of_month`), `attempts` (persuasion attempts allowed).
- `dates.today_allowed`: whether a promise for today is allowed.
- `negotiation.non_answer_is_refusal`: true when the brief says a non-answer counts like a flat refusal (uses a persuasion attempt); false when it says to ask again.
- `persuasion`: ordered list of persuasion steps used after flat refusals. Each: `amount` (`current` = the full amount, or the floor if the customer already said the full amount is too much; `full`; `floor`), `date` (`today`, `next_business_day`, `last_business_day_this_week` (if today is that day: last business day of next week), `last_business_day_next_week`, `deadline`, `business_days_after_today:N`), optional `bands` (list of band names the step applies to).
- `multi`: `notes` (true only if the brief requires `add_note` for products without a promise), `single_date_after_deadline` (`use_product_deadline` if one date named for all products is recorded on each product's own deadline when it is later; otherwise `offer_deadline`), `no_notes_on_transfer` (true if no notes on a transfer).
- `reasons`: the reason codes used for products without a promise: `refused`, `hardship`, `dispute`, `paid`, `service_error` -> the exact codes from the brief/tool API.
- `outcomes`: map of the generic outcomes `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, `not_reached` -> the exact `outcome` codes of `close_call`. Add `partial_promise` only if the brief closes differently when a promised amount is below the full past-due amount.
- `closing.no_promise_reason_priority` (optional): when several products end without a promise for different reasons and the brief gives an order for the close reason, the reason codes in that order (highest first). Without it, the reason of the first product (in `get_account` order) whose reason is not `paid` is used.
- `promise_reasons` (optional): `{"full": "<reason code>", "partial": "<reason code>"}` only if the brief requires a reason with the promise outcome.
- `transfer_reasons`: map of each transfer queue (exact enum of `transfer_to_agent`) -> the close reason code used after that transfer.
- `early_closes`: map of situations that end the call before the account is read -> `[outcome, reason]` (exact codes). Keys: `unclear`, `callback`, `no_callback`, `wrong_number`, `deceased`, `id_failed`, `id_declined`. Add others only if the brief has them.
- `close_texts` (optional): map of the same keys -> the spoken closing sentence (include the goodbye).
- `situations`: things the customer may say during the negotiation, one id per distinct situation in the brief (do not merge, e.g., "already in a debt-management plan" with "asks for a new plan"). Map of id -> object:
  - `trigger`: when it applies (one or two sentences, from the brief).
  - `action`: what the agent says/does (from the brief), without tool names.
  - `effect`: `transfer` (the call is transferred to `queue`), `product` (that product, or all products with `scope: "all"`, ends without a promise with `reason`), `call` (the whole call ends with `outcome` and `reason`), or `none` (just say something and continue).
  - `queue` (for `transfer`, exact enum value), `reason` (exact code), `outcome` (for `call`), `scope` ("all" when it always applies to every product), `say` (instruction for what to say when it happens and the call continues), `close_say` (sentence spoken at the end of the call if it ends because of this).
  - `offer_queue`: when the agent must first OFFER a transfer (for example to a support team): the queue. Accepting transfers the call there; declining applies `effect`.
  - `ask_first`: true when the agent must first ask once whether it can help (for example a request for a human); the second request applies `effect`.
  Always include, if the brief covers them: hardship, restructuring/new plan, human request, already paid, dispute, does not want to talk.
- `negotiation_rules`: other negotiation rules, as short imperative sentences.
- `global_rules`: rules that hold at every step (robot/AI question, scam question, unknown information, ...).
- `coverage`: list of strings "rule <number or short name> -> <spec field>" for EVERY rule in the brief, including every amendment kept, every exact sentence and every renamed API field. Rules that no field can hold go into the closest `*_rules` list, word for word, and their coverage line says "prose only".

## Example (for a different brief: do NOT copy its values)

EXAMPLE_SPEC
