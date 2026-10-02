"""Network Day: one simulated day of a mule network, modelled on public Thai cases.

Design and sources: 04-prototype-poc/08-network-scenario/PROPOSAL.md and
02-research/crypto-mule-accounts/real-world-cases.md. All people, accounts, shops and
addresses are fictional.

`build()` returns a scenario in the same shape as `scenarios.build()`. TRUTH (roles) is for
evaluators only; engine code never imports this module.
"""
from __future__ import annotations

import heapq
import itertools
import json
import random
import statistics
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from functools import lru_cache

SEED = 20261001
TZ = timezone(timedelta(hours=7))
DAY0 = datetime(2026, 10, 1, 0, 0, tzinfo=TZ)        # 1 Oct: also rent day (dorm look-alikes)
DAY_END = DAY0 + timedelta(hours=23, minutes=59)
RATE = 35.20                                          # THB per USDT

BANKS = ["bank_a", "bank_b", "bank_c", "bank_d", "bank_e"]
PREFIX = dict(zip(BANKS, "ABCDE"))
SETTLEMENT = "acct:bank_b:B-9000"                     # licensed exchange settlement account (hub)

# Face-scan rule (BoT, from mid-2023): mobile transfers >= 50,000 THB per transaction or
# > 200,000 THB per day need biometric checks. Bought mule accounts cannot pass it.
FACE_SCAN_TX_MINOR = 50_000_00
FACE_SCAN_DAY_MINOR = 200_000_00

N = dict(victims_big=1, victims_large=9, victims_medium=40, victims_small=100,
         l1_bought=60, l1_rented=20, l2=12, l2_kyc_exchange=4, otc=3, gold=2,
         merchants=40, suppliers=12, triangle_sellers=3, dorm=2, shops=2, crypto_investors=2,
         students=2, background=500, spray=20)

rng = random.Random(SEED)
ctr = itertools.count()


def T(h: float = 0, m: float = 0, s: float = 0, d: float = 0) -> datetime:
    return DAY0 + timedelta(days=d, hours=h, minutes=m, seconds=s)


def thb(v: float) -> int:
    return int(round(v * 100))


# ---------------------------------------------------------------- world state

accounts: dict[str, dict] = {}
truth: dict[str, str] = {}
bal: dict[str, int] = defaultdict(int)
lots: dict[str, deque] = defaultdict(deque)          # FIFO taint lots: [amount, origin_time, victim]
out_today: dict[str, int] = defaultdict(int)
history: list[dict] = []
live: list[tuple[str, dict]] = []                     # (client, event)
followups: list[dict] = []                            # chain events that happen only if not held
exits: list[tuple[str, float, int]] = []              # (exit_kind, minutes since victim paid, amount)
taint_received: dict[str, int] = defaultdict(int)     # victim-origin THB received, by account
used_ids: dict[str, set] = defaultdict(set)
sid = itertools.count(1)


def new_acct(bank: str, role: str, kind: str, name: str, opening_thb: float) -> str:
    while True:
        n = rng.randint(1000, 8999)
        if n not in used_ids[bank] and n != 9000:
            used_ids[bank].add(n)
            break
    ref = f"acct:{bank}:{PREFIX[bank]}-{n:04d}"
    accounts[ref] = {"account_id": ref, "institution": bank, "display": f"{bank.replace('_', ' ').title()} •{n:04d}",
                     "holder_kind": kind, "holder_name": f"{name} (synthetic)", "balance_minor": thb(opening_thb)}
    truth[ref] = role
    bal[ref] = thb(opening_thb)
    if opening_thb:
        lots[ref].append([thb(opening_thb), None, None])
    return ref


def ev(org: str, etype: str, at: datetime, delay_s: float, **kw) -> dict:
    return {"source_org": org, "source_event_id": f"N-{org}-{next(sid):06d}", "event_type": etype,
            "occurred_at": at.isoformat(), "available_at": (at + timedelta(seconds=delay_s)).isoformat(), **kw}


def transfer_event(at: datetime, frm: str, to: str, amt: int, fmt="transfer", ref=None, to_kind=None) -> dict:
    org = frm.split(":")[1]
    attrs = {"payment_format": fmt}
    if to_kind:
        attrs["to_account_kind"] = to_kind
    return ev(org, "bank_transfer", at, 3, asset="THB", amount_minor=amt, from_ref=frm, to_ref=to,
              reference_id=ref, attributes=attrs)


def hist_transfer(at: datetime, frm: str, to: str, amt: int, fmt="transfer", **kw) -> None:
    history.append(transfer_event(at, frm, to, amt, fmt, **kw))


# ---------------------------------------------------------------- event loop

Q: list = []


