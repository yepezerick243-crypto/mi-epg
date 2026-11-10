
import os
import re
import json
import requests
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache

URL_INTV = "https://intv.com.co/inicio/television/parrilla-de-television/"
CANAL_ID = "WarnerChannel.us@Colombia"
ZONA = ZoneInfo("America/Guayaquil")

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

TVMAZE_URL = "https://api.tvmaze.com"
TMDB_URL = "https://api.themoviedb.org/3"

ARCHIVO_XML = "epg.xml"

SESION = requests.Session()
SESION.headers.update({"User-Agent": "Mozilla/5.0"})


def extraer_json(texto, inicio):
    posicion = texto.find("{", inicio)

    if posicion == -1:
        return None

    profundidad = 0
    dentro_texto = False
    escape = False

    for i in range(posicion, len(texto)):
        caracter = texto[i]

        if dentro_texto:
            if escape:
                escape = False
            elif caracter == "\\":
                escape = True
            elif caracter == '"':
                dentro_texto = False
        else:
            if caracter == '"':
                dentro_texto = True
            elif caracter == "{":
                profundidad += 1
            elif caracter == "}":
                profundidad -= 1

                if profundidad == 0:
                    return texto[posicion:i + 1]

    return None


def obtener_programacion():
    respuesta = SESION.get(URL_INTV, timeout=30)
    respuesta.raise_for_status()

    inicio = respuesta.text.find("var tvGuideData")

    if inicio == -1:
        raise Exception("No se encontró tvGuideData en INTV.")

    contenido = extraer_json(respuesta.text, inicio)

    if not contenido:
        raise Exception("No se pudo extraer el JSON de INTV.")

    datos = json.loads(contenido)
    canales = datos.get("scheduleData", {})

    for nombre, informacion in canales.items():
        if nombre.strip().lower() == "warner channel":
            return informacion.get("programs", [])

    raise Exception("No se encontró Warner Channel.")


def convertir_fecha(milisegundos):
    fecha = datetime.fromtimestamp(
        int(milisegundos) / 1000,
        tz=ZONA
    )
    return fecha.strftime("%Y%m%d%H%M%S %z")


def fecha_xml_a_datetime(fecha):
    return datetime.strptime(
        fecha,
        "%Y%m%d%H%M%S %z"
    ).astimezone(ZONA)


def obtener_texto(programa, campos):
    for campo in campos:
        valor = programa.get(campo)

        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    return ""


@lru_cache(maxsize=300)
def buscar_tvmaze(nombre_serie):
    if not nombre_serie:
        return None

    try:
        respuesta = SESION.get(
            f"{TVMAZE_URL}/search/shows",
            params={"q": nombre_serie},
            timeout=15
        )
        respuesta.raise_for_status()

        resultados = respuesta.json()

        if resultados:
            return resultados[0]["show"]

    except Exception as error:
        print("Error TVmaze:", error)

    return None


@lru_cache(maxsize=300)
def buscar_tmdb(nombre, tipo):
    if not TMDB_API_KEY or not nombre:
        return None

    endpoint = "movie" if tipo == "movie" else "tv"

    try:
        respuesta = SESION.get(
            f"{TMDB_URL}/search/{endpoint}",
            params={
                "api_key": TMDB_API_KEY,
                "query": nombre,
                "language": "es-ES"
            },
            timeout=15
        )
        respuesta.raise_for_status()

        resultados = respuesta.json().get("results", [])

        if resultados:
            return resultados[0]

    except Exception as error:
        print("Error TMDb:", error)

    return None


def enriquecer_programa(elemento, programa):
    serie = obtener_texto(
        programa,
        ["series", "show", "program", "seriesTitle"]
    )

    tipo = obtener_texto(
        programa,
        ["type", "category", "genre"]
    ).lower()

    sinopsis = obtener_texto(
        programa,
        ["description", "synopsis", "overview"]
    )

    # TVmaze: información de series
    if serie:
        resultado = buscar_tvmaze(serie)

        if resultado and not sinopsis:
            sinopsis = resultado.get("summary") or ""

    # TMDb: información de películas o series
    if (
        "movie" in tipo
        or "pelicula" in tipo
        or "película" in tipo
    ):
        resultado = buscar_tmdb(
            programa.get("title", ""),
            "movie"
        )

    elif (
        "series" in tipo
        or "serie" in tipo
        or serie
    ):
        resultado = buscar_tmdb(
            serie or programa.get("title", ""),
            "tv"
        )

    else:
        resultado = None

    if resultado and not sinopsis:
        sinopsis = resultado.get("overview", "")

    if sinopsis:
        sinopsis = re.sub(
            r"<[^>]+>",
            "",
            sinopsis
        ).strip()

        descripcion = ET.SubElement(
            elemento,
            "desc",
            {"lang": "es"}
        )

        descripcion.text = sinopsis


