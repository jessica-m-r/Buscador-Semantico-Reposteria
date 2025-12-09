from flask import Flask, render_template, request, jsonify
from rdflib import Graph, RDFS, RDF, Namespace, Literal
from SPARQLWrapper import SPARQLWrapper, JSON
from deep_translator import GoogleTranslator
import re

app = Flask(__name__)

# Cargar ontología local
g = Graph()
g.parse("reposteria_poblada_google.rdf", format="xml")

NS = Namespace("http://www.semanticweb.org/ontologies/reposteria#")

# Configurar endpoint de DBpedia
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"

# ===============================================
# CONFIGURACIÓN DE IDIOMAS
# ===============================================
LANGUAGES = {
    'es': {'name': 'Español', 'flag': '🇪🇸', 'dbpedia': 'es', 'dbpedia_enabled': True},
    'en': {'name': 'English', 'flag': '🇬🇧', 'dbpedia': 'en', 'dbpedia_enabled': True},
    'fr': {'name': 'Français', 'flag': '🇫🇷', 'dbpedia': 'fr', 'dbpedia_enabled': True},
    'it': {'name': 'Italiano', 'flag': '🇮🇹', 'dbpedia': 'it', 'dbpedia_enabled': False},
    'de': {'name': 'Deutsch', 'flag': '🇩🇪', 'dbpedia': 'de', 'dbpedia_enabled': False},
    'pt': {'name': 'Português', 'flag': '🇵🇹', 'dbpedia': 'pt', 'dbpedia_enabled': False}
}

# Idiomas habilitados para DBpedia
DBPEDIA_ENABLED_LANGUAGES = ['es', 'en', 'fr']

# Cache de traductores
translators_cache = {}

def get_translator(source_lang, target_lang):
    """Obtener traductor del cache o crear uno nuevo"""
    key = f"{source_lang}_{target_lang}"
    if key not in translators_cache:
        translators_cache[key] = GoogleTranslator(source=source_lang, target=target_lang)
    return translators_cache[key]

def translate_text(text, source_lang, target_lang):
    """Traducir texto entre idiomas"""
    if source_lang == target_lang or not text:
        return text
    
    try:
        translator = get_translator(source_lang, target_lang)
        return translator.translate(text)
    except Exception as e:
        print(f"Error traduciendo '{text}': {e}")
        return text

# ===============================================
# TOKENIZACIÓN INTELIGENTE
# ===============================================
def tokenize_search_term(term):
    """Divide el término de búsqueda en palabras clave"""
    # Stopwords multiidioma
    stopwords = {
        'es': {'de', 'del', 'con', 'sin', 'para', 'por', 'y', 'o', 'u', 'el', 'la', 'los', 'las', 'un', 'una'},
        'en': {'the', 'a', 'an', 'and', 'or', 'with', 'without', 'for', 'of', 'in', 'on', 'at'},
        'fr': {'le', 'la', 'les', 'de', 'du', 'des', 'et', 'ou', 'avec', 'sans', 'pour'},
        'it': {'il', 'lo', 'la', 'i', 'gli', 'le', 'di', 'e', 'o', 'con', 'senza'},
        'de': {'der', 'die', 'das', 'den', 'dem', 'des', 'und', 'oder', 'mit', 'ohne'},
        'pt': {'o', 'a', 'os', 'as', 'de', 'do', 'da', 'e', 'ou', 'com', 'sem'}
    }
    
    # Combinar todas las stopwords
    all_stopwords = set()
    for lang_stops in stopwords.values():
        all_stopwords.update(lang_stops)
    
    words = term.lower().split()
    tokens = [
        word.strip() 
        for word in words 
        if word.strip() not in all_stopwords and len(word.strip()) >= 2
    ]
    
    return tokens

# ===============================================
# FUNCIONES DE ONTOLOGÍA
# ===============================================
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

def get_literal_by_language(inst, prop, preferred_lang='es'):
    """
    Obtener un literal en el idioma preferido
    Si no existe, buscar en inglés, y si no, retornar el primero disponible
    """
    values = list(g.objects(inst, prop))
    
    if not values:
        return None
    
    # Buscar en el idioma preferido
    for value in values:
        if isinstance(value, Literal) and hasattr(value, 'language'):
            if value.language == preferred_lang:
                return str(value)
    
    # Buscar en inglés como fallback
    for value in values:
        if isinstance(value, Literal) and hasattr(value, 'language'):
            if value.language == 'en':
                return str(value)
    
    # Retornar el primero disponible
    return str(values[0])

