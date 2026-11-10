
import os
import re
import json
import time
import unicodedata
import requests
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache

# =========================================================
# CONFIGURACION
# =========================================================

URL_INTV = "https://intv.com.co/inicio/television/parrilla-de-television/"

CANAL_ID = "WarnerChannel.us@Colombia"
ZONA = ZoneInfo("America/Guayaquil")

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

TVMAZE_URL = "https://api.tvmaze.com"
TMDB_URL = "https://api.themoviedb.org/3"

ARCHIVO_XML = "epg.xml"

# Series cuyos episodios aparecen en la lista de INTV.
SERIES_CONOCIDAS = [
    "The Big Bang Theory",
    "Two and a Half Men",
    "Cobra Kai",
]

# Nombres en español como respaldo si TMDb no devuelve
# una traducción española para alguna serie.
NOMBRES_SERIES_ES = {
    "the big bang theory": "La teoría del Big Bang",
    "two and a half men": "Dos hombres y medio",
    "cobra kai": "Cobra Kai",
}

SESION = requests.Session()
SESION.headers.update({"User-Agent": "Mozilla/5.0"})


# =========================================================
# UTILIDADES
# =========================================================

def normalizar(texto):
    texto = str(texto or "").strip().lower()

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    texto = re.sub(r"[^a-z0-9]+", " ", texto)

    return " ".join(texto.split())


def obtener_texto(programa, campos):
    for campo in campos:
        valor = programa.get(campo)

        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    return ""


def limpiar_texto(texto):
    if not texto:
        return ""

    texto = re.sub(r"<[^>]+>", "", str(texto))
    return texto.strip()


# =========================================================
# EXTRACCION DE INTV
# =========================================================

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
    respuesta = None

    for intento in range(1, 5):
        try:
            print(f"Conectando con INTV: intento {intento}/4")

            respuesta = SESION.get(
                URL_INTV,
                timeout=(20, 60)
            )

            respuesta.raise_for_status()
            break

        except requests.RequestException as error:
            print(f"INTV no respondió: {error}")

            if intento < 4:
                print("Esperando 15 segundos para reintentar...")
                time.sleep(15)
            else:
                raise Exception(
                    "No fue posible conectar con INTV después de "
                    "4 intentos. Se conservará el XML anterior."
                ) from error

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
            programas = informacion.get("programs", [])

            if not programas:
                raise Exception(
                    "INTV no entregó programas de Warner Channel."
                )

            return programas

    raise Exception("No se encontró Warner Channel en INTV.")


# =========================================================
# FECHAS
# =========================================================

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


# =========================================================
# TVMAZE: SERIES Y EPISODIOS
# =========================================================

@lru_cache(maxsize=100)
def buscar_serie_tvmaze(nombre):
    try:
        respuesta = SESION.get(
            f"{TVMAZE_URL}/search/shows",
            params={"q": nombre},
            timeout=20
        )

        respuesta.raise_for_status()

        resultados = respuesta.json()
        nombre_buscado = normalizar(nombre)

        for resultado in resultados:
            show = resultado.get("show", {})

            if normalizar(show.get("name")) == nombre_buscado:
                return show

    except Exception as error:
        print("Error buscando serie en TVmaze:", error)

    return None


@lru_cache(maxsize=100)
def obtener_episodios_tvmaze(show_id):
    try:
        respuesta = SESION.get(
            f"{TVMAZE_URL}/shows/{show_id}/episodes",
            timeout=30
        )

        respuesta.raise_for_status()
        return respuesta.json()

    except Exception as error:
        print("Error obteniendo episodios TVmaze:", error)
        return []


def construir_catalogo_series():
    catalogo = {}

    print("Consultando series y episodios en TVmaze...")

    for nombre in SERIES_CONOCIDAS:
        show = buscar_serie_tvmaze(nombre)

        if not show:
            print("Serie no encontrada en TVmaze:", nombre)
            continue

        episodios = obtener_episodios_tvmaze(show["id"])

        cantidad = 0

        for episodio in episodios:
            titulo = episodio.get("name")
            temporada = episodio.get("season")
            numero = episodio.get("number")

            if not titulo or temporada is None or numero is None:
                continue

            clave = normalizar(titulo)

            if not clave:
                continue

            # Si hay dos coincidencias con el mismo título,
            # no se sobrescribe silenciosamente la primera.
            if clave in catalogo:
                catalogo[clave] = None
                continue

            catalogo[clave] = {
                "serie": nombre,
                "episodio": titulo,
                "temporada": temporada,
                "numero": numero,
                "show_id": show["id"],
            }

            cantidad += 1

        print(f"{nombre}: {cantidad} episodios consultados")

    return catalogo


