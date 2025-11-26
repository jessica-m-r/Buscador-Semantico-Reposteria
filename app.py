from flask import Flask, render_template, request,jsonify
from rdflib import Graph, RDFS, RDF, Namespace, Literal
from SPARQLWrapper import SPARQLWrapper, JSON
import re
# ============================
# CACHE EN MEMORIA (RAM)
# ============================
local_cache = {}        # cache de resultados locales
dbpedia_cache = {}      # cache de resultados DBpedia


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
    Busca SOLO comidas en DBpedia usando múltiples términos
    """
    tokens = tokenize_search_term(term)
    
    if not tokens:
        return []
    
    results = []
    
    try:
        sparql = SPARQLWrapper(DBPEDIA_ENDPOINT)
        sparql.setTimeout(20)
        
        # Traducir términos comunes al inglés para mejor búsqueda
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
        
        # Traducir tokens al inglés
        search_tokens = []
        for token in tokens:
            translated = term_translations.get(token, token)
            search_tokens.append(translated)
        
        # Construir filtro SPARQL con OR lógico
        filter_conditions = " || ".join([
            f'CONTAINS(LCASE(?label), LCASE("{token}"))' 
            for token in search_tokens
        ])
        
        # Consulta SPARQL mejorada
        query = f"""
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?item ?label ?thumbnail
        WHERE {{
            ?item rdfs:label ?label .
            ?item a dbo:Food .
            
            FILTER(LANG(?label) = "en")
            FILTER({filter_conditions})
            
            OPTIONAL {{ ?item dbo:thumbnail ?thumbnail . }}
        }}
        LIMIT 10
        """
        
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        query_results = sparql.query().convert()
        
        processed_items = set()
        
        for result in query_results["results"]["bindings"]:
            item_uri = result["item"]["value"]
            
            if item_uri in processed_items:
                continue
            processed_items.add(item_uri)
            
            label = result.get("label", {}).get("value", item_uri.split("/")[-1])
            thumbnail_url = result.get("thumbnail", {}).get("value", None)
            
            print(f"\n{'='*60}")
            print(f"Procesando: {label}")
            print(f"URI: {item_uri}")
            print(f"Thumbnail: {thumbnail_url}")
            
            # Obtener descripción
            abstract = "Descripción no disponible en DBpedia"
            try:
                abstract_query = f"""
                PREFIX dbo: <http://dbpedia.org/ontology/>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                
                SELECT ?text
                WHERE {{
                    {{
                        <{item_uri}> dbo:abstract ?text .
                        FILTER(LANG(?text) = "en")
                    }}
                    UNION
                    {{
                        <{item_uri}> rdfs:comment ?text .
                        FILTER(LANG(?text) = "en")
                    }}
                    UNION
                    {{
                        <{item_uri}> dbo:description ?text .
                    }}
                }}
                LIMIT 1
                """
                
                sparql_abstract = SPARQLWrapper(DBPEDIA_ENDPOINT)
                sparql_abstract.setQuery(abstract_query)
                sparql_abstract.setReturnFormat(JSON)
                sparql_abstract.setTimeout(10)
                abstract_result = sparql_abstract.query().convert()
                
                if abstract_result["results"]["bindings"]:
                    abstract = abstract_result["results"]["bindings"][0]["text"]["value"]
                    print(f"✓ Descripción obtenida correctamente")
                else:
                    print(f"✗ No se encontró ninguna descripción")
                    
            except Exception as e:
                print(f"✗ Error obteniendo descripción: {str(e)}")
                abstract = "Descripción no disponible en DBpedia"
            
            # Limitar el abstract a 400 caracteres
            if abstract and abstract != "Descripción no disponible en DBpedia" and len(abstract) > 400:
                abstract = abstract[:397] + "..."
            
            # Buscar ingredientes
            ingredientes = []
            try:
                ing_query = f"""
                PREFIX dbo: <http://dbpedia.org/ontology/>
                
                SELECT DISTINCT ?ingredient 
                WHERE {{
                    <{item_uri}> dbo:ingredient ?ingredient .
                }}
                LIMIT 15
                """
                sparql_ing = SPARQLWrapper(DBPEDIA_ENDPOINT)
                sparql_ing.setQuery(ing_query)
                sparql_ing.setReturnFormat(JSON)
                sparql_ing.setTimeout(10)
                ing_results = sparql_ing.query().convert()
                
                for ing_result in ing_results["results"]["bindings"]:
                    ing = ing_result["ingredient"]["value"]
                    ing_name = ing.split("/")[-1].replace("_", " ")
                    if ing_name not in ingredientes:
                        ingredientes.append(ing_name)
                        
                print(f"Ingredientes: {len(ingredientes)}")
            except Exception as e:
                print(f"Error obteniendo ingredientes: {e}")
            
            # Buscar país de origen y región
            pais_origen = None
            region = None
            
            try:
                location_query = f"""
                PREFIX dbo: <http://dbpedia.org/ontology/>
                PREFIX dbp: <http://dbpedia.org/property/>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                
                SELECT DISTINCT ?countryLabel ?regionLabel 
                WHERE {{
                    OPTIONAL {{
                        <{item_uri}> dbo:country ?country .
                        ?country rdfs:label ?countryLabel .
                        FILTER(LANG(?countryLabel) = "en")
                    }}
                    OPTIONAL {{
                        <{item_uri}> dbp:country ?country2 .
                        ?country2 rdfs:label ?countryLabel .
                        FILTER(LANG(?countryLabel) = "en")
                    }}
                    OPTIONAL {{
                        <{item_uri}> dbo:region ?region .
                        ?region rdfs:label ?regionLabel .
                        FILTER(LANG(?regionLabel) = "en")
                    }}
                }}
                LIMIT 1
                """
                sparql_loc = SPARQLWrapper(DBPEDIA_ENDPOINT)
                sparql_loc.setQuery(location_query)
                sparql_loc.setReturnFormat(JSON)
                sparql_loc.setTimeout(10)
                loc_results = sparql_loc.query().convert()
                
                if loc_results["results"]["bindings"]:
                    loc_data = loc_results["results"]["bindings"][0]
                    if "countryLabel" in loc_data:
                        pais_origen = loc_data["countryLabel"]["value"]
                    if "regionLabel" in loc_data:
                        region = loc_data["regionLabel"]["value"]
            except Exception as e:
                print(f"Error obteniendo ubicación: {e}")
            
            # Calcular relevancia basada en tokens coincidentes
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
                "ingredientes": ingredientes[:12],
                "herramientas": [],
                "tecnicas": [],
                "atributos": atributos,
                "usada_en": [],
                "thumbnail": thumbnail_url,
                "fuente": "dbpedia",
                "relevance": relevance_score
            })
        
    except Exception as e:
        print(f"Error consultando DBpedia: {e}")
    
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