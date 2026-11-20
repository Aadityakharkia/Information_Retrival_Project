"""Index compression (Syllabus Module 3, IIR Ch. 5).

* Gap (d-gap) encoding of docID lists
* Variable-Byte (VB) codes
* Elias gamma and delta codes
* Dictionary-as-a-string with front coding (lexicon compression)
* A report comparing raw vs compressed postings size
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


# ---------------------------------------------------------------- gaps
def to_gaps(sorted_ids: List[int]) -> List[int]:
    return [sorted_ids[0]] + [b - a for a, b in zip(sorted_ids, sorted_ids[1:])] if sorted_ids else []


def from_gaps(gaps: List[int]) -> List[int]:
    out, acc = [], 0
    for g in gaps:
        acc += g
        out.append(acc)
    return out


# ---------------------------------------------------------------- variable byte
def vb_encode_number(n: int) -> bytes:
    out = []
    while True:
        out.insert(0, n % 128)
        if n < 128:
            break
        n //= 128
    out[-1] += 128  # continuation bit marks the last byte
    return bytes(out)


def vb_encode(nums: Iterable[int]) -> bytes:
    return b"".join(vb_encode_number(n) for n in nums)


def vb_decode(stream: bytes) -> List[int]:
    nums, n = [], 0
    for byte in stream:
        if byte < 128:
            n = 128 * n + byte
        else:
            nums.append(128 * n + byte - 128)
            n = 0
    return nums


# ---------------------------------------------------------------- Elias gamma / delta (bit strings)
def gamma_encode_number(n: int) -> str:
    """Gamma code for n >= 1: unary(len(offset)) + offset."""
    if n < 1:
        raise ValueError("gamma code defined for n >= 1")
    offset = bin(n)[3:]
    return "1" * len(offset) + "0" + offset


def gamma_encode(nums: Iterable[int]) -> str:
    return "".join(gamma_encode_number(n + 1) for n in nums)  # +1 so 0-gaps are encodable


def gamma_decode(bits: str) -> List[int]:
    out, i = [], 0
    while i < len(bits):
        length = 0
        while bits[i] == "1":
            length += 1
            i += 1
        i += 1
        offset = bits[i:i + length]
        i += length
        out.append(int("1" + offset, 2) - 1)
    return out


def delta_encode_number(n: int) -> str:
    offset = bin(n)[3:]
    return gamma_encode_number(len(offset) + 1) + offset


def delta_encode(nums: Iterable[int]) -> str:
    return "".join(delta_encode_number(n + 1) for n in nums)


# ---------------------------------------------------------------- lexicon: front coding
def front_code(sorted_terms: List[str], block: int = 4) -> List[str]:
    """Blocked front coding (IIR §5.2.2). e.g. 8automat*a1e2ic3ion"""
    out = []
    for i in range(0, len(sorted_terms), block):
        blk = sorted_terms[i:i + block]
        prefix = blk[0]
        for t in blk[1:]:
            while not t.startswith(prefix):
                prefix = prefix[:-1]
        enc = f"{len(blk[0])}{prefix}*{blk[0][len(prefix):]}"
        for t in blk[1:]:
            suf = t[len(prefix):]
            enc += f"{len(suf)}◊{suf}"
        out.append(enc)
    return out


# ---------------------------------------------------------------- report
@dataclass
class CompressionReport:
    raw_bytes: int
    vb_bytes: int
    gamma_bytes: int
    delta_bytes: int
    dict_raw_bytes: int
    dict_front_coded_bytes: int

    def as_rows(self) -> List[Tuple[str, int, float]]:
        r = self.raw_bytes
        return [("Postings, uncompressed (4-byte ints)", r, 1.0),
                ("Postings, gaps + Variable-Byte", self.vb_bytes, self.vb_bytes / r),
                ("Postings, gaps + Elias-gamma", self.gamma_bytes, self.gamma_bytes / r),
                ("Postings, gaps + Elias-delta", self.delta_bytes, self.delta_bytes / r),
                ("Dictionary, fixed-width 20B/term", self.dict_raw_bytes, 1.0),
                ("Dictionary, blocked front-coding", self.dict_front_coded_bytes,
                 self.dict_front_coded_bytes / self.dict_raw_bytes)]


def compression_report(postings: Dict[str, Dict[int, List[int]]]) -> CompressionReport:
    raw = vb = gam = dlt = 0
    for plist in postings.values():
        ids = sorted(plist)
        gaps = to_gaps(ids)
        raw += 4 * len(ids)
        vb += len(vb_encode(gaps))
        gam += (len(gamma_encode(gaps)) + 7) // 8
        dlt += (len(delta_encode(gaps)) + 7) // 8
    terms = sorted(postings)
    fc = sum(len(s.encode()) for s in front_code(terms))
    return CompressionReport(raw, vb, gam, dlt, 20 * len(terms), fc)