@lru_cache(maxsize=100)
def obtener_nombre_serie_es(nombre_ingles):
    if not TMDB_API_KEY:
        return NOMBRES_SERIES_ES.get(normalizar(nombre_ingles), "")

    try:
        respuesta = SESION.get(
            f"{TMDB_URL}/search/tv",
            params={
                "api_key": TMDB_API_KEY,
                "query": nombre_ingles,
                "language": "es-ES"
            },
            timeout=20
        )

        respuesta.raise_for_status()

        resultados = respuesta.json().get("results", [])
        nombre_buscado = normalizar(nombre_ingles)

        for resultado in resultados:
            if (
                normalizar(resultado.get("original_name"))
                == nombre_buscado
                or normalizar(resultado.get("name"))
                == nombre_buscado
            ):
                nombre_es = resultado.get("name", "").strip()

                if nombre_es:
                    return nombre_es

    except Exception as error:
        print("Error buscando nombre español de serie:", error)

    return NOMBRES_SERIES_ES.get(normalizar(nombre_ingles), "")


# =========================================================
# TMDb: PELICULAS Y SINOPSIS EN ESPAÑOL
# =========================================================

def obtener_traduccion_es(tipo, tmdb_id):
    if not TMDB_API_KEY:
        return {}

    try:
        respuesta = SESION.get(
            f"{TMDB_URL}/{tipo}/{tmdb_id}/translations",
            params={"api_key": TMDB_API_KEY},
            timeout=20
        )

        respuesta.raise_for_status()

        traducciones = respuesta.json().get("translations", [])

        # Preferir español de España y después español de México.
        prioridades = ["ES", "MX"]

        for pais in prioridades:
            for traduccion in traducciones:
                if (
                    traduccion.get("iso_639_1") == "es"
                    and traduccion.get("iso_3166_1") == pais
                ):
                    return traduccion.get("data", {})

        for traduccion in traducciones:
            if traduccion.get("iso_639_1") == "es":
                return traduccion.get("data", {})

    except Exception as error:
        print("Error obteniendo traducción española:", error)

    return {}


@lru_cache(maxsize=300)
def buscar_pelicula_tmdb(titulo):
    if not TMDB_API_KEY or not titulo:
        return None

    try:
        respuesta = SESION.get(
            f"{TMDB_URL}/search/movie",
            params={
                "api_key": TMDB_API_KEY,
                "query": titulo,
                "language": "es-ES",
                "include_adult": "false"
            },
            timeout=20
        )

        respuesta.raise_for_status()

        resultados = respuesta.json().get("results", [])
        titulo_buscado = normalizar(titulo)

        for resultado in resultados:
            posibles_titulos = [
                resultado.get("title", ""),
                resultado.get("original_title", "")
            ]

            if any(
                normalizar(nombre) == titulo_buscado
                for nombre in posibles_titulos
                if nombre
            ):
                return resultado

    except Exception as error:
        print("Error buscando película en TMDb:", error)

    return None


def obtener_datos_pelicula(titulo):
    resultado = buscar_pelicula_tmdb(titulo)

    if not resultado:
        return None

    tmdb_id = resultado.get("id")

    if not tmdb_id:
        return None

    traduccion = obtener_traduccion_es("movie", tmdb_id)

    titulo_es = traduccion.get("title", "").strip()
    sinopsis_es = limpiar_texto(traduccion.get("overview", ""))

    # Consultar también los detalles en español.
    try:
        respuesta = SESION.get(
            f"{TMDB_URL}/movie/{tmdb_id}",
            params={
                "api_key": TMDB_API_KEY,
                "language": "es-ES"
            },
            timeout=20
        )

        respuesta.raise_for_status()
        detalles = respuesta.json()

        if not titulo_es:
            titulo_es = detalles.get("title", "").strip()

        if not sinopsis_es:
            sinopsis_es = limpiar_texto(
                detalles.get("overview", "")
            )

    except Exception as error:
        print("Error obteniendo detalles de película:", error)

    # Si TMDb no devuelve un título localizado, conservar
    # el título que proporcionó INTV.
    if not titulo_es:
        titulo_es = titulo

    return {
        "id": tmdb_id,
        "titulo": titulo_es,
        "sinopsis": sinopsis_es
    }


