
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

IDIOMAS_BUSQUEDA = [
    "es-ES",
    "en-US",
    "pt-BR",
    "fr-FR",
    "de-DE",
    "it-IT",
]

SERIES_CONOCIDAS = [
    "The Big Bang Theory",
    "Two and a Half Men",
    "Cobra Kai",
]

NOMBRES_SERIES_ES = {
    "the big bang theory": "La teoría del Big Bang",
    "two and a half men": "Dos hombres y medio",
    "cobra kai": "Cobra Kai",
}

# Identificaciones manuales verificadas.
# Formato: titulo INTV: (serie, temporada, episodio)
EPISODIOS_MANUALES = {
    "Adoptando chicas": (
        "Two and a Half Men", 4, 23
    ),
    "Chicas y helado": (
        "Two and a Half Men", 4, 24
    ),
    "Aves grandes, arañas y mamá": (
        "Two and a Half Men", 5, 1
    ),
    "Creo que ofendiste a Don": (
        "Two and a Half Men", 6, 13
    ),
    "Primero estar de pie": (
        "Cobra Kai", 4, 2
    ),
}

# Título identificado como perteneciente a la serie,
# pero sin temporada y episodio verificados.
SERIES_SIN_EPISODIO = {
    "Viento a favor": "Two and a Half Men",
}

# Películas identificadas manualmente por ID de TMDb.
PELICULAS_MANUALES = {
    "Un jefe en pañales": 295693,
}