def at(t: datetime, fn, *args) -> None:
    if t <= DAY_END:
        heapq.heappush(Q, (t, next(ctr), fn, args))


EXIT_KIND = {"exchange_settlement": "licensed_exchange", "otc_seller": "otc_p2p_seller",
             "gold_shop": "gold_shop", "benign_merchant": "spent_at_merchant",
             "triangle_seller": "spent_at_merchant"}
MULE = {"mule_l1_bought", "mule_l1_rented", "mule_l2", "mule_l2_kyc"}


def pay(t: datetime, frm: str, to: str, amt: int, fmt="transfer", ref=None, to_kind=None) -> int:
    amt = min(amt, bal[frm])
    if amt <= 0:
        return 0
    if truth[frm] == "mule_l1_bought":   # cannot face-scan: per-tx and per-day caps
        amt = min(amt, FACE_SCAN_TX_MINOR - 1, FACE_SCAN_DAY_MINOR - out_today[frm])
        if amt <= 0:
            return 0
    bal[frm] -= amt
    bal[to] += amt
    out_today[frm] += amt
    # move taint lots FIFO
    moved, need = [], amt
    if truth[frm].startswith("victim"):
        lots[frm].clear()
        moved = [[amt, t, frm]]
    else:
        q = lots[frm]
        while need > 0 and q:
            lot = q[0]
            take = min(need, lot[0])
            moved.append([take, lot[1], lot[2]])
            lot[0] -= take
            need -= take
            if lot[0] == 0:
                q.popleft()
    taint_received[to] += sum(a for a, origin, _ in moved if origin is not None)
    kind = EXIT_KIND.get(truth[to])
    if kind and truth[frm] in MULE:
        for a, origin, _ in moved:
            if origin is not None:
                exits.append((kind, (t - origin).total_seconds() / 60, a))
    if not kind:
        lots[to].extend(moved)
    live.append((frm.split(":")[1], transfer_event(t, frm, to, amt, fmt, ref, to_kind)))
    on_receive(t, to, amt, frm)
    return amt


def chunks(total: int, lo: float, hi: float) -> list[int]:
    out = []
    while total > 0:
        c = min(total, thb(rng.uniform(lo, hi)))
        out.append(c)
        total -= c
    return out


# ---------------------------------------------------------------- build population

def build_population():
    pop = {}
    pop["background"] = [new_acct(rng.choice(BANKS), "background", "person", "Ordinary customer",
                                  rng.uniform(5_000, 200_000)) for _ in range(N["background"])]
    pop["merchants"] = [new_acct(rng.choice(BANKS), "benign_merchant", "merchant", f"Food/shop merchant {i+1}",
                                 rng.uniform(3_000, 40_000)) for i in range(N["merchants"])]
    pop["suppliers"] = [new_acct(rng.choice(BANKS), "benign_supplier", "merchant", f"Wholesale supplier {i+1}",
                                 rng.uniform(50_000, 500_000)) for i in range(N["suppliers"])]
    pop["triangle"] = [new_acct(rng.choice(BANKS), "triangle_seller", "merchant", f"Online seller {i+1}",
                                rng.uniform(5_000, 60_000)) for i in range(N["triangle_sellers"])]
    pop["gold"] = [new_acct(b, "gold_shop", "merchant", f"Gold shop {i+1}", rng.uniform(300_000, 900_000))
                   for i, b in enumerate(["bank_a", "bank_c"])]
    pop["gold_supplier"] = new_acct("bank_d", "benign_supplier", "merchant", "Gold wholesaler", 2_000_000)
    pop["otc"] = [new_acct(b, "otc_seller", "person", f"Individual {i+1}", rng.uniform(20_000, 150_000))
                  for i, b in enumerate(["bank_c", "bank_d", "bank_e"])]
    pop["l1_bought"] = [new_acct(rng.choice(BANKS), "mule_l1_bought", "person", "Customer",
                                 rng.uniform(500, 2_000)) for _ in range(N["l1_bought"])]
    pop["l1_rented"] = [new_acct(rng.choice(BANKS), "mule_l1_rented", "person", "Customer",
                                 rng.uniform(1_000, 15_000)) for _ in range(N["l1_rented"])]
    pop["l2"] = [new_acct(rng.choice(BANKS), "mule_l2_kyc" if i < N["l2_kyc_exchange"] else "mule_l2",
                          "person", "Customer", rng.uniform(1_000, 20_000)) for i in range(N["l2"])]
    pop["dorm"] = [new_acct(rng.choice(BANKS), "benign_lookalike_dorm", "person", f"Dorm owner {i+1}",
                            rng.uniform(5_000, 30_000)) for i in range(N["dorm"])]
    pop["shops"] = [new_acct(rng.choice(BANKS), "benign_lookalike_shop_sweep", "merchant", f"Online shop {i+1}",
                             rng.uniform(2_000, 20_000)) for i in range(N["shops"])]
    pop["own_savings"] = [new_acct(rng.choice(BANKS), "benign_own_account", "person", "Savings (same owner)",
                                   rng.uniform(50_000, 300_000)) for _ in range(N["dorm"] + N["shops"])]
    pop["investors"] = [new_acct(rng.choice(BANKS), "benign_lookalike_crypto_investor", "person",
                                 f"Retail crypto investor {i+1}", rng.uniform(100_000, 300_000))
                        for i in range(N["crypto_investors"])]
    pop["students"] = [new_acct(rng.choice(BANKS), "benign_accidental_refund", "person", f"Student {i+1}",
                                rng.uniform(300, 3_000)) for i in range(N["students"])]
    accounts[SETTLEMENT] = {"account_id": SETTLEMENT, "institution": "bank_b", "display": "Bank B •9000",
                            "holder_kind": "exchange_settlement",
                            "holder_name": "Licensed exchange settlement account (synthetic)",
                            "balance_minor": thb(5_000_000)}
    truth[SETTLEMENT] = "exchange_settlement"
    bal[SETTLEMENT] = thb(5_000_000)
    return pop


