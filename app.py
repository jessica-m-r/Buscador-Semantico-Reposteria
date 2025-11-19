from flask import Flask, render_template, request
from rdflib import Graph, RDFS, RDF, Namespace, Literal

app = Flask(__name__)

# Carga de la ontología local
g = Graph()
g.parse("reposteria.rdf", format="xml")  # Ajusta el nombre de tu archivo RDF

# Namespace principal
NS = Namespace("http://www.semanticweb.org/ontologies/reposteria#")

# Función para obtener subclases recursivamente
def get_all_subclasses(cls):
    subclasses = set()
    for sub in g.subjects(RDFS.subClassOf, cls):
        subclasses.add(sub)
        subclasses |= get_all_subclasses(sub)
    return subclasses

# Función de búsqueda
def search_products(term):
    term_lower = term.lower()
    results = []
    product_classes = {NS.Producto} | get_all_subclasses(NS.Producto)

    seen = set()  # Para no repetir instancias

    for prod in g.subjects(RDF.type, None):
        if prod in seen:
            continue  # Ya procesada

        if any((prod, RDF.type, cls) in g for cls in product_classes):
            nombre = g.value(prod, NS.nombre)
            if nombre and term_lower in str(nombre).lower():
                ingredientes = list({str(i).split("#")[-1] for i in g.objects(prod, NS.tieneIngrediente)})
                tecnicas = list({str(t).split("#")[-1] for t in g.objects(prod, NS.requiereTecnica)})
                herramientas = list({str(h).split("#")[-1] for h in g.objects(prod, NS.usaHerramienta)})

                results.append({
                    "nombre": str(nombre),
                    "ingredientes": ingredientes,
                    "tecnicas": tecnicas,
                    "herramientas": herramientas
                })
                seen.add(prod)  # Marcamos como procesada
    return results


@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    term = ""
    if request.method == "POST":
        term = request.form.get("term", "")
        results = search_products(term) if term else []
    return render_template("index.html", results=results, term=term)

if __name__ == "__main__":
    app.run(debug=True)
