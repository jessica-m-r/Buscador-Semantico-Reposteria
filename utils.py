# utils.py
from rdflib import Graph, RDFS, RDF, Namespace, Literal, URIRef
from typing import List, Dict, Any
from SPARQLWrapper import SPARQLWrapper, JSON


class OntologyHelper:
    def __init__(self, rdf_path: str, ns_uri: str = "http://www.semanticweb.org/ontologies/reposteria#"):
        self.rdf_path = rdf_path
        self.g = Graph()
        self.g.parse(rdf_path, format="xml")
        self.NS = Namespace(ns_uri)

    def _short(self, uri) -> str:
        if isinstance(uri, Literal):
            return str(uri)
        try:
            return str(uri).split("#")[-1]
        except Exception:
            return str(uri)

    # -------------------------
    # INSTANCIAS
    # -------------------------
    def search_instances(self, term: str) -> List[Dict[str, Any]]:
        term_lower = term.lower()
        results = []
        seen = set()

        for inst in self.g.subjects(RDF.type, None):
            if inst in seen:
                continue

            nombre_literal = self.g.value(inst, self.NS.nombre)
            inst_name = self._short(nombre_literal) if nombre_literal else self._short(inst)

            if term_lower and term_lower not in inst_name.lower():
                continue

            clases = [self._short(c) for c in self.g.objects(inst, RDF.type)]
            superclases = []
            for cls_uri in self.g.objects(inst, RDF.type):
                superclases += [self._short(s) for s in self.g.objects(cls_uri, RDFS.subClassOf)]

            es_producto = any("producto" in c.lower() for c in superclases + clases)

            ingredientes, herramientas, tecnicas = [], [], []
            atributos: Dict[str, List[str]] = {}

            for prop, obj in self.g.predicate_objects(inst):
                if prop == RDF.type:
                    continue

                # Propiedades específicas de Producto
                if es_producto:
                    if prop == self.NS.tieneIngrediente:
                        ingredientes.append(self._short(obj))
                        continue
                    if prop == self.NS.usaHerramienta:
                        herramientas.append(self._short(obj))
                        continue
                    if prop == self.NS.requiereTecnica:
                        tecnicas.append(self._short(obj))
                        continue

                # Literales -> atributos
                if isinstance(obj, Literal):
                    atributos.setdefault(self._short(prop), []).append(str(obj))
                else:
                    atributos.setdefault(self._short(prop), []).append(self._short(obj))
                        # Usado en
            usada_en = []
            for s, p, o in self.g.triples((None, None, None)):
                if str(o) == str(inst):
                    usada_en.append(self._short(s))

            # Descripción, categorías y URI DBpedia
            descripcion = self.g.value(inst, self.NS.descripcionDBpedia)
            categorias = [self._short(s) for s in self.g.objects(inst, self.NS.tieneCategoriaDBpedia)]
            dbpedia_uri = self.g.value(inst, self.NS.dbpediaURI)

            results.append({
                "tipo": "instancia",
                "nombre": inst_name,
                "uri": str(inst),
                "clases": clases,
                "superclases": list(set(superclases)),
                "es_producto": es_producto,
                "ingredientes": list(dict.fromkeys(ingredientes)),
                "herramientas": list(dict.fromkeys(herramientas)),
                "tecnicas": list(dict.fromkeys(tecnicas)),
                "atributos": atributos,
                "usada_en": list(dict.fromkeys(usada_en)),
                "descripcion": str(descripcion) if descripcion else "",
                "categorias": categorias,
                "dbpedia_uri": str(dbpedia_uri) if dbpedia_uri else ""
            })
            seen.add(inst)

        return results

    # -------------------------
    # Búsqueda múltiple términos
    # -------------------------
    def search_instances_multiple_terms(self, terms: List[str]) -> List[Dict[str, Any]]:
        if not terms:
            return self.search_instances("")
        all_results = self.search_instances("")
        filtered = []
        lower_terms = [t.lower() for t in terms]
        for r in all_results:
            combined_parts = [
                r.get("nombre", ""),
                " ".join(r.get("clases", [])),
                " ".join(r.get("superclases", [])),
                " ".join(r.get("ingredientes", [])),
                " ".join(r.get("herramientas", [])),
                " ".join(r.get("tecnicas", [])),
                " ".join([f"{k} {' '.join(v)}" for k, v in r.get("atributos", {}).items()]),
                r.get("descripcion", ""),
                " ".join(r.get("categorias", [])),
            ]
            texto = " ".join(combined_parts).lower()
            if all(t in texto for t in lower_terms):
                filtered.append(r)
        return filtered

    # -------------------------
    # Consultar DBpedia online solo bajo demanda
    # -------------------------
    @staticmethod
    def fetch_from_dbpedia(uri: str) -> Dict[str, Any]:
        sparql = SPARQLWrapper("https://dbpedia.org/sparql")
        sparql.setReturnFormat(JSON)
        sparql.setQuery(f"""
        SELECT ?abstract ?thumbnail WHERE {{
            <{uri}> dbo:abstract ?abstract .
            OPTIONAL {{ <{uri}> dbo:thumbnail ?thumbnail . }}
            FILTER (lang(?abstract) = 'en')
        }} LIMIT 1
        """)
        try:
            results = sparql.query().convert()["results"]["bindings"]
            if results:
                r = results[0]
                return {
                    "abstract": r["abstract"]["value"],
                    "thumbnail": r.get("thumbnail", {}).get("value", "")
                }
            return {}
        except Exception:
            return {}