# ---------------------------------------------------------------- history (30 days, context only)

def build_history(pop):
    bg = pop["background"]
    for m in pop["merchants"] + pop["triangle"] + pop["shops"]:
        for _ in range(rng.randint(20, 80)):
            hist_transfer(T(d=-rng.uniform(0.05, 30)), rng.choice(bg), m, thb(rng.randint(40, 2_500)), "qr")
    for g in pop["gold"]:
        for _ in range(rng.randint(15, 40)):
            hist_transfer(T(d=-rng.uniform(0.05, 30)), rng.choice(bg), g, thb(rng.uniform(5_000, 150_000)))
    for o in pop["otc"]:   # OTC sellers look "established": many payers for weeks
        for _ in range(rng.randint(60, 120)):
            hist_transfer(T(d=-rng.uniform(0.05, 30)), rng.choice(bg), o, thb(rng.uniform(5_000, 49_000)))
    for a in pop["l1_bought"]:  # bought: one activation deposit, days old
        hist_transfer(T(d=-rng.uniform(1, 20)), rng.choice(bg), a, thb(rng.uniform(100, 500)))
    for a in pop["l1_rented"] + pop["l2"]:  # rented: real people with normal history
        for k in range(rng.randint(8, 25)):
            hist_transfer(T(d=-rng.uniform(0.5, 30)), rng.choice(bg), a, thb(rng.uniform(200, 25_000)))
        for k in range(rng.randint(5, 15)):
            hist_transfer(T(d=-rng.uniform(0.5, 30)), a, rng.choice(pop["merchants"]), thb(rng.uniform(40, 800)), "qr")
    for i, d in enumerate(pop["dorm"]):  # last month's rent day: same fan-in then forward
        tenants = rng.sample(bg, 20)
        for tn in tenants:
            hist_transfer(T(d=-30, h=rng.uniform(7, 11)), tn, d, thb(rng.uniform(3_500, 6_000)))
        hist_transfer(T(d=-30, h=11.5), d, pop["own_savings"][i], thb(80_000))
    for i, s in enumerate(pop["shops"]):
        for k in range(30):
            hist_transfer(T(d=-30 + k, h=22), s, pop["own_savings"][len(pop["dorm"]) + i], thb(rng.uniform(4_000, 15_000)))
    for j, inv in enumerate(pop["investors"]):
        for k in range(3):
            hist_transfer(T(d=-30 + k * 10, h=10), inv, SETTLEMENT, thb(40_000), ref=f"DEP-H{j}{k}",
                          to_kind="exchange_settlement")
    for s in pop["students"]:
        for k in range(6):
            hist_transfer(T(d=-30 + k * 5, h=9), rng.choice(bg), s, thb(rng.uniform(500, 2_000)))
    history.append(ev("chain", "address_label", T(d=-10), 60, to_ref=CONSOL[0],
                      attributes={"category": "scam_linked", "source": "simulated_chain_label_feed"}))


# ---------------------------------------------------------------- crypto side

CONSOL = ["addr:tron:TSYNconsolidation00000000000000001", "addr:tron:TSYNconsolidation00000000000000002"]
OFFSHORE = "addr:tron:TSYNoffshoreexchangedeposit0000001"
HOT = "addr:tron:TSYNexchangehot000000000000000001"
SPRAY = [f"addr:tron:TSYNspray{n:024d}" for n in range(1, N["spray"] + 1)]
OTC_WALLET = {}
spray_iter = itertools.cycle(SPRAY)
xcust: dict[str, dict] = {}
customers: list[dict] = []
consol_bal = defaultdict(int)
otc_pending = defaultdict(int)
wd_seq = itertools.count(1)
dep_seq = itertools.count(80000)


