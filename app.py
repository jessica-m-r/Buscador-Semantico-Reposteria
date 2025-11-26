# app.py
from flask import Flask, render_template, request
from utils import OntologyHelper
from SPARQLWrapper import SPARQLWrapper, JSON

app = Flask(__name__)

# -------------------------
# Ontología local
# -------------------------
ontology = OntologyHelper(r"D:\WebSemantica\buscador_reposteria\reposteria_poblada.rdf")


# -------------------------
# Función para buscar en DBpedia online
# -------------------------
def search_dbpedia(term: str, limit: int = 10):
    sparql = SPARQLWrapper("https://dbpedia.org/sparql")
    sparql.setReturnFormat(JSON)
    sparql.setTimeout(30)

    query = f"""
    PREFIX dbo: <http://dbpedia.org/ontology/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?dessert ?label ?abstract ?description ?ingredientName ?ingredient ?ingredientLabel
    WHERE {{
        {{
            ?dessert a dbo:Food ;
                     rdfs:label ?label .
        }}
        UNION
        {{
            ?dessert rdfs:label ?label .
            FILTER regex(?label, "{term}", "i")
        }}
        
        FILTER (lang(?label) = "en" || lang(?label) = "es")
        FILTER regex(?label, "{term}", "i")
        
        # Abstract (descripción larga)
        OPTIONAL {{ 
            ?dessert dbo:abstract ?abstract .
            FILTER (lang(?abstract) = "en" || lang(?abstract) = "es")
        }}
        
        # Description (descripción corta)
        OPTIONAL {{ 
            ?dessert dbo:description ?description .
            FILTER (lang(?description) = "en" || lang(?description) = "es")
        }}
        
        # Nombre de ingredientes (texto plano)
        OPTIONAL {{ 
            ?dessert dbo:ingredientName ?ingredientName .
            FILTER (lang(?ingredientName) = "en" || lang(?ingredientName) = "es" || !bound(lang(?ingredientName)))
        }}
        
        # Ingredientes (URIs con sus labels)
        OPTIONAL {{ 
            ?dessert dbo:ingredient ?ingredient .
            OPTIONAL {{
                ?ingredient rdfs:label ?ingredientLabel .
                FILTER (lang(?ingredientLabel) = "en" || lang(?ingredientLabel) = "es")
            }}
        }}
    }} 
    LIMIT 100
    """

    sparql.setQuery(query)
    results = []
    results_dict = {}
    
    try:
        print(f"Ejecutando consulta DBpedia para: {term}")
        res = sparql.query().convert()["results"]["bindings"]
        print(f"Filas encontradas: {len(res)}")
        
        # Agrupar resultados por URI del postre (puede haber múltiples filas por ingrediente)
        for r in res:
            uri = r["dessert"]["value"]
            
            if uri not in results_dict:
                results_dict[uri] = {
                    "nombre": r["label"]["value"],
                    "tipo": "Postre (DBpedia)",
                    "descripcion": "",
                    "ingredientes": set(),
                    "dbpedia_uri": uri
                }
            
            # Obtener descripción (priorizar description sobre abstract)
            if "description" in r and r["description"]["value"]:
                results_dict[uri]["descripcion"] = r["description"]["value"]
            elif "abstract" in r and r["abstract"]["value"] and not results_dict[uri]["descripcion"]:
                # Truncar abstract si es muy largo
                abstract = r["abstract"]["value"]
                results_dict[uri]["descripcion"] = abstract[:300] + "..." if len(abstract) > 300 else abstract
            
            # Obtener ingredientName (texto plano)
            if "ingredientName" in r and r["ingredientName"]["value"]:
                ingredient_text = r["ingredientName"]["value"]
                # Dividir por comas si hay múltiples ingredientes
                for ing in ingredient_text.split(','):
                    results_dict[uri]["ingredientes"].add(ing.strip())
            
            # Obtener ingredientes estructurados
            if "ingredientLabel" in r and r["ingredientLabel"]["value"]:
                results_dict[uri]["ingredientes"].add(r["ingredientLabel"]["value"])
            elif "ingredient" in r:
                # Extraer nombre del URI si no hay label
                ingredient_uri = r["ingredient"]["value"]
                ingredient_name = ingredient_uri.split('/')[-1].replace('_', ' ')
                results_dict[uri]["ingredientes"].add(ingredient_name)
        
        # Convertir el diccionario a lista
        for uri, data in results_dict.items():
            data["ingredientes"] = list(data["ingredientes"])[:10]  # Limitar a 10 ingredientes
            if not data["descripcion"]:
                data["descripcion"] = "Sin descripción disponible"
            results.append(data)
        
        # Limitar resultados finales
        results = results[:limit]
        print(f"Postres únicos procesados: {len(results)}")
        
    except Exception as e:
        print(f"Error consultando DBpedia: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return results


# -------------------------
# Controlador principal
# -------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    term = ""
    results_local = []
    results_dbpedia = []

    if request.method == "POST":
        term = request.form.get("term", "").strip()
        if term:
            # -------------------------
            # Búsqueda local (múltiples términos)
            # -------------------------
            terms = term.split()
            results_local = ontology.search_instances_multiple_terms(terms)

            # -------------------------
            # Búsqueda online DBpedia
            # -------------------------
            results_dbpedia = search_dbpedia(term, limit=10)

    return render_template(
        "index.html",
        term=term,
        results_local=results_local,
        results_dbpedia=results_dbpedia
    )

if __name__ == "__main__":
    app.run(debug=True)
