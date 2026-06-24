"""Natural-language -> Oracle SQL for FundLink.

Uses an OpenAI-compatible chat endpoint (configured in config.ini [llm]) to
translate an English question into a single read-only Oracle SELECT against the
accessible FundLink views, then runs it through the SELECT-only guard in
``fundlink.run_query``.

This is independent of the RDF/SPARQL layer: it produces SQL, not SPARQL.
"""
from __future__ import annotations

import configparser
import re
from functools import lru_cache

import httpx
from openai import OpenAI

from . import fundlink

# Curated schema shown to the model. Only accessible objects are listed so the
# model never invents tables it cannot read.
SCHEMA_PROMPT = r"""
You are an expert Oracle SQL generator for a fund-reporting data warehouse.
Translate the user's question into ONE valid Oracle SELECT statement.

================ ACCESSIBLE OBJECTS (use fully-qualified names) ================

1) EDW_PL.D_SHARE_CLASS  -- one row per share class (SCD history kept)
   PRIMARY KEY-ish: D_SHC_SHARECLASS_ISIN
   Filter D_SHC_ACTIVE_FLAG = 'Y' to get the CURRENT version (else you get duplicates).
   Columns you may use:
     D_SHC_SHARECLASS_ISIN          ISIN code, e.g. 'LU1518617417'
     D_SHC_SHARECLASS_NM            Share class name
     D_SHC_CLASS                    Share class letter/code (e.g. 'N','B')
     D_SHC_CURRENCYISO_CODE         Currency ISO code: EUR, USD, CHF, GBP, JPY
     D_SHC_STATUS                   Status text
     D_SHC_ACTIVE_FLAG              'Y' current, 'N' historical
     D_SHC_SHARECLASS_HEDGED_FLAG   '1' hedged, '0' not
     D_SHC_DISTRIBUTION_POLICY      distribution policy
     D_SHC_DSBF_NM                  SUB-FUND name  (join key to positions, see below)
     D_SHC_DSBF_NFDB_NM             sub-fund name (alt spelling)
     D_SHC_DSBF_CODE                sub-fund code (FundLink code; NOT the positions code)
     D_SHC_DSBF_ASSETFOCUSCLASS_NM  asset class: Bonds, Equity, Balanced, Fof, ...
     D_SHC_DSBF_DPAMASSETCLASS_NM   finer asset class (e.g. 'High Yield Bonds')
     D_SHC_DSBF_MANAGER             manager name
     D_SHC_DSBF_BACKUPMANAGER       backup manager
     D_SHC_DSBF_UCITS_FLAG          '1' UCITS, '0' not
     D_SHC_DSBF_ESG_ARTICLE         SFDR/ESG article classification (often NULL)
     D_SHC_MORNINGSTAR_RATING       morningstar rating
     D_SHC_DUMF_NM                  umbrella fund name
     D_SHC_DUMF_COUNTRYISO_CODE     domicile country ISO code
     D_SHC_DUMF_CURRENCYISO_CODE    umbrella currency
     D_SHC_DBCM_BENCHMARK_NM        benchmark name

2) EDW_PL.D_SUBFUND        -- sub-fund master (columns prefixed D_SBF_*)
3) EDW_PL.D_UMBRELLA_FUND  -- umbrella fund master (columns prefixed D_UMF_*)

4) EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION  -- HOLDINGS / POSITIONS (for EXPOSURE)
   *** VERY LARGE TABLE (tens of millions of rows). ***
   You MUST always include: LOAD_END_DATE > DATE '2999-01-01'  (selects current records)
   You MUST always restrict to a single sub-fund AND its latest VALUATION_DATE.
   Grain: one row per instrument held, per sub-fund, per valuation date.
   Columns you may use:
     SUBFUND_LONGNAME             sub-fund name  <-- JOIN to D_SHC_DSBF_NM
     SUBFUND_CODE                 DPAS accounting code (different from D_SHC_DSBF_CODE; do NOT join on it)
     FUND_LONGNAME, FUND_CODE     parent fund
     VALUATION_DATE               position date
     ISIN                         instrument ISIN (the holding, not the share class)
     INSTR_LONG_NAME              instrument name
     ISSUER_LONGNAME              issuer name
     GEO_SECT_CDE                 2-letter ISO COUNTRY of the holding (BR=Brazil, US, DE, KR, IN, ...)
     SECTOR, INDUSTRY             classification
     CATEGORY_2                   instrument type (OBLIG=bond, ...)
     RATING                       credit rating
     MARKET_VALUE                 absolute market value
     MARKET_VALUE_NAV_PERCENTAGE  raw weight vs NAV (does NOT sum to 100 -> always normalize)
     CURRENCY: INSTR_EVALUATION_CCY, SUBFUND_CCY, FUND_CCY

============================= JOIN GUIDANCE =============================
- Positions are at SUB-FUND level. A SHARE CLASS inherits its sub-fund's exposure.
- Resolve a share class to its sub-fund via D_SHARE_CLASS, then join to positions
  on NAME:  UPPER(p.SUBFUND_LONGNAME) = UPPER(s.D_SHC_DSBF_NM)
  (Do NOT join on codes; the two systems use different code schemes.)
- "Latest" positions = the MAX(VALUATION_DATE) for that sub-fund among current rows.

========================= EXPOSURE (normalized) =========================
MARKET_VALUE_NAV_PERCENTAGE is a raw figure; ALWAYS express exposure as a share:
    100 * SUM(weight for the group) / SUM(weight for the whole sub-fund snapshot)
Use a WITH/CTE so the latest valuation date is computed once.

============================== ORACLE RULES ==============================
- Output ONE SELECT only. No prose, no markdown fences, no trailing semicolon.
- Use FETCH FIRST n ROWS ONLY for row limits (NEVER LIMIT, NEVER TOP).
- Default to current rows (D_SHC_ACTIVE_FLAG='Y'; LOAD_END_DATE > DATE '2999-01-01').
- Cap non-aggregate result sets with FETCH FIRST 100 ROWS ONLY.
- Match text case-insensitively with UPPER(col) LIKE '%'||UPPER('term')||'%' when the
  user gives a partial name/country word; map country WORDS to ISO codes
  (Brazil->BR, United States/US->US, Germany->DE, China->CN, India->IN, etc.).
- NEVER write INSERT/UPDATE/DELETE/MERGE/DDL.
"""


