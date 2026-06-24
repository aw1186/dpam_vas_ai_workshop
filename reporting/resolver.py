"""Fuzzy fund / share-class name resolution for FundLink.

Maps a free-text fund mention (possibly partial or approximate) to the closest
real share class or sub-fund in EDW_PL.D_SHARE_CLASS, so natural-language
questions don't need the exact official name.

Uses rapidfuzz token-set matching, which handles word-subset mentions well
(e.g. "emerging markets sustainable" -> "DPAM L BONDS EMERGING MARKETS SUSTAINABLE").
"""
from __future__ import annotations

import time

from rapidfuzz import fuzz, process, utils

from . import fundlink

_CACHE = {"ts": 0.0, "catalog": None}
_TTL = 3600  # seconds; share-class names change rarely


def _load_catalog():
    sql = (
        "SELECT D_SHC_SHARECLASS_ISIN, D_SHC_SHARECLASS_NM, D_SHC_DSBF_NM "
        "FROM EDW_PL.D_SHARE_CLASS "
        "WHERE D_SHC_ACTIVE_FLAG = 'Y' AND D_SHC_SHARECLASS_ISIN IS NOT NULL"
    )
    with fundlink.get_connection() as conn:
        conn.call_timeout = 30000
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    shareclasses = []          # list of (name, isin, subfund)
    subfunds = {}              # subfund name -> a sample isin
    isins = {}                 # ISIN (upper) -> (scname, sfname, isin)
    for isin, scname, sfname in rows:
        if scname:
            shareclasses.append((scname, isin, sfname))
        if isin:
            isins[isin.upper()] = (scname, sfname, isin)
        if sfname and sfname not in subfunds:
            subfunds[sfname] = isin

    return {
        "shareclasses": shareclasses,
        "subfunds": list(subfunds.items()),  # (name, sample_isin)
        "isins": isins,
    }


def _catalog():
    now = time.time()
    if _CACHE["catalog"] is None or now - _CACHE["ts"] > _TTL:
        _CACHE["catalog"] = _load_catalog()
        _CACHE["ts"] = now
    return _CACHE["catalog"]


def resolve(mention, limit=5):
    """Return the best fund matches for a free-text mention.

    Each result: {kind, name, isin, subfund, score}.
    kind is 'isin', 'shareclass' or 'subfund'. Sorted by score desc.
    """
    mention = (mention or "").strip()
    if not mention:
        return []
    cat = _catalog()

    # Exact ISIN hit short-circuits everything.
    up = mention.upper().replace(" ", "")
    if up in cat["isins"]:
        scname, sfname, isin = cat["isins"][up]
        return [{
            "kind": "isin", "name": scname or sfname, "isin": isin,
            "subfund": sfname, "score": 100.0,
        }]

    results = []

    sc_names = [n for n, _, _ in cat["shareclasses"]]
    for name, score, idx in process.extract(
        mention, sc_names, scorer=fuzz.token_set_ratio,
        processor=utils.default_process, limit=limit
    ):
        _, isin, sfname = cat["shareclasses"][idx]
        results.append({
            "kind": "shareclass", "name": name, "isin": isin,
            "subfund": sfname, "score": float(score),
        })

    sf_names = [n for n, _ in cat["subfunds"]]
    for name, score, idx in process.extract(
        mention, sf_names, scorer=fuzz.token_set_ratio,
        processor=utils.default_process, limit=limit
    ):
        isin = cat["subfunds"][idx][1]
        results.append({
            "kind": "subfund", "name": name, "isin": isin,
            "subfund": name, "score": float(score),
        })

    results.sort(key=lambda r: r["score"], reverse=True)

    seen, uniq = set(), []
    for r in results:
        key = (r["kind"], r["name"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq[:limit]


def best(mention, threshold=70):
    """Return the single best match above ``threshold`` (0-100), or None."""
    matches = resolve(mention, limit=1)
    if matches and matches[0]["score"] >= threshold:
        return matches[0]
    return None
