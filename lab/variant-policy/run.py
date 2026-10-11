"""Hand-derived brief oracles; execute only the local policy, never Freya or bank APIs.
Run: python3 lab/variant-policy/run.py [v1|v2|v3|s1|s2 ...]
The expected values below are literals derived from the briefs, not CFG or policy helpers.
Commit results are explicitly simulated to exercise finalization; no network is used.
"""
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SPECS = {
    'v1': 'out/v1.spec.json', 'v2': 'out/v2.spec.json', 'v3': 'out/v3.spec.json',
    's1': 'lab/stress/s1.got2.json', 's2': 'lab/stress/s2.got2.json',
}
CASES = []


def ev(event, product='p1', date=None, amount=None, situation=None):
    return dict(event=event, product=product, date=date, amount=amount, situation=situation)


def sit(situation, product='p1'):
    return ev('situation', product, situation=situation)


def p(kind, late, full=100, floor=25):
    return dict(kind=kind, late=late, full=full, floor=floor)


def outcome(code, reason='', promises=(), notes=(), ready=None):
    x = dict(outcome=code, reason=reason, promises=list(promises), notes=list(notes))
    if ready is not None:
        x['commit_ready'] = ready
    return x


def add(brief, name, now, products, deadlines, events, expected, rule, checkpoints=None, floors=None, failed=(), transfer=None):
    CASES.append(dict(id=brief + '-' + name, brief=brief, now=now, products=products,
                      deadlines=deadlines, events=events, expected=expected, rule=rule,
                      checkpoints=checkpoints or {}, floors=floors, failed=list(failed), transfer=transfer))


def cb(brief, name, now, proposals, states, rule):
    CASES.append(dict(id=brief + '-' + name, brief=brief, now=now,
                      callback=proposals, expected=states, rule=rule))


def offered(date, amount, attempts=None):
    x = dict(status='offered', offer_date=date, offer_amount=amount)
    if attempts is not None:
        x['attempts_used'] = attempts
    return x


# NORTHWIND: 12 October is Monday; 19 October is a bank holiday.
add('v1', 'three-bands-clamp', '2026-10-12T10:00',
    [p('credit_card', 10), p('overdraft', 11), p('mortgage', 31)],
    ['2026-10-26', '2026-10-22', '2026-10-15'], [ev('propose', 'all', '2026-10-23')],
    outcome('promise_to_pay', promises=[['p1',100,'2026-10-23'],['p2',100,'2026-10-22'],['p3',100,'2026-10-15']]),
    'Rules 14,19: 9 business days; 10 calendar days previous-BD; fourth inclusive BD; clamp separately.')
add('v1', 'priority-three-steps', '2026-10-16T16:45', [p('mortgage',60)], ['2026-10-22'],
    [ev('refuse'),ev('refuse'),ev('refuse'),ev('refuse')], outcome('no_commitment','offer_declined',notes=[['p1','offer_declined']]),
    'Rules 23-24: full next BD, full second BD, floor inclusive deadline; no fourth attempt.',
    {0:[offered('2026-10-20',100,1)],1:[offered('2026-10-21',100,2)],2:[offered('2026-10-22',25,3)]})
add('v1', 'calendar-weekend-back', '2026-10-15T10:00', [p('overdraft',30)], ['2026-10-23'],
    [ev('vague'),ev('vague'),ev('accept_offer')], outcome('promise_to_pay',promises=[['p1',100,'2026-10-23']]),
    'Rules 14,17: 25 October Sunday rolls back to Friday 23; vague answers consume zero attempts.',
    {1:[offered('2026-10-23',100,0)]})
add('v1', 'past-offer-today', '2026-10-12T16:00', [p('credit_card',1)], ['2026-10-26'],
    [ev('propose',date='2026-10-09'),ev('accept_offer')], outcome('promise_to_pay',promises=[['p1',100,'2026-10-12']]),
    'Rule 15: past date must produce an offer of today, not an open-ended question.', {0:[offered('2026-10-12',100,0)]})