def get_all_literals_by_language(inst, prop, preferred_lang='es'):
    """
    Obtener todos los literales en el idioma preferido
    """
    values = list(g.objects(inst, prop))
    results = []
    
    # Primero buscar en el idioma preferido
    for value in values:
        if isinstance(value, Literal) and hasattr(value, 'language'):
            if value.language == preferred_lang:
                results.append(str(value))
    
    # Si no hay resultados, buscar en inglés
    if not results:
        for value in values:
            if isinstance(value, Literal) and hasattr(value, 'language'):
                if value.language == 'en':
                    results.append(str(value))
    
    # Si aún no hay resultados, tomar todos
    if not results:
        results = [str(v) for v in values if isinstance(v, Literal)]
    
    return results

# ===============================================
# BÚSQUEDA LOCAL MEJORADA CON MULTIIDIOMA
# ===============================================
def search_instances(term, language='es'):
    """Búsqueda mejorada con soporte multi-idioma"""
    tokens = tokenize_search_term(term)
    
    if not tokens:
        return []
    
    results = []
    seen = set()

    for inst in g.subjects(RDF.type, None):
        if inst in seen:
            continue

        # Obtener todos los literales de idioma que coincidan con el idioma de búsqueda
        inst_idioma_literal = [
            str(v) for v in g.objects(inst, NS.idioma)
            if isinstance(v, Literal) and getattr(v, 'language', None) == language
        ]

        # Si la instancia tiene idioma y no coincide con el deseado, se ignora
        if inst_idioma_literal:
            if inst_idioma_literal[0].lower() != LANGUAGES[language]['name'].lower():
                continue


        # ============================================
        # ESTRATEGIA DE BÚSQUEDA MEJORADA
        # ============================================
        relevance_score = 0
        matched_tokens = []

        # 1. Buscar en TODOS los literales de nombre (multiidioma)
        nombres_multiidioma = []
        for prop in [NS.nombre, RDFS.label]:
            for obj in g.objects(inst, prop):
                if isinstance(obj, Literal) and getattr(obj, "language", None) == language:
                    nombres_multiidioma.append(str(obj).lower())
        if not nombres_multiidioma:
            continue
        # Si no hay nombres en idioma deseado, fallback a inglés
        if not nombres_multiidioma:
            for prop in [NS.nombre, RDFS.label]:
                for obj in g.objects(inst, prop):
                    if isinstance(obj, Literal) and getattr(obj, 'language', None) == 'en':
                        nombres_multiidioma.append(str(obj).lower())

        # 2. Obtener nombre preferido para mostrar
        nombre_display = get_literal_by_language(inst, NS.nombre, language)
        if not nombre_display:
            nombre_display = get_literal_by_language(inst, RDFS.label, language)
        if not nombre_display:
            nombre_display = inst.split("#")[-1]

        # 3. Buscar coincidencias en nombres (cualquier idioma)
        for nombre in nombres_multiidioma:
            for token in tokens:
                if token in nombre:
                    relevance_score += 5  # Mayor peso para coincidencias en nombre
                    if token not in matched_tokens:
                        matched_tokens.append(token)

        # 4. Obtener información de la instancia
        clases = [cls.split("#")[-1] for cls in g.objects(inst, RDF.type)]
        clases_uris = list(g.objects(inst, RDF.type))
        
        # Detectar si es producto
        es_producto = False
        superclases_all = []
        for cls_uri in clases_uris:
            sups = get_all_superclasses(cls_uri)
            superclases_all.extend([s.split("#")[-1] for s in sups])
            if cls_uri.split("#")[-1].lower() == "producto" or "Producto" in [s.split("#")[-1] for s in sups]:
                es_producto = True

        # 5. Buscar en ingredientes/herramientas/técnicas
        ingredientes = []
        herramientas = []
        tecnicas = []

        for prop, obj in g.predicate_objects(inst):
            prop_name = prop.split("#")[-1]

            # Ingredientes
            if prop == NS.tieneIngrediente or "ingrediente" in prop_name.lower():
                # Buscar nombre del ingrediente solo en el idioma seleccionado
                ing_nombres = []
                for nombre_prop in [NS.nombre, RDFS.label]:
                    for ing_obj in g.objects(obj, nombre_prop):
                        if isinstance(ing_obj, Literal) and getattr(ing_obj, 'language', None) == language:
                            ing_nombres.append(str(ing_obj).lower())

                # Si no hay resultados en el idioma deseado, fallback a inglés
                if not ing_nombres:
                    for nombre_prop in [NS.nombre, RDFS.label]:
                        for ing_obj in g.objects(obj, nombre_prop):
                            if isinstance(ing_obj, Literal) and getattr(ing_obj, 'language', None) == 'en':
                                ing_nombres.append(str(ing_obj).lower())

                
                # Usar nombre en idioma preferido para mostrar
                ing_display = get_literal_by_language(obj, NS.nombre, language)
                if not ing_display:
                    ing_display = get_literal_by_language(obj, RDFS.label, language)
                if not ing_display:
                    ing_display = obj.split("#")[-1]
                ingredientes.append(ing_display)
                
                # Buscar coincidencias en todos los nombres del ingrediente
                for ing_nombre in ing_nombres:
                    for token in tokens:
                        if token in ing_nombre.lower():
                            relevance_score += 3  # Coincidencia en ingrediente
                            if token not in matched_tokens:
                                matched_tokens.append(token)

            # Herramientas
            elif prop == NS.usaHerramienta or "herramienta" in prop_name.lower():
                herr_nombres = []
                for nombre_prop in [NS.nombre, RDFS.label]:
                    for herr_obj in g.objects(obj, nombre_prop):
                        if isinstance(herr_obj, Literal):
                            herr_nombres.append(str(herr_obj))
                
                herr_display = get_literal_by_language(obj, NS.nombre, language)
                if not herr_display:
                    herr_display = get_literal_by_language(obj, RDFS.label, language)
                if not herr_display:
                    herr_display = obj.split("#")[-1]
                herramientas.append(herr_display)
                
                for herr_nombre in herr_nombres:
                    for token in tokens:
                        if token in herr_nombre.lower():
                            relevance_score += 2
                            if token not in matched_tokens:
                                matched_tokens.append(token)

            # Técnicas
            elif prop == NS.requiereTecnica or "tecnica" in prop_name.lower():
                tec_nombres = []
                for nombre_prop in [NS.nombre, RDFS.label]:
                    for tec_obj in g.objects(obj, nombre_prop):
                        if isinstance(tec_obj, Literal):
                            tec_nombres.append(str(tec_obj))
                
                tec_display = get_literal_by_language(obj, NS.nombre, language)
                if not tec_display:
                    tec_display = get_literal_by_language(obj, RDFS.label, language)
                if not tec_display:
                    tec_display = obj.split("#")[-1]
                tecnicas.append(tec_display)
                
                for tec_nombre in tec_nombres:
                    for token in tokens:
                        if token in tec_nombre.lower():
                            relevance_score += 2
                            if token not in matched_tokens:
                                matched_tokens.append(token)

        # 6. Buscar en clases y superclases
        for cls_name in clases + superclases_all:
            cls_lower = cls_name.lower()
            for token in tokens:
                if token in cls_lower:
                    relevance_score += 1
                    if token not in matched_tokens:
                        matched_tokens.append(token)

        # 7. Buscar en otros literales (descripción, etc.)
        atributos = {}
        for prop, obj in g.predicate_objects(inst):
            if prop == RDF.type:
                continue
            
            prop_name = prop.split("#")[-1]
            
            # Saltar propiedades ya procesadas
            if prop in [NS.tieneIngrediente, NS.usaHerramienta, NS.requiereTecnica]:
                continue
            if "ingrediente" in prop_name.lower() or "herramienta" in prop_name.lower() or "tecnica" in prop_name.lower():
                continue

            if isinstance(obj, Literal):
                # Buscar en el literal
                obj_str = str(obj).lower()
                for token in tokens:
                    if token in obj_str:
                        relevance_score += 1
                        if token not in matched_tokens:
                            matched_tokens.append(token)
                
                # Guardar atributo en idioma preferido
                if hasattr(obj, 'language'):
                    if obj.language == language:
                        atributos.setdefault(prop_name, []).append(str(obj))
                else:
                    atributos.setdefault(prop_name, []).append(str(obj))
            else:
                # Objeto no literal
                if not es_producto:
                    atributos.setdefault(prop_name, []).append(obj.split("#")[-1])

        # Solo incluir si hay coincidencias
        if relevance_score == 0:
            continue

        # 8. Buscar usos de esta instancia
        usada_en = []
        for s, p, o in g:
            if str(o) == str(inst):
                usada_en.append(str(s).split("#")[-1])

        results.append({
            "tipo": "instancia",
            "nombre": nombre_display,
            "clases": clases,
            "superclases": list(set(superclases_all)),
            "es_producto": es_producto,
            "ingredientes": ingredientes if es_producto else [],
            "herramientas": herramientas if es_producto else [],
            "tecnicas": tecnicas if es_producto else [],
            "atributos": atributos,
            "usada_en": list(set(usada_en)),
            "idioma": inst_idioma_literal[0] if inst_idioma_literal else language,
            "fuente": "local",
            "relevance": relevance_score
        })

        seen.add(inst)

    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    return results