@lru_cache(maxsize=1)
def _llm_config():
    config = configparser.ConfigParser()
    config.read(fundlink.CONFIG_PATH)
    return {
        "api_key": config.get("llm", "api_key"),
        "base_url": config.get("llm", "base_url"),
        "model": config.get("llm", "model", fallback="gpt-4.1-mini"),
        "ca_bundle": config.get("llm", "ca_bundle", fallback="").strip(),
        "verify": config.getboolean("llm", "verify", fallback=True),
    }


@lru_cache(maxsize=1)
def _client():
    cfg = _llm_config()
    # TLS verification: prefer an explicit CA bundle, else honour verify flag.
    if cfg["ca_bundle"]:
        verify = cfg["ca_bundle"]
    else:
        verify = cfg["verify"]
    http_client = httpx.Client(verify=verify, timeout=60)
    return OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        http_client=http_client,
    )


def _strip_sql(text: str) -> str:
    """Remove markdown fences / stray prose, keep the SELECT statement."""
    text = text.strip()
    # Drop ```sql ... ``` fences if present.
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    # Keep from the first SELECT / WITH onward.
    match = re.search(r"\b(with|select)\b", text, re.IGNORECASE)
    if match:
        text = text[match.start():]
    return text.strip().rstrip(";").strip()


