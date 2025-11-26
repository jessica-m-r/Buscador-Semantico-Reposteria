BUSCADOR SEMÁNTICO – REPOSTERÍA

Buscador semántico basado en una ontología RDF/OWL del dominio de la repostería.
Permite explorar postres, ingredientes, utensilios y técnicas, mostrando relaciones y atributos de forma estructurada.
Funciona localmente con la ontología poblada y puede realizar consultas dinámicas a DBpedia para información adicional.

------------------------------------------------------------

CONTENIDO DEL REPOSITORIO

- app.py                 : Aplicación Flask que carga la ontología local (reposteria_poblada.rdf) y realiza búsquedas. También puede consultar DBpedia.
- templates/             : Plantillas HTML para la interfaz del buscador.
- static/css/styles.css  : Estilos de la interfaz.
- reposteria.rdf         : Ontología base en formato OWL/RDF con clases y relaciones.
- dbpedia_populator.py   : Script para poblar la ontología automáticamente desde DBpedia con postres e ingredientes.
- reposteria_poblada.rdf : Ontología resultante después de poblarla (generada por dbpedia_populator.py).

------------------------------------------------------------

REQUISITOS

Instalar librerías necesarias:
pip install flask rdflib SPARQLWrapper

------------------------------------------------------------

USO DE LA APLICACIÓN (LOCAL Y DBPEDIA)

1. Asegúrate de tener app.py y reposteria_poblada.rdf en la misma carpeta.
2. Instala las dependencias.
3. Ejecuta la aplicación:
   python app.py
4. Abre en el navegador:
   http://127.0.0.1:5000

Nota: La aplicación usará la ontología local para búsquedas principales y puede realizar consultas a DBpedia para información adicional de postres o ingredientes.

------------------------------------------------------------

POBLACIÓN DE LA ONTOLOGÍA DESDE DBPEDIA

Para llenar la ontología con postres e ingredientes automáticamente:
python dbpedia_populator.py 
Este proceso crea dinámicamente nuevos ingredientes si no existen en la ontología y asigna clases según el tipo de postre o ingrediente.

------------------------------------------------------------

NOTAS

- Funciona de manera local usando la ontología poblada.
- Búsqueda semántica basada en clases, propiedades y relaciones.
- Librerías utilizadas:
  * Flask          : Servidor web y API.
  * RDFlib         : Manejo y consulta de la ontología RDF/OWL.
  * SPARQLWrapper  : Consulta a DBpedia para poblar o complementar información.
- La ontología base (reposteria.rdf) puede poblarse automáticamente con dbpedia_populator.py.
