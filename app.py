from flask import Flask, render_template, request,jsonify
from rdflib import Graph, RDFS, RDF, Namespace, Literal
from SPARQLWrapper import SPARQLWrapper, JSON
import re

app = Flask(__name__)

# Cargar ontología local
g = Graph()
g.parse("reposteria_poblada.rdf", format="xml")

NS = Namespace("http://www.semanticweb.org/ontologies/reposteria#")

# Configurar endpoint de DBpedia
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"

# ===============================================
# NUEVA FUNCIÓN: TOKENIZACIÓN INTELIGENTE
# ===============================================
def tokenize_search_term(term):
    """
    Divide el término de búsqueda en palabras clave,
    eliminando stopwords (palabras vacías) y limpiando.
    
    Retorna: lista de tokens en minúsculas
    """
    # Stopwords en español (palabras a ignorar)
    stopwords = {
        'de', 'del', 'con', 'sin', 'para', 'por', 'y', 'o', 'u',
        'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
        'al', 'a', 'en', 'sobre', 'bajo', 'entre', 'desde', 'hasta',
        'que', 'como', 'muy', 'mas', 'pero', 'si', 'no'
    }
    
    # Convertir a minúsculas y dividir por espacios
    words = term.lower().split()
    
    # Filtrar: eliminar stopwords y palabras muy cortas (< 2 caracteres)
    tokens = [
        word.strip() 
        for word in words 
        if word.strip() not in stopwords and len(word.strip()) >= 2
    ]
    
    return tokens


def get_all_subclasses(cls):
    subclasses = set()
    for sub in g.subjects(RDFS.subClassOf, cls):
        subclasses.add(sub)
        subclasses |= get_all_subclasses(sub)
    return subclasses

def get_all_superclasses(cls):
    superclasses = set()
    for sup in g.objects(cls, RDFS.subClassOf):
        superclasses.add(sup)
        superclasses |= get_all_superclasses(sup)
    return superclasses

def get_instances_of_class(cls):
    subclasses = {cls} | get_all_subclasses(cls)
    instances = set()
    for c in subclasses:
        for inst in g.subjects(RDF.type, c):
            instances.add(inst)
    return list(instances)

# -----------------------------------------------
# BÚSQUEDA LOCAL MEJORADA (MULTI-TÉRMINO)
# -----------------------------------------------
def search_instances(term):
    """
    Busca instancias que coincidan con cualquiera de los tokens
    del término de búsqueda. Incluye sistema de relevancia.
    """
    tokens = tokenize_search_term(term)
    
    # Si no hay tokens válidos, retornar vacío
    if not tokens:
        return []
    
    results = []
    seen = set()

    for inst in g.subjects(RDF.type, None):
        if inst in seen:
            continue

        nombre = g.value(inst, NS.nombre)
        inst_name = str(nombre) if nombre else inst.split("#")[-1]

        # Sistema de puntuación de relevancia
        relevance_score = 0
        matched_tokens = []

        # Buscar coincidencias en el nombre
        for token in tokens:
            if token in inst_name.lower():
                relevance_score += 3  # Coincidencia en nombre vale más
                matched_tokens.append(token)

        # Buscar en propiedades literales
        for prop, obj in g.predicate_objects(inst):
            if isinstance(obj, Literal):
                obj_str = str(obj).lower()
                for token in tokens:
                    if token in obj_str and token not in matched_tokens:
                        relevance_score += 1
                        matched_tokens.append(token)

        # Buscar en nombres de objetos relacionados
        for prop, obj in g.predicate_objects(inst):
            if not isinstance(obj, Literal):
                obj_name = obj.split("#")[-1].lower()
                for token in tokens:
                    if token in obj_name and token not in matched_tokens:
                        relevance_score += 2
                        matched_tokens.append(token)

        # Buscar en nombres de clases
        for cls_uri in g.objects(inst, RDF.type):
            cls_name = cls_uri.split("#")[-1].lower()
            for token in tokens:
                if token in cls_name and token not in matched_tokens:
                    relevance_score += 1
                    matched_tokens.append(token)

        # Si no hubo ninguna coincidencia, saltar esta instancia
        if relevance_score == 0:
            continue

        # Construir información de la instancia
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
            superclases_names = [s.split("#")[-1].lower() for s in get_all_superclasses(cls_uri)]
            if "producto" in superclases_names:
                es_producto = True
                break

        ingredientes = []
        herramientas = []
        tecnicas = []
        atributos = {}

        for prop, obj in g.predicate_objects(inst):
            prop_name = prop.split("#")[-1]

            if prop == RDF.type:
                continue

            if es_producto:
                if prop == NS.tieneIngrediente or prop_name.lower().startswith("ingrediente"):
                    ingredientes.append(obj.split("#")[-1])
                    continue

                if prop == NS.usaHerramienta or prop_name.lower().startswith("herramienta"):
                    herramientas.append(obj.split("#")[-1])
                    continue

                if prop == NS.requiereTecnica or prop_name.lower().startswith("tecnica"):
                    tecnicas.append(obj.split("#")[-1])
                    continue

            if isinstance(obj, Literal):
                atributos.setdefault(prop_name, []).append(str(obj))
                continue

            if not es_producto:
                if not isinstance(obj, Literal):
                    atributos.setdefault(prop_name, []).append(obj.split("#")[-1])

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
            "usada_en": list(set(usada_en)),
            "fuente": "local",
            "relevance": relevance_score  # Para ordenamiento
        })

        seen.add(inst)

    # Ordenar por relevancia (mayor a menor)
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)

    return results