def chain(t, frm, to, usdt_minor, live_event=True, note=None):
    e = ev("chain", "chain_transfer", t, 30, asset="USDT", amount_minor=usdt_minor, from_ref=frm, to_ref=to,
           attributes={"tx_hash": f"synthetic-{next(sid):08x}", "chain": "tron", "confirmed": True,
                       **({"note": note} if note else {})})
    (live.append(("chain", e)) if live_event else followups.append(e))
    if to in CONSOL:
        consol_bal[to] += usdt_minor


def deposit(t, owner_acct, amt):
    cust = next(c for c in xcust.values() if c["bank"] == owner_acct)
    ref = f"DEP-{next(dep_seq)}"
    got = pay(t, owner_acct, SETTLEMENT, amt, ref=ref, to_kind="exchange_settlement")
    if not got:
        return
    t2 = t + timedelta(seconds=rng.uniform(20, 40))
    live.append(("exchange", ev("exchange", "exchange_deposit", t2, 15, asset="THB", amount_minor=got,
                                to_ref=cust["id"], reference_id=ref, attributes={"credited_from": SETTLEMENT})))
    cust["thb_lots"].append((t2 + timedelta(seconds=15), got))   # usable once the credit is booked
    at(t2 + timedelta(seconds=rng.uniform(60, 180)), trade, cust["id"])


def _take(lots: list, by: datetime) -> int:
    """Sum and remove balance lots booked before `by` (the exchange books events by available time)."""
    ready = [x for x in lots if x[0] < by]
    for x in ready:
        lots.remove(x)
    return sum(a for _, a in ready)


def trade(t, cid):
    c = xcust[cid]
    sell = _take(c["thb_lots"], t + timedelta(seconds=5))
    if sell <= 0:
        return
    gross = sell * 1_000_000 // int(RATE * 100)
    fee = gross // 1000
    live.append(("exchange", ev("exchange", "exchange_trade", t, 5, from_ref=cid, attributes={
        "sell_asset": "THB", "sell_minor": sell, "buy_asset": "USDT", "buy_gross_minor": gross,
        "fee_asset": "USDT", "fee_minor": fee, "buy_net_minor": gross - fee, "rate_thb_per_usdt": f"{RATE:.2f}"})))
    c["usdt_lots"].append((t + timedelta(seconds=5), gross - fee))
    threshold = 1_500_000_000 if c["benign"] else 6_000_000_000   # 1,500 / 6,000 USDT
    if sum(a for _, a in c["usdt_lots"]) >= threshold or t.hour >= 22:
        at(t + timedelta(minutes=rng.uniform(2, 6)), withdraw, cid)


def withdraw(t, cid):
    c = xcust[cid]
    amt = _take(c["usdt_lots"], t + timedelta(seconds=2))
    if amt <= 0:
        return
    dest = c["own_wallet"] if c["benign"] else next(spray_iter)
    wid = f"W-{next(wd_seq):04d}"
    until = t + timedelta(minutes=rng.uniform(8, 20))
    live.append(("exchange", ev("exchange", "withdrawal_request", t, 2, asset="USDT", amount_minor=amt,
                                from_ref=cid, to_ref=dest, attributes={
                                    "withdrawal_id": wid, "chain": "tron",
                                    "controllable_until": until.isoformat()})))
    chain(until, HOT, dest, amt, live_event=False, note=f"broadcast of {wid} if not held")
    if not c["benign"]:
        chain(until + timedelta(minutes=rng.uniform(20, 60)), dest, rng.choice(CONSOL), amt - 1_000_000,
              live_event=False, note=f"funnel after {wid} if not held")


def otc_flush(t):
    for seller, thb_minor in list(otc_pending.items()):
        if thb_minor > 0:
            usdt = int(thb_minor / 100 / (RATE * 1.015) * 1_000_000)
            chain(t, OTC_WALLET[seller], rng.choice(CONSOL), usdt, note="OTC seller delivers USDT off-platform")
            otc_pending[seller] = 0
    at(t + timedelta(minutes=30), otc_flush)


def offshore_sweep(t):
    for c in CONSOL:
        if consol_bal[c] > 0:
            chain(t, c, OFFSHORE, consol_bal[c], note="consolidation -> offshore exchange (live part only)")
            consol_bal[c] = 0


# ---------------------------------------------------------------- mule behaviour

state = {}