# Few-shot examples teach the model the exact patterns (esp. exposure).
FEWSHOT = [
    (
        "How many active share classes are there per currency?",
        "SELECT D_SHC_CURRENCYISO_CODE, COUNT(*) AS SHARE_CLASS_COUNT\n"
        "FROM EDW_PL.D_SHARE_CLASS\n"
        "WHERE D_SHC_ACTIVE_FLAG = 'Y'\n"
        "GROUP BY D_SHC_CURRENCYISO_CODE\n"
        "ORDER BY SHARE_CLASS_COUNT DESC",
    ),
    (
        "List 5 active equity share classes with their ISIN and name",
        "SELECT D_SHC_SHARECLASS_ISIN, D_SHC_SHARECLASS_NM\n"
        "FROM EDW_PL.D_SHARE_CLASS\n"
        "WHERE D_SHC_ACTIVE_FLAG = 'Y'\n"
        "  AND UPPER(D_SHC_DSBF_ASSETFOCUSCLASS_NM) = 'EQUITY'\n"
        "FETCH FIRST 5 ROWS ONLY",
    ),
    (
        "What is the country exposure of share class LU1874836205?",
        "WITH sc AS (\n"
        "  SELECT D_SHC_DSBF_NM AS subfund_name\n"
        "  FROM EDW_PL.D_SHARE_CLASS\n"
        "  WHERE D_SHC_SHARECLASS_ISIN = 'LU1874836205' AND D_SHC_ACTIVE_FLAG = 'Y'\n"
        "  FETCH FIRST 1 ROWS ONLY\n"
        "),\n"
        "pos AS (\n"
        "  SELECT p.GEO_SECT_CDE AS country, p.MARKET_VALUE_NAV_PERCENTAGE AS mv\n"
        "  FROM EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION p\n"
        "  JOIN sc ON UPPER(p.SUBFUND_LONGNAME) = UPPER(sc.subfund_name)\n"
        "  WHERE p.LOAD_END_DATE > DATE '2999-01-01'\n"
        "    AND p.VALUATION_DATE = (\n"
        "      SELECT MAX(p2.VALUATION_DATE) FROM EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION p2\n"
        "      JOIN sc ON UPPER(p2.SUBFUND_LONGNAME) = UPPER(sc.subfund_name)\n"
        "      WHERE p2.LOAD_END_DATE > DATE '2999-01-01'\n"
        "    )\n"
        ")\n"
        "SELECT country,\n"
        "       ROUND(100 * SUM(mv) / NULLIF((SELECT SUM(mv) FROM pos), 0), 2) AS pct_exposure\n"
        "FROM pos\n"
        "GROUP BY country\n"
        "ORDER BY pct_exposure DESC\n"
        "FETCH FIRST 25 ROWS ONLY",
    ),
    (
        "What is the exposure of share class LU1874836205 to Brazil?",
        "WITH sc AS (\n"
        "  SELECT D_SHC_DSBF_NM AS subfund_name\n"
        "  FROM EDW_PL.D_SHARE_CLASS\n"
        "  WHERE D_SHC_SHARECLASS_ISIN = 'LU1874836205' AND D_SHC_ACTIVE_FLAG = 'Y'\n"
        "  FETCH FIRST 1 ROWS ONLY\n"
        "),\n"
        "pos AS (\n"
        "  SELECT p.GEO_SECT_CDE AS country, p.MARKET_VALUE_NAV_PERCENTAGE AS mv\n"
        "  FROM EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION p\n"
        "  JOIN sc ON UPPER(p.SUBFUND_LONGNAME) = UPPER(sc.subfund_name)\n"
        "  WHERE p.LOAD_END_DATE > DATE '2999-01-01'\n"
        "    AND p.VALUATION_DATE = (\n"
        "      SELECT MAX(p2.VALUATION_DATE) FROM EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION p2\n"
        "      JOIN sc ON UPPER(p2.SUBFUND_LONGNAME) = UPPER(sc.subfund_name)\n"
        "      WHERE p2.LOAD_END_DATE > DATE '2999-01-01'\n"
        "    )\n"
        ")\n"
        "SELECT ROUND(100 * SUM(CASE WHEN country = 'BR' THEN mv ELSE 0 END)\n"
        "             / NULLIF(SUM(mv), 0), 2) AS brazil_pct_exposure\n"
        "FROM pos",
    ),
    (
        "Top 10 holdings of the DPAM L Bonds Emerging Markets Sustainable sub-fund",
        "WITH latest AS (\n"
        "  SELECT MAX(p.VALUATION_DATE) AS vd\n"
        "  FROM EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION p\n"
        "  WHERE p.LOAD_END_DATE > DATE '2999-01-01'\n"
        "    AND UPPER(p.SUBFUND_LONGNAME) = UPPER('DPAM L BONDS EMERGING MARKETS SUSTAINABLE')\n"
        ")\n"
        "SELECT p.INSTR_LONG_NAME, p.ISIN, p.GEO_SECT_CDE, p.RATING,\n"
        "       ROUND(p.MARKET_VALUE_NAV_PERCENTAGE, 4) AS weight\n"
        "FROM EDW_FL.SAT_FUNDDATA_DPASPOS_POSITION p, latest\n"
        "WHERE p.LOAD_END_DATE > DATE '2999-01-01'\n"
        "  AND UPPER(p.SUBFUND_LONGNAME) = UPPER('DPAM L BONDS EMERGING MARKETS SUSTAINABLE')\n"
        "  AND p.VALUATION_DATE = latest.vd\n"
        "ORDER BY p.MARKET_VALUE_NAV_PERCENTAGE DESC\n"
        "FETCH FIRST 10 ROWS ONLY",
    ),
]


def generate_sql(question: str) -> str:
    """Translate a natural-language question into an Oracle SELECT."""
    cfg = _llm_config()
    messages = [{"role": "system", "content": SCHEMA_PROMPT}]
    for q, a in FEWSHOT:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})

    resp = _client().chat.completions.create(
        model=cfg["model"],
        temperature=0,
        messages=messages,
    )
    return _strip_sql(resp.choices[0].message.content or "")


def ask(question: str):
    """Full pipeline: NL -> SQL -> result.

    Returns a dict: {sql, columns, rows, error}. ``sql`` is always populated so
    the UI can show what was generated even if execution fails.
    """
    out = {"sql": "", "columns": None, "rows": None, "error": None}
    try:
        out["sql"] = generate_sql(question)
    except Exception as exc:
        out["error"] = f"LLM error: {exc}"
        return out

    if not out["sql"]:
        out["error"] = "The model did not return a SQL statement."
        return out

    try:
        columns, raw_rows = fundlink.run_query(out["sql"])
        out["columns"] = columns
        out["rows"] = [[("" if v is None else v) for v in r] for r in raw_rows]
    except Exception as exc:
        out["error"] = f"SQL error: {exc}"
    return out
