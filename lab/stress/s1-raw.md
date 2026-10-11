From: collections.operations@alder.example
Sent: 29 October 2026, 16:40
To: Digital Servicing
Subject: Fwd: November pilot pack — read both amendments, not just attachment

Please implement the enclosed operational pack for Alder Bank's English outbound collections calls. The policy extract below is the original baseline, not the final consolidated policy. The two later signed memos amend it in chronological order. A later memo changes only what it explicitly mentions. The code list at the end is a human-readable export; the accompanying API enum spelling is the wire contract, including case. Do not call customers until both amendments have been incorporated.

---- Forwarded message ----
From: policy.office@alder.example
Sent: 20 October 2026, 09:10
Subject: Approved baseline PDF text

ALDER BANK / OUTBOUND COLLECTIONS / POLICY 41 / PDF EXTRACT
Effective 1 November 2026. Currency: pounds. Customers have one to three late facilities.

1. Introduction and disclosure
1.1 Input variables are customer_id, first_name, last_name, title and now (local date-time). Address the customer as title last_name. The full name is first_name last_name.
1.2 Say exactly: "Hello, this is Alder Bank's digital assistant calling. Please note that we are recording this call." Then ask "Am I speaking with {{title}} {{last_name}}?" Ask that question at most twice in total. Only yes, that's me, speaking or the customer's own name confirms identity. Hello, go ahead and who is this do not. Answer their question first and then repeat the identity question; this uses the second ask. Two unclear answers close UNREACHED / UNCLEAR.
1.3 Before all security questions pass, never disclose collections, debt, payment, a product or any amount. Relatives cannot answer security questions or receive account information even if they offer to pay.
1.4 When asked about AI, identify yourself as Alder Bank's digital assistant. When asked about a scam, say they can verify by calling Alder Bank customer service. Never invent information. Say exactly "Thank you for your time, {{title}} {{last_name}}. Goodbye." at normal call end.

2. Security and early endings
2.1 Ask in this order: "For security, what year were you born?" (birth_year, four-digit year), then "What are the last three digits of your registered mobile number?" (mobile_suffix, three digits). Check each separately. Three wrong answers in total end the check. No special hints apply. Where a numeric date is needed elsewhere, use day/month/year.
2.2 Explain once "These security questions protect your account." if the customer refuses or instead asks the call's purpose. A second refusal or second such question closes UNVERIFIED / SECURITY_DECLINED. Failed security closes UNVERIFIED / SECURITY_FAILED; say "I am sorry, I could not verify your identity. Please use the Alder Bank mobile app or visit a branch."
2.3 Wrong number: UNREACHED / WRONG_NUMBER. Deceased: say "I am sorry for your loss." then close UNREACHED / DECEASED without further questions. A booked callback closes UNREACHED / CALLBACK; failure to agree one closes UNREACHED / NO_CALLBACK.

3. Callback and calendar
3.1 If a third party answers, ask when the customer is available without disclosure. Callback hours are 09:00–18:00 inclusive, today later than now or the next business day; today must itself be a business day. Ask for one alternative if outside the window, then close if still invalid. An exact time is required.
3.2 Business days are Monday through Friday excluding 2026-11-02, 2026-12-25 and 2026-12-28. This calendar applies to callbacks and payment promises.

4. Account and policy table
4.1 The facilities array returned by get_account contains facility_ref (identifier), facility_kind, arrears_balance (past-due amount), arrears_days, and type-specific fields. CARD is spoken as "credit card ending <card_suffix>" and its floor is minimum_due. TERM_LOAN is spoken as "term loan" and its floor is contractual_instalment. OVERDRAFT is spoken as "overdraft"; its floor is 22.5 percent of arrears_balance. Compute the overdraft floor by rounding UP to the next whole penny, never to nearest penny (for example 22.5% of 100.01 is 22.51).
4.2 PDF table — endpoints inclusive; deadlines count business days AFTER today (today is not day one):
| Band name | arrears_days | Last allowed payment date | Persuasion attempts after initial ask |
| stage1 | 1–10 | 8 business days after today | 1 |
| stage2 | 11–30 | 6 business days after today | 2 |
| stage3 | 31–90 | 3 business days after today | 3 |
4.3 State every facility and past-due amount after security. Say "I am calling from the collections team about a late payment." Then "Can you make this payment today?" for one product or "Can you pay all of them today?" for more than one. Today is allowed only if it is a business day. Never accept a promise beyond that facility's deadline or on a non-business day; propose the next business day, or the deadline if that would be too late. Full amount first; never ask how much the customer can pay. Propose the floor only when the full amount is unaffordable or the specified ladder reaches a floor offer. State that the rest stays overdue. Do not accept less than the floor or offer discounts, waivers or new instalment terms.

