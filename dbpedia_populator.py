"""
Script para poblar ontología obteniendo postres de DBpedia inglés
y traduciéndolos a múltiples idiomas con deep-translator (GRATIS)
CORREGIDO: Obtiene dbo:description además de dbo:abstract
"""
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib import Graph, Namespace, RDF, RDFS, Literal, URIRef
from rdflib.namespace import XSD
from deep_translator import GoogleTranslator
import re
import time

# Definir namespaces
REP = Namespace("http://www.semanticweb.org/ontologies/reposteria#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")

class DBpediaDeepTranslatorPopulator:
    def __init__(self, rdf_file):
        """Inicializar con el archivo RDF"""
        self.graph = Graph()
        try:
            self.graph.parse(rdf_file, format="xml")
            print(f"✓ Ontología cargada: {rdf_file}")
        except Exception as e:
            print(f"✗ Error cargando ontología: {e}")
            raise
        
        self.graph.bind("", REP)
        self.graph.bind("owl", OWL)
        self.graph.bind("rdfs", RDFS)
        
        print(f"✓ deep-translator inicializado (Google Translate gratuito)")
        
        # DBpedia endpoint (solo inglés)
        self.sparql = SPARQLWrapper('https://dbpedia.org/sparql')
        self.sparql.setReturnFormat(JSON)
        self.sparql.setTimeout(120)
        self.sparql.addCustomHttpHeader("User-Agent", "Mozilla/5.0 (compatible; OntologyPopulator/1.0)")
        
        # Idiomas objetivo (códigos ISO 639-1)
        self.target_languages = {
            'es': 'Español',
            'fr': 'Francés',
            'it': 'Italiano',
            'de': 'Alemán',
            'pt': 'Portugués'
        }
        
        # Cache de traductores por idioma (más eficiente)
        self.translators = {}
        for lang in self.target_languages.keys():
            self.translators[lang] = GoogleTranslator(source='en', target=lang)
        
        self.created_ingredients = {}  # {(nombre_en, lang): uri}
        self.processed_desserts = set()
        self.translation_cache = {}  # Cache para evitar traducciones repetidas
        
    def search_desserts_dbpedia(self, limit=15):
        """
        Buscar postres en DBpedia inglés
        CORREGIDO: Obtiene tanto dbo:abstract como dbo:description
        """
        query = f"""
        PREFIX dct: <http://purl.org/dc/terms/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dbo: <http://dbpedia.org/ontology/>
        
        SELECT DISTINCT ?dessert ?name ?abstract ?description WHERE {{
            {{
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Desserts> .
            }} UNION {{
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Cakes> .
            }} UNION {{
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Pastries> .
            }} UNION {{
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Cookies> .
            }}
            
            ?dessert rdfs:label ?name .
            FILTER (LANG(?name) = "en")
            
            # Intentar obtener abstract
            OPTIONAL {{
                ?dessert dbo:abstract ?abstract .
                FILTER (LANG(?abstract) = "en")
            }}
            
            # Intentar obtener description
            OPTIONAL {{
                ?dessert dbo:description ?description .
                FILTER (LANG(?description) = "en")
            }}
            
            FILTER (!REGEX(STR(?dessert), "Categ", "i"))
        }}
        LIMIT {limit}
        """
        
        self.sparql.setQuery(query)
        
        try:
            print(f"\n  Consultando DBpedia inglés...")
            results = self.sparql.query().convert()
            desserts = results["results"]["bindings"]
            print(f"  ✓ Encontrados {len(desserts)} postres en inglés")
            return desserts
        except Exception as e:
            print(f"  ✗ Error consultando DBpedia: {e}")
            return []
    
    def get_dessert_ingredients(self, dessert_uri):
        """Obtener ingredientes de un postre"""
        query = f"""
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dbp: <http://dbpedia.org/property/>
        
        SELECT DISTINCT ?ingredient ?ingredientLabel WHERE {{
            {{
                <{dessert_uri}> dbo:ingredient ?ingredient .
            }} UNION {{
                <{dessert_uri}> dbp:ingredient ?ingredient .
            }} UNION {{
                <{dessert_uri}> dbp:ingredients ?ingredient .
            }} UNION {{
                <{dessert_uri}> dbp:mainIngredient ?ingredient .
            }}
            
            OPTIONAL {{
                ?ingredient rdfs:label ?ingredientLabel .
                FILTER (LANG(?ingredientLabel) = "en")
            }}
        }}
        LIMIT 15
        """
        
        self.sparql.setQuery(query)
        
        try:
            results = self.sparql.query().convert()
            ingredients = []
            for binding in results["results"]["bindings"]:
                if 'ingredientLabel' in binding:
                    ingredients.append(binding['ingredientLabel']['value'])
                elif 'ingredient' in binding and binding['ingredient'].get('type') == 'literal':
                    ingredients.append(binding['ingredient']['value'])
            return ingredients
        except Exception as e:
            return []
    
    def get_dessert_country(self, dessert_uri):
        """Obtener país de origen"""
        query = f"""
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX dbp: <http://dbpedia.org/property/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?country ?countryLabel WHERE {{
            {{
                <{dessert_uri}> dbo:country ?country .
            }} UNION {{
                <{dessert_uri}> dbo:origin ?country .
            }} UNION {{
                <{dessert_uri}> dbp:country ?country .
            }}
            
            OPTIONAL {{
                ?country rdfs:label ?countryLabel .
                FILTER (LANG(?countryLabel) = "en")
            }}
        }}
        LIMIT 1
        """
        
        self.sparql.setQuery(query)
        
        try:
            results = self.sparql.query().convert()
            if results["results"]["bindings"]:
                result = results["results"]["bindings"][0]
                if 'countryLabel' in result:
                    return result['countryLabel']['value']
                elif 'country' in result:
                    return result['country']['value'].split('/')[-1].replace('_', ' ')
            return None
        except Exception as e:
            return None
    
    def translate_text(self, text, target_lang, max_retries=3):
        """Traducir texto usando deep-translator con reintentos"""
        if not text or text.strip() == "":
            return None
        
        # Verificar cache
        cache_key = (text[:100], target_lang)  # Usar primeros 100 chars como key
        if cache_key in self.translation_cache:
            return self.translation_cache[cache_key]
        
        # Limitar longitud (deep-translator tiene límite de ~5000 chars)
        if len(text) > 4500:
            text = text[:4500]
        
        translator = self.translators[target_lang]
        
        for attempt in range(max_retries):
            try:
                translated = translator.translate(text)
                
                # Guardar en cache
                self.translation_cache[cache_key] = translated
                return translated
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"      ⚠ Reintentando traducción... ({attempt + 1}/{max_retries})")
                    time.sleep(1)
                    # Recrear traductor si falla
                    self.translators[target_lang] = GoogleTranslator(source='en', target=target_lang)
                    translator = self.translators[target_lang]
                else:
                    print(f"      ⚠ Error traduciendo a {target_lang}: {e}")
                    return None
        
        return None
    
    def clean_name(self, name):
        """Limpiar nombre para URI"""
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'[^\w\s-]', '', name, flags=re.UNICODE)
        name = name.strip().replace(' ', '_')
        if len(name) > 50:
            name = name[:50]
        return name
    
    def map_to_ontology_class(self, name_en):
        """Mapear nombre inglés a clase de la ontología"""
        name_lower = name_en.lower()
        
        if any(word in name_lower for word in ['cookie', 'biscuit', 'macaroon']):
            return REP.Galleta
        elif any(word in name_lower for word in ['mousse', 'pudding', 'custard', 'flan']):
            return REP.PostreDeCuchara
        elif any(word in name_lower for word in ['cake', 'tart', 'pie', 'pastry']):
            return REP.Pastel
        elif any(word in name_lower for word in ['candy', 'chocolate', 'truffle', 'bonbon']):
            return REP.Confiteria
        else:
            return REP.Pastel
    
    def classify_ingredient(self, ingredient_name):
        """Clasificar ingrediente por tipo"""
        ing_lower = ingredient_name.lower()
        
        animal_keywords = [
            'egg', 'milk', 'cream', 'butter', 'cheese', 'yogurt', 
            'gelatin', 'honey', 'whey', 'dairy', 'lard'
        ]
        if any(keyword in ing_lower for keyword in animal_keywords):
            return REP.Animal
        
        aditivo_keywords = [
            'extract', 'essence', 'powder', 'yeast', 'baking', 
            'coloring', 'vanilla', 'soda', 'salt', 'cinnamon'
        ]
        if any(keyword in ing_lower for keyword in aditivo_keywords):
            return REP.Aditivo
        
        return REP.Vegetal
    
    def create_ingredient(self, ingredient_name_en, target_lang, lang_code):
        """Crear o reutilizar ingrediente traducido"""
        # Verificar si ya existe este ingrediente en este idioma
        cache_key = (ingredient_name_en, lang_code)
        if cache_key in self.created_ingredients:
            return self.created_ingredients[cache_key]
        
        # Traducir nombre del ingrediente (si no es inglés)
        if target_lang:
            ingredient_name_translated = self.translate_text(ingredient_name_en, target_lang)
            if not ingredient_name_translated:
                ingredient_name_translated = ingredient_name_en
        else:
            ingredient_name_translated = ingredient_name_en
        
        # Crear URI única
        clean_id = self.clean_name(ingredient_name_translated)
        ingredient_uri = REP[f"Ing_{clean_id}_{lang_code}"]
        
        # Verificar si ya existe en el grafo
        if (ingredient_uri, RDF.type, OWL.NamedIndividual) not in self.graph:
            self.graph.add((ingredient_uri, RDF.type, OWL.NamedIndividual))
            ingredient_class = self.classify_ingredient(ingredient_name_en)
            self.graph.add((ingredient_uri, RDF.type, ingredient_class))
            
            # Agregar nombre en el idioma traducido
            self.graph.add((ingredient_uri, REP.nombre, Literal(ingredient_name_translated, lang=lang_code)))
            
            # Agregar también nombre original en inglés (para referencia)
            if lang_code != 'en':
                self.graph.add((ingredient_uri, REP.nombre, Literal(ingredient_name_en, lang='en')))
        
        self.created_ingredients[cache_key] = ingredient_uri
        return ingredient_uri
    
    def add_dessert_with_translations(self, dessert_data):
        """
        Agregar un postre en inglés y crear versiones traducidas
        en todos los idiomas objetivo
        CORREGIDO: Prioriza description sobre abstract
        """
        dessert_uri = dessert_data['dessert']['value']
        name_en = dessert_data['name']['value']
        
        # Priorizar description sobre abstract
        description_en = dessert_data.get('description', {}).get('value', '')
        abstract_en = dessert_data.get('abstract', {}).get('value', '')
        
        # Usar description si existe, si no usar abstract
        text_en = description_en if description_en else abstract_en
        
        # Verificar si ya procesamos este postre
        if dessert_uri in self.processed_desserts:
            return 0
        
        self.processed_desserts.add(dessert_uri)
        
        print(f"\n  {'─'*66}")
        print(f"  📍 POSTRE: {name_en}")
        print(f"  {'─'*66}")
        
        # Mostrar qué tipo de texto se encontró
        if description_en:
            print(f"    ✓ Description encontrada: {description_en[:80]}...")
        elif abstract_en:
            print(f"    ℹ Abstract encontrado: {abstract_en[:80]}...")
        else:
            print(f"    ⚠ Sin descripción ni abstract")
        
        # Obtener datos comunes
        ingredients_en = self.get_dessert_ingredients(dessert_uri)
        country_en = self.get_dessert_country(dessert_uri)
        product_class = self.map_to_ontology_class(name_en)
        
        if ingredients_en:
            print(f"    Ingredientes originales: {', '.join(ingredients_en[:5])}")
        if country_en:
            print(f"    País de origen: {country_en}")
        
        added_count = 0
        
        # Primero agregar versión en inglés
        print(f"\n    🇬🇧 Inglés (original):")
        if self._add_dessert_version(
            name_en, text_en, ingredients_en, country_en, 
            product_class, dessert_uri, 'en', 'Inglés', None
        ):
            added_count += 1
        
        # Luego agregar versiones traducidas
        for lang_code, lang_name in self.target_languages.items():
            print(f"\n    🌍 {lang_name}:")
            
            # Traducir nombre
            name_translated = self.translate_text(name_en, lang_code)
            if not name_translated:
                print(f"      ⚠ No se pudo traducir el nombre, usando original")
                name_translated = name_en
            
            print(f"      Nombre: {name_translated}")
            
            # Traducir descripción/abstract (truncar si es muy larga)
            text_translated = None
            if text_en:
                text_short = text_en[:400]  # Limitar longitud
                text_translated = self.translate_text(text_short, lang_code)
                if text_translated:
                    if len(text_translated) > 300:
                        text_translated = text_translated[:297] + "..."
                    print(f"      Descripción: {text_translated[:60]}...")
            
            # Traducir país
            country_translated = None
            if country_en:
                country_translated = self.translate_text(country_en, lang_code)
                if not country_translated:
                    country_translated = country_en
            
            # Agregar versión traducida
            if self._add_dessert_version(
                name_translated, text_translated, ingredients_en, 
                country_translated, product_class, dessert_uri, 
                lang_code, lang_name, lang_code
            ):
                added_count += 1
            
            # Pausa para evitar rate limiting
            time.sleep(0.3)
        
        print(f"\n  ✓ Agregado en {added_count} idiomas")
        return added_count
    
    def _add_dessert_version(self, name, text, ingredients_en, country, 
                            product_class, dbpedia_uri, lang_iso, lang_name, target_lang):
        """Agregar una versión específica del postre en un idioma"""
        try:
            clean_id = self.clean_name(name)
            individual_uri = REP[f"{lang_iso.upper()}_{clean_id}"]
            
            # Verificar si ya existe
            if (individual_uri, RDF.type, OWL.NamedIndividual) in self.graph:
                print(f"      ⚠ Ya existe en la ontología")
                return False
            
            # Agregar tipos
            self.graph.add((individual_uri, RDF.type, OWL.NamedIndividual))
            self.graph.add((individual_uri, RDF.type, product_class))
            
            # Propiedades básicas
            self.graph.add((individual_uri, REP.nombre, Literal(name, lang=lang_iso)))
            self.graph.add((individual_uri, REP.idioma, Literal(lang_name)))
            
            # Descripción (texto puede ser description o abstract)
            if text:
                self.graph.add((individual_uri, REP.descripcion, Literal(text, lang=lang_iso)))
                print(f"      ✓ Descripción agregada ({len(text)} caracteres)")
            else:
                print(f"      ⚠ Sin descripción disponible")
            
            # País
            if country:
                self.graph.add((individual_uri, REP.paisOrigen, Literal(country)))
            
            # Ingredientes (traducir y agregar)
            if ingredients_en:
                print(f"      Ingredientes:", end=" ")
                added_ings = []
                for i, ing_en in enumerate(ingredients_en[:8]):  # Limitar a 8
                    ing_uri = self.create_ingredient(ing_en, target_lang, lang_iso)
                    self.graph.add((individual_uri, REP.tieneIngrediente, ing_uri))
                    
                    if i < 3:  # Mostrar solo los primeros 3
                        ing_names = list(self.graph.objects(ing_uri, REP.nombre))
                        if ing_names:
                            # Buscar el nombre en el idioma correcto
                            for ing_name in ing_names:
                                if hasattr(ing_name, 'language') and ing_name.language == lang_iso:
                                    added_ings.append(str(ing_name))
                                    break
                
                if added_ings:
                    print(", ".join(added_ings[:3]) + ("..." if len(ingredients_en) > 3 else ""))
                else:
                    print(f"{len(ingredients_en)} agregados")
            
            # Referencia a DBpedia original
            self.graph.add((individual_uri, RDFS.seeAlso, URIRef(dbpedia_uri)))
            
            print(f"      ✓ Agregado exitosamente")
            return True
            
        except Exception as e:
            print(f"      ✗ Error: {e}")
            return False
    
    def populate_with_translations(self, num_desserts=10):
        """
        Poblar ontología obteniendo postres de DBpedia inglés
        y traduciéndolos a múltiples idiomas
        """
        print(f"\n{'='*70}")
        print(f"POBLACIÓN CON DEEP-TRANSLATOR (GOOGLE - GRATUITO)")
        print(f"Fuente: DBpedia Inglés → Traducción a {len(self.target_languages)} idiomas")
        print(f"{'='*70}\n")
        
        # Buscar postres en inglés
        desserts = self.search_desserts_dbpedia(limit=num_desserts)
        
        if not desserts:
            print("⚠ No se encontraron postres")
            return
        
        total_versions = 0
        desserts_with_description = 0
        
        for i, dessert in enumerate(desserts, 1):
            print(f"\n[{i}/{len(desserts)}]")
            
            # Contar si tiene descripción
            if dessert.get('description', {}).get('value') or dessert.get('abstract', {}).get('value'):
                desserts_with_description += 1
            
            versions_added = self.add_dessert_with_translations(dessert)
            total_versions += versions_added
            
            # Pausa entre postres
            time.sleep(0.5)
        
        # Estadísticas finales
        print(f"\n{'='*70}")
        print(f"RESULTADOS FINALES")
        print(f"{'='*70}")
        print(f"✓ Postres procesados: {len(desserts)}")
        print(f"✓ Postres con descripción/abstract: {desserts_with_description}")
        print(f"✓ Versiones de idioma creadas: {total_versions}")
        print(f"✓ Ingredientes únicos creados: {len(self.created_ingredients)}")
        print(f"✓ Traducciones en cache: {len(self.translation_cache)}")
        
        total_individuals = len(list(self.graph.subjects(RDF.type, OWL.NamedIndividual)))
        print(f"✓ Total de individuos en ontología: {total_individuals}")
        
        print(f"\nIdiomas incluidos:")
        print(f"  • Inglés (original)")
        for lang_code, lang_name in self.target_languages.items():
            print(f"  • {lang_name}")
        
        print(f"{'='*70}")
    
    def save(self, output_file):
        """Guardar la ontología actualizada"""
        try:
            self.graph.serialize(destination=output_file, format='xml')
            print(f"\n✓ Ontología guardada exitosamente en: {output_file}")
        except Exception as e:
            print(f"\n✗ Error guardando ontología: {e}")


