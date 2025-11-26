"""
Script mejorado para poblar ontología de repostería con datos de DBpedia
Versión con creación dinámica de ingredientes
"""
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib import Graph, Namespace, RDF, RDFS, Literal, URIRef
from rdflib.namespace import XSD
import re
import time

# Definir namespaces
REP = Namespace("http://www.semanticweb.org/ontologies/reposteria#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")

class DBpediaPopulator:
    def __init__(self, rdf_file):
        """Inicializar con el archivo RDF existente"""
        self.graph = Graph()
        self.graph.parse(rdf_file, format="xml")
        self.graph.bind("", REP)
        self.graph.bind("owl", OWL)
        self.graph.bind("rdfs", RDFS)
        
        self.sparql = SPARQLWrapper("https://dbpedia.org/sparql")
        self.sparql.setReturnFormat(JSON)
        self.sparql.setTimeout(60)
        
        # Rastrear ingredientes creados
        self.created_ingredients = set()
        
    def search_desserts_by_category(self):
        """Buscar postres usando categorías de DBpedia"""
        query = """
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dct: <http://purl.org/dc/terms/>
        
        SELECT DISTINCT ?dessert ?name WHERE {
            {
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Desserts> .
            } UNION {
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Cakes> .
            } UNION {
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Cookies> .
            } UNION {
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Pastries> .
            } UNION {
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Pies> .
            } UNION {
                ?dessert dct:subject <http://dbpedia.org/resource/Category:Tarts> .
            }
            
            ?dessert rdfs:label ?name .
            FILTER (lang(?name) = "en")
        }
        LIMIT 100
        """
        
        self.sparql.setQuery(query)
        try:
            print("Consultando categorías de postres en DBpedia...")
            results = self.sparql.query().convert()
            return results["results"]["bindings"]
        except Exception as e:
            print(f"Error consultando DBpedia: {e}")
            return []
    
    def get_dessert_details(self, dessert_uri):
        """Obtener detalles de un postre específico"""
        query = f"""
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dbp: <http://dbpedia.org/property/>
        
        SELECT ?abstract ?country ?ingredient ?ingredientLabel WHERE {{
            OPTIONAL {{ 
                <{dessert_uri}> dbo:abstract ?abstract .
                FILTER (lang(?abstract) = "en" || lang(?abstract) = "es")
            }}
            
            OPTIONAL {{
                <{dessert_uri}> dbo:country ?country .
            }}
            
            OPTIONAL {{
                <{dessert_uri}> dbo:ingredient ?ingredient .
                OPTIONAL {{
                    ?ingredient rdfs:label ?ingredientLabel .
                    FILTER (lang(?ingredientLabel) = "en")
                }}
            }}
        }}
        LIMIT 20
        """
        
        self.sparql.setQuery(query)
        try:
            results = self.sparql.query().convert()
            return results["results"]["bindings"]
        except Exception as e:
            print(f"  Error obteniendo detalles: {e}")
            return []
    
    def clean_name(self, name):
        """Limpiar nombre para URI"""
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'[^\w\s-]', '', name)
        name = name.strip().replace(' ', '')
        return name
    
    def extract_country_name(self, country_uri):
        """Extraer nombre del país de la URI"""
        if not country_uri:
            return None
        name = country_uri.split('/')[-1].replace('_', ' ')
        return name
    
    def map_to_ontology_class(self, name):
        """Mapear nombre a clase de la ontología"""
        name_lower = name.lower()
        
        if any(word in name_lower for word in ['cookie', 'biscuit', 'macaroon']):
            return REP.Galleta
        elif any(word in name_lower for word in ['mousse', 'pudding', 'flan', 'custard', 'panna', 'syllabub', 'zabaglone']):
            return REP.PostreDeCuchara
        elif any(word in name_lower for word in ['cake', 'tart', 'pie', 'strudel', 'pastry', 'gateau', 'torte']):
            return REP.Pastel
        elif any(word in name_lower for word in ['candy', 'chocolate', 'truffle', 'bonbon', 'praline', 'nougat']):
            return REP.Confiteria
        else:
            return REP.Pastel
    
    def classify_ingredient(self, ingredient_name):
        """Clasificar un ingrediente según su tipo"""
        ing_lower = ingredient_name.lower()
        
        # Ingredientes de origen animal
        animal_keywords = ['egg', 'milk', 'cream', 'butter', 'cheese', 'yogurt', 'gelatin', 'honey']
        if any(keyword in ing_lower for keyword in animal_keywords):
            return REP.Animal
        
        # Aditivos
        aditivo_keywords = ['extract', 'essence', 'powder', 'yeast', 'baking', 'soda', 'coloring', 'color']
        if any(keyword in ing_lower for keyword in aditivo_keywords):
            return REP.Aditivo
        
        # Por defecto, vegetal
        return REP.Vegetal
    
    def create_ingredient(self, ingredient_name):
        """Crear un nuevo ingrediente en la ontología"""
        clean_id = self.clean_name(ingredient_name)
        ingredient_uri = REP[clean_id]
        
        # Verificar si ya existe
        if (ingredient_uri, RDF.type, OWL.NamedIndividual) in self.graph:
            return ingredient_uri
        
        # Verificar si ya lo creamos en esta sesión
        if clean_id in self.created_ingredients:
            return ingredient_uri
        
        print(f"    * Creando ingrediente: {ingredient_name}")
        
        # Agregar como individuo
        self.graph.add((ingredient_uri, RDF.type, OWL.NamedIndividual))
        
        # Clasificar el ingrediente
        ingredient_class = self.classify_ingredient(ingredient_name)
        self.graph.add((ingredient_uri, RDF.type, ingredient_class))
        
        # Agregar propiedades básicas
        self.graph.add((ingredient_uri, REP.nombre, Literal(ingredient_name)))
        self.graph.add((ingredient_uri, REP.descripcion, Literal(f"Ingrediente: {ingredient_name}")))
        
        # Registrar que lo creamos
        self.created_ingredients.add(clean_id)
        
        return ingredient_uri
    
    def map_ingredient(self, ingredient_name):
        """Mapear nombre de ingrediente a la ontología (existente o nuevo)"""
        # Diccionario de mapeo para ingredientes conocidos
        ingredient_map = {
            'sugar': REP.Azucar,
            'flour': REP.Harina,
            'egg': REP.Huevo,
            'butter': REP.Mantequilla,
            'milk': REP.Leche,
            'chocolate': REP.Chocolate,
            'cream': REP.Nata,
            'cheese': REP.Queso,
            'vanilla': REP.Vainilla,
            'lemon': REP.Limon,
            'apple': REP.Manzana,
            'banana': REP.Platano,
            'cinnamon': REP.Canela,
            'almond': REP.Almendras,
            'nut': REP.Nueces,
            'walnut': REP.Nueces,
            'coffee': REP.Cafe,
            'orange': REP.Naranja,
            'carrot': REP.Zanahoria,
            'coconut': REP.Coco,
            'strawberry': REP.Fresas,
            'yogurt': REP.Yogur
        }
        
        ing_lower = ingredient_name.lower()
        
        # Buscar en ingredientes conocidos
        for key, uri in ingredient_map.items():
            if key in ing_lower:
                return uri
        
        # Si no está en el mapa, crear uno nuevo
        return self.create_ingredient(ingredient_name)
    
    def add_dessert_to_ontology(self, name, dessert_uri, details):
        """Agregar un postre a la ontología"""
        clean_id = self.clean_name(name)
        individual_uri = REP[f"DBpedia_{clean_id}"]
        
        # Verificar si ya existe
        if (individual_uri, RDF.type, OWL.NamedIndividual) in self.graph:
            return False
        
        print(f"  + Agregando: {name}")
        
        # Agregar tipo
        self.graph.add((individual_uri, RDF.type, OWL.NamedIndividual))
        
        # Determinar clase
        product_class = self.map_to_ontology_class(name)
        self.graph.add((individual_uri, RDF.type, product_class))
        
        # Propiedades básicas
        self.graph.add((individual_uri, REP.nombre, Literal(name)))
        
        # Procesar detalles
        abstract = None
        country = None
        ingredients = []
        
        for detail in details:
            if 'abstract' in detail and not abstract:
                abstract = detail['abstract']['value']
                if len(abstract) > 300:
                    abstract = abstract[:297] + "..."
                self.graph.add((individual_uri, REP.descripcion, Literal(abstract)))
            
            if 'country' in detail and not country:
                country = self.extract_country_name(detail['country']['value'])
                if country:
                    self.graph.add((individual_uri, REP.paisOrigen, Literal(country)))
            
            if 'ingredientLabel' in detail:
                ing_name = detail['ingredientLabel']['value']
                # Ahora siempre obtendremos una URI (existente o nueva)
                ing_uri = self.map_ingredient(ing_name)
                if ing_uri not in ingredients:
                    self.graph.add((individual_uri, REP.tieneIngrediente, ing_uri))
                    ingredients.append(ing_uri)
        
        # No agregamos propiedades por defecto que no vengan de DBpedia
        # Solo agregamos lo que realmente encontramos en los datos
        
        # Referencia a DBpedia
        self.graph.add((individual_uri, RDFS.seeAlso, URIRef(dessert_uri)))
        
        return True
    
    def populate_from_dbpedia(self, max_desserts=30):
        """Proceso completo de población"""
        print(f"Buscando postres en DBpedia...")
        
        results = self.search_desserts_by_category()
        
        if not results:
            print("No se encontraron resultados en DBpedia")
            return
        
        print(f"\nEncontrados {len(results)} postres en categorías")
        print("\nAgregando postres a la ontología...\n")
        
        added_count = 0
        processed_count = 0
        
        for result in results:
            if added_count >= max_desserts:
                break
            
            name = result['name']['value']
            dessert_uri = result['dessert']['value']
            
            processed_count += 1
            print(f"[{processed_count}/{len(results)}] Procesando: {name}")
            
            # Obtener detalles
            details = self.get_dessert_details(dessert_uri)
            
            # Agregar a la ontología
            if self.add_dessert_to_ontology(name, dessert_uri, details):
                added_count += 1
            else:
                print(f"  - Ya existe")
            
            # Pequeña pausa para no saturar el servidor
            time.sleep(0.5)
        
        print(f"\n{'='*60}")
        print(f"✓ Se agregaron {added_count} nuevos postres")
        print(f"✓ Se crearon {len(self.created_ingredients)} nuevos ingredientes")
        print(f"✓ Se procesaron {processed_count} resultados")
        print(f"✓ Total de individuos en la ontología: {len(list(self.graph.subjects(RDF.type, OWL.NamedIndividual)))}")
        print(f"{'='*60}")
    
    def save(self, output_file):
        """Guardar la ontología actualizada"""
        self.graph.serialize(destination=output_file, format='xml')
        print(f"\n✓ Ontología guardada en: {output_file}")


# Uso del script
if __name__ == "__main__":
    print("=" * 60)
    print("POBLADOR DE ONTOLOGÍA DESDE DBPEDIA")
    print("Con creación dinámica de ingredientes")
    print("=" * 60)
    
    input_file = "reposteria.rdf"
    output_file = "reposteria_poblada.rdf"
    
    populator = DBpediaPopulator(input_file)
    populator.populate_from_dbpedia(max_desserts=30)
    populator.save(output_file)
    
    print("\n" + "=" * 60)
    print("PROCESO COMPLETADO")
    print("=" * 60)