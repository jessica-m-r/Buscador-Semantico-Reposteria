from flask import Flask, render_template, request, redirect, url_for
from rdflib import Graph, Namespace, RDF, RDFS, Literal

app = Flask(__name__)

# --- Cargar ontología local ---
g = Graph()
g.parse("populated.owl", format="xml")
NS = Namespace("http://example.org/reposteria#")
g.bind("rdfs", RDFS)

# --- Función de búsqueda en ontología ---
def search_local(term, lang="es", qtype="name"):
    results = []
    term_lower = term.lower()
    
    for postre in g.subjects(RDF.type, NS.Postre):
        # etiquetas
        labels = [str(l) for l in g.objects(postre, RDFS.label)]
        label_match = any(term_lower in l.lower() for l in labels)
        
        # abstracción y país
        abstract = g.value(postre, NS.abstract)
        abstract_text = str(abstract) if abstract else ""
        countries = [str(c) for c in g.objects(postre, NS.esTipicoDe)]
        
        # ingredientes, técnicas, utensilios
        ingredients = [{"uri": str(i), "label": str(g.value(i, RDFS.label) or i)} 
                       for i in g.objects(postre, NS.requiereIngrediente)]
        techniques = [{"uri": str(t), "label": str(g.value(t, RDFS.label) or t)} 
                       for t in g.objects(postre, NS.usaTecnica)]
        utensils = [{"uri": str(u), "label": str(g.value(u, RDFS.label) or u)} 
                    for u in g.objects(postre, NS.requiereUtensilio)]
        
        # cal, tiempo
        calories = g.value(postre, NS.tieneCalorias)
        time = g.value(postre, NS.tieneTiempoPreparacion)
        
        # filtro de búsqueda
        match = False
        if qtype == "name" and label_match:
            match = True
        elif qtype == "ingredient" and any(term_lower in i['label'].lower() for i in ingredients):
            match = True
        elif qtype == "country" and any(term_lower in c.lower() for c in countries):
            match = True
        
        if match:
            results.append({
                "uri": str(postre),
                "label": labels[0] if labels else str(postre),
                "abstract": abstract_text,
                "country": ", ".join(countries),
                "ingredients": ingredients,
                "techniques": techniques,
                "utensils": utensils,
                "calories": str(calories) if calories else "",
                "time": str(time) if time else ""
            })
    return results

# --- Ruta principal ---
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        term = request.form.get("term", "").strip()
        qtype = request.form.get("qtype", "name")

        if not term:
            return redirect(url_for("index"))

        results = search_local(term, qtype)
        return render_template("results.html", items=results, term=term, qtype=qtype)

    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