def cargar_programas_anterior():
    programas = {}

    if not os.path.exists(ARCHIVO_XML):
        print("No existe un XML anterior. Se creará uno nuevo.")
        return programas

    try:
        arbol = ET.parse(ARCHIVO_XML)
        raiz = arbol.getroot()

        limite = datetime.now(ZONA) - timedelta(hours=24)

        for elemento in raiz.findall("programme"):
            canal = elemento.get("channel")
            inicio = elemento.get("start")
            fin = elemento.get("stop")

            if not canal or not inicio or not fin:
                continue

            try:
                fecha_fin = fecha_xml_a_datetime(fin)

                # Conservar programas que no hayan terminado
                # hace más de 24 horas.
                if fecha_fin < limite:
                    continue

                clave = (canal, inicio)
                programas[clave] = elemento

            except (ValueError, TypeError):
                continue

        print(
            "Programas recuperados del XML anterior:",
            len(programas)
        )

    except ET.ParseError:
        print("El XML anterior no se pudo leer. Se creará uno nuevo.")

    return programas


def crear_programa(programa):
    titulo = obtener_texto(programa, ["title"])

    inicio = programa.get("start")
    fin = programa.get("end")

    if not titulo or not inicio or not fin:
        return None

    try:
        inicio_num = int(inicio)
        fin_num = int(fin)

        if fin_num <= inicio_num:
            return None

        elemento = ET.Element(
            "programme",
            {
                "start": convertir_fecha(inicio_num),
                "stop": convertir_fecha(fin_num),
                "channel": CANAL_ID
            }
        )

        ET.SubElement(
            elemento,
            "title",
            {"lang": "es"}
        ).text = titulo

        enriquecer_programa(elemento, programa)

        return elemento

    except (ValueError, TypeError, OSError) as error:
        print("Error creando programa:", titulo, error)
        return None


def generar_xml():
    print("=" * 55)
    print("GENERADOR EPG WARNER CHANNEL")
    print("=" * 55)

    programas_intv = obtener_programacion()

    print(
        "Registros recibidos de INTV:",
        len(programas_intv)
    )

    # Recuperar los programas de ejecuciones anteriores
    programas_finales = cargar_programas_anterior()

    nuevos = 0
    actualizados = 0
    descartados = 0

    # Incorporar los datos nuevos de INTV
    for programa in programas_intv:
        titulo = obtener_texto(programa, ["title"])

        inicio = programa.get("start")
        fin = programa.get("end")

        if not titulo or not inicio or not fin:
            descartados += 1
            continue

        try:
            if int(fin) <= int(inicio):
                descartados += 1
                continue
        except (ValueError, TypeError):
            descartados += 1
            continue

        elemento = crear_programa(programa)

        if elemento is None:
            descartados += 1
            continue

        clave = (
            CANAL_ID,
            elemento.get("start")
        )

        if clave in programas_finales:
            actualizados += 1
        else:
            nuevos += 1

        # El dato nuevo reemplaza el anterior si coincide
        # el canal y la hora de inicio.
        programas_finales[clave] = elemento

    # Crear el XMLTV
    raiz = ET.Element(
        "tv",
        {"generator-info-name": "EPG Warner Channel INTV"}
    )

    canal = ET.SubElement(
        raiz,
        "channel",
        {"id": CANAL_ID}
    )

    ET.SubElement(
        canal,
        "display-name",
        {"lang": "es"}
    ).text = "Warner Channel"

    # Orden cronológico
    lista_ordenada = sorted(
        programas_finales.values(),
        key=lambda p: fecha_xml_a_datetime(p.get("start"))
    )

    for programa in lista_ordenada:
        raiz.append(programa)

    ET.indent(raiz, space="  ")

    ET.ElementTree(raiz).write(
        ARCHIVO_XML,
        encoding="UTF-8",
        xml_declaration=True
    )

    print("---------------------------------------")
    print("Programas nuevos:", nuevos)
    print("Programas actualizados:", actualizados)
    print("Registros descartados:", descartados)
    print("Total conservado:", len(lista_ordenada))
    print("Archivo generado:", ARCHIVO_XML)
    print("Zona horaria: America/Guayaquil")
    print("TVmaze integrado.")
    print(
        "TMDb:",
        "Configurado" if TMDB_API_KEY else "Sin clave"
    )
    print("---------------------------------------")


if __name__ == "__main__":
    generar_xml()