def search_classes(term, language='es'):
    """Busca clases (sin filtro de idioma ya que las clases son universales)"""
    tokens = tokenize_search_term(term)
    
    if not tokens:
        return []
    
    results = []

    for cls in g.subjects(RDF.type, RDFS.Class):
        cls_name = cls.split("#")[-1]
        cls_name_lower = cls_name.lower()

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

    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    return results

# ===============================================
# CONFIGURACIÓN DE ENDPOINTS DBPEDIA POR IDIOMA
# ===============================================
DBPEDIA_ENDPOINTS = {
    'es': 'https://es.dbpedia.org/sparql',
    'en': 'https://dbpedia.org/sparql',
    'fr': 'https://fr.dbpedia.org/sparql',
    'it': 'https://it.dbpedia.org/sparql',
    'de': 'https://de.dbpedia.org/sparql',
    'pt': 'https://pt.dbpedia.org/sparql'
}

# Palabras clave de postres por idioma
DESSERT_KEYWORDS = {
    'es': ['pastel', 'tarta', 'galleta', 'postre', 'dulce', 'chocolate', 'helado', 'flan', 'natilla', 'mousse', 'brownie'],
    'en': ['cake', 'cookie', 'brownie', 'tart', 'pie', 'pudding', 'mousse', 'dessert', 'chocolate', 'pastry', 'sweet', 'ice cream'],
    'fr': ['gâteau', 'tarte', 'biscuit', 'dessert', 'chocolat', 'mousse', 'pâtisserie', 'glace', 'crème']
}

