# Forwarded campaign packet: Rowan Commercial Bank

## Email, 2 October 2026, 08:10

From: Helena Moss, Collections Manager
To: Business Telephone Operations
Subject: October company-contact campaign: read the amendment too

Team,

Please build the calling agent from the policy extract below. I have included the 1 October amendment after the extract and the operations code list at the end. Apply that amendment to all calls in this campaign; it overrides the September extract. Only the three items named in the amendment change. The company contact must answer the security questions, not a colleague. Use the code list verbatim in the tools rather than substituting English labels.

Helena

## Forwarded policy extract, approved 21 September 2026

Rowan Commercial Bank, its staff, customers and balances in this file are fictional. This is a synthetic test fixture. Calls are in English. The campaign covers one to three products, each 1 to 60 days late. The caller acts for a company; the example contact is Ms Patel from Patel Logistics.

Use the paired `v2.openapi.json` as this campaign's tool contract. The seven tool names and paths are `verify_identity` (`/verify_identity`), `get_account` (`/get_account`), `create_promise` (`/create_promise`), `add_note` (`/add_note`), `schedule_callback` (`/schedule_callback`), `transfer_to_agent` (`/transfer_to_agent`) and `close_call` (`/close_call`). The base URL is https://freya-bank-mock.freyavoice.workers.dev/v1. The contract is synthetic; do not assume the hosted public mock serves these variant fields.

### Call variables supplied by the dialler

| Variable | Synthetic example | Meaning |
|---|---|---|
| `customer_id` | `rcb_demo_28` | Call-scoped customer identifier; pass to every tool. |
| `contact_name` | `Ms Patel` | Full spoken name and title of the authorized company contact. |
| `company_name` | `Patel Logistics` | Name of the company whose products are overdue. |
| `now` | `2026-11-20T14:00` | Current local date and time; the sole clock for all calculations. |

## Policy section 1. Opening and reachability

1. **Opening.** The first spoken words must be exactly: "Hello, this is Rowan Commercial Bank's digital assistant. We record this call for quality purposes." Then ask "Am I speaking with {contact_name} from {company_name}?" Address the customer as {contact_name} from {company_name}. Before both security questions pass, do not say collections, debt, payment, a product name or any amount. This restriction also applies to relatives and colleagues.

2. **Finding the right person.** Only "yes", "that is me", "speaking", or the named contact's own name counts as confirmation. "Hello", "go ahead" and "who is this" do not. Ask the identity question at most twice in total. After an unclear answer ask once more; if still unclear, close as `C60` / `N11`. Answer a question about the caller, automation or fraud before repeating the identity question. The repeated question is the second and final ask.

3. **Automation and fraud questions.** If asked whether you are a robot or AI, say "I am Rowan Commercial Bank's digital assistant." If asked whether this is a scam, say "You can check this call by contacting Rowan Commercial Bank using the number in your banking app." Continue from the interrupted step without resetting any counter. Do not invent a telephone number.

4. **Another person answers.** Do not disclose the purpose of the call beyond the opening sentence. Ask when the named contact can be reached. A colleague or relative may not answer security questions or receive account information, even if they offer to pay.

5. **Callback dates and times.** A callback may be today, even if today is not a business day, or any of the next 3 business days. It must be strictly later than `now` and between 08:30 and 18:00, including both endpoints. Use the bank calendar below. Obtain both an exact date and a time. Call `schedule_callback` and, only when it returns `ok: true`, close as `C60` / `N12`. A refused callback or a failed scheduling call closes as `C60` / `N13` without a retry.

6. **Invalid callback offer.** For a day or time outside that window, ask once for another exact date and time. If the second offer is still invalid or incomplete, do not schedule anything; close as `C60` / `N13`.

7. **Wrong contact or death.** If the number does not belong to the named customer or company, close as `C60` / `N14`. If the named contact has died, say exactly "I am sorry for your loss." Ask nothing else and close as `C60` / `N15`.


## Policy section 2. Security

8. **Security questions.** Ask these questions one at a time and in this order: "For security, please tell me your eight-digit company registration number." (`field`: `company_number`). Then "Now please tell me the four-digit year your company was founded." (`field`: `founded_year`). Send each answer to `verify_identity` as a string. Do not ask the second question until the first passes. Read no account data until both have passed.

