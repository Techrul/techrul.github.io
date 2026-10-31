"""Rating engines shared by every game on the site: Elo, Glicko-2 and OpenSkill (Plackett-Luce, one-on-one).

Moved out of ratings.py unchanged (tennis output is byte-identical) so CS2 and later games use the same code.
The engines only see winner, loser, date and rating period; each game's adapter decides what a "player" is
(a tennis player, a CS2 roster under Valve's 3-of-5 rule, ...) and which matches count.
"""
import math
from collections import defaultdict
from datetime import timedelta

from openskill.models import PlackettLuce

ELO_K = 32
G2_TAU = 0.5
G2_SCALE = 173.7178

# Inactivity (the site's default; inactivity=False gives the textbook models, also published). Elo has no uncertainty,
# so only Glicko-2 and OpenSkill change: for every month (Glicko-2) or week (OpenSkill) a player has
# no match, their uncertainty grows, at a rate that would take it from zero back to a newcomer's
# level in INACTIVE_RESET_YEARS. Both rank by a cautious value (rating - 2 RD, mu - 3 sigma), so
# absent players slide down gradually. Uncertainty never goes above a newcomer's.
INACTIVE_RESET_YEARS = 5
G2_PHI_MAX = 350 / G2_SCALE
G2_INACTIVE_C2 = G2_PHI_MAX ** 2 / (12 * INACTIVE_RESET_YEARS)    # added to phi^2 per month without a match
OSK_SIGMA_MAX = 25 / 3
OSK_INACTIVE_TAU2 = OSK_SIGMA_MAX ** 2 / (52 * INACTIVE_RESET_YEARS)  # added to sigma^2 per week without a match


# ----------------------------------------------------------------------------- Glicko-2
class G2:
    __slots__ = ("mu", "phi", "sigma")

    def __init__(self):
        self.mu, self.phi, self.sigma = 0.0, 350 / G2_SCALE, 0.06


def g_fn(phi):
    return 1 / math.sqrt(1 + 3 * phi * phi / math.pi ** 2)


def g2_update(p, games, extra=0.0):
    """One Glicko-2 rating period. extra: added to phi^2 when the player had no games (inactivity variant)."""
    if not games:
        p.phi = min(math.sqrt(p.phi ** 2 + p.sigma ** 2 + extra), G2_PHI_MAX)
        return
    v_inv = d_sum = 0.0
    for muj, phij, s in games:
        gj = g_fn(phij)
        e = 1 / (1 + math.exp(-gj * (p.mu - muj)))
        v_inv += gj ** 2 * e * (1 - e)
        d_sum += gj * (s - e)
    v = 1 / v_inv
    delta = v * d_sum
    a = math.log(p.sigma ** 2)

    def f(x):
        ex = math.exp(x)
        return (ex * (delta ** 2 - p.phi ** 2 - v - ex)) / (2 * (p.phi ** 2 + v + ex) ** 2) - (x - a) / G2_TAU ** 2

    A = a
    if delta ** 2 > p.phi ** 2 + v:
        B = math.log(delta ** 2 - p.phi ** 2 - v)
    else:
        k = 1
        while f(a - k * G2_TAU) < 0:
            k += 1
        B = a - k * G2_TAU
    fA, fB = f(A), f(B)
    for _ in range(100):
        if abs(B - A) < 1e-6:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2
        B, fB = C, fC
    sigma_new = math.exp(A / 2)
    phi_star = math.sqrt(p.phi ** 2 + sigma_new ** 2)
    phi_new = 1 / math.sqrt(1 / phi_star ** 2 + 1 / v)
    p.mu += phi_new ** 2 * d_sum
    p.phi, p.sigma = phi_new, sigma_new


# ----------------------------------------------------------------------------- skill models
def months_between(a, b):
    """'YYYYMM' strings -> number of month steps from a to b."""
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[4:6]) - int(a[4:6])