add('v1', 'hardship-voluntary-promise', '2026-10-12T10:00', [p('credit_card',10)], ['2026-10-26'],
    [sit('hardship'),ev('refuse'),ev('propose',date='2026-10-13',amount=50)],
    outcome('promise_to_pay',promises=[['p1',50,'2026-10-13']]),
    'Rule 25: after care transfer declined, a volunteered valid promise replaces hardship.')
add('v1', 'nonanswer-advances', '2026-10-12T10:00', [p('credit_card',1)], ['2026-10-26'],
    [ev('no_answer'),ev('refuse')], outcome('no_commitment','offer_declined',notes=[['p1','offer_declined']]),
    'Rule 23: a non-answer triggers the next persuasion attempt immediately.', {0:[offered('2026-10-13',100,1)]})
cb('v1','sunday-callback','2026-10-18T16:00', [['today','17:30']], [{'state':'book','date':'2026-10-18','time':'17:30'}],
   'Rule 5 explicitly allows today even if not a business day.')
cb('v1','incomplete-correction','2026-10-16T17:00', [['2026-10-22','10:00'],['2026-10-21',None]],
   [{'state':'ask'},{'state':'give_up'}], 'Rules 5-6: next two BDs are 20 and 21; second offer incomplete means no callback.')
add('v1','transfer-discards-unrecorded','2026-10-12T10:00',[p('credit_card',1)],['2026-10-26'],
    [ev('pay_today'),sit('restructuring')],outcome('handed_over','options_requested',ready='no'),
    'Rule 38: transfer discards unrecorded promises and must not permit commit; no notes.',transfer='payment_options')
add('v1','above-balance-correction','2026-10-12T10:00',[p('credit_card',1)],['2026-10-26'],
    [ev('propose',date='2026-10-13',amount=150),ev('accept_offer')],outcome('promise_to_pay',promises=[['p1',100,'2026-10-13']]),
    'Rule 22: explain above-balance amount cannot be recorded and OFFER full amount, not silently agree.',
    {0:[offered('2026-10-13',100,0)]})

# ROWAN: amendment retains Christmas Eve closure and adds New Year's Eve.
add('v2','monday-current-floor','2026-11-16T10:00',[p('business_card',15)],['2026-11-30'],
    [ev('too_much'),ev('refuse'),ev('refuse'),ev('refuse')],outcome('C40','R10',notes=[['p1','R10']]),
    'Rule 24 and M2: established has two steps; first uses floor after unaffordability, last BD this week; second floor deadline.',
    {1:[offered('2026-11-20',25,1)],2:[offered('2026-11-30',25,2)]})
add('v2','friday-next-week','2026-11-20T16:00',[p('working_capital',14)],['2026-12-02'],
    [ev('refuse'),ev('accept_offer')],outcome('C10',promises=[['p1',100,'2026-11-27']]),
    'Rules 14,24: Friday today is last BD so use next Friday; inclusive eighth BD skips Monday holiday.',{0:[offered('2026-11-27',100,1)]})
add('v2','saturday-week-ended','2026-11-21T10:00',[p('business_card',15)],['2026-12-04'],
    [ev('refuse'),ev('accept_offer')],outcome('C10',promises=[['p1',100,'2026-11-24']]),
    'Rule 24: if last business day of this week already passed, use NEXT business day, not next Friday.',{0:[offered('2026-11-24',100,1)]})
add('v2','amended-holiday-clamp','2026-12-23T16:00',[p('business_card',1),p('equipment_finance',60)],
    ['2027-01-06','2027-01-06'],[ev('propose','all','2026-12-31'),ev('accept_offer','all')],
    outcome('C10',promises=[['p1',100,'2027-01-01'],['p2',100,'2027-01-01']]),
    'M1 adds 31 December but not 1 January: both closed-day offers move to 1 January.',
    {0:[offered('2027-01-01',100,0),offered('2027-01-01',100,0)]})
cb('v2','weekend-today','2026-11-21T16:30',[['today','16:45']],[{'state':'book','date':'2026-11-21','time':'16:45'}],
   'Rule 5 permits today on a weekend; M3 end is inclusive 16:45.')