def on_receive(t, acct, amt, frm):
    r = truth[acct]
    if r in ("mule_l1_bought", "mule_l1_rented"):
        at(t + timedelta(minutes=rng.uniform(2, 15)), forward_l1, acct)
    elif r in ("mule_l2", "mule_l2_kyc") and not state["l2_pending"].get(acct):
        state["l2_pending"][acct] = True
        at(t + timedelta(minutes=rng.uniform(5, 25)), forward_l2, acct)
    elif r == "otc_seller" and truth[frm] in MULE:
        otc_pending[acct] += amt
    elif r == "benign_accidental_refund" and truth[frm] in MULE:
        back = rng.choice([a for a in state["pop"]["l1_bought"] if a != frm])
        at(t + timedelta(minutes=rng.uniform(10, 20)), pay, acct, back, amt)


def forward_l1(t, acct):
    pop = state["pop"]
    keep = state["keep"].setdefault(acct, accounts[acct]["balance_minor"] + thb(rng.uniform(0, 3_000)))
    avail = bal[acct] - keep
    if avail <= 0:
        return
    if acct in state["mistake_senders"] and not state["mistake_done"].get(acct):
        state["mistake_done"][acct] = True
        student = state["mistake_senders"][acct]
        pay(t, acct, student, thb(rng.choice([8_000, 15_000])))
        avail = bal[acct] - keep
    # Destination is drawn per chunk; the mix puts roughly three quarters of victim money
    # into crypto (BoT: 75% in Q4/2567).
    def pick_dest():
        roll = rng.random()
        if roll < 0.65:
            kyc = pop["l2"][:N["l2_kyc_exchange"]]
            return rng.choice(kyc if rng.random() < 0.5 else pop["l2"][N["l2_kyc_exchange"]:])
        if roll < 0.90:
            return rng.choice(pop["otc"])
        return rng.choice(pop["gold"])
    lo, hi = (45_000, 49_900) if truth[acct] == "mule_l1_bought" else (60_000, 400_000)
    tt = t
    for c in chunks(avail, lo, hi):   # queued, so each chunk books at its own time
        at(tt, pay, acct, pick_dest(), c)
        tt += timedelta(seconds=rng.uniform(30, 120))
    if not state["spent"].get(acct) and rng.random() < 0.8:
        state["spent"][acct] = True
        for k in range(rng.randint(1, 2)):
            # The featured merchant gets exactly one mule payment, from an account that will be reported.
            if k == 0 and not state["featured_paid"] and acct in state["featured_payers"]:
                m, state["featured_paid"] = state["featured"], True
            else:
                m = next(state["merchant_cycle"])
            at(tt + timedelta(minutes=rng.uniform(5, 90)), pay, acct, m, thb(rng.randint(40, 1_500)), "qr")


def forward_l2(t, acct):
    pop = state["pop"]
    state["l2_pending"][acct] = False
    avail = bal[acct] - accounts[acct]["balance_minor"]
    if avail <= 0:
        return
    tt = t
    if truth[acct] == "mule_l2_kyc":
        for c in chunks(avail, 100_000, 400_000):
            at(tt, deposit, acct, c)
            tt += timedelta(seconds=rng.uniform(60, 180))
        return
    for c in chunks(avail, 100_000, 500_000):
        dest = rng.choice(pop["otc"]) if rng.random() < 0.70 else rng.choice(pop["gold"])
        at(tt, pay, acct, dest, c)
        tt += timedelta(seconds=rng.uniform(60, 180))


# ---------------------------------------------------------------- victims and signals

victims: list[dict] = []