# No se buscarán estos títulos.
TITULOS_NO_BUSCAR = {
    "Hollywood One on One",
    "El Buzz",
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


def solicitar_json(url, params=None, timeout=25):
    respuesta = SESION.get(
        url,
        params=params,
        timeout=timeout
    )

    respuesta.raise_for_status()
    return respuesta.json()


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
        resultados = solicitar_json(
            f"{TVMAZE_URL}/search/shows",
            params={"q": nombre}
        )

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
        return solicitar_json(
            f"{TVMAZE_URL}/shows/{show_id}/episodes",
            timeout=40
        )

    except Exception as error:
        print("Error obteniendo episodios TVmaze:", error)
        return []


@lru_cache(maxsize=100)
def obtener_aliases_tvmaze(show_id):
    aliases = set()

    try:
        resultados = solicitar_json(
            f"{TVMAZE_URL}/shows/{show_id}/akas"
        )

        for resultado in resultados:
            nombre = resultado.get("name", "")

            if nombre:
                aliases.add(normalizar(nombre))

    except Exception as error:
        print("No se pudieron obtener alias de TVmaze:", error)

    return aliases


# =========================================================
# TMDb: IDENTIFICAR SERIES
# =========================================================

@lru_cache(maxsize=100)
def buscar_serie_tmdb(nombre_original):
    if not TMDB_API_KEY:
        return None

    for idioma in IDIOMAS_BUSQUEDA:
        try:
            resultados = solicitar_json(
                f"{TMDB_URL}/search/tv",
                params={
                    "api_key": TMDB_API_KEY,
                    "query": nombre_original,
                    "language": idioma,
                    "include_adult": "false"
                }
            ).get("results", [])

            buscado = normalizar(nombre_original)

            for resultado in resultados:
                nombres = [
                    resultado.get("name", ""),
                    resultado.get("original_name", "")
                ]

                if any(
                    normalizar(nombre) == buscado
                    for nombre in nombres if nombre
                ):
                    return resultado

        except Exception as error:
            print(
                f"Error buscando serie en TMDb ({idioma}):",
                error
            )

    return None


@lru_cache(maxsize=100)
def obtener_nombre_serie_es(nombre_original):
    if not TMDB_API_KEY:
        return NOMBRES_SERIES_ES.get(
            normalizar(nombre_original),
            ""
        )

    serie = buscar_serie_tmdb(nombre_original)

    if serie:
        try:
            detalles = solicitar_json(
                f"{TMDB_URL}/tv/{serie['id']}",
                params={
                    "api_key": TMDB_API_KEY,
                    "language": "es-ES"
                }
            )

            nombre_es = detalles.get("name", "").strip()

            if nombre_es:
                return nombre_es

        except Exception as error:
            print("Error obteniendo nombre español de serie:", error)

    return NOMBRES_SERIES_ES.get(
        normalizar(nombre_original),
        ""
    )


# =========================================================
# TMDb: EPISODIOS EN VARIOS IDIOMAS
# =========================================================

@lru_cache(maxsize=200)
def obtener_detalles_serie_tmdb(tmdb_id):
    try:
        return solicitar_json(
            f"{TMDB_URL}/tv/{tmdb_id}",
            params={
                "api_key": TMDB_API_KEY,
                "language": "en-US"
            }
        )

    except Exception as error:
        print("Error obteniendo temporadas de TMDb:", error)
        return {}


@lru_cache(maxsize=500)
def obtener_episodios_temporada_tmdb(
    tmdb_id,
    temporada,
    idioma
):
    try:
        datos = solicitar_json(
            f"{TMDB_URL}/tv/{tmdb_id}/season/{temporada}",
            params={
                "api_key": TMDB_API_KEY,
                "language": idioma
            },
            timeout=30
        )

        return datos.get("episodes", [])

    except Exception as error:
        print(
            f"Error en temporada {temporada}, idioma {idioma}:",
            error
        )

        return []


def agregar_coincidencia(catalogo, titulo, informacion):
    clave = normalizar(titulo)

    if not clave:
        return

    existente = catalogo.get(clave)

    if existente is None and clave in catalogo:
        return

    if existente is None:
        catalogo[clave] = informacion
        return

    misma_coincidencia = (
        existente["serie"] == informacion["serie"]
        and existente["temporada"] == informacion["temporada"]
        and existente["numero"] == informacion["numero"]
    )

    if not misma_coincidencia:
        catalogo[clave] = None


def construir_catalogo_series():
    catalogo = {}
    episodios_por_serie = {}

    print("Consultando series y episodios en TVmaze...")

    for nombre in SERIES_CONOCIDAS:
        show = buscar_serie_tvmaze(nombre)

        if not show:
            print("Serie no encontrada en TVmaze:", nombre)
            continue

        show_id = show["id"]
        episodios_tvmaze = obtener_episodios_tvmaze(show_id)

        tmdb_serie = buscar_serie_tmdb(nombre)
        tmdb_id = tmdb_serie.get("id") if tmdb_serie else None

        episodios_por_numero = {}

        for episodio in episodios_tvmaze:
            temporada = episodio.get("season")
            numero = episodio.get("number")
            titulo = episodio.get("name")

            if (
                temporada is None
                or numero is None
                or not titulo
            ):
                continue

            clave = (temporada, numero)

            episodios_por_numero[clave] = {
                "serie": nombre,
                "episodio": titulo,
                "temporada": temporada,
                "numero": numero,
                "show_id": show_id,
            }

            agregar_coincidencia(
                catalogo,
                titulo,
                episodios_por_numero[clave]
            )

        episodios_por_serie[normalizar(nombre)] = (
            episodios_por_numero
        )

        cantidad_tvmaze = len(episodios_por_numero)

        if tmdb_id:
            detalles = obtener_detalles_serie_tmdb(tmdb_id)
            temporadas = detalles.get("seasons", [])

            for temporada_info in temporadas:
                numero_temporada = temporada_info.get(
                    "season_number"
                )

                if numero_temporada is None:
                    continue

                for idioma in IDIOMAS_BUSQUEDA:
                    episodios_traducidos = (
                        obtener_episodios_temporada_tmdb(
                            tmdb_id,
                            numero_temporada,
                            idioma
                        )
                    )

                    for episodio_tmdb in episodios_traducidos:
                        numero = episodio_tmdb.get(
                            "episode_number"
                        )

                        titulo = episodio_tmdb.get("name", "")

                        if numero is None or not titulo:
                            continue

                        clave = (numero_temporada, numero)

                        if clave not in episodios_por_numero:
                            continue

                        informacion = episodios_por_numero[clave]

                        agregar_coincidencia(
                            catalogo,
                            titulo,
                            informacion
                        )

        print(
            f"{nombre}: {cantidad_tvmaze} episodios de TVmaze"
            + (
                " y traducciones de TMDb"
                if tmdb_id else " (sin identificación en TMDb)"
            )
        )

        aliases = obtener_aliases_tvmaze(show_id)

        if aliases:
            print(
                f"Alias adicionales encontrados para {nombre}:",
                len(aliases)
            )

    # Incorporar los títulos manuales usando los datos
    # originales de los episodios de TVmaze.
    print("Aplicando identificaciones manuales...")

    for titulo, datos in EPISODIOS_MANUALES.items():
        nombre_serie, temporada, numero = datos

        episodios = episodios_por_serie.get(
            normalizar(nombre_serie),
            {}
        )

        informacion = episodios.get((temporada, numero))

        if informacion:
            agregar_coincidencia(
                catalogo,
                titulo,
                informacion
            )

            print(
                f"Identificado: {titulo} -> "
                f"{nombre_serie} S{temporada:02d}E{numero:02d}"
            )
        else:
            print(
                "No se encontró el episodio manual en TVmaze:",
                titulo
            )

    return catalogo


# =========================================================
# TMDb: PELICULAS Y TITULOS ALTERNATIVOS
# =========================================================

@lru_cache(maxsize=500)
def obtener_titulos_alternativos_pelicula(tmdb_id):
    titulos = set()

    if not TMDB_API_KEY:
        return titulos

    try:
        datos = solicitar_json(
            f"{TMDB_URL}/movie/{tmdb_id}/alternative_titles",
            params={"api_key": TMDB_API_KEY}
        )

        for elemento in datos.get("titles", []):
            titulo = elemento.get("title", "")

            if titulo:
                titulos.add(normalizar(titulo))

    except Exception as error:
        print("Error obteniendo títulos alternativos:", error)

    return titulos


@lru_cache(maxsize=500)
def buscar_pelicula_tmdb(titulo):
    if not TMDB_API_KEY or not titulo:
        return None

    titulo_buscado = normalizar(titulo)

    # Comprobar primero las películas identificadas manualmente.
    for titulo_manual, tmdb_id in PELICULAS_MANUALES.items():
        if normalizar(titulo_manual) == titulo_buscado:
            return {"id": tmdb_id}

    candidatos = {}

    for idioma in IDIOMAS_BUSQUEDA:
        try:
            resultados = solicitar_json(
                f"{TMDB_URL}/search/movie",
                params={
                    "api_key": TMDB_API_KEY,
                    "query": titulo,
                    "language": idioma,
                    "include_adult": "false"
                }
            ).get("results", [])

            for resultado in resultados:
                tmdb_id = resultado.get("id")

                if not tmdb_id:
                    continue

                candidatos[tmdb_id] = resultado

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
            print(
                f"Error buscando película en TMDb ({idioma}):",
                error
            )

    for tmdb_id, resultado in candidatos.items():
        alternativos = obtener_titulos_alternativos_pelicula(
            tmdb_id
        )

        if titulo_buscado in alternativos:
            return resultado

    return None


def obtener_traduccion_es(tipo, tmdb_id):
    if not TMDB_API_KEY:
        return {}

    try:
        datos = solicitar_json(
            f"{TMDB_URL}/{tipo}/{tmdb_id}/translations",
            params={"api_key": TMDB_API_KEY}
        )

        traducciones = datos.get("translations", [])

        prioridades = ["MX", "ES"]

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


def obtener_datos_pelicula(titulo):
    resultado = buscar_pelicula_tmdb(titulo)

    if not resultado:
        return None

    tmdb_id = resultado.get("id")

    if not tmdb_id:
        return None

    traduccion = obtener_traduccion_es("movie", tmdb_id)

    titulo_es = traduccion.get("title", "").strip()
    sinopsis_es = limpiar_texto(
        traduccion.get("overview", "")
    )

    # Consultar primero la ficha mexicana de TMDb.
    try:
        detalles = solicitar_json(
            f"{TMDB_URL}/movie/{tmdb_id}",
            params={
                "api_key": TMDB_API_KEY,
                "language": "es-MX"
            }
        )

        if not titulo_es:
            titulo_es = detalles.get("title", "").strip()

        if not sinopsis_es:
            sinopsis_es = limpiar_texto(
                detalles.get("overview", "")
            )

    except Exception as error:
        print("Error obteniendo detalles es-MX:", error)

    # Si no hay datos mexicanos, intentar español de España.
    if not titulo_es or not sinopsis_es:
        try:
            detalles = solicitar_json(
                f"{TMDB_URL}/movie/{tmdb_id}",
                params={
                    "api_key": TMDB_API_KEY,
                    "language": "es-ES"
                }
            )

            if not titulo_es:
                titulo_es = detalles.get("title", "").strip()

            if not sinopsis_es:
                sinopsis_es = limpiar_texto(
                    detalles.get("overview", "")
                )

        except Exception as error:
            print("Error obteniendo detalles es-ES:", error)

    if not titulo_es:
        return None

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

        # PRIMERO: buscar episodio en todos los idiomas
        # y en las identificaciones manuales.
        episodio = catalogo_series.get(clave)

        if episodio:
            nombre_serie_es = obtener_nombre_serie_es(
                episodio["serie"]
            )

            if not nombre_serie_es:
                nombre_serie_es = NOMBRES_SERIES_ES.get(
                    normalizar(episodio["serie"]),
                    episodio["serie"]
                )

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

            numero_episodio = ET.SubElement(
                elemento,
                "episode-num",
                {"system": "onscreen"}
            )

            numero_episodio.text = (
                f"Temporada {episodio['temporada']} "
                f"Episodio {episodio['numero']}"
            )

            return elemento

        # SEGUNDO: título que pertenece a una serie,
        # pero cuyo episodio no se ha podido verificar.
        serie_sin_episodio = None

        for titulo_manual, nombre_serie in SERIES_SIN_EPISODIO.items():
            if normalizar(titulo_manual) == clave:
                serie_sin_episodio = nombre_serie
                break

        if serie_sin_episodio:
            nombre_serie_es = obtener_nombre_serie_es(
                serie_sin_episodio
            )

            if not nombre_serie_es:
                nombre_serie_es = NOMBRES_SERIES_ES.get(
                    normalizar(serie_sin_episodio),
                    serie_sin_episodio
                )

            agregar_texto(
                elemento,
                "title",
                nombre_serie_es,
                "es"
            )

            agregar_texto(
                elemento,
                "sub-title",
                titulo_intv,
                "es"
            )

            print(
                "Serie identificada, episodio pendiente:",
                titulo_intv
            )

            return elemento

        # TERCERO: buscar película en TMDb.
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

            print(
                f"Película identificada: {titulo_intv} "
                f"(TMDb ID: {pelicula['id']})"
            )

            return elemento

        # CUARTO: conservar el título original
        # sin inventar información.
        agregar_texto(
            elemento,
            "title",
            titulo_intv,
            "es"
        )

        # Estos títulos quedan excluidos de las búsquedas.
        if titulo_intv not in TITULOS_NO_BUSCAR:
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
    print("GENERADOR EPG WARNER CHANNEL MULTIIDIOMA")
    print("=" * 55)

    programas_intv = obtener_programacion()

    print(
        "Registros recibidos de INTV:",
        len(programas_intv)
    )

    catalogo_series = construir_catalogo_series()

    print(
        "Episodios identificables:",
        sum(
            1 for valor in catalogo_series.values()
            if valor
        )
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

    os.replace(archivo_temporal, ARCHIVO_XML)

    print("---------------------------------------")
    print("Idiomas de búsqueda:", ", ".join(IDIOMAS_BUSQUEDA))
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