cb('v2','amended-end-correction','2026-11-20T16:40',[['today','16:46'],['2026-11-26','16:45']],
   [{'state':'ask'},{'state':'book','date':'2026-11-26','time':'16:45'}], 'M3 rejects 16:46; third next BD after holiday is Thursday 26.')
add('v2','account-order-reason','2026-11-16T10:00',[p('business_card',1),p('working_capital',1),p('equipment_finance',1)],
    ['2026-11-26']*3,[sit('paid','p1'),ev('refuse','p2'),sit('dispute','p3')],
    outcome('C40','R10',notes=[['p1','R40'],['p2','R10'],['p3','R30']]),
    'Rule 39: choose first account-order non-paid reason, NOT dispute priority. Auto advance offers p2 once.')
add('v2','vague-deadline','2026-11-16T10:00',[p('working_capital',60)],['2026-11-30'],
    [ev('vague'),ev('vague'),ev('accept_offer')],outcome('C10',promises=[['p1',100,'2026-11-30']]),
    'Rule 17: second vague proposes deadline without persuasion.',{1:[offered('2026-11-30',100,0)]})
add('v2','inclusive-holiday-today','2026-11-23T10:00',[p('business_card',14)],['2026-12-03'],
    [ev('pay_today'),ev('accept_offer')],outcome('C10',promises=[['p1',100,'2026-11-24']]),
    'Rules 14-16: inclusive count starts Tuesday when today is holiday; today proposal moves to Tuesday.',{0:[offered('2026-11-24',100,0)]})
add('v2','transfer-discards-unrecorded','2026-11-16T10:00',[p('business_card',1)],['2026-11-26'],
    [ev('pay_today'),sit('restructuring')],outcome('C30','T11',ready='no'),
    'Rule 38: no commit of unrecorded promises after transfer.',transfer='business_arrangements')

# WILLOW: Saturdays count, except 31 October; today is never allowed.
add('v3','monday-today-prohibited','2026-10-26T16:00',[p('personal_loan',9)],['2026-11-05'],
    [ev('propose',date='today'),ev('accept_offer')],outcome('payment_agreed',promises=[['p1',100,'2026-10-27']]),
    'Rules 14-15: 8 BDs exclude today, skip holiday Saturday; volunteered today offered next BD.',{0:[offered('2026-10-27',100,0)]})
add('v3','friday-holiday-weekend','2026-10-30T16:00',[p('personal_loan',10)],['2026-11-06'],
    [ev('pay_today')],outcome('payment_agreed',promises=[['p1',100,'2026-11-02']]),
    'Rule 20: affirmative initial next-BD ask means Monday 2 November, skipping Saturday holiday.')
add('v3','saturday-working-day','2026-11-06T10:00',[p('personal_loan',1)],['2026-11-16'],
    [ev('pay_today')],outcome('payment_agreed',promises=[['p1',100,'2026-11-07']]),
    'Rules 13,20: ordinary Saturday IS a business day and is the earliest promise.')
add('v3','calendar-next-adjust','2026-11-22T10:00',[p('personal_loan',40)],['2026-12-01'],
    [ev('vague'),ev('vague'),ev('accept_offer')],outcome('payment_agreed',promises=[['p1',100,'2026-12-01']]),
    'Rule 14: 7 calendar days gives Sunday 29; Monday 30 holiday, so next BD Tuesday 1.',{1:[offered('2026-12-01',100,0)]})
add('v3','current-floor-ladder','2026-10-30T16:00',[p('personal_loan',10)],['2026-11-06'],
    [ev('too_much'),ev('refuse'),ev('refuse'),ev('refuse')],outcome('payment_unagreed','declined_payment'),
    'Rules 24,38: current floor on third BD Wednesday 4, then floor deadline; never add notes.',
    {1:[offered('2026-11-04',25,1)],2:[offered('2026-11-06',25,2)]})
