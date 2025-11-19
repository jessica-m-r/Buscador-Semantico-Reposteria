from flask import Flask, render_template, request
from rdflib import Graph, RDFS, RDF, Namespace, Literal

app = Flask(__name__)

# Cargar ontología
g = Graph()
g.parse("reposteria.rdf", format="xml")

NS = Namespace("http://www.semanticweb.org/ontologies/reposteria#")

# Obtener subclases recursivamente
def get_all_subclasses(cls):
    subclasses = set()
    for sub in g.subjects(RDFS.subClassOf, cls):
        subclasses.add(sub)
        subclasses |= get_all_subclasses(sub)
    return subclasses

# Obtener superclases recursivamente
def get_all_superclasses(cls):
    superclasses = set()
    for sup in g.objects(cls, RDFS.subClassOf):
        superclasses.add(sup)
        superclasses |= get_all_superclasses(sup)
    return superclasses

# Obtener instancias de una clase (incluye subclases)
def get_instances_of_class(cls):
    subclasses = {cls} | get_all_subclasses(cls)
    instances = set()
    for c in subclasses:
        for inst in g.subjects(RDF.type, c):
            instances.add(inst)
    return list(instances)

# -----------------------------------------------
# 🔍 BÚSQUEDA DE INSTANCIAS
# -----------------------------------------------
def search_instances(term):
    term_lower = term.lower()
    results = []
    seen = set()

    for inst in g.subjects(RDF.type, None):
        if inst in seen:
            continue

        nombre = g.value(inst, NS.nombre)
        inst_name = str(nombre) if nombre else inst.split("#")[-1]

        if term_lower in inst_name.lower():

            # ---------------------------
            # Clases y superclases
            # ---------------------------
            clases = [cls.split("#")[-1] for cls in g.objects(inst, RDF.type)]

            superclases = []
            for cls_uri in g.objects(inst, RDF.type):
                superclases += [str(s.split("#")[-1]) for s in get_all_superclasses(cls_uri)]

            clases_uris = list(g.objects(inst, RDF.type))
            es_producto = False
            for cls_uri in clases_uris:
                cls_name = cls_uri.split("#")[-1].lower()
                if cls_name == "producto":
                    es_producto = True
                    break
                # Verificar si Producto está en las superclases
                superclases_names = [s.split("#")[-1].lower() for s in get_all_superclasses(cls_uri)]
                if "producto" in superclases_names:
                    es_producto = True
                    break

            # ---------------------------
            # SEPARACIÓN DE ATRIBUTOS
            # ---------------------------

            ingredientes = []
            herramientas = []
            tecnicas = []
            atributos = {}

            for prop, obj in g.predicate_objects(inst):

                prop_name = prop.split("#")[-1]

                # IGNORAR rdf:type
                if prop == RDF.type:
                    continue

                if es_producto:
                    # --- Ingredientes ---
                    if prop == NS.tieneIngrediente or prop_name.lower().startswith("ingrediente"):
                        ingredientes.append(obj.split("#")[-1])
                        continue

                    # --- Herramientas ---
                    if prop == NS.usaHerramienta or prop_name.lower().startswith("herramienta"):
                        herramientas.append(obj.split("#")[-1])
                        continue

                    # --- Técnicas ---
                    if prop == NS.requiereTecnica or prop_name.lower().startswith("tecnica"):
                        tecnicas.append(obj.split("#")[-1])
                        continue

                # --- Literal (los valores numéricos o texto) ---
                if isinstance(obj, Literal):
                    atributos.setdefault(prop_name, []).append(str(obj))
                    continue

                # Para no-Productos, incluir todas las propiedades que no sean literales
                if not es_producto:
                    if not isinstance(obj, Literal):
                        atributos.setdefault(prop_name, []).append(obj.split("#")[-1])
                continue

            # ---------------------------
            # ¿Es usada por otras instancias?
            # ---------------------------
            usada_en = []
            for s, p, o in g:
                if str(o) == str(inst):
                    usada_en.append(str(s).split("#")[-1])

            results.append({
                "tipo": "instancia",
                "nombre": inst_name,
                "clases": clases,
                "superclases": list(set(superclases)),
                "es_producto": es_producto,
                "ingredientes": ingredientes if es_producto else [],
                "herramientas": herramientas if es_producto else [],
                "tecnicas": tecnicas if es_producto else [],
                "atributos": atributos,
                "usada_en": list(set(usada_en))
            })

            seen.add(inst)

    return results

# -----------------------------------------------
# 🔍 BÚSQUEDA DE CLASES
# -----------------------------------------------
def search_classes(term):
    term_lower = term.lower()
    results = []

    for cls in g.subjects(RDF.type, RDFS.Class):
        cls_name = cls.split("#")[-1]

        if term_lower != cls_name.lower():
            continue

        # Propiedades (atributos) definidas para esa clase
        atributos = []
        for s, p, o in g.triples((cls, None, None)):
            if "domain" in p.split("#")[-1]: 
                continue
            atributos.append(p.split("#")[-1])

        subclasses = [c.split("#")[-1] for c in get_all_subclasses(cls)]
        superclasses = [c.split("#")[-1] for c in get_all_superclasses(cls)]
        instancias = [i.split("#")[-1] for i in get_instances_of_class(cls)]

        results.append({
            "tipo": "clase",
            "nombre": cls_name,
            "atributos": list(set(atributos)),
            "subclases": subclasses,
            "superclases": superclasses,
            "instancias": instancias
        })

    return results


# -----------------------------------------------
# 🔍 CONTROLADOR PRINCIPAL
# -----------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    term = ""

    if request.method == "POST":
        term = request.form.get("term", "").strip()

        if term:
            # Buscar instancias
            inst_res = search_instances(term)

            # Buscar clases
            class_res = search_classes(term)

            results = inst_res + class_res

    return render_template("index.html", results=results, term=term)

if __name__ == "__main__":
    app.run(debug=True)