def run(matches, backtest_from, preds=None, weekly=None, inactivity=True, periods_per_year=12, deltas=None):
    """Elo, Glicko-2 and OpenSkill over `matches`, oldest first. Each match is a dict:
        w, l     winner and loser (any hashable id: a tennis player, a CS2 roster, a chess player)
        date     naive datetime (UTC), used for weekly ticks and inactivity
        period   Glicko-2 rating period: 'YYYYMM' (tennis: the tournament's start month), or an integer period
                 number (CS2: week number); periods with no matches in between still count as periods
    periods_per_year: how many rating periods make a year (12 for months, 52 for weeks); sets how fast an
                 inactive player's uncertainty grows per period (INACTIVE_RESET_YEARS either way)
        key      optional; preds[key] gets each model's pre-match win chance for the winner
    deltas: optional dict; deltas[key] = {"elo": (winner, loser), "openskill": (winner, loser)}, each side's rating
                 change from this match (OpenSkill: the shown value, mu - 3 sigma). Glicko-2 has none: it rates a
                 whole period's results together, not match by match.
    weekly(monday, elo, g2, osk, last_match, count) is called once per week, before that week's matches.
    inactivity=True grows Glicko-2 / OpenSkill uncertainty while a player is not playing (see constants)."""
    elo = defaultdict(lambda: 1500.0)
    g2 = defaultdict(G2)
    model = PlackettLuce()
    osk = {}
    pending = defaultdict(list)
    period = None
    bt = {m: {"n": 0, "correct": 0, "logloss": 0.0} for m in ("elo", "glicko", "openskill")}
    per_period = G2_INACTIVE_C2 if periods_per_year == 12 else G2_PHI_MAX ** 2 / (periods_per_year * INACTIVE_RESET_YEARS)
    extra = per_period if inactivity else 0.0

    def flush():
        snap = {k: (v.mu, v.phi) for k, v in g2.items()}
        for k in list(g2):
            g2_update(g2[k], [(snap[o][0], snap[o][1], s) for o, s in pending.get(k, [])], extra)
        pending.clear()

    def record(name, p_winner):
        p = min(max(p_winner, 1e-6), 1 - 1e-6)
        bt[name]["n"] += 1
        bt[name]["correct"] += 1 if p > 0.5 else 0
        bt[name]["logloss"] += -math.log(p)

    last_match = {}
    count = defaultdict(int)
    next_week = None

    def tick(monday):
        # OpenSkill: one week of extra uncertainty for everyone without a match in the week just ended
        if inactivity:
            since = monday - timedelta(days=7)
            for pid, rt in osk.items():
                if last_match.get(pid, since) < since:
                    rt.sigma = min(math.sqrt(rt.sigma ** 2 + OSK_INACTIVE_TAU2), OSK_SIGMA_MAX)
        if weekly is not None:
            weekly(monday, elo, g2, osk, last_match, count)

    for r in matches:
        if next_week is None:
            next_week = r["date"] + timedelta(days=(7 - r["date"].weekday()) % 7 or 7)
        while next_week <= r["date"]:
            tick(next_week)
            next_week += timedelta(days=7)
        per = r["period"]
        if period is None:
            period = per
        if per != period:
            flush()
            # periods with no matches at all (tennis: the December break) are still rating periods
            for _ in range((per - period if isinstance(per, int) else months_between(period, per)) - 1):
                flush()
            period = per
        w, l = r["w"], r["l"]
        if w not in osk:
            osk[w] = model.rating()
        if l not in osk:
            osk[l] = model.rating()
        _ = g2[w], g2[l]

        if r["date"] >= backtest_from:
            p_elo = 1 / (1 + 10 ** ((elo[l] - elo[w]) / 400))
            record("elo", p_elo)
            phi = math.sqrt(g2[w].phi ** 2 + g2[l].phi ** 2)
            record("glicko", 1 / (1 + math.exp(-g_fn(phi) * (g2[w].mu - g2[l].mu))))
            p_osk = model.predict_win([[osk[w]], [osk[l]]])[0]
            record("openskill", p_osk)
            if preds is not None:  # per-match winner probabilities, for comparisons in other scripts
                p_g2 = 1 / (1 + math.exp(-g_fn(phi) * (g2[w].mu - g2[l].mu)))
                preds[r.get("key", (w, l))] = {"elo": p_elo, "glicko": p_g2, "openskill": p_osk}

        e = 1 / (1 + 10 ** ((elo[l] - elo[w]) / 400))
        elo[w] += ELO_K * (1 - e)
        elo[l] -= ELO_K * (1 - e)
        pending[w].append((l, 1.0))
        pending[l].append((w, 0.0))
        ow, ol = osk[w].ordinal(), osk[l].ordinal()
        (nw,), (nl,) = model.rate([[osk[w]], [osk[l]]], ranks=[0, 1])
        osk[w], osk[l] = nw, nl
        if deltas is not None:
            deltas[r.get("key", (w, l))] = {"elo": (ELO_K * (1 - e), -ELO_K * (1 - e)),
                                            "openskill": (nw.ordinal() - ow, nl.ordinal() - ol)}
        for pid in (w, l):
            last_match[pid] = r["date"]
            count[pid] += 1
    flush()
    if weekly is not None and last_match:
        weekly(max(last_match.values()), elo, g2, osk, last_match, count)  # state after the latest matches
    return elo, g2, osk, last_match, count, bt
