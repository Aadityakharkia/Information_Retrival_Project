"""Turns a user's interaction history into bounded, time-decayed ranking evidence.

Design rules (see docs/REPORT.md, "Search memory"):
  * a click alone is weak evidence; what happens after the click (dwell time, revisits,
    following links onward, explicit feedback) decides whether a document was useful;
  * a click followed by an immediate return ("pogo-sticking") and results that are shown
    again and again but never opened count slightly against a document;
  * every signal decays with a half-life, so old interests fade;
  * affinity is squashed with tanh, so no amount of clicking makes it unbounded;
  * graph authority (who links to whom) is NOT a user signal: only links the user actually
    followed are recorded here.
"""
from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

HALF_LIFE_DAYS = 21.0
LONG_DWELL, SHORT_DWELL = 30.0, 10.0      # seconds

W = {
    "open": 0.25,             # tentative: opening is not proof of relevance
    "dwell_long": 0.75,       # stayed at least 30 s
    "dwell_mid": 0.3,         # 10-30 s
    "dwell_short": -0.2,      # left within 10 s
    "revisit": 0.45,          # x log1p(extra opens)
    "link_from": 0.3,         # explored further from this document
    "link_to": 0.25,          # reached by following a link
    "feedback": 1.5,          # explicit thumbs up / down
    "skip": -0.06,            # per impression in the top results without ever being opened (max 4)
}
SCALE = 1.5                   # affinity = tanh(raw / SCALE)


@dataclass
class Evidence:
    raw: float = 0.0
    opens: int = 0
    dwell: float = 0.0
    links_out: int = 0
    links_in: int = 0
    feedback: int = 0
    impressions: int = 0
    last: float = 0.0
    queries: Counter = field(default_factory=Counter)

    def reasons(self) -> List[str]:
        r = []
        if self.feedback > 0:
            r.append("You marked it relevant")
        if self.feedback < 0:
            r.append("You marked it not relevant")
        if self.opens >= 2:
            r.append(f"You opened it {self.opens} times")
        elif self.opens == 1 and self.dwell >= LONG_DWELL:
            r.append(f"You read it for {int(self.dwell // 60)} min {int(self.dwell % 60)} s" if self.dwell >= 60 else f"You read it for {int(self.dwell)} s")
        if self.links_out:
            r.append("You followed links from it")
        if self.links_in:
            r.append("You reached it by following a link")
        return r


@dataclass
class Profile:
    user: str
    collection: str
    evidence: Dict[str, Evidence]
    affinity: Dict[str, float]                       # doc -> (-1, 1)
    query_docs: List[Tuple[str, str, float]]         # (query, doc, weight): queries that led to useful documents
    explored: Dict[str, float]                       # docs the user navigated from / to via links
    recent_queries: List[Tuple[str, float]]          # (query, decayed count)
    n_events: int
    version: str

    @property
    def empty(self) -> bool:
        return not self.affinity

    def positive(self, min_aff: float = 0.15) -> Dict[str, float]:
        return {d: a for d, a in self.affinity.items() if a >= min_aff}


def decay(ts: float, now: float, half_life_days: float = HALF_LIFE_DAYS) -> float:
    return 0.5 ** (max(0.0, now - ts) / 86400.0 / half_life_days)


def build_profile(user: str, collection: str, events: List[Dict], version: str = "",
                  now: Optional[float] = None, half_life_days: float = HALF_LIFE_DAYS) -> Profile:
    now = now or time.time()
    ev: Dict[str, Evidence] = defaultdict(Evidence)
    open_w: Dict[str, List[float]] = defaultdict(list)
    fb_latest: Dict[str, Tuple[float, float]] = {}
    query_docs: Counter = Counter()
    explored: Counter = Counter()
    queries: Counter = Counter()
    for e in events:
        w = decay(e["ts"], now, half_life_days)
        d, k = e["doc"], e["kind"]
        if k == "search":
            if e["query"].strip():
                queries[e["query"].strip()] += w
            continue
        if not d:
            continue
        x = ev[d]
        x.last = max(x.last, e["ts"])
        if k == "impression":
            x.impressions += 1
        elif k == "open":
            x.opens += 1
            open_w[d].append(w)
            if e["query"]:
                x.queries[e["query"]] += 1
        elif k == "dwell":
            s = float(e["value"])
            x.dwell += s
            x.raw += w * (W["dwell_long"] if s >= LONG_DWELL else W["dwell_mid"] if s >= SHORT_DWELL else W["dwell_short"])
            if e["query"] and s >= SHORT_DWELL:
                query_docs[(e["query"], d)] += w * (1.0 if s >= LONG_DWELL else 0.5)
        elif k == "link":
            x.links_out += 1
            x.raw += w * W["link_from"]
            explored[d] += w
            if e["to_doc"]:
                y = ev[e["to_doc"]]
                y.links_in += 1
                y.raw += w * W["link_to"]
                y.last = max(y.last, e["ts"])
                explored[e["to_doc"]] += w
        elif k == "feedback":
            if d not in fb_latest or e["ts"] >= fb_latest[d][0]:
                fb_latest[d] = (e["ts"], math.copysign(w, e["value"]) if e["value"] else 0.0)
            if e["query"] and e["value"] > 0:
                query_docs[(e["query"], d)] += w
    for d, ws in open_w.items():
        ev[d].raw += W["open"] * max(ws) + W["revisit"] * math.log1p(sum(ws[1:]) if len(ws) > 1 else 0)
    for d, (_, sgn) in fb_latest.items():          # only the latest judgement per document counts
        ev[d].raw += W["feedback"] * sgn
        ev[d].feedback = 1 if sgn > 0 else -1 if sgn < 0 else 0
    for _d, x in ev.items():
        if x.opens == 0 and x.links_in == 0 and x.feedback == 0:
            x.raw += W["skip"] * min(x.impressions // 2, 4)   # shown repeatedly, never chosen
    affinity = {d: math.tanh(x.raw / SCALE) for d, x in ev.items() if abs(x.raw) > 1e-6}
    return Profile(user, collection, dict(ev), affinity,
                   [(q, d, round(w, 4)) for (q, d), w in query_docs.most_common(300)],
                   dict(explored), queries.most_common(50), len(events), version)