def search_dbpedia_food(term, language='es', limit=3, offset=0):
    """
    Búsqueda en DBpedia usando estrategia híbrida CORREGIDA
    Solo funciona para idiomas habilitados: español, inglés y francés
    
    Args:
        term: término de búsqueda
        language: idioma de búsqueda
        limit: número de resultados a retornar
        offset: número de resultados a saltar (para paginación)
    """
    # VERIFICAR SI EL IDIOMA ESTÁ HABILITADO PARA DBPEDIA
    if language not in DBPEDIA_ENABLED_LANGUAGES:
        print(f"❌ DBpedia no habilitado para el idioma: {language}")
        return []
    
    tokens = tokenize_search_term(term)
    
    if not tokens:
        return []
    
    print(f"🌐 Búsqueda DBpedia habilitada para: {LANGUAGES[language]['name']}")
    
    # Búsqueda normal solo para idiomas permitidos
    print(f"  → Intentando en {language}.dbpedia.org...")
    results = _search_in_endpoint(tokens, language, language, limit, offset)
    
    # Solo si NO hay resultados, intentar en el endpoint principal
    if len(results) == 0 and language != 'en':
        print(f"  → No se encontraron resultados en {language}.dbpedia.org")
        print(f"  → Buscando en dbpedia.org con etiquetas en {language}...")
        results = _search_in_endpoint(tokens, language, 'en', limit, offset, search_in_main=True)
    else:
        print(f"  ✓ Encontrados {len(results)} resultados en {language}.dbpedia.org")
    
    return results


