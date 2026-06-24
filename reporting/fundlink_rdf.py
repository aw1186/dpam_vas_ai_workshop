"""Relational -> RDF -> SPARQL bridge for FundLink.

SPARQL cannot run against Oracle relational tables directly, so this module:

  1. Pulls rows from the accessible view EDW_PL.D_SHARE_CLASS via oracledb.
  2. Materialises each row as RDF triples in an in-memory rdflib Graph,
     using a small FundLink ontology (the "RDF" model).
  3. Lets you run SPARQL (SELECT / ASK) over that graph, including
     validation rules ("RM" = risk/monitoring rules expressed in SPARQL).

The column -> predicate map below is the metadata-driven mapping used to
turn the wide share-class view into clean RDF.
"""
from __future__ import annotations

from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import RDFS, XSD

from . import fundlink

# --- Ontology / vocabulary --------------------------------------------------
FL = Namespace("https://fundlink.dp/ont#")
RES = Namespace("https://fundlink.dp/id/shareclass/")

# Map a curated subset of the 82 columns -> RDF predicates.
# (column_name, predicate_localname)
COLUMN_PREDICATES = [
    ("D_SHC_SHARECLASS_ISIN", "isin"),
    ("D_SHC_SHARECLASS_NM", "name"),
    ("D_SHC_CLASS", "shareClass"),
    ("D_SHC_CURRENCYISO_CODE", "currency"),
    ("D_SHC_STATUS", "status"),
    ("D_SHC_ACTIVE_FLAG", "activeFlag"),
    ("D_SHC_SHARECLASS_HEDGED_FLAG", "hedgedFlag"),
    ("D_SHC_DSBF_NM", "subFundName"),
    ("D_SHC_DSBF_ASSETFOCUSCLASS_NM", "assetClass"),
    ("D_SHC_DSBF_MANAGER", "manager"),
    ("D_SHC_DSBF_UCITS_FLAG", "ucitsFlag"),
    ("D_SHC_DSBF_ESG_ARTICLE", "esgArticle"),
    ("D_SHC_DUMF_NM", "umbrellaFund"),
    ("D_SHC_DUMF_COUNTRYISO_CODE", "domicile"),
]

SELECT_COLS = ["D_SHC_PK"] + [c for c, _ in COLUMN_PREDICATES]


def fetch_rows(limit: int = 500, active_only: bool = True):
    """Fetch share-class rows from the accessible Oracle view."""
    cols = ", ".join(SELECT_COLS)
    sql = f"SELECT {cols} FROM EDW_PL.D_SHARE_CLASS"
    if active_only:
        sql += " WHERE D_SHC_ACTIVE_FLAG = 'Y'"
    sql += f" FETCH FIRST {int(limit)} ROWS ONLY"

    with fundlink.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            names = [c[0] for c in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]


def build_graph(rows) -> Graph:
    """Convert relational rows into an RDF graph."""
    g = Graph()
    g.bind("fl", FL)
    g.bind("rdfs", RDFS)

    # Declare the class once.
    g.add((FL.ShareClass, RDF.type, RDFS.Class))

    for row in rows:
        pk = row.get("D_SHC_PK")
        isin = row.get("D_SHC_SHARECLASS_ISIN")
        subject = RES[isin] if isin else RES[pk]

        g.add((subject, RDF.type, FL.ShareClass))
        if isin:
            g.add((subject, RDFS.label, Literal(isin)))

        for col, pred in COLUMN_PREDICATES:
            val = row.get(col)
            if val is None or val == "":
                continue
            g.add((subject, FL[pred], Literal(val, datatype=XSD.string)))
    return g


def run_sparql(graph: Graph, query: str):
    """Run a SPARQL query and return (columns, rows) for SELECT,
    or (['result'], [[bool]]) for ASK."""
    result = graph.query(query)
    if result.type == "ASK":
        return ["result"], [[bool(result.askAnswer)]]
    columns = [str(v) for v in result.vars]
    rows = [[None if cell is None else str(cell) for cell in row] for row in result]
    return columns, rows


def load(limit: int = 500, active_only: bool = True) -> Graph:
    """Convenience: fetch + build the RDF graph in one call."""
    return build_graph(fetch_rows(limit=limit, active_only=active_only))


# --- RM (risk/monitoring) rules expressed as SPARQL -------------------------
# Each rule's SPARQL SELECT must return a ?isin column listing the share
# classes that VIOLATE the rule. ``severity`` maps to a Control status.
RULE_DEFS = [
    {
        "id": "rdf_missing_name",
        "name": "Share class name present",
        "descr": "Active share class is missing a name.",
        "severity": "fail",
        "sparql": """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?isin WHERE {
  ?sc a fl:ShareClass ; fl:isin ?isin .
  FILTER NOT EXISTS { ?sc fl:name ?n }
}
""",
    },
    {
        "id": "rdf_missing_esg",
        "name": "ESG article classified",
        "descr": "Share class has no SFDR/ESG article classification.",
        "severity": "warn",
        "sparql": """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?isin WHERE {
  ?sc a fl:ShareClass ; fl:isin ?isin .
  FILTER NOT EXISTS { ?sc fl:esgArticle ?a }
}
""",
    },
    {
        "id": "rdf_missing_currency",
        "name": "Currency populated",
        "descr": "Share class is missing its ISO currency.",
        "severity": "fail",
        "sparql": """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?isin WHERE {
  ?sc a fl:ShareClass ; fl:isin ?isin .
  FILTER NOT EXISTS { ?sc fl:currency ?c }
}
""",
    },
    {
        "id": "rdf_missing_assetclass",
        "name": "Asset class assigned",
        "descr": "Share class has no asset focus class.",
        "severity": "warn",
        "sparql": """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?isin WHERE {
  ?sc a fl:ShareClass ; fl:isin ?isin .
  FILTER NOT EXISTS { ?sc fl:assetClass ?a }
}
""",
    },
]


def run_rules(graph: Graph):
    """Run every RM rule and return a list of result dicts.

    Each entry: {id, name, descr, severity, violations: set(isin)}.
    """
    results = []
    for rule in RULE_DEFS:
        _, rows = run_sparql(graph, rule["sparql"])
        violations = {r[0] for r in rows if r and r[0]}
        results.append({**rule, "violations": violations})
    return results