add('v3','past-next-business-day','2026-10-30T16:00',[p('personal_loan',10)],['2026-11-06'],
    [ev('propose',date='2026-10-29'),ev('accept_offer')],outcome('payment_agreed',promises=[['p1',100,'2026-11-02']]),
    'Rule 15: past date must offer next BD, never ask for a day from today on.',{0:[offered('2026-11-02',100,0)]})
cb('v3','holiday-today-callback','2026-10-31T16:00',[['today','16:30']],[{'state':'book','date':'2026-10-31','time':'16:30'}],
   'Rule 5 permits today even on a bank holiday, inclusive 16:30.')
cb('v3','saturday-horizon','2026-11-06T16:30',[['today','16:30'],['2026-11-07','09:30']],
   [{'state':'ask'},{'state':'book','date':'2026-11-07','time':'09:30'}], 'Rule 5: now itself rejected; next one BD is Saturday, start inclusive.')
add('v3','paid-no-notes','2026-10-26T10:00',[p('personal_loan',1)],['2026-11-05'],[sit('paid')],
    outcome('payment_claimed'), 'Rules 32,38: paid outcome has no reason and no product notes.')
add('v3','hardship-voluntary-promise','2026-10-26T10:00',[p('personal_loan',10)],['2026-11-02'],
    [sit('hardship'),ev('refuse'),ev('propose',date='2026-10-27',amount=50)],
    outcome('payment_agreed',promises=[['p1',50,'2026-10-27']]), 'Rule 25 permits volunteered valid promise after declining wellbeing transfer.')

# ALDER: final M2 restores 22.5%, stage3=3, end=18; M1 stage2=4, start=09:30 and 3 Nov holiday survive.
add('s1','amendments-multi-clamp','2026-10-30T16:00',[p('CARD',10),p('TERM_LOAN',11),p('OVERDRAFT',31)],
    ['2026-11-13','2026-11-09','2026-11-06'],[ev('propose','all','2026-11-12')],
    outcome('PTP',promises=[['p1',100,'2026-11-12'],['p2',100,'2026-11-09'],['p3',100,'2026-11-06']]),
    'M1/M2: both Nov 2 and Nov 3 closed; band deadlines 8/4/3 BDs; joint date clamps per facility.',floors=[25,25,22.5])
add('s1','round-up-fractional-penny','2026-10-26T10:00',[p('OVERDRAFT',90,100.01)],['2026-10-29'],
    [ev('propose',date='2026-10-27',amount=22.50),ev('accept_offer')],outcome('PTP',promises=[['p1',22.51,'2026-10-27']]),
    'Rule 4.1/M2: 22.5% of 100.01 is 22.50225, CEIL penny 22.51; 22.50 rejected.',{0:[offered('2026-10-27',22.51,0)]},floors=[22.51])
add('s1','exact-penny-not-extra','2026-10-26T10:00',[p('OVERDRAFT',10,100)],['2026-11-09'],
    [ev('propose',date='2026-10-27',amount=22.5)],outcome('PTP',promises=[['p1',22.5,'2026-10-27']]),
    'Rule 4.1/M2: exact 22.50 does not round up to 22.51.',floors=[22.5])
add('s1','three-step-current','2026-11-01T16:00',[p('OVERDRAFT',31,100.01)],['2026-11-06'],
    [ev('too_much'),ev('refuse'),ev('refuse'),ev('refuse'),ev('refuse')],outcome('NO_PTP','REFUSAL',notes=[['p1','REFUSAL']]),
    'Rule 5.1: first FULL even after unaffordable; second CURRENT floor; third floor deadline. Two following holidays skipped.',
    {1:[offered('2026-11-04',100.01,1)],2:[offered('2026-11-05',22.51,2)],3:[offered('2026-11-06',22.51,3)]},floors=[22.51])
add('s1','service-error-priority','2026-10-26T10:00',[p('CARD',1),p('TERM_LOAN',1),p('OVERDRAFT',1)],['2026-11-09']*3,
    [sit('dispute','p1'),sit('paid','p2'),ev('propose','p3','2026-10-27')],
    outcome('NO_PTP','SYSTEM_ERROR',promises=[['p3',100,'2026-10-27']],notes=[['p1','DISPUTED'],['p2','PAID_CLAIM'],['p3','SYSTEM_ERROR']]),
    'Rule 5.3: both recording attempts fail; service error outranks earlier dispute, exact uppercase wire codes.',failed=['p3'])
