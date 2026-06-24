"""Demo: build an RDF graph from FundLink and query it with SPARQL.

Run:  python -m reporting.sparql_demo   (from the project root)
"""
from reporting import fundlink_rdf

# A SPARQL SELECT: share classes grouped data.
Q_SELECT = """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?isin ?name ?currency ?assetClass ?esgArticle
WHERE {
  ?sc a fl:ShareClass ;
      fl:isin ?isin .
  OPTIONAL { ?sc fl:name ?name }
  OPTIONAL { ?sc fl:currency ?currency }
  OPTIONAL { ?sc fl:assetClass ?assetClass }
  OPTIONAL { ?sc fl:esgArticle ?esgArticle }
}
ORDER BY ?isin
LIMIT 15
"""

# A SPARQL aggregation: count share classes per currency.
Q_COUNT = """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?currency (COUNT(?sc) AS ?n)
WHERE { ?sc a fl:ShareClass ; fl:currency ?currency . }
GROUP BY ?currency
ORDER BY DESC(?n)
"""

# An RM-style validation rule (SPARQL ASK):
# "Is there any active share class that is missing an ISIN?"
Q_RULE_MISSING_ISIN = """
PREFIX fl: <https://fundlink.dp/ont#>
ASK {
  ?sc a fl:ShareClass .
  FILTER NOT EXISTS { ?sc fl:isin ?isin }
}
"""

# RM rule: list share classes with a name but no ESG article classification.
Q_RULE_NO_ESG = """
PREFIX fl: <https://fundlink.dp/ont#>
SELECT ?isin ?name
WHERE {
  ?sc a fl:ShareClass ;
      fl:isin ?isin ;
      fl:name ?name .
  FILTER NOT EXISTS { ?sc fl:esgArticle ?a }
}
LIMIT 10
"""


def _print(title, columns, rows):
    print(f"\n=== {title} ===")
    print("  " + " | ".join(columns))
    for r in rows:
        print("  " + " | ".join("" if c is None else str(c) for c in r))


def main():
    ok, msg = fundlink_rdf.fundlink.test_connection()
    print(f"[connection] {msg}")
    if not ok:
        return

    print("[load] fetching share classes and building RDF graph...")
    g = fundlink_rdf.load(limit=500, active_only=True)
    print(f"[graph] {len(g)} triples")

    for title, q in [
        ("SELECT share classes", Q_SELECT),
        ("COUNT by currency", Q_COUNT),
        ("RULE: any active SC missing ISIN? (ASK)", Q_RULE_MISSING_ISIN),
        ("RULE: SC without ESG article", Q_RULE_NO_ESG),
    ]:
        cols, rows = fundlink_rdf.run_sparql(g, q)
        _print(title, cols, rows)


if __name__ == "__main__":
    main()
