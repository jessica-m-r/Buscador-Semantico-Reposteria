import argparse
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib import Graph, Namespace, RDF, RDFS, Literal, URIRef

DBPEDIA = "http://dbpedia.org/sparql"
REPO = Namespace("http://example.org/reposteria#")

def query_dbpedia(q):
    sparql = SPARQLWrapper(DBPEDIA)
    sparql.setQuery(q)
    sparql.setReturnFormat(JSON)
    try:
        res = sparql.query().convert()
        return res['results']['bindings']
    except Exception as e:
        print("Error SPARQL:", e)
        return []

def fetch_postres(lang="es", limit=50):
    q = f"""
    PREFIX dbo: <http://dbpedia.org/ontology/>
    PREFIX dct: <http://purl.org/dc/terms/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?dessert ?label ?abstract ?countryLabel ?ingredientLabel ?toolLabel ?calories ?duration
    WHERE {{
      ?dessert dct:subject ?cat .
      FILTER(CONTAINS(LCASE(str(?cat)), "dessert") || CONTAINS(LCASE(str(?cat)), "postre") || CONTAINS(LCASE(str(?cat)), "desserts"))
      ?dessert rdfs:label ?label .
      FILTER(LANG(?label)="{lang}")
      OPTIONAL {{ ?dessert dbo:abstract ?abstract . FILTER(LANG(?abstract)="{lang}") }}
      OPTIONAL {{ ?dessert dbo:country ?country . ?country rdfs:label ?countryLabel . FILTER(LANG(?countryLabel)="{lang}") }}
      OPTIONAL {{ ?dessert dbo:ingredient ?ingredient . ?ingredient rdfs:label ?ingredientLabel . FILTER(LANG(?ingredientLabel)="{lang}") }}
      OPTIONAL {{ ?dessert dbo:tool ?tool . ?tool rdfs:label ?toolLabel . FILTER(LANG(?toolLabel)="{lang}") }}
      OPTIONAL {{ ?dessert dbo:calories ?calories }}
      OPTIONAL {{ ?dessert dbo:duration ?duration }}
    }}
    LIMIT {limit}
    """
    return query_dbpedia(q)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="es")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--out", default="populated.owl")
    args = parser.parse_args()

    g = Graph()
    try:
        g.parse("reposteria.owl", format="xml")
    except Exception as e:
        print("No se pudo cargar reposteria.owl:", e)

    g.bind("rdfs", RDFS)
    g.bind("reposteria", REPO)

    items = fetch_postres(lang=args.lang, limit=args.limit)

    for r in items:
        dessert_uri = r.get("dessert", {}).get("value")
        label = r.get("label", {}).get("value")
        abstract = r.get("abstract", {}).get("value", "")
        country = r.get("countryLabel", {}).get("value", "")
        ingredient_label = r.get("ingredientLabel", {}).get("value", "")
        tool_label = r.get("toolLabel", {}).get("value", "")
        calories = r.get("calories", {}).get("value", "")
        duration = r.get("duration", {}).get("value", "")

        if not dessert_uri or not label:
            continue

        postre_uri = URIRef(dessert_uri.replace("http://dbpedia.org/resource/", "http://example.org/reposteria/"))
        g.add((postre_uri, RDF.type, REPO.Postre))
        g.add((postre_uri, RDFS.label, Literal(label, lang=args.lang)))
        if abstract:
            g.add((postre_uri, REPO.abstract, Literal(abstract, lang=args.lang)))
        if country:
            g.add((postre_uri, REPO.esTipicoDe, Literal(country, lang=args.lang)))
        if calories:
            g.add((postre_uri, REPO.tieneCalorias, Literal(calories)))
        if duration:
            g.add((postre_uri, REPO.tieneTiempoPreparacion, Literal(duration)))

        # Ingredientes
        if ingredient_label:
            ing_uri = URIRef("http://example.org/reposteria/" + ingredient_label.replace(" ", "_"))
            g.add((ing_uri, RDF.type, REPO.Ingrediente))
            g.add((ing_uri, RDFS.label, Literal(ingredient_label, lang=args.lang)))
            g.add((postre_uri, REPO.requiereIngrediente, ing_uri))

        # Utensilios / herramientas
        if tool_label:
            tool_uri = URIRef("http://example.org/reposteria/" + tool_label.replace(" ", "_"))
            g.add((tool_uri, RDF.type, REPO.Utensilio))
            g.add((tool_uri, RDFS.label, Literal(tool_label, lang=args.lang)))
            g.add((postre_uri, REPO.requiereUtensilio, tool_uri))

    g.serialize(destination=args.out, format="pretty-xml")
    print("Ontología poblada guardada en", args.out)

if __name__ == "__main__":
    main()