cb('s1','holiday-today-disallowed','2026-11-02T10:00',[['today','11:00'],['2026-11-04','09:30']],
   [{'state':'ask'},{'state':'book','date':'2026-11-04','time':'09:30'}], 'Rules 3.1/M1/M2: today must be BD; Nov 3 holiday remains; Wednesday is next BD.')
cb('s1','partial-rollback-window','2026-10-30T17:59',[['today','18:00'],['2026-11-04','09:29']],
   [{'state':'book','date':'2026-10-30','time':'18:00'},{'state':'ask'}], 'M2 restores end=18:00 but retains M1 start=09:30. Second call independently validates early-time rejection.')
add('s1','transfer-discards-unrecorded','2026-10-26T10:00',[p('CARD',1)],['2026-11-09'],
    [ev('pay_today'),sit('restructuring')],outcome('XFER','PLAN_REQUEST',ready='no'),
    'Rule 5.3 and 6.2: immediate arrangements transfer, no notes or new promise recording.',transfer='ARRANGEMENTS')
add('s1','mixed-dispute-priority','2026-10-26T10:00',[p('CARD',1),p('TERM_LOAN',1),p('OVERDRAFT',1)],['2026-11-09']*3,
    [ev('refuse'),ev('refuse'),sit('paid','p2'),sit('dispute','p3')],
    outcome('NO_PTP','DISPUTED',notes=[['p1','REFUSAL'],['p2','PAID_CLAIM'],['p3','DISPUTED']]),
    'Rule 5.3: dispute outranks earlier refusal; paid not selected; one note each.')
add('s1','hardship-accepted','2026-10-26T10:00',[p('CARD',1)],['2026-11-09'],
    [sit('hardship'),ev('accept_offer')],outcome('XFER','SUPPORT_ACCEPTED',ready='no'),
    'Rule 6.1: accepting vulnerability offer transfers, uses no persuasion and no notes.',{0:[{'attempts_used':0}]},transfer='VULNERABILITY')

# MERE: nearest penny, today forbidden, three separate critical steps, debt-management transfer.
add('s2','today-before-holiday','2026-11-04T16:00',[p('bnpl',14,100.01)],['2026-11-16'],
    [ev('propose',date='today'),ev('accept_offer')],outcome('promise',promises=[['p1',100.01,'2026-11-06']]),
    'Sections 3-4: today forbidden; tomorrow Nov 5 holiday, so offer Friday; floor nearest penny=40.00.',
    {0:[offered('2026-11-06',100.01,0)]},floors=[40.0])
add('s2','critical-three-steps','2026-11-02T10:00',[p('bnpl',120,100.02)],['2026-11-06'],
    [ev('refuse'),ev('refuse'),ev('refuse'),ev('refuse')],outcome('no_promise','refused',notes=[['p1','refused']]),
    'Section 4: full second BD, CURRENT full deadline, FLOOR deadline; keep separate identical-date steps.',
    {0:[offered('2026-11-04',100.02,1)],1:[offered('2026-11-06',100.02,2)],2:[offered('2026-11-06',40.01,3)]},floors=[40.01])
add('s2','nearest-penny-two-products','2026-11-02T10:00',[p('bnpl',14,100.01),p('bnpl',15,100.02)],
    ['2026-11-12','2026-11-10'],[ev('propose','p1','2026-11-03',40),ev('propose','p2','2026-11-03',40.01)],
    outcome('promise',promises=[['p1',40,'2026-11-03'],['p2',40.01,'2026-11-03']]),
    'Section 4: 40.004 -> 40.00; 40.008 -> 40.01; boundary dpd14 watch /15 late.',floors=[40,40.01])