# =========================================================
# CREACION DE PROGRAMAS XMLTV
# =========================================================

def agregar_texto(elemento, etiqueta, texto, idioma=None):
    atributos = {}

    if idioma:
        atributos["lang"] = idioma

    nuevo = ET.SubElement(elemento, etiqueta, atributos)
    nuevo.text = texto

    return nuevo


def crear_programa(programa, catalogo_series):
    titulo_intv = obtener_texto(programa, ["title"])

    inicio = programa.get("start")
    fin = programa.get("end")

    if not titulo_intv or not inicio or not fin:
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

        clave = normalizar(titulo_intv)

        # -------------------------------------------------
        # PRIMERO: buscar coincidencia exacta de episodio
        # -------------------------------------------------

        episodio = catalogo_series.get(clave)

        if episodio:
            nombre_serie_es = obtener_nombre_serie_es(
                episodio["serie"]
            )

            if not nombre_serie_es:
                nombre_serie_es = episodio["serie"]

            agregar_texto(
                elemento,
                "title",
                nombre_serie_es,
                "es"
            )

            agregar_texto(
                elemento,
                "sub-title",
                episodio["episodio"],
                "en"
            )

            numero_temporada = episodio["temporada"]
            numero_episodio = episodio["numero"]

            agregar_texto(
                elemento,
                "episode-num",
                f"Temporada {numero_temporada} "
                f"Episodio {numero_episodio}",
                None
            )

            return elemento

        # -------------------------------------------------
        # SEGUNDO: comprobar si es una película
        # -------------------------------------------------

        pelicula = obtener_datos_pelicula(titulo_intv)

        if pelicula:
            agregar_texto(
                elemento,
                "title",
                pelicula["titulo"],
                "es"
            )

            if pelicula["sinopsis"]:
                agregar_texto(
                    elemento,
                    "desc",
                    pelicula["sinopsis"],
                    "es"
                )

            return elemento

        # -------------------------------------------------
        # TERCERO: no inventar coincidencias
        # -------------------------------------------------

        agregar_texto(
            elemento,
            "title",
            titulo_intv,
            "es"
        )

        print("Sin coincidencia verificada:", titulo_intv)

        return elemento

    except (ValueError, TypeError, OSError) as error:
        print("Error creando programa:", titulo_intv, error)
        return None


# =========================================================
# RECUPERAR XML ANTERIOR
# =========================================================

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

    except ET.ParseError as error:
        raise Exception(
            "El XML anterior está dañado. Se cancela la generación "
            "para evitar perder la programación existente."
        ) from error

    return programas


# =========================================================
# GENERAR XMLTV
# =========================================================

def generar_xml():
    print("=" * 55)
    print("GENERADOR EPG WARNER CHANNEL")
    print("=" * 55)

    programas_intv = obtener_programacion()

    print(
        "Registros recibidos de INTV:",
        len(programas_intv)
    )

    catalogo_series = construir_catalogo_series()

    print(
        "Episodios identificables:",
        sum(1 for valor in catalogo_series.values() if valor)
    )

    programas_finales = cargar_programas_anterior()

    nuevos = 0
    actualizados = 0
    descartados = 0

    for programa in programas_intv:
        elemento = crear_programa(
            programa,
            catalogo_series
        )

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

        programas_finales[clave] = elemento

    raiz = ET.Element(
        "tv",
        {"generator-info-name": "EPG Warner Channel INTV"}
    )

    canal = ET.SubElement(
        raiz,
        "channel",
        {"id": CANAL_ID}
    )

    agregar_texto(
        canal,
        "display-name",
        "Warner Channel",
        "es"
    )

    lista_ordenada = sorted(
        programas_finales.values(),
        key=lambda p: fecha_xml_a_datetime(p.get("start"))
    )

    for programa in lista_ordenada:
        raiz.append(programa)

    ET.indent(raiz, space="  ")

    archivo_temporal = ARCHIVO_XML + ".tmp"

    ET.ElementTree(raiz).write(
        archivo_temporal,
        encoding="UTF-8",
        xml_declaration=True
    )

    # Reemplazo seguro: el XML anterior solo se sustituye
    # cuando el nuevo archivo se ha escrito correctamente.
    os.replace(archivo_temporal, ARCHIVO_XML)

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
    try:
        generar_xml()

    except Exception as error:
        print("=" * 55)
        print("GENERACIÓN CANCELADA")
        print(error)
        print("El epg.xml anterior no será modificado.")
        print("=" * 55)
        raise
