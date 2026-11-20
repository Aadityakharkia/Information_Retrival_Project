"""Search-as-you-type suggestions built from the index itself.

Sources, all derived from the collection or the user's own history (nothing hard-coded):
  completions  keyphrases, mined collocations and dictionary terms that start with what is typed
               (sorted arrays + binary search, so each keystroke costs O(log V + matches));
  titles       documents whose title words match the typed words (title-word prefix index);
  history      the user's own earlier queries (time-decayed);
  popular      queries run by at least k different users (k-anonymity: nobody's rare query leaks);
  related      conceptually related terms from the concept graph / term co-occurrence;
  correction   a spelling correction from the k-gram index when the last word is unknown.
"""
from __future__ import annotations

import bisect
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .text.preprocess import STOPWORDS, tokenize

_WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")


class Suggester:
    def __init__(self, engine):
        e = engine
        self.engine = e
        words = [(w, f) for w, f in e.kgram.freq.items() if len(w) > 2 and w not in STOPWORDS and w.isalpha()]
        words.sort()
        self.words, self.word_freq = [w for w, _ in words], [f for _, f in words]
        junk = {"ibid", "et", "al", "pp", "vol", "fig", "eq", "see"}
        ph = sorted((p.lower(), f) for p, f in e.phrases.items() if 1 < len(p.split()) <= 5 and len(p) <= 60
                    and not junk & set(p.lower().split()) and max(len(w) for w in p.split()) <= 18)
        self.phrases, self.phrase_freq = [p for p, _ in ph], [f for _, f in ph]
        tok: List[Tuple[str, int]] = []
        self.title_lower = []
        for i, d in enumerate(e.docs):
            t = d.display_title.lower()
            self.title_lower.append(t)
            for w in set(_WORD.findall(t)):
                if len(w) > 2 and w not in STOPWORDS:
                    tok.append((w, i))
        tok.sort()
        self.title_tok = [w for w, _ in tok]
        self.title_doc = [i for _, i in tok]

    @staticmethod
    def _range(arr: Sequence[str], prefix: str) -> Tuple[int, int]:
        lo = bisect.bisect_left(arr, prefix)
        hi = bisect.bisect_left(arr, prefix + "￿")
        return lo, hi

    def completions(self, p: str, k: int = 6) -> List[str]:
        """Phrase completions; when earlier words are typed, a candidate next word is scored by how often it
        actually follows them in the collection (positional index), not just by its own frequency."""
        e = self.engine
        head, _, last = p.rpartition(" ")
        out: Dict[str, float] = {}
        lo, hi = self._range(self.phrases, p)
        for i in range(lo, min(hi, lo + 400)):
            out[self.phrases[i]] = max(out.get(self.phrases[i], 0), self.phrase_freq[i] * 3.0)
        if len(last) >= 2:
            lo, hi = self._range(self.words, last)
            words = sorted(range(lo, min(hi, lo + 3000)), key=lambda i: -self.word_freq[i])[:40]
            prev = e.analyzer(head)[-1:] if head else []
            # stop words typed after the last content word ("peer to |") widen the allowed gap
            gap = 0
            for w in reversed(head.split()):
                if e.analyzer(w):
                    break
                gap += 1
            co_scores = {}
            for i in words:
                w = self.words[i]
                if w == last:
                    continue
                if prev:
                    t = e.analyzer.analyze_term(w)
                    co = len(e.index.phrase_match(prev + [t], slop=gap)) if t else 0
                    if co == 0:
                        continue
                    co_scores[i] = co
                    sc = co * 2.0 + self.word_freq[i] / 1e4      # ties (learn / learning) go to the commoner word
                else:
                    sc = self.word_freq[i] / 4.0
                key = f"{head} {w}".strip()
                out[key] = max(out.get(key, 0), sc)
            if head and prev:      # head + keyphrase, only if the phrase really follows the typed words somewhere
                lo, hi = self._range(self.phrases, last)
                for i in sorted(range(lo, min(hi, lo + 200)), key=lambda i: -self.phrase_freq[i])[:15]:
                    first = e.analyzer.analyze_term(self.phrases[i].split()[0])
                    if first and len(e.index.phrase_match(prev + [first], slop=gap)) >= 2:
                        key = f"{head} {self.phrases[i]}"
                        out[key] = max(out.get(key, 0), self.phrase_freq[i] * 1.0)
        res, stems = [], set()
        top = max(out.values(), default=0)
        out = {x: v for x, v in out.items() if v >= 0.05 * top or v >= 6}
        for x, _ in sorted(out.items(), key=lambda x: -x[1]):
            key = " ".join(e.analyzer(x)) or x            # one suggestion per stemmed form (network / networks)
            if x != p and key not in stems:
                stems.add(key)
                res.append(x)
            if len(res) == k:
                break
        return res

    def titles(self, p: str, k: int = 3) -> List[Dict]:
        words = [w for w in _WORD.findall(p) if w not in STOPWORDS]
        if not words or len(words[-1]) < 2 or (len(words) == 1 and len(words[0]) < 3):
            return []
        lo, hi = self._range(self.title_tok, words[-1])
        cands = {self.title_doc[i] for i in range(lo, min(hi, lo + 3000))}
        full = words[:-1]
        e = self.engine
        scored = []
        for d in cands:
            t = self.title_lower[d]
            if all(re.search(rf"\b{re.escape(w)}", t) for w in full) and d not in e.index.deleted:
                scored.append((-(float(e.pagerank[d]) + (1.0 if t.startswith(p) else 0.0) + 0.3 * len(full)), len(t), d))
        scored.sort()
        return [{"id": e.docs[d].doc_id, "title": e.docs[d].display_title} for _, _, d in scored[:k]]

    def related(self, p: str, k: int = 4) -> List[str]:
        """Conceptually related terms for the (completed) query from the concept graph and term co-occurrence."""
        e = self.engine
        words = [w for w in tokenize(p) if w not in STOPWORDS]
        if not words or e.kgram.freq.get(words[-1], 0) < 3:
            return []
        out: List[str] = []
        if e.kg:
            out += [n.lower() for n, _ in e.kg.expansion_terms(" ".join(words), k=k)]
        if len(out) < 2:
            for t in e.analyzer(" ".join(words))[-2:]:
                for n, _ in e.thesaurus.neighbours(t, 4):
                    w = e.surface.get(n, n)
                    if w.isalpha() and len(w) > 3 and w not in STOPWORDS and e.index.df(n) >= 3:
                        out.append(w)
        typed = set(words) | {e.analyzer.analyze_term(w) for w in words}
        res = []
        for x in out:
            if x not in res and not set(x.split()) <= typed and e.analyzer.analyze_term(x.split()[-1]) not in typed:
                res.append(x)
        return res[:k]

    def suggest(self, prefix: str, history: Sequence[Tuple[str, float]] = (), popular: Optional[Dict[str, int]] = None,
                k: int = 6) -> Dict:
        p = " ".join(tokenize(prefix)) if prefix.strip() else ""
        if prefix.endswith(" ") and p:
            p += " "
        p = p.lower()
        if len(p.strip()) < 2:
            hist = [q for q, _ in history[:5]]
            return {"query": prefix, "completions": [], "history": hist, "popular": [], "titles": [], "related": [], "correction": None}
        ps = p.strip()
        hist = [q for q, _ in sorted(history, key=lambda x: -x[1]) if q.lower().startswith(ps) and q.lower() != ps][:3]
        pop = [q for q, n in sorted((popular or {}).items(), key=lambda x: -x[1])
               if q.startswith(ps) and q != ps and q not in {h.lower() for h in hist}][:3]
        comp = [c for c in self.completions(ps, k + 3) if c not in {h.lower() for h in hist} | set(pop)][:k]
        correction = None
        last = ps.split()[-1]
        if not comp and len(last) >= 4 and last not in self.engine.kgram.freq:
            fixes = self.engine.kgram.suggest(last)
            if fixes:
                correction = (ps.rpartition(" ")[0] + " " + fixes[0][0]).strip()
        return {"query": prefix, "completions": comp, "history": hist, "popular": pop,
                "titles": self.titles(ps), "related": self.related(comp[0] if comp and comp[0].startswith(ps) else ps),
                "correction": correction}