def victim_plan(pop):
    def mk(cat, loss_lo, loss_hi, n_pay):
        loss = rng.uniform(loss_lo, loss_hi)
        a = new_acct(rng.choice(BANKS), f"victim_{cat}", "person", "Customer", loss * 1.15 + 5_000)
        start = T(h=rng.uniform(8.5, 19.5))
        k = rng.randint(*n_pay)
        times = sorted(start + timedelta(minutes=rng.uniform(0, 240)) for _ in range(k))
        parts = [loss / k] * k
        victims.append({"acct": a, "cat": cat, "loss": thb(loss), "times": times, "parts": [thb(p) for p in parts],
                        "paid_to": []})

    big = new_acct("bank_a", "victim_big", "person", "Retired official", 12_000_000)
    victims.append({"acct": big, "cat": "big", "loss": thb(10_500_000),
                    "times": [T(h=9, m=10), T(h=10, m=5), T(h=11, m=20), T(h=13), T(h=14, m=40)],
                    "parts": [thb(2_100_000)] * 5, "paid_to": []})
    for _ in range(N["victims_large"]):
        mk("large", 500_000, 2_000_000, (2, 4))
    for _ in range(N["victims_medium"]):
        mk("medium", 50_000, 500_000, (1, 3))
    for _ in range(N["victims_small"]):
        mk("small", 2_000, 50_000, (1, 2))

    # mule windows: each account is "live" for a few hours, then burned
    win = {}
    for a in pop["l1_bought"] + pop["l1_rented"]:
        s = T(h=rng.uniform(8, 20.5))
        win[a] = (s, s + timedelta(minutes=rng.uniform(150, 270)))
    cap_in = defaultdict(int)

    def pick(t, amt):
        bought_ok = amt < FACE_SCAN_TX_MINOR * 4
        pool = pop["l1_bought"] if bought_ok else pop["l1_rented"]
        act = [a for a in pool if win[a][0] <= t <= win[a][1]
               and (not bought_ok or cap_in[a] + amt <= FACE_SCAN_DAY_MINOR - thb(10_000))]
        if not act:
            act = [a for a in pop["l1_rented"] if win[a][0] <= t <= win[a][1]] or pop["l1_rented"]
        a = rng.choice(act)
        cap_in[a] += amt
        return a

    for v in victims:
        for t, p in zip(v["times"], v["parts"]):
            to = pick(t, p)
            v["paid_to"].append((t, to))
            at(t, pay, v["acct"], to, p)
        v["will_report"] = rng.random() <= P_REPORT[v["cat"]]
    # Accounts paid by morning victims who will report: their report surely lands the same day.
    state["featured_payers"] = {a for v in victims if v["will_report"] and v["times"][-1] <= T(h=12)
                                for _, a in v["paid_to"] if truth[a] == "mule_l1_bought"}


P_REPORT = {"big": 1.0, "large": 0.9, "medium": 0.5, "small": 0.3}


def schedule_signals():
    for v in victims:
        if v["cat"] == "triangle":
            continue  # reported in benign_day
        if not v["will_report"]:
            v["reported_at"] = None
            continue
        rt = v["times"][-1] + timedelta(minutes=rng.uniform(45, 360))
        v["reported_at"] = rt if rt <= DAY_END else None
        if v["reported_at"] is None:
            continue
        for to in sorted({a for _, a in v["paid_to"]}):
            live.append(("signals", ev("signals", "external_signal", rt, 120, to_ref=to, attributes={
                "category": "victim_report", "source": "simulated_report_source",
                "reporter": v["acct"], "scam_type": rng.choice(
                    ["fake_official", "investment", "romance", "part_time_job"])})))


# ---------------------------------------------------------------- benign day

def benign_day(pop):
    bg = pop["background"]
    for _ in range(1_800):
        a, b = rng.sample(bg, 2)
        at(T(h=rng.uniform(6, 23.5)), pay, a, b, thb(rng.lognormvariate(6.5, 1.1)))
    for m in pop["merchants"] + pop["triangle"] + pop["shops"]:
        for _ in range(rng.randint(10, 45)):
            at(T(h=rng.uniform(7, 22)), pay, rng.choice(bg), m, thb(rng.randint(40, 2_500)), "qr")
    for g in pop["gold"]:
        for _ in range(rng.randint(3, 8)):
            at(T(h=rng.uniform(9, 19)), pay, rng.choice(bg), g, thb(rng.uniform(10_000, 120_000)))
        at(T(h=16), lambda t, g=g: pay(t, g, pop["gold_supplier"], int(bal[g] * 0.6)))
    for o in pop["otc"]:   # OTC sellers also have ordinary retail buyers today
        for _ in range(rng.randint(5, 12)):
            at(T(h=rng.uniform(8, 22)), pay, rng.choice(bg), o, thb(rng.uniform(5_000, 49_000)))
    for m in pop["merchants"]:  # merchants pay a supplier in the evening (2nd-order exposure)
        at(T(h=20, m=rng.uniform(0, 60)), lambda t, m=m: pay(t, m, rng.choice(pop["suppliers"]),
                                                             int(bal[m] * rng.uniform(0.3, 0.6))))
    for i, d in enumerate(pop["dorm"]):
        for tn in rng.sample(bg, rng.randint(18, 24)):
            at(T(h=rng.uniform(7, 11)), pay, tn, d, thb(rng.uniform(3_500, 6_000)))
        at(T(h=11, m=30), lambda t, d=d, s=pop["own_savings"][i]: pay(t, d, s, int(bal[d] * 0.9)))
    for i, s in enumerate(pop["shops"]):
        at(T(h=22), lambda t, s=s, o=pop["own_savings"][len(pop["dorm"]) + i]: pay(t, s, o, int(bal[s] * 0.95)))
    for j, inv in enumerate(pop["investors"]):
        amt = thb([40_000, 80_000][j])
        at(T(h=10 + 2.5 * j, m=15), lambda t, inv=inv, amt=amt: deposit(t, inv, amt))
    # triangle scam: victims pay a real online seller, then report the seller's account
    for k, seller in enumerate(pop["triangle"]):
        v = new_acct(rng.choice(BANKS), "victim_triangle", "person", "Customer", 20_000)
        t = T(h=rng.uniform(10, 17))
        at(t, pay, v, seller, thb(rng.uniform(1_200, 9_500)))
        rt = t + timedelta(minutes=rng.uniform(60, 180))
        live.append(("signals", ev("signals", "external_signal", rt, 120, to_ref=seller, attributes={
            "category": "victim_report", "source": "simulated_report_source", "reporter": v,
            "scam_type": "triangle_purchase"})))
        victims.append({"acct": v, "cat": "triangle", "loss": 0, "times": [t], "parts": [], "paid_to": [(t, seller)],
                        "reported_at": rt})