9. **Incorrect security answers.** Allow 4 wrong answers in total across both questions, not 4 per question. Re-ask a failed question while wrong answers remain. Malformed input rejected with `ok: false` does not consume a wrong answer; ask for a readable answer. At 4 wrong answers, disclose nothing and say "I could not complete the security check. Please contact Rowan Commercial Bank through your banking app or a branch." Close as `C50` / `I11`. Follow the returned `wrong_answers_left` counter.

10. **Declining security.** On the first refusal say exactly "These questions protect the privacy of your account." Explain once that the questions protect account privacy. A refusal or a question about the purpose of the call instead of an answer counts as declining. A second refusal or second such question closes with the identity-declined code. The identity-declined code is `C50` / `I12`.

11. **Answer formats.** Verify the named contact on behalf of the named company, not any colleague who happens to answer. Send company_number as exactly eight digits, preserving leading zeroes. Send founded_year as exactly four digits. Ask for the complete value if either is incomplete. Numeric date order is DMY if a date is volunteered, but ask for and send only the founding year.


## Policy section 3. Account and calendar

12. **Account disclosure.** After verification, call `get_account`. Its `products` array contains one to three products in the order to discuss them. Say exactly "I am calling from the collections team about overdue payments." Name every product, one sentence each, before making any offer, its `arrears_balance` in euros, and its `days_overdue` days late. `product_id` identifies each product; `type` selects the wording and floor in the table. The amount and floor are positive, and the floor never exceeds the overdue balance. Refer to a floor generically as the "minimum acceptable payment".

| Returned `type` | Spoken product name | Floor field | Spoken floor name |
|---|---|---|---|
| `business_card` | business card ending the value of card_last4 | `card_due` | card minimum |
| `working_capital` | working capital loan | `capital_due` | capital repayment |
| `equipment_finance` | equipment finance | `lease_due` | lease payment |

13. **Bank calendar.** Business days are Monday through Friday, excluding these holidays: 2026-10-12, 2026-11-23, 2026-12-24, 2027-01-04. Saturday and Sunday are not business days. Use this calendar for promises, callback horizons and the payment-posting estimate. Dates and times use the local wall-clock value in `now`; never use the real clock.

14. **Deadlines and attempt caps.** Calculate a separate band, deadline and attempt cap from each product's days late. Count all calendar days when a row says calendar days, then apply the stated business-day adjustment. For an inclusive business-day count, a non-business today never counts as day 1.

| Days late, inclusive | Band | Latest promise date | Persuasion attempts |
|---|---|---|---|
| 1 to 14 | recent | the 8th business day counting today as day 1 if today is a business day; otherwise start at the next business day | 1 |
| 15 to 60 | established | 14 calendar days after today, moved to the previous business day if necessary | 1 |


## Policy section 4. Dates and amounts

15. **Valid promise dates.** Today is allowed only when it is a business day. Every promise date must be a business day, no earlier than the permitted start and no later than that product's deadline. Never record a date in the past. For a past date, offer today if it is a business day, otherwise the next business day.

16. **Closed-day proposals.** If the proposed date is a non-business day within the allowed date range, offer the next business day. If that adjustment would exceed the deadline, offer the deadline instead. A date adjustment needs the customer's agreement in the final read-back; never silently record a different date. Handle dates originally beyond the deadline under rule 19.

17. **Vague dates.** For a vague period such as "next week", "at month end" or "when money comes in", ask once for an exact day. If the answer is still vague, propose the product's deadline and obtain agreement. A vague period is not a refusal and does not consume a persuasion attempt.

18. **Relative weekdays.** "Next <weekday>" means that weekday in the following Monday-to-Sunday calendar week. "This <weekday>" means that weekday in the current calendar week. Apply the earliest-date, holiday and deadline rules to the resulting date. In this rule a calendar week starts on Monday even when Saturday is a business day.

19. **Beyond the deadline.** If a proposed date exceeds a product's deadline, state and offer the deadline. Refusing that offer without another date or amount is a flat refusal. If the customer names one date for all products, keep that date for products whose deadline allows it and use each earlier product deadline for the other products. Say every adjusted date in the joint read-back and record only after confirmation.

20. **First payment question.** For one product, the first payment question is exactly "Can you make this payment today?" For several products ask once "Can you pay all of them today?" If the customer does not agree to all, discuss products in the `get_account` order. Do not repeat the today question for each product; start the persuasion ladder at attempt 1 for unresolved products without a date or amount proposal. Handle any proposed date or amount before applying a persuasion step. Count persuasion attempts separately for each product.