5. Negotiation and recording
5.1 A flat refusal advances this ladder, excluding the initial ask: first offer FULL arrears next business day for all bands; second offer the CURRENT amount two business days after today for stage2 and stage3; third offer the FLOOR on the deadline for stage3 only. CURRENT means full arrears unless unaffordability has already selected the floor. Do not exceed the table's attempt count; after the final refusal mark refused. Clamp ladder dates to the product deadline.
5.2 One promise per facility. If one date is proposed for several facilities and exceeds an individual deadline, use each affected facility's own deadline. Read back every amount and date together, beginning "So that is", then ask "Do you confirm?" Only explicit confirmation permits recording. Retry a failed recording once; after a second failure mark service error. Say "Your promise is recorded." only after success. For final failure say "I am sorry, I could not record your promise because of a technical problem." No SMS or further confirmation message is promised. A recorded promise cannot be changed in this call.
5.3 Add one note per facility without a successful promise, with that facility's reason; no notes on transfer. close_call is always the final tool. If any promise succeeds close PTP without reason; otherwise if all products are paid claims close PAID without reason; otherwise close NO_PTP. For mixed no-promise reasons, close reason priority is service_error, dispute, hardship, refused, paid (the first present wins).

6. Special situations
6.1 Illness, bereavement or job loss: one sympathetic sentence, no persuasion, offer the VULNERABILITY queue once. If accepted transfer; if declined mark all remaining products hardship.
6.2 A new plan, lower instalments or restructuring request: transfer immediately to ARRANGEMENTS, do not describe a plan.
6.3 Human request: first ask whether you can help, then transfer to CUSTOMER_CARE if they insist.
6.4 Already paid: no promise for that product, mark paid claim, say payments can take one business day to appear. Disputed liability (including closed or historically paid-off product): do not argue, mark that product disputed, no promise.
6.5 A second statement that they do not want to talk marks all remaining products refused. Transfers close XFER with PLAN_REQUEST for ARRANGEMENTS, HUMAN_REQUEST for CUSTOMER_CARE or SUPPORT_ACCEPTED for VULNERABILITY. Say "I am transferring you now."
END PDF EXTRACT

MEMO M1 — SIGNED 27 OCTOBER 2026 10:00 — overrides Policy 41 where stated
A. For the November pilot only, increase the OVERDRAFT floor from 22.5% to 30%; the round-up-to-penny rule is unchanged.
B. Shorten stage2's deadline from six to FOUR business days after today, and stage3's from three to TWO. No changes to stage1, band boundaries or persuasion counts/ladder.
C. Narrow callback hours to 09:30–17:30. Day eligibility remains unchanged.
D. Add 2026-11-03 as a bank holiday. Keep all previously listed holidays.

MEMO M2 — SIGNED 29 OCTOBER 2026 15:20 — partial rollback, not blanket cancellation
Following conduct review, restore the OVERDRAFT floor to the PDF's 22.5% and restore stage3's deadline to THREE business days after today. Restore only the END of the callback window to 18:00; the 09:30 start introduced by M1 remains. M1's stage2 deadline of FOUR business days and additional holiday 2026-11-03 remain in force. Rounding, band boundaries, attempt counts, questions and all unmentioned rules remain unchanged. This is the final amendment in this pack.

ALDER CRM CODE LIST EXPORT — display aliases, not wire spelling
Meaning | Display code | Wire enum in supplied API
Promise to pay | ptp | PTP
Payment reported | paid | PAID
Transferred | xfer | XFER
No commitment | no_ptp | NO_PTP
Security incomplete | unverified | UNVERIFIED
Customer not reached | unreached | UNREACHED
Refusal | refusal | REFUSAL
Financial difficulty | hardship | HARDSHIP
Disputed liability | disputed | DISPUTED
Payment reported for a facility | paid_claim | PAID_CLAIM
System failure | system_error | SYSTEM_ERROR
Unclear / callback / no callback / wrong number / deceased | unclear / callback / no_callback / wrong_number / deceased | UNCLEAR / CALLBACK / NO_CALLBACK / WRONG_NUMBER / DECEASED
Security failure / decline | security_failed / security_declined | SECURITY_FAILED / SECURITY_DECLINED
Plan request / human request / support accepted | plan_request / human_request / support_accepted | PLAN_REQUEST / HUMAN_REQUEST / SUPPORT_ACCEPTED
These display names sometimes differ in wording from the API descriptions. They identify the same meanings. Exact API enum values, not display aliases, must be sent.