# ---------------------------------------------------------------- stats

def stats(pop):
    transfers = [e for _, e in live if e["event_type"] == "bank_transfer"]
    by_from = defaultdict(list)
    for e in transfers:
        by_from[e["from_ref"]].append(e)
    signals = [e for _, e in live if e["event_type"] == "external_signal"]

    # Blunt rule: freeze reported accounts, then every account that received money from a
    # frozen account after it was tainted, up to 4 hops (exchange settlement hub excluded).
    hit = {}
    frontier = [(s["to_ref"], DAY0, 0) for s in signals]
    while frontier:
        a, since, hop = frontier.pop()
        if a in hit and hit[a] <= hop:
            continue
        hit[a] = hop
        if hop >= 4:
            continue
        for e in by_from[a]:
            t = datetime.fromisoformat(e["occurred_at"])
            if t >= since and e["to_ref"] != SETTLEMENT:
                frontier.append((e["to_ref"], t, hop + 1))

    def group(r):
        if r in MULE or r == "otc_seller":
            return "criminal_or_complicit"
        if r.startswith("victim"):
            return "victim"
        return "innocent"
    g = Counter(group(truth[a]) for a in hit)
    innocent = [a for a in hit if group(truth[a]) == "innocent"]
    per_role = defaultdict(lambda: {"accounts": 0, "whole_balance_frozen_thb": 0.0, "victim_money_received_thb": 0.0})
    for a in innocent:
        r = per_role[truth[a]]
        r["accounts"] += 1
        r["whole_balance_frozen_thb"] += bal[a] / 100
        r["victim_money_received_thb"] += taint_received[a] / 100
    per_role = {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in per_role.items()}

    exit_amt = defaultdict(int)
    mins = []
    for kind, m, a in exits:
        exit_amt[kind] += a
        mins.append((m, a))
    mins.sort()
    tot = sum(a for _, a in mins)

    def wq(q):
        acc = 0
        for m, a in mins:
            acc += a
            if acc >= q * tot:
                return round(m, 1)
    still_in_mules = sum(sum(l[0] for l in lots[a] if l[1] is not None) for a in truth if truth[a] in MULE)

    # Simple R0-like screen: >= 3 inflows today and >= 80% of inflow sent on within 60 min
    inflow = defaultdict(list)
    for e in transfers:
        inflow[e["to_ref"]].append((datetime.fromisoformat(e["occurred_at"]), e["amount_minor"]))
    flagged = Counter()
    for a, ins in inflow.items():
        if a == SETTLEMENT or len(ins) < 3:
            continue
        quick = sum(e["amount_minor"] for e in by_from[a]
                    if any(0 <= (datetime.fromisoformat(e["occurred_at"]) - ti).total_seconds() <= 3600 for ti, _ in ins))
        if quick >= 0.8 * sum(x for _, x in ins):
            flagged[truth[a]] += 1

    loss = sum(v["loss"] for v in victims)
    rep = [v for v in victims if v.get("reported_at")]
    return {
        "seed": SEED,
        "population": dict(Counter(truth.values())),
        "events": {"history": len(history), "live": len(live), "followups_if_not_held": len(followups),
                   "live_by_type": dict(Counter(e["event_type"] for _, e in live))},
        "victims": {"count": len(victims), "loss_thb": loss / 100,
                    "reported_same_day": len(rep), "report_signals": len(signals),
                    "loss_reported_thb": sum(v["loss"] for v in rep) / 100},
        "where_victim_money_went_thb": {**{k: v / 100 for k, v in exit_amt.items()},
                                        "still_in_mule_accounts": still_in_mules / 100},
        "minutes_victim_payment_to_exit_weighted": {"p10": wq(0.1), "median": wq(0.5), "p90": wq(0.9)},
        "exchange_withdrawals": sum(1 for _, e in live if e["event_type"] == "withdrawal_request"),
        "blunt_freeze_baseline": {
            "accounts_frozen": len(hit), "by_group": dict(g),
            "innocent_by_role": per_role,
            "innocent_whole_balance_frozen_thb": round(sum(bal[a] for a in innocent) / 100, 2),
            "innocent_victim_money_received_thb": round(sum(taint_received[a] for a in innocent) / 100, 2),
        },
        "passthrough_screen_hits_by_role": dict(flagged),
    }