def _search_in_endpoint(tokens, display_language, endpoint_language, limit=3, offset=0, search_in_main=False):
    """
    Función auxiliar para buscar en un endpoint específico - VERSIÓN CORREGIDA
    
    Args:
        tokens: lista de palabras clave de búsqueda
        display_language: idioma para mostrar resultados
        endpoint_language: idioma del endpoint a consultar
        limit: número de resultados a retornar
        offset: número de resultados a saltar
        search_in_main: si True, busca en endpoint principal con etiquetas en display_language
    """
    if search_in_main:
        endpoint = DBPEDIA_ENDPOINTS['en']
        label_lang = display_language
        endpoint_name = f"dbpedia.org (etiquetas: {display_language})"
    else:
        endpoint = DBPEDIA_ENDPOINTS.get(endpoint_language, DBPEDIA_ENDPOINTS['en'])
        label_lang = endpoint_language
        endpoint_name = endpoint.replace('https://', '').replace('/sparql', '')
    
    dessert_keywords = DESSERT_KEYWORDS.get(display_language, DESSERT_KEYWORDS['en'])
    
    results = []
    
    try:
        sparql = SPARQLWrapper(endpoint)
        sparql.setTimeout(30)
        
        # Crear filtro simple solo con el primer token
        main_token = tokens[0] if tokens else ""
        
        # Versión sin acentos
        import unicodedata
        nfd = unicodedata.normalize('NFD', main_token)
        token_normalized = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
        
        if token_normalized.lower() != main_token.lower():
            filter_conditions = f'(CONTAINS(LCASE(?label), LCASE("{main_token}")) || CONTAINS(LCASE(?label), LCASE("{token_normalized}")))'
        else:
            filter_conditions = f'CONTAINS(LCASE(?label), LCASE("{main_token}"))'
        
        # Construir prefijo de propiedades según idioma del endpoint
        if endpoint_language == 'es':
            prop_prefix = 'http://es.dbpedia.org/property/'
            ingredient_props = ['ingredientes', 'ingredients']
        elif endpoint_language == 'fr':
            prop_prefix = 'http://fr.dbpedia.org/property/'
            ingredient_props = ['ingrédients', 'ingredients']
        else:  # English
            prop_prefix = 'http://dbpedia.org/property/'
            ingredient_props = ['ingredients', 'ingredient']
        
        # CONSULTA SIMPLIFICADA Y OPTIMIZADA
        # Para inglés, filtrar solo por comida usando clases de DBpedia
        if endpoint_language == 'en':
            food_filter = """
            # Filtrar solo recursos relacionados con comida
            ?item a ?type .
            FILTER(
                ?type = dbo:Food || 
                ?type = dbo:Dessert ||
                ?type = <http://dbpedia.org/class/yago/Dessert107609840> ||
                ?type = <http://dbpedia.org/class/yago/BakedGoods107622061> ||
                ?type = <http://dbpedia.org/class/yago/Cake107628005> ||
                ?type = <http://dbpedia.org/class/yago/Cookie107655392> ||
                ?type = <http://dbpedia.org/class/yago/Pastry107622826>
            )
            """
        else:
            food_filter = ""
        
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX dbp: <{prop_prefix}>
        
        SELECT DISTINCT ?item ?label ?thumbnail ?abstract ?description
        WHERE {{
            ?item rdfs:label ?label .
            FILTER(LANG(?label) = "{label_lang}")
            FILTER({filter_conditions})
            
            {food_filter}
            
            OPTIONAL {{ ?item dbo:thumbnail ?thumbnail . }}
            
            OPTIONAL {{
                ?item dbo:abstract ?abstract .
                FILTER(LANG(?abstract) = "{label_lang}")
            }}
            
            OPTIONAL {{
                ?item dbo:description ?description .
                FILTER(LANG(?description) = "{label_lang}")
            }}
        }}
        LIMIT {limit}
        OFFSET {offset}
        """
        
        print(f"\n=== Buscando en {endpoint_name}: {' '.join(tokens)} ===")
        
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        query_results = sparql.query().convert()
        
        bindings = query_results['results']['bindings']
        print(f"✓ Encontrados {len(bindings)} resultados")
        
        processed_items = set()
        
        for result in bindings:
            item_uri = result["item"]["value"]
            
            if item_uri in processed_items:
                continue
            processed_items.add(item_uri)
            
            label = result.get("label", {}).get("value", item_uri.split("/")[-1])
            thumbnail_url = result.get("thumbnail", {}).get("value", None)
            
            print(f"  • {label}")
            
            # Descripción - intentar abstract primero, luego description
            abstract = result.get("abstract", {}).get("value", "")
            
            # Si no hay abstract, intentar con description
            if not abstract:
                abstract = result.get("description", {}).get("value", "")
            
            # Truncar si es muy largo
            if abstract and len(abstract) > 300:
                abstract = abstract[:297] + "..."
            elif not abstract:
                no_description = {
                    'es': 'Descripción no disponible',
                    'en': 'Description not available',
                    'fr': 'Description non disponible'
                }
                abstract = no_description.get(display_language, 'No description')
            
            # Obtener ingredientes en una segunda consulta MÁS LIGERA
            ingredientes = []
            try:
                ing_query = f"""
                PREFIX dbp: <{prop_prefix}>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX dbo: <http://dbpedia.org/ontology/>
                
                SELECT ?ing WHERE {{
                    <{item_uri}> dbp:{ingredient_props[0]} ?ing .
                }}
                LIMIT 5
                """
                
                sparql.setQuery(ing_query)
                ing_results = sparql.query().convert()
                
                for ing_result in ing_results['results']['bindings']:
                    ing_value = ing_result.get('ing', {}).get('value', '')
                    if ing_value:
                        # Limpiar
                        ing_clean = ing_value.strip()
                        if "http://" in ing_clean:
                            ing_clean = ing_clean.split("/")[-1].replace("_", " ")
                        ing_clean = re.sub(r'\([^)]*\)', '', ing_clean).strip()
                        if ing_clean and len(ing_clean) > 1:
                            ingredientes.append(ing_clean)
            except:
                pass  # Si falla la consulta de ingredientes, continuar sin ellos
            
            # Calcular relevancia
            relevance_score = 0
            label_lower = label.lower()
            for token in tokens:
                if token.lower() in label_lower:
                    relevance_score += 3
            
            for ing in ingredientes:
                for token in tokens:
                    if token.lower() in ing.lower():
                        relevance_score += 1
            
            # Construir resultado
            atributos = {
                "descripcion": [abstract],
                "dbpedia_uri": [item_uri]
            }
            
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
                "idioma": LANGUAGES[display_language]['name'],
                "fuente": f"dbpedia ({endpoint_name})",
                "relevance": relevance_score
            })
        
        print(f"✓ Procesados {len(results)} resultados correctamente\n")
        
    except Exception as e:
        error_msg = str(e)
        print(f"✗ Error en {endpoint_name}: {error_msg[:100]}")
        
        if "timeout" in error_msg.lower() or "10060" in error_msg:
            print(f"  → Timeout de conexión")
        elif "500" in error_msg:
            print(f"  → Error del servidor")
    
    results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
    return results

# ===============================================
# CONTROLADORES
# ===============================================
@app.route("/", methods=["GET", "POST"])
def index():
    term = ""
    language = request.form.get("language", "es")
    local_results = []

    if request.method == "POST":
        term = request.form.get("term", "").strip()
        if term:
            inst_res = search_instances(term, language)
            class_res = search_classes(term, language)
            local_results = inst_res + class_res

    return render_template("index.html", 
                         results=local_results, 
                         term=term, 
                         languages=LANGUAGES,
                         current_language=language)

@app.route("/dbpedia_search", methods=["POST"])
def dbpedia_search():
    term = request.json.get("term", "").strip()
    language = request.json.get("language", "es")
    limit = request.json.get("limit", 3)
    offset = request.json.get("offset", 0)
    
    # Verificar si el idioma está habilitado para DBpedia
    if language not in DBPEDIA_ENABLED_LANGUAGES:
        return jsonify({
            "error": "dbpedia_disabled",
            "message": f"DBpedia no está disponible para {LANGUAGES[language]['name']}",
            "enabled_languages": DBPEDIA_ENABLED_LANGUAGES
        })
    
    if term:
        dbpedia_results = search_dbpedia_food(term, language, limit, offset)
        return jsonify({
            "results": dbpedia_results,
            "has_more": len(dbpedia_results) == limit,
            "offset": offset,
            "limit": limit
        })
    return jsonify({"results": [], "has_more": False})

if __name__ == "__main__":
    app.run(debug=True)