add('s2','three-bands-clamp','2026-11-06T16:00',[p('revolving_card',14),p('bnpl',45),p('bnpl',46)],
    ['2026-11-17','2026-11-13','2026-11-11'],[ev('propose','all','2026-11-16')],
    outcome('promise',promises=[['p1',100,'2026-11-16'],['p2',100,'2026-11-13'],['p3',100,'2026-11-11']]),
    'Sections 4-5: boundary bands 14,45,46 and joint date uses per-product deadlines.')
add('s2','service-error-priority','2026-11-02T10:00',[p('revolving_card',1),p('bnpl',1),p('bnpl',1)],['2026-11-12']*3,
    [sit('dispute','p1'),sit('paid','p2'),ev('propose','p3','2026-11-03')],
    outcome('no_promise','service_error',promises=[['p3',100,'2026-11-03']],notes=[['p1','dispute'],['p2','paid'],['p3','service_error']]),
    'Sections 5,7: second recording failure outranks dispute; every unsuccessful product gets one note.',failed=['p3'])
cb('s2','holiday-today-disallowed','2026-11-05T10:00',[['today','11:00'],['2026-11-09','08:30']],
   [{'state':'ask'},{'state':'book','date':'2026-11-09','time':'08:30'}], 'Section 3: holiday today invalid, second next BD Monday allowed, opening inclusive.')
cb('s2','late-afternoon-window','2026-11-06T17:00',[['today','17:00'],['2026-11-10','17:00']],
   [{'state':'ask'},{'state':'book','date':'2026-11-10','time':'17:00'}], 'Section 3: now rejected strictly; Tuesday second next BD, end inclusive.')
add('s2','managed-plan-discards-promise','2026-11-02T10:00',[p('revolving_card',1)],['2026-11-12'],
    [ev('pay_today'),sit('debt_management')],outcome('transferred','managed_plan',ready='no'),
    'Section 6: existing debt management at any point stops recording unrecorded promise, no notes.',transfer='debt_management')
add('s2','managed-plan-before-account','2026-11-02T10:00',[],[],[sit('debt_management')],
    outcome('transferred','managed_plan',ready='no'), 'Section 6: transfer works before account loaded, no account/promise/note needed.',transfer='debt_management')
add('s2','hardship-all-notes','2026-11-02T10:00',[p('revolving_card',1),p('bnpl',15)],['2026-11-12','2026-11-10'],
    [sit('hardship'),ev('refuse')],outcome('no_promise','hardship',notes=[['p1','hardship'],['p2','hardship']]),
    'Sections 6-7: decline support, all unresolved become hardship without persuasion.',{1:[{'attempts_used':0},{'attempts_used':0}]})


def compare(expected, got, path='', diffs=None):
    diffs = [] if diffs is None else diffs
    if isinstance(expected, dict):
        for key, val in expected.items():
            compare(val, got.get(key) if isinstance(got, dict) else None, path + '.' + str(key), diffs)
    elif expected != got:
        diffs.append(dict(path=path.lstrip('.'), expected=expected, got=got))
    return diffs