# ---------------------------------------------------------------- build

FEATURED_MERCHANT_NAME = "ร้านป้ามะลิ ข้าวมันไก่ (synthetic)"


def _featured_merchant() -> str:
    """Merchant the guided Merchant page follows: paid once by a mule account that is later reported,
    so one receipt covers the whole restricted amount."""
    if not state["featured_paid"]:
        raise RuntimeError("no reported mule account paid the featured merchant; adjust the seed")
    return state["featured"]


def featured_report_at() -> datetime:
    """When the first report on the featured merchant's payer arrives (engine-visible time)."""
    scn = _generate()[0]
    payer = featured_payment()["from_ref"]
    return min(datetime.fromisoformat(d["due"]) for d in scn["deliveries"]
               if d["event"]["event_type"] == "external_signal" and d["event"]["to_ref"] == payer)


def featured_payment() -> dict:
    """The mule payment to the featured merchant (for the matching evidence fixture)."""
    scn = _generate()[0]
    m = scn["merchant_account_id"]
    return next(d["event"] for d in scn["deliveries"] if d["event"]["event_type"] == "bank_transfer"
                and d["event"]["to_ref"] == m and truth[d["event"]["from_ref"]] in MULE)


@lru_cache(maxsize=1)
def _generate() -> tuple[dict, dict]:
    pop = build_population()
    for o in pop["otc"]:
        OTC_WALLET[o] = f"addr:tron:TSYNotc{len(OTC_WALLET) + 1:026d}"
    build_history(pop)
    mule_customers = pop["l2"][:N["l2_kyc_exchange"]]
    for i, a in enumerate(mule_customers + pop["investors"]):
        cid = f"xcust:exchange:X-{601 + i}"
        benign = a in pop["investors"]
        xcust[cid] = {"id": cid, "bank": a, "thb_lots": [], "usdt_lots": [], "benign": benign,
                      "own_wallet": f"addr:tron:TSYNselfcustody{i:019d}"}
        truth[cid] = "benign_crypto_investor_customer" if benign else "mule_exchange_customer"
        customers.append({"customer_id": cid, "display": f"Exchange customer X-{601 + i}",
                          "balances": {"THB": 0, "USDT": 0}})
    rented = rng.sample(pop["l1_rented"], 2)
    featured, others = pop["merchants"][0], pop["merchants"][1:]
    state.update(pop=pop, keep={}, spent={}, l2_pending={}, mistake_done={},
                 mistake_senders=dict(zip(rented, pop["students"])),
                 featured=featured, featured_paid=False,
                 merchant_cycle=itertools.cycle(rng.sample(others, len(others))))
    victim_plan(pop)
    benign_day(pop)
    at(T(h=8, m=30), otc_flush)
    for h in (13, 17, 21, 23.5):
        at(T(h=h), offshore_sweep)
    while Q:
        t, _, fn, args = heapq.heappop(Q)
        fn(t, *args)
    schedule_signals()

    live.sort(key=lambda ce: datetime.fromisoformat(ce[1]["available_at"]))
    featured = _featured_merchant()
    accounts[featured]["holder_name"] = FEATURED_MERCHANT_NAME
    scenario = {
        "name": "network_day",
        "description": SCENARIO_DESCRIPTION,
        "start": START, "end": DAY_END,
        "history": history,
        "deliveries": [{"client": c, "event": e, "due": e["available_at"]} for c, e in live],
        # Funnel/offshore hops after a withdrawal broadcast depend on officer holds, so they are
        # kept for evaluation only; the simulated exchange broadcasts held-or-not withdrawals itself.
        "followups_if_not_held": followups,
        "accounts": list(accounts.values()), "customers": customers,
        "merchant_account_id": featured,
        "demo_script": [],
    }
    return scenario, stats(pop)


SCENARIO_DESCRIPTION = ("Network Day: 153 victims, 92 mule accounts across 5 banks, OTC sellers, gold shops and "
                        "innocent merchants in one simulated day (modelled on public Thai cases).")
START = DAY0 + timedelta(hours=6)


def build() -> dict:
    return deepcopy(_generate()[0])


def stats_report() -> dict:
    return deepcopy(_generate()[1])


def TRUTH() -> dict[str, str]:  # evaluator-only
    _generate()
    return dict(truth)