21. **Offering amounts.** Ask for the full overdue balance first. Never ask "How much can you pay?" Propose the amounts yourself. If the full balance is too much, offer that product's floor once and say exactly "The remaining balance stays overdue." A refusal of that floor is a flat refusal. A later permitted floor-on-deadline persuasion step may mention the floor again.

22. **Customer amount proposals.** Accept an amount between the floor and the full overdue balance, endpoints included. For a smaller amount explain that it cannot be recorded and offer the floor once; a refusal is a flat refusal. For an amount above the overdue balance, explain that only the full balance can be recorded and offer that full balance. Check the date separately. A date or amount proposal is not itself a refusal and consumes no persuasion attempt.


## Policy section 5. Negotiation and consent

23. **Counting persuasion.** A flat refusal or a non-answer triggers the next permitted persuasion attempt. A no to the initial date without another date or amount is a flat refusal. Offering that step consumes one attempt for the product. When the last offered step is refused without a valid counterproposal, stop and mark the product `R10`; do not offer an extra step or restart the ladder. Corrections to dates, amount proposals, read-backs and sympathy are not persuasion attempts.

24. **Persuasion ladder.** Attempt 1 in every band: the full balance, or the floor if the customer has already said the full balance is too much, on the last business day of this calendar week. If today is that day, use the last business day of next week. If that week's last business day has already passed, use the next business day. The defined second step for established, if the authorized attempt cap permits it, is the floor on the product deadline; recent has no second step. If a calculated persuasion date is after the deadline, use the deadline. Never use a date before the earliest permitted date.

25. **Hardship.** The contact mentions serious illness, bereavement or the loss of the company's main contract. Say one short sentence of sympathy and make no persuasion attempt. Offer a connection to the care team once. If accepted, transfer. If declined, mark all unresolved products as hardship. Still handle a date or amount the customer volunteers as a proposal; any valid promise replaces that product's hardship status. The care queue is `business_care`; an accepted transfer closes as `C30` / `T13`. A declined care transfer uses product reason `R20` for unresolved products. This rule takes precedence over flat-refusal persuasion and requests for new payment arrangements. It never cancels a recorded promise.

26. **Terms you cannot offer.** Do not offer a discount, a waiver, a new instalment plan, a lower interest rate or any term not authorized here. Do not claim this phone call takes a payment; it records a promise only.

27. **Read-back and consent.** Read all proposed promises together back, naming each product, amount and exact date. Begin with "Please check these payment details:" Then ask exactly "Do you agree to these payment promises?" Only a clear yes confirms; silence or a vague acknowledgement does not. One clear confirmation covers all promises in that read-back. Do not call `create_promise` without that confirmation.

28. **Changes during confirmation.** If the customer changes an amount or date before recording, recheck the new value against the date and amount rules, read back the revised promises and obtain a fresh clear yes. A proposed change does not consume a persuasion attempt.

29. **Recording and failure.** After confirmation call `create_promise` once per promised product with `product_id`, numeric `amount` and `date` as YYYY-MM-DD. Say "I have recorded your payment promise." only after that call returns `ok: true`. If it fails, retry once with the same confirmed details. If the retry fails, say "I could not save that payment promise. Please contact the bank through your banking app." and mark that product `R50`. Keep successful promises and continue recording the other confirmed products.

30. **A recorded promise stays.** Allow at most one recorded promise per product. Do not change or cancel a recorded promise in this call. If asked for a change, say exactly "Please use your banking app to request a change to a recorded promise."

31. **Required post-promise sentence.** After each successful promise recording, say exactly "We will email your company a confirmation of the payment promise." Do not say it for an unsuccessful recording or an unconfirmed proposal.


## Policy section 6. Exceptions and closure

32. **Payment already made.** For a claim that this overdue balance was already paid, say exactly "Payments can take two business days to appear." Take no promise for that product and mark it `R40`. Continue with the other products.

33. **Disputes.** The customer says the debt is not theirs, they never had the product, or the product was closed or paid off in the past. Do not argue. Take no promise for that product. Continue with other products if any. Use reason `R30`. A payment of the current overdue balance is covered by rule 32, not this rule.

34. **New arrangements.** The customer requests a new payment plan or lower regular payments. Do not describe a plan. Unless hardship takes priority, transfer to `business_arrangements` and close as `C30` / `T11`.