def execute(case):
    spec = json.loads((ROOT / SPECS[case['brief']]).read_text())
    mod = types.ModuleType('local_variant_policy')
    exec((ROOT / 'builder/runtime/policy.py').read_text(), mod.__dict__)
    mod.CFG = spec
    v = {'now': case['now'], 'customer_id': 'local-only', 'first_name':'Test','last_name':'Customer','title':'Mx'}
    result = dict(id=case['id'], brief=case['brief'], rule=case['rule'], now=case['now'])
    if 'callback' in case:
        got = []
        for day, time in case['callback']:
            mod.run_callback(v, dict(day=day, time=time))
            snapshot = dict(state=v.get('cb_state'), say=v.get('cb_say'))
            if v.get('cb_state') == 'book':
                snapshot.update(date=v.get('cb_date'),time=v.get('cb_time'))
            got.append(snapshot)
        diffs = []
        for index, (exp, actual) in enumerate(zip(case['expected'], got)):
            compare(exp, actual, 'callback.' + str(index), diffs)
        result.update(expected=case['expected'], got=got, mismatches=diffs)
        return result
    a = spec['account']
    for index, prod in enumerate(case['products']):
        raw = {a['id_field']:'p' + str(index + 1), a['type_field']:prod['kind'],
               a['amount_field']:prod['full'], a['days_late_field']:prod['late'],
               'card_last4':'1234','card_suffix':'1234','purchase_label':'desk'}
        floor_field = a['types'][prod['kind']].get('floor_field')
        if floor_field:
            raw[floor_field] = prod['floor']
        for field, value in raw.items():
            v['load_account_response.data.%s.%d.%s' % (a['products_field'],index,field)] = str(value)
    mod.run_prepare(v)
    initial = mod.load_state(v)
    diffs = compare(case['deadlines'], [prod['deadline'] for prod in initial['products']], 'prepare.deadlines')
    if case['floors'] is not None:
        compare(case['floors'], [prod['floor'] for prod in initial['products']], 'prepare.floors', diffs)
    trace = []
    for index, event in enumerate(case['events']):
        mod.run_assess(v, event)
        state = mod.load_state(v)
        trace.append(dict(event=event, products=state['products'], instruction=v.get('next_instruction'), phase=v.get('policy_phase')))
        for pi, expected in enumerate(case['checkpoints'].get(index, [])):
            compare(expected, state['products'][pi], 'events.%d.products.%d' % (index,pi), diffs)
    mod.run_commit_check(v)
    promises = [[v.get('c%d_product'%i), float(v.get('c%d_amount'%i)),v.get('c%d_date'%i)]
                for i in range(1,4) if v.get('c%d_go'%i) == 'yes']
    # Simulate bank outcomes only for non-transfer closes. A transfer's erroneous commit
    # eligibility is retained in `got.promises` as a policy defect, never executed.
    if not case['transfer']:
        for i in range(1,4):
            if v.get('c%d_go'%i) == 'yes':
                ok = v['c%d_product'%i] not in case['failed']
                v['commit_%d_response.data.ok'%i] = 'true' if ok else 'false'
                if not ok:
                    v['commit_%d_retry_response.data.ok'%i] = 'false'
    else:
        v['transfer_queue_done'] = case['transfer']
    ready = v.get('commit_ready')
    mod.run_finalize(v)
    got = dict(outcome=v.get('final_outcome'), reason=v.get('final_reason'), promises=promises,
               notes=[[v.get('n%d_product'%i),v.get('n%d_reason'%i)] for i in range(1,4) if v.get('n%d_go'%i)=='yes'],
               commit_ready=ready, transfer_requested=v.get('transfer_now'), final_say=v.get('final_say'))
    compare(case['expected'],got,'final',diffs)
    if case['transfer']:
        compare(case['transfer'],v.get('transfer_now'),'transfer_requested',diffs)
    if v.get('finalize_error'):
        diffs.append(dict(path='finalize_error',expected=None,got=v['finalize_error']))
    result.update(expected=dict(deadlines=case['deadlines'],floors=case['floors'],checkpoints=case['checkpoints'],final=case['expected']),
                  got=dict(prepare=initial,trace=trace,final=got),mismatches=diffs)
    return result


def main():
    selected = set(sys.argv[1:]) or set(SPECS)
    unknown = selected - set(SPECS)
    if unknown:
        raise SystemExit('Unknown briefs: ' + ', '.join(sorted(unknown)))
    results = [execute(case) for case in CASES if case['brief'] in selected]
    report = dict(description='Literal brief-derived expectations; local policy execution with simulated tool results, no network',results=results)
    (HERE / 'results.json').write_text(json.dumps(report,indent=2) + '\n')
    for brief in SPECS:
        rows = [r for r in results if r['brief']==brief]
        if rows:
            print('%s: %d scenarios, %d pass, %d mismatched' % (brief,len(rows),sum(not r['mismatches'] for r in rows),sum(bool(r['mismatches']) for r in rows)))
    for row in results:
        if row['mismatches']:
            print(row['id'],json.dumps(row['mismatches'],ensure_ascii=False))
    return 1 if any(row['mismatches'] for row in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
