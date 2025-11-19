from flask import Flask, render_template, request
from rdflib import Graph, RDFS, RDF, Namespace, URIRef, Literal

app = Flask(__name__)

# Carga de la ontología local
g = Graph()
g.parse("reposteria.rdf", format="xml")  # Ajusta el nombre de tu archivo RDF

# Namespace principal de tu ontología
NS = Namespace("http://www.semanticweb.org/ontologies/reposteria#")

# Función para obtener todas las subclases recursivamente
def get_all_subclasses(cls):
    subclasses = set()
    for sub in g.subjects(RDFS.subClassOf, cls):
        subclasses.add(sub)
        subclasses |= get_all_subclasses(sub)
    return subclasses

# Función para buscar productos por término (ignora mayúsculas)
def search_products(term):
    term_lower = term.lower()
    results = []

    # Obtenemos todas las subclases de Producto
    product_classes = {NS.Producto} | get_all_subclasses(NS.Producto)

    for prod in g.subjects(RDF.type, None):
        # Verificamos si la instancia es de una subclase de Producto
        if any((prod, RDF.type, cls) in g for cls in product_classes):
            # Intentamos obtener el nombre, primero con propiedad nombre
            nombre = g.value(prod, NS.nombre)
            if nombre is None:
                # Si no hay NS.nombre, buscamos cualquier literal dentro de la instancia
                for obj in g.objects(prod, None):
                    if isinstance(obj, Literal):
                        nombre = obj
                        break
            if nombre and term_lower in str(nombre).lower():
                # Recolectamos ingredientes, técnicas y herramientas
                ingredientes = [str(i.split("#")[-1]) for i in g.objects(prod, NS.tieneIngrediente)]
                tecnicas = [str(t.split("#")[-1]) for t in g.objects(prod, NS.requiereTecnica)]
                herramientas = [str(h.split("#")[-1]) for h in g.objects(prod, NS.usaHerramienta)]

                results.append({
                    "nombre": str(nombre),
                    "ingredientes": ingredientes,
                    "tecnicas": tecnicas,
                    "herramientas": herramientas
                })
    return results

@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    if request.method == "POST":
        term = request.form.get("term")
        if term:
            results = search_products(term)
    return render_template("results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True)