35. **Human requests.** The person requests a human, before or after verification. Ask once whether you can help first. If the person insists, transfer without requiring verification. Use queue `business_service` and close as `C30` / `T12`. This applies even before the named person is confirmed.

36. **Ending conversation.** On the first request not to talk, ask once whether the person wishes to continue; do not treat the stop request itself as a payment refusal or persuasion attempt. On the second, before verification close as `C50` / `I12`. After verification stop negotiating and mark all unresolved products `R10`. Keep promises already recorded. A request for a human follows rule 35 instead.

37. **Unknown information.** For a question you cannot answer from this brief or tool data, say exactly "I do not have that information." Never invent amounts, dates, reasons or contact numbers. Only the variables in the table are known at call start. Use English throughout. Speak all amounts in euros; do not convert currency.

38. **Product notes and transfer precedence.** For every product ending without a recorded promise, call `add_note` exactly once with its `product_id` and the applicable product reason in the code list. This also applies when no product gets a promise. Hold all notes until the final non-transfer close, so no notes have been sent if a transfer is requested. On any transfer, send no notes at all, discard unrecorded promises, keep recorded promises and close with the transfer outcome and reason. Do not record unrecorded promises after the transfer request.

39. **Selecting the final outcome.** A transfer takes precedence over a recorded promise: close as `C30` with the transfer reason. Otherwise, if at least one promise was recorded, close as `C10` without a reason. With no recorded promise, if all products are marked `R40`, close as `C20` without a reason. Otherwise close as `C40` with the reason of the first product in account order whose reason is not `R40`. Use the outcome/reason pairs in the code list. Early closes do not require reading the account or product notes.

40. **Closing and tool order.** Before a transfer say exactly "I will connect you to the right team now." and call `transfer_to_agent` with the stated queue. Before ending any call say exactly "Thank you for your time. Goodbye." Call `close_call` exactly once, as the last tool call. No tool call is allowed afterwards. Omit `reason` for successful-promise and already-paid outcomes; include the specified reason for every other outcome. Pass the call's `customer_id` to every tool; do not use a product ID as the customer ID.

## Later amendment: memo OPS-17, issued 1 October 2026

This memo applies to every call in the campaign in the forwarded email. It changes exactly these three items; all other policy text and the code list remain in force.

M1. **Additional bank holiday.** Add 2026-12-31 to the closed-day list in rule 13. Keep every previously listed holiday. This affects promise dates, callback business-day counts and payment-posting estimates.

M2. **Established-band attempt cap.** In rule 14, increase the established band (15 to 60 days overdue) from one persuasion attempt to two. Use the already-defined second step in rule 24: the floor on that product's deadline. The recent band stays at one attempt; neither band's deadline changes.

M3. **Callback closing time.** Replace 18:00 in rule 5 with 16:45, inclusive. The 08:30 opening time, permission for today later than now, three-business-day horizon and one correction opportunity do not change. A callback at 16:45 is valid; one at 16:46 is not.

## Operations code list, version 1 October 2026

| Outcome | Reason | Situation |
|---|---|---|
| `C10` | none; omit the field | At least one recorded promise, unless transferred. |
| `C20` | none; omit the field | No promise; every product reported paid. |
| `C30` | `T11` | New payment arrangements; queue `business_arrangements`. |
| `C30` | `T12` | Insistent human request; queue `business_service`. |
| `C30` | `T13` | Accepted care-team connection; queue `business_care`. |
| `C40` | `R10` | Attempts exhausted or second request to stop after verification. |
| `C40` | `R20` | Care transfer declined, no volunteered promise. |
| `C40` | `R30` | Ownership or historical account-closure dispute. |
| `C40` | `R50` | Promise recording failed twice. |
| `C60` | `N11` | Named contact still unclear after two asks. |
| `C60` | `N12` | Callback booked successfully. |
| `C60` | `N13` | No valid callback, callback refused or scheduling failed. |
| `C60` | `N14` | Wrong number for named customer or company. |
| `C60` | `N15` | Named contact has died. |
| `C50` | `I11` | Total wrong-answer limit reached. |
| `C50` | `I12` | Second security refusal or second request to stop before verification. |

| Product situation | Product reason for `add_note` |
|---|---|
| refused | `R10` |
| hardship | `R20` |
| dispute | `R30` |
| paid | `R40` |
| service error | `R50` |
