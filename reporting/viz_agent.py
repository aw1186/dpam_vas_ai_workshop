"""Visualization agents for natural-language query results.

Two cooperating agents:
- ``advise`` (chart-advisor agent): inspects the result shape and decides
  whether a chart is appropriate and which type/axes to use. LLM-driven with a
  deterministic heuristic fallback.
- ``build_chart`` (visualization agent): turns the advisor's spec into a ready
  Chart.js config (including colours), or returns None if not chartable.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

# A pleasant, color-blind-friendly palette.
PALETTE = [
    "#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed",
    "#0891b2", "#db2777", "#65a30d", "#ea580c", "#4f46e5",
    "#0d9488", "#9333ea", "#ca8a04", "#e11d48", "#059669",
]


def _is_number(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _numeric_flags(columns, rows):
    flags = [True] * len(columns)
    seen = [False] * len(columns)
    for r in rows:
        for i, v in enumerate(r):
            if v == "" or v is None:
                continue
            seen[i] = True
            if not _is_number(v):
                flags[i] = False
    # A column with no values seen is not considered numeric.
    return [flags[i] and seen[i] for i in range(len(columns))]


def _looks_like_date(name):
    return bool(re.search(r"date|period|month|year|day", name, re.IGNORECASE))


def _heuristic(question, columns, rows):
    """Deterministic fallback decision."""
    n = len(columns)
    if n < 2 or len(rows) < 2:
        return {"visualize": False, "reason": "Too few columns/rows to chart."}

    numeric = _numeric_flags(columns, rows)
    num_idx = [i for i, f in enumerate(numeric) if f]
    cat_idx = [i for i, f in enumerate(numeric) if not f]
    if not num_idx or not cat_idx:
        return {"visualize": False, "reason": "Need one category + one numeric column."}

    x = columns[cat_idx[0]]
    ys = [columns[i] for i in num_idx]

    if _looks_like_date(x):
        ctype = "line"
    elif len(rows) <= 8 and len(ys) == 1:
        ctype = "pie"
    else:
        ctype = "bar"

    return {
        "visualize": True,
        "chart_type": ctype,
        "x": x,
        "y": ys[:3],
        "title": question.strip().rstrip("?") or "Result",
        "reason": "Heuristic: categorical x with numeric measure(s).",
    }


def _llm_advise(question, columns, rows):
    """Ask the LLM for a chart spec. Returns dict or None on any failure."""
    try:
        from . import nl2sql  # lazy import to avoid circular import

        numeric = _numeric_flags(columns, rows)
        schema = [
            {"name": c, "numeric": bool(numeric[i])}
            for i, c in enumerate(columns)
        ]
        sample = rows[:5]
        sys = (
            "You are a data-visualization advisor. Given a query result schema "
            "and a sample, decide if a chart helps and how to draw it.\n"
            "Return ONLY JSON with keys: visualize (bool), chart_type "
            "('bar'|'line'|'pie'|'doughnut'), x (column name for labels), "
            "y (list of numeric column names), title (string), reason (string).\n"
            "Rules: use a categorical/date column for x and numeric column(s) "
            "for y. Use 'line' for time series, 'pie'/'doughnut' only for a "
            "single measure with few (<=8) categories that look like shares. "
            "If the result is a single value, free text, or not meaningful to "
            "chart, set visualize=false."
        )
        payload = {
            "question": question,
            "columns": schema,
            "row_count": len(rows),
            "sample_rows": sample,
        }
        cfg = nl2sql._llm_config()
        resp = nl2sql._client().chat.completions.create(
            model=cfg["model"],
            temperature=0,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        )
        spec = nl2sql._extract_json(resp.choices[0].message.content or "")
        if isinstance(spec, dict) and "visualize" in spec:
            return spec
    except Exception:
        pass
    return None


def advise(question, columns, rows):
    """Chart-advisor agent: decide whether and how to visualize."""
    if not columns or not rows:
        return {"visualize": False, "reason": "No tabular result."}
    spec = _llm_advise(question, columns, rows)
    if spec is None:
        spec = _heuristic(question, columns, rows)
    return spec


def build_chart(spec, columns, rows):
    """Visualization agent: produce a Chart.js config dict, or None."""
    if not spec or not spec.get("visualize"):
        return None

    col_idx = {c: i for i, c in enumerate(columns)}
    x = spec.get("x")
    ys = spec.get("y") or []
    if isinstance(ys, str):
        ys = [ys]
    ys = [y for y in ys if y in col_idx]
    if x not in col_idx or not ys:
        return None

    # Cap points so charts stay readable.
    rows = rows[:40]
    xi = col_idx[x]
    labels = [str(r[xi]) for r in rows]

    ctype = spec.get("chart_type", "bar")
    if ctype not in ("bar", "line", "pie", "doughnut"):
        ctype = "bar"

    datasets = []
    if ctype in ("pie", "doughnut"):
        yi = col_idx[ys[0]]
        data = [_to_float(r[yi]) for r in rows]
        colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
        datasets.append({
            "label": ys[0],
            "data": data,
            "backgroundColor": colors,
            "borderColor": "#ffffff",
            "borderWidth": 1,
        })
    else:
        for j, y in enumerate(ys[:4]):
            yi = col_idx[y]
            data = [_to_float(r[yi]) for r in rows]
            color = PALETTE[j % len(PALETTE)]
            datasets.append({
                "label": y,
                "data": data,
                "backgroundColor": color if ctype == "bar" else "transparent",
                "borderColor": color,
                "borderWidth": 2,
                "fill": False,
                "tension": 0.25,
            })

    if not datasets or all(all(v is None for v in d["data"]) for d in datasets):
        return None

    return {
        "type": ctype,
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "responsive": True,
            "plugins": {
                "legend": {"display": ctype in ("pie", "doughnut") or len(datasets) > 1},
                "title": {"display": bool(spec.get("title")), "text": spec.get("title", "")},
            },
        },
    }