# Uso del script
if __name__ == "__main__":
    print("=" * 70)
    print("POBLADOR CON DEEP-TRANSLATOR (100% GRATUITO)")
    print("Obtiene postres de DBpedia Inglés y los traduce automáticamente")
    print("CORREGIDO: Prioriza dbo:description sobre dbo:abstract")
    print("=" * 70)
    
    # CONFIGURACIÓN
    input_file = "reposteria.rdf"
    output_file = "reposteria_poblada_google.rdf"
    
    try:
        populator = DBpediaDeepTranslatorPopulator(input_file)
        
        # Ajusta cuántos postres quieres procesar
        populator.populate_with_translations(num_desserts=50)
        
        populator.save(output_file)
        
        print("\n" + "=" * 70)
        print("✓ PROCESO COMPLETADO EXITOSAMENTE")
        print("=" * 70)
        print("\nCada postre ahora existe en 6 idiomas:")
        print("  • Versión original en inglés de DBpedia")
        print("  • Versión traducida al español")
        print("  • Versión traducida al francés")
        print("  • Versión traducida al italiano")
        print("  • Versión traducida al alemán")
        print("  • Versión traducida al portugués")
        print("\n💡 Ventaja: 100% GRATUITO con deep-translator")
        print("📝 Ahora captura dbo:description (más corta) y dbo:abstract (más larga)")
        
    except Exception as e:
        print(f"\n✗ ERROR CRÍTICO: {e}")
        import traceback
        traceback.print_exc()