def search_classes(term):
    """
    Busca clases que coincidan con cualquiera de los tokens
    """
    tokens = tokenize_search_term(term)
    
    if not tokens:
        return []
    
    results = []

    for cls in g.subjects(RDF.type, RDFS.Class):
        cls_name = cls.split("#")[-1]
        cls_name_lower = cls_name.lower()

        # Verificar si algún token coincide con el nombre de la clase
        match = False
        relevance_score = 0
        
        for token in tokens:
            if token in cls_name_lower:
                match = True
                relevance_score += 1

        if not match:
            continue

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
            "instancias": instancias,
            "fuente": "local",
            "relevance": relevance_score
        })

    # Ordenar por relevancia
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)

    return results


# -----------------------------------------------
# BUSQUEDA EN DBPEDIA MEJORADA (MULTI-TÉRMINO)
# -----------------------------------------------
def search_dbpedia_food(term):
    """
    Búsqueda optimizada en DBpedia - Versión mejorada con mejor compatibilidad
    """
    tokens = tokenize_search_term(term)
    
    if not tokens:
        return []
    
    results = []
    
    try:
        sparql = SPARQLWrapper(DBPEDIA_ENDPOINT)
        sparql.setTimeout(15)
        
        # Traducciones
        term_translations = {
            'chocolate': 'chocolate',
            'vainilla': 'vanilla',
            'pastel': 'cake',
            'galleta': 'cookie',
            'galletas': 'cookie',
            'tarta': 'tart',
            'postre': 'dessert',
            'brownie': 'brownie',
            'cheesecake': 'cheesecake',
            'cupcake': 'cupcake',
            'bizcocho': 'sponge cake',
            'mousse': 'mousse',
            'flan': 'flan',
            'tiramisu': 'tiramisu',
            'macarons': 'macaron',
            'avena': 'oat',
            'nuez': 'walnut',
            'almendra': 'almond',
            'fresa': 'strawberry',
            'limon': 'lemon',
            'naranja': 'orange'
        }
        
        search_tokens = []
        for token in tokens:
            translated = term_translations.get(token, token)
            search_tokens.append(translated)
        
        filter_conditions = " || ".join([
            f'CONTAINS(LCASE(?label), LCASE("{token}"))' 
            for token in search_tokens
        ])
        
        # *** CONSULTA OPTIMIZADA - PRODUCTOS DE REPOSTERÍA ***
        query = f"""
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX dbp: <http://dbpedia.org/property/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dct: <http://purl.org/dc/terms/>
        
        SELECT DISTINCT 
            ?item 
            ?label 
            ?thumbnail
            (SAMPLE(?desc) AS ?abstract)
            (GROUP_CONCAT(DISTINCT ?ingredientName; separator="|") AS ?ingredients)
            (SAMPLE(?countryName) AS ?countryLabel)
            (SAMPLE(?regionName) AS ?regionLabel)
        WHERE {{
            # Item principal - debe ser Food
            ?item rdfs:label ?label .
            ?item a dbo:Food .
            
            FILTER(LANG(?label) = "en")
            FILTER({filter_conditions})
            
            # FILTRO: Debe contener ingredientes típicos de repostería O palabras clave
            FILTER(
                # Palabras clave de repostería en el nombre
                CONTAINS(LCASE(?label), "cake") ||
                CONTAINS(LCASE(?label), "cookie") ||
                CONTAINS(LCASE(?label), "brownie") ||
                CONTAINS(LCASE(?label), "tart") ||
                CONTAINS(LCASE(?label), "pie") ||
                CONTAINS(LCASE(?label), "pudding") ||
                CONTAINS(LCASE(?label), "mousse") ||
                CONTAINS(LCASE(?label), "cheesecake") ||
                CONTAINS(LCASE(?label), "cupcake") ||
                CONTAINS(LCASE(?label), "macaron") ||
                CONTAINS(LCASE(?label), "tiramisu") ||
                CONTAINS(LCASE(?label), "flan") ||
                CONTAINS(LCASE(?label), "éclair") ||
                CONTAINS(LCASE(?label), "donut") ||
                CONTAINS(LCASE(?label), "doughnut") ||
                CONTAINS(LCASE(?label), "muffin") ||
                CONTAINS(LCASE(?label), "pastry") ||
                CONTAINS(LCASE(?label), "sweet") ||
                CONTAINS(LCASE(?label), "dessert") ||
                CONTAINS(LCASE(?label), "chocolate") ||
                CONTAINS(LCASE(?label), "truffle") ||
                CONTAINS(LCASE(?label), "candy") ||
                CONTAINS(LCASE(?label), "confection") ||
                CONTAINS(LCASE(?label), "biscuit") ||
                CONTAINS(LCASE(?label), "wafer") ||
                CONTAINS(LCASE(?label), "meringue") ||
                CONTAINS(LCASE(?label), "soufflé") ||
                CONTAINS(LCASE(?label), "parfait") ||
                CONTAINS(LCASE(?label), "sundae") ||
                CONTAINS(LCASE(?label), "gelato") ||
                CONTAINS(LCASE(?label), "sorbet") ||
                CONTAINS(LCASE(?label), "ice cream") ||
                CONTAINS(LCASE(?label), "frosting") ||
                CONTAINS(LCASE(?label), "icing") ||
                CONTAINS(LCASE(?label), "cream") ||
                CONTAINS(LCASE(?label), "custard") ||
                CONTAINS(LCASE(?label), "ganache") ||
                CONTAINS(LCASE(?label), "glaze") ||
                CONTAINS(LCASE(?label), "praline") ||
                CONTAINS(LCASE(?label), "nougat") ||
                CONTAINS(LCASE(?label), "fondant") ||
                CONTAINS(LCASE(?label), "danish") ||
                CONTAINS(LCASE(?label), "croissant") ||
                CONTAINS(LCASE(?label), "scone") ||
                CONTAINS(LCASE(?label), "shortbread") ||
                CONTAINS(LCASE(?label), "sponge") ||
                CONTAINS(LCASE(?label), "layer cake") ||
                CONTAINS(LCASE(?label), "torte") ||
                CONTAINS(LCASE(?label), "strudel") ||
                CONTAINS(LCASE(?label), "cobbler") ||
                CONTAINS(LCASE(?label), "crumble") ||
                CONTAINS(LCASE(?label), "panna cotta") ||
                CONTAINS(LCASE(?label), "baklava") ||
                CONTAINS(LCASE(?label), "cannoli") ||
                CONTAINS(LCASE(?label), "profiterole") ||
                CONTAINS(LCASE(?label), "choux") ||
                CONTAINS(LCASE(?label), "creme") ||
                CONTAINS(LCASE(?label), "crème")
            )
            
            # Thumbnail (opcional)
            OPTIONAL {{ ?item dbo:thumbnail ?thumbnail . }}
            
            # Abstract/Descripción (más flexible, acepta cualquier idioma si no hay inglés)
            OPTIONAL {{
                ?item dbo:abstract ?desc .
                FILTER(LANG(?desc) = "en")
            }}
            
            # Ingredientes (más flexible)
            OPTIONAL {{
                ?item dbo:ingredient ?ingredient .
                OPTIONAL {{
                    ?ingredient rdfs:label ?ingredientName .
                    FILTER(LANG(?ingredientName) = "en")
                }}
            }}
            
            # País (busca en múltiples propiedades)
            OPTIONAL {{
                {{
                    ?item dbo:country ?country .
                }}
                UNION
                {{
                    ?item dbp:country ?country .
                }}
                OPTIONAL {{
                    ?country rdfs:label ?countryName .
                    FILTER(LANG(?countryName) = "en")
                }}
            }}
            
            # Región
            OPTIONAL {{
                ?item dbo:region ?region .
                OPTIONAL {{
                    ?region rdfs:label ?regionName .
                    FILTER(LANG(?regionName) = "en")
                }}
            }}
        }}
        GROUP BY ?item ?label ?thumbnail
        LIMIT 15
        """
        
        print(f"\n=== Buscando en DBpedia: {term} ===")
        
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        query_results = sparql.query().convert()
        
        print(f"Resultados encontrados: {len(query_results['results']['bindings'])}")
        
        processed_items = set()
        
        for result in query_results["results"]["bindings"]:
            item_uri = result["item"]["value"]
            
            if item_uri in processed_items:
                continue
            processed_items.add(item_uri)
            
            label = result.get("label", {}).get("value", item_uri.split("/")[-1])
            thumbnail_url = result.get("thumbnail", {}).get("value", None)
            
            print(f"  • {label}")
            
            # Descripción
            abstract = result.get("abstract", {}).get("value", "")
            
            if not abstract or abstract == "":
                abstract = "Descripción no disponible en DBpedia"
            elif len(abstract) > 400:
                abstract = abstract[:397] + "..."
            
            # Ingredientes
            ingredientes = []
            ingredients_str = result.get("ingredients", {}).get("value", "")
            if ingredients_str and ingredients_str != "":
                raw_ingredients = ingredients_str.split("|")
                for ing in raw_ingredients[:12]:
                    if ing and ing.strip():
                        # Limpiar el nombre del ingrediente
                        ing_clean = ing.strip()
                        # Si es una URI, extraer el nombre
                        if "http://" in ing_clean:
                            ing_clean = ing_clean.split("/")[-1].replace("_", " ")
                        if ing_clean and ing_clean not in ingredientes:
                            ingredientes.append(ing_clean)
            
            # País y región
            pais_origen = result.get("countryLabel", {}).get("value", None)
            region = result.get("regionLabel", {}).get("value", None)
            
            # Limpiar valores vacíos
            if pais_origen == "":
                pais_origen = None
            if region == "":
                region = None
            
            # Calcular relevancia
            relevance_score = 0
            label_lower = label.lower()
            for token in search_tokens:
                if token.lower() in label_lower:
                    relevance_score += 1
            
            # Construir atributos
            atributos = {
                "descripcion": [abstract]
            }
            
            if pais_origen:
                atributos["pais_origen"] = [pais_origen]
            
            if region:
                atributos["region"] = [region]
            
            atributos["dbpedia_uri"] = [item_uri]
            
            results.append({
                "tipo": "instancia",
                "nombre": label,
                "clases": ["Food (DBpedia)"],
                "superclases": [],
                "es_producto": True,
                "ingredientes": ingredientes,
                "herramientas": [],
                "tecnicas": [],
                "atributos": atributos,
                "usada_en": [],
                "thumbnail": thumbnail_url,
                "fuente": "dbpedia",
                "relevance": relevance_score
            })
        
        print(f"Total procesados: {len(results)}\n")
        
    except Exception as e:
        print(f"Error consultando DBpedia: {e}")
        import traceback
        traceback.print_exc()
    
    # Ordenar por relevancia
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    
    return results
# -----------------------------------------------
# CONTROLADOR PRINCIPAL
# -----------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    term = ""
    local_results = []

    if request.method == "POST":
        term = request.form.get("term", "").strip()
        if term:
            # Solo resultados locales
            inst_res = search_instances(term)
            class_res = search_classes(term)
            local_results = inst_res + class_res

    # Renderizamos solo los resultados locales
    return render_template("index.html", results=local_results, term=term)


@app.route("/dbpedia_search", methods=["POST"])
def dbpedia_search():
    term = request.json.get("term", "").strip()
    if term:
        dbpedia_results = search_dbpedia_food(term)
        return jsonify(dbpedia_results)
    return jsonify([])

if __name__ == "__main__":
    app.run(debug=True)