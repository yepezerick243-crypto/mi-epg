
import os
import re
import json
import time
import requests
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher
from pathlib import Path

# ============================================================
# CONFIGURACIÓN
# ============================================================

URL_PAGINA = (
    "https://www.directv.com.ec/guia/"
    "ChannelDetail.aspx?id=1206&name=WTVHD"
)

URL_API = (
    "https://www.directv.com.ec/guia/"
    "ChannelDetail.aspx/GetProgramming"
)

CANAL_ID = "WarnerChannel.us@Colombia"
CANAL_NOMBRE = "Warner Channel"
CANAL_NUMERO = 1206
CANAL_DIRECTV = "WTVHD"

ZONA = ZoneInfo("America/Guayaquil")
OFFSET_XML = "-0500"

ARCHIVO_XML = Path("epg.xml")
ARCHIVO_CACHE = Path("peliculas.json")

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_URL = "https://api.themoviedb.org/3"

IDIOMAS = ["es-419", "es-ES", "en-US"]

SERIES = {
    66: "The Big Bang Theory",
    130: "Two and a Half Men",
    4310: "Cobra Kai",
    34653: "All American"
}

TMDB_SERIES = {
    "The Big Bang Theory": 1418,
    "Two and a Half Men": 2691,
    "Cobra Kai": 77169,
    "All American": 82428
}

EPISODIOS_CONFIRMADOS = {
    "The Next Episode": {
        "serie": "All American",
        "temporada": 6,
        "numero": 11,
        "episodio": "The Next Episode"
    },
    "Lo mejor que se puede comprar": {
        "serie": "Two and a Half Men",
        "temporada": 6,
        "numero": 7,
        "episodio": "Best H.O. Money Can Buy"
    },
    "Primero estar de pie": {
        "serie": "Cobra Kai",
        "temporada": 4,
        "numero": 2,
        "episodio": "First Learn Stand"
    }
}

EPISODIOS_CONOCIDOS = {
    "Then Learn Fly": "Cobra Kai",
    "Award Tour": "All American"
}

PELICULAS_DIRECTAS = {
    "La purga: El año de la elección": 316727
}

# ============================================================
# SESIONES
# ============================================================

sesion = requests.Session()

HEADERS_DIRECTV = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": "https://www.directv.com.ec",
    "Referer": URL_PAGINA,
    "X-Requested-With": "XMLHttpRequest"
}

sesion_tmdb = requests.Session()


# ============================================================
# UTILIDADES
# ============================================================

def normalizar(texto):
    texto = str(texto or "").lower()
    texto = re.sub(r"[^a-z0-9áéíóúñü ]", " ", texto)
    return " ".join(texto.split())


def similitud(a, b):
    return SequenceMatcher(
        None,
        normalizar(a),
        normalizar(b)
    ).ratio()


def fecha_xml(fecha):
    return fecha.strftime("%Y%m%d%H%M%S") + " " + OFFSET_XML


def convertir_fecha(texto):
    formatos = [
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S"
    ]

    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).replace(
                tzinfo=ZONA
            )
        except (ValueError, TypeError):
            pass

    return None


def texto_xml(elemento, nombre, texto):
    hijo = ET.SubElement(elemento, nombre)
    hijo.text = str(texto or "")
    return hijo


# ============================================================
# DIRECTV: INICIAR SESIÓN
# ============================================================

def iniciar_sesion_directv():
    global sesion

    sesion = requests.Session()

    pagina = sesion.get(
        URL_PAGINA,
        headers=HEADERS_DIRECTV,
        timeout=30
    )

    pagina.raise_for_status()

    if "captcha.perfdrive.com" in pagina.text.lower():
        raise RuntimeError(
            "DIRECTV bloqueó la sesión con Radware CAPTCHA."
        )

    print("Sesión DIRECTV iniciada correctamente.")
    print("Cookies:", list(sesion.cookies.keys()))


# ============================================================
# DIRECTV: OBTENER PROGRAMACIÓN
# ============================================================

def consultar_directv(fecha):

    payload = {
        "filterParameters": {
            "day": fecha.day,
            "time": 0,
            "minute": 0,
            "month": fecha.month,
            "year": fecha.year,
            "offSetValue": 0,
            "homeScreenFilter": "",
            "filtersScreenFilters": [""],
            "isHd": "",
            "isChannelDetails": "Y",
            "channelName": CANAL_DIRECTV,
            "channelNum": CANAL_NUMERO
        }
    }

    for intento in range(4):
        try:
            respuesta = sesion.post(
                URL_API,
                headers=HEADERS_DIRECTV,
                json=payload,
                timeout=40
            )

            print(
                f"DIRECTV {fecha:%d/%m/%Y}: "
                f"HTTP {respuesta.status_code}, "
                f"{len(respuesta.content)} bytes"
            )

            respuesta.raise_for_status()

            if "captcha.perfdrive.com" in respuesta.text.lower():
                raise RuntimeError(
                    "DIRECTV bloqueó la consulta con Radware CAPTCHA."
                )

            if not respuesta.text.strip():
                raise ValueError(
                    "DIRECTV devolvió una respuesta vacía."
                )

            try:
                datos = respuesta.json()
            except ValueError:
                raise ValueError(
                    "Respuesta no JSON: "
                    + repr(respuesta.text[:300])
                )

            canales = datos.get("d", [])

            if not isinstance(canales, list) or not canales:
                raise ValueError(
                    "No se encontró la lista de canales: "
                    + repr(respuesta.text[:300])
                )

            programas = []

            for canal in canales:
                if canal.get("ChannelFullName") != CANAL_DIRECTV:
                    continue

                for p in canal.get("ProgramList", []):
                    inicio = convertir_fecha(
                        p.get("startTimeString")
                    )

                    fin = convertir_fecha(
                        p.get("endTimeString")
                    )

                    titulo = (p.get("title") or "").strip()

                    if not inicio or not fin or not titulo:
                        continue

                    if inicio.date() != fecha.date():
                        continue

                    if fin <= inicio:
                        continue

                    programas.append({
                        "inicio": inicio,
                        "fin": fin,
                        "titulo": titulo,
                        "descripcion": p.get("description") or "",
                        "categoria": p.get("categoryId") or "",
                        "tms_id": p.get("tmsId") or ""
                    })

            if len(programas) < 5:
                raise ValueError(
                    f"Programación incompleta: "
                    f"{len(programas)} programas."
                )

            print(
                f"Correcto: {len(programas)} programas "
                f"para {fecha:%d/%m/%Y}"
            )

            return programas

        except Exception as error:
            print(
                f"Intento {intento + 1}/4 "
                f"para {fecha:%d/%m/%Y}: {error}"
            )

            if intento < 3:
                time.sleep(8)

    return []


# ============================================================
# TVMAZE: CARGAR EPISODIOS
# ============================================================

def cargar_tvmaze():
    resultados = {}

    for serie_id, nombre in SERIES.items():
        try:
            respuesta = requests.get(
                f"https://api.tvmaze.com/shows/{serie_id}/episodes",
                timeout=30
            )

            respuesta.raise_for_status()

            episodios = respuesta.json()
            resultados[nombre] = episodios

            print(
                f"TVmaze: {nombre} - "
                f"{len(episodios)} episodios"
            )

        except Exception as error:
            print(f"Error TVmaze {nombre}: {error}")
            resultados[nombre] = []

    return resultados


def identificar_tvmaze(titulo, datos_tvmaze):

    if titulo in EPISODIOS_CONFIRMADOS:
        return EPISODIOS_CONFIRMADOS[titulo]

    serie_conocida = EPISODIOS_CONOCIDOS.get(titulo)

    if serie_conocida:
        candidatos = datos_tvmaze.get(serie_conocida, [])

        coincidencias = [
            ep for ep in candidatos
            if normalizar(ep.get("name")) == normalizar(titulo)
        ]

        if len(coincidencias) == 1:
            ep = coincidencias[0]

            return {
                "serie": serie_conocida,
                "temporada": ep.get("season"),
                "numero": ep.get("number"),
                "episodio": ep.get("name")
            }

    exactos = []

    for serie, episodios in datos_tvmaze.items():
        for ep in episodios:
            if normalizar(ep.get("name")) == normalizar(titulo):
                exactos.append((serie, ep))

    if len(exactos) == 1:
        serie, ep = exactos[0]

        return {
            "serie": serie,
            "temporada": ep.get("season"),
            "numero": ep.get("number"),
            "episodio": ep.get("name"),
            "descripcion": ep.get("summary") or ""
        }

    candidatos = []

    for serie, episodios in datos_tvmaze.items():
        for ep in episodios:
            nombre = ep.get("name", "")
            puntuacion = similitud(titulo, nombre)

            if puntuacion >= 0.90:
                candidatos.append((puntuacion, serie, ep))

    candidatos.sort(reverse=True, key=lambda x: x[0])

    if not candidatos:
        return None

    if len(candidatos) > 1:
        if candidatos[0][0] - candidatos[1][0] < 0.08:
            return None

    _, serie, ep = candidatos[0]

    return {
        "serie": serie,
        "temporada": ep.get("season"),
        "numero": ep.get("number"),
        "episodio": ep.get("name"),
        "descripcion": ep.get("summary") or ""
    }


# ============================================================
# TMDB: FUNCIONES GENERALES
# ============================================================

def tmdb_get(ruta, parametros=None):

    if not TMDB_API_KEY:
        return None

    params = dict(parametros or {})
    params["api_key"] = TMDB_API_KEY

    try:
        respuesta = sesion_tmdb.get(
            TMDB_URL + ruta,
            params=params,
            timeout=30
        )

        respuesta.raise_for_status()

        return respuesta.json()

    except Exception as error:
        print(f"Error TMDb {ruta}: {error}")
        return None


# ============================================================
# TMDB: EPISODIOS
# ============================================================

def cargar_episodios_tmdb():

    resultados = {}

    if not TMDB_API_KEY:
        print("TMDB_API_KEY no está configurada.")
        return resultados

    for serie, serie_id in TMDB_SERIES.items():

        episodios = []

        detalles = tmdb_get(
            f"/tv/{serie_id}",
            {"language": "en-US"}
        )

        if not detalles:
            resultados[serie] = []
            continue

        temporadas = [
            t.get("season_number")
            for t in detalles.get("seasons", [])
            if t.get("season_number", 0) > 0
        ]

        for temporada in temporadas:
            for idioma in IDIOMAS:

                datos = tmdb_get(
                    f"/tv/{serie_id}/season/{temporada}",
                    {"language": idioma}
                )

                if not datos:
                    continue

                for ep in datos.get("episodes", []):
                    episodios.append({
                        "serie": serie,
                        "temporada": temporada,
                        "numero": ep.get("episode_number"),
                        "episodio": ep.get("name", ""),
                        "descripcion": ep.get("overview", "")
                    })

        resultados[serie] = episodios

        print(
            f"TMDb: {serie} - "
            f"{len(episodios)} registros"
        )

    return resultados


def identificar_tmdb_episodio(titulo, datos_tmdb):

    candidatos = []

    for serie, episodios in datos_tmdb.items():
        for ep in episodios:

            puntuacion = similitud(
                titulo,
                ep.get("episodio", "")
            )

            if puntuacion >= 0.92:
                candidatos.append((puntuacion, serie, ep))

    candidatos.sort(reverse=True, key=lambda x: x[0])

    if not candidatos:
        return None

    if len(candidatos) > 1:
        if candidatos[0][0] - candidatos[1][0] < 0.08:
            return None

    _, serie, ep = candidatos[0]

    return {
        "serie": serie,
        "temporada": ep["temporada"],
        "numero": ep["numero"],
        "episodio": ep["episodio"],
        "descripcion": ep.get("descripcion", "")
    }


# ============================================================
# TMDB: PELÍCULAS Y CACHÉ
# ============================================================

def cargar_cache_peliculas():

    if not ARCHIVO_CACHE.exists():
        return {}

    try:
        with open(
            ARCHIVO_CACHE,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(archivo)

        if isinstance(datos, dict):
            if "peliculas" in datos:
                return datos["peliculas"]

            return datos

    except Exception as error:
        print("Error leyendo peliculas.json:", error)

    return {}


def guardar_cache_peliculas(cache):

    with open(
        ARCHIVO_CACHE,
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            {"peliculas": cache},
            archivo,
            ensure_ascii=False,
            indent=2
        )


def buscar_pelicula_tmdb(titulo, cache):

    clave = normalizar(titulo)

    if clave in cache:
        return cache[clave]

    if titulo in EPISODIOS_CONFIRMADOS:
        return None

    if titulo in EPISODIOS_CONOCIDOS:
        return None

    if not TMDB_API_KEY:
        return None

    pelicula_id = PELICULAS_DIRECTAS.get(titulo)

    if pelicula_id:

        detalles = tmdb_get(
            f"/movie/{pelicula_id}",
            {"language": "es-ES"}
        )

        if detalles:
            resultado = {
                "titulo": detalles.get("title") or titulo,
                "descripcion": detalles.get("overview") or "",
                "id": pelicula_id
            }

            cache[clave] = resultado
            return resultado

    candidatos = []

    for idioma in IDIOMAS:

        datos = tmdb_get(
            "/search/movie",
            {
                "query": titulo,
                "language": idioma,
                "include_adult": "false"
            }
        )

        if not datos:
            continue

        for pelicula in datos.get("results", []):

            nombres = [
                pelicula.get("title", ""),
                pelicula.get("original_title", "")
            ]

            puntuacion = max(
                similitud(titulo, nombre)
                for nombre in nombres
                if nombre
            ) if any(nombres) else 0

            if puntuacion >= 0.90:
                candidatos.append((puntuacion, pelicula))

    candidatos.sort(
        reverse=True,
        key=lambda x: x[0]
    )

    if not candidatos:
        return None

    mejor = candidatos[0]

    if len(candidatos) > 1:
        if mejor[0] - candidatos[1][0] < 0.08:
            return None

    pelicula_id = mejor[1].get("id")

    detalles = tmdb_get(
        f"/movie/{pelicula_id}",
        {"language": "es-ES"}
    )

    if not detalles:
        return None

    resultado = {
        "titulo": detalles.get("title") or titulo,
        "descripcion": detalles.get("overview") or "",
        "id": pelicula_id
    }

    cache[clave] = resultado

    return resultado


# ============================================================
# IDENTIFICAR PROGRAMAS
# ============================================================

def identificar_programa(
    programa,
    datos_tvmaze,
    datos_tmdb,
    cache_peliculas
):

    titulo = programa["titulo"]

    categoria = normalizar(programa["categoria"])
    tms_id = programa["tms_id"].upper()

    parece_serie = (
        "series" in categoria
        or tms_id.startswith("EP")
    )

    parece_pelicula = (
        "movie" in categoria
        or "pelicula" in categoria
        or tms_id.startswith("MV")
    )

    if parece_serie:

        episodio = identificar_tvmaze(
            titulo,
            datos_tvmaze
        )

        if not episodio:
            episodio = identificar_tmdb_episodio(
                titulo,
                datos_tmdb
            )

        return {
            "tipo": "serie",
            "datos": episodio
        }

    if parece_pelicula:

        pelicula = buscar_pelicula_tmdb(
            titulo,
            cache_peliculas
        )

        return {
            "tipo": "pelicula",
            "datos": pelicula
        }

    episodio = identificar_tvmaze(
        titulo,
        datos_tvmaze
    )

    if not episodio:
        episodio = identificar_tmdb_episodio(
            titulo,
            datos_tmdb
        )

    if episodio:
        return {
            "tipo": "serie",
            "datos": episodio
        }

    pelicula = buscar_pelicula_tmdb(
        titulo,
        cache_peliculas
    )

    if pelicula:
        return {
            "tipo": "pelicula",
            "datos": pelicula
        }

    return {
        "tipo": "programa",
        "datos": None
    }


# ============================================================
# GENERAR PROGRAMA XMLTV
# ============================================================

def crear_programa(programa, datos_tvmaze, datos_tmdb, cache):

    inicio = programa["inicio"]
    fin = programa["fin"]
    titulo = programa["titulo"]

    resultado = identificar_programa(
        programa,
        datos_tvmaze,
        datos_tmdb,
        cache
    )

    elemento = ET.Element(
        "programme",
        {
            "start": fecha_xml(inicio),
            "stop": fecha_xml(fin),
            "channel": CANAL_ID
        }
    )

    if resultado["tipo"] == "serie" and resultado["datos"]:

        datos = resultado["datos"]

        texto_xml(
            elemento,
            "title",
            datos["serie"]
        )

        subtitulo = (
            f"Temporada {datos['temporada']}, "
            f"Episodio {datos['numero']} - "
            f"{datos['episodio']}"
        )

        texto_xml(
            elemento,
            "sub-title",
            subtitulo
        )

        if datos.get("temporada") is not None and datos.get("numero") is not None:

            ET.SubElement(
                elemento,
                "episode-num",
                {"system": "onscreen"}
            ).text = (
                f"S{int(datos['temporada']):02d}"
                f"E{int(datos['numero']):02d}"
            )

        descripcion = (
            datos.get("descripcion")
            or programa["descripcion"]
        )

        if descripcion:
            texto_xml(
                elemento,
                "desc",
                re.sub("<[^>]+>", "", descripcion).strip()
            )

        ET.SubElement(
            elemento,
            "category"
        ).text = "Serie"

    elif resultado["tipo"] == "pelicula" and resultado["datos"]:

        datos = resultado["datos"]

        texto_xml(
            elemento,
            "title",
            datos["titulo"]
        )

        descripcion = (
            datos.get("descripcion")
            or programa["descripcion"]
        )

        if descripcion:
            texto_xml(
                elemento,
                "desc",
                descripcion
            )

        ET.SubElement(
            elemento,
            "category"
        ).text = "Película"

    else:

        texto_xml(
            elemento,
            "title",
            titulo
        )

        if programa["descripcion"]:
            texto_xml(
                elemento,
                "desc",
                programa["descripcion"]
            )

        ET.SubElement(
            elemento,
            "category"
        ).text = programa["categoria"] or "Entretenimiento"

    return elemento


# ============================================================
# XML: CONSERVAR PROGRAMACIÓN ANTERIOR
# ============================================================

def cargar_xml_anterior():

    if not ARCHIVO_XML.exists():
        return []

    try:
        arbol = ET.parse(ARCHIVO_XML)
        raiz = arbol.getroot()

        hoy = datetime.now(ZONA).date()

        limite = datetime.combine(
            hoy,
            datetime.min.time(),
            tzinfo=ZONA
        )

        anteriores = []

        for programa in raiz.findall("programme"):

            inicio = programa.get("start", "")

            try:
                fecha = datetime.strptime(
                    inicio[:14],
                    "%Y%m%d%H%M%S"
                ).replace(tzinfo=ZONA)

                if fecha < limite:
                    anteriores.append(
                        ET.fromstring(
                            ET.tostring(
                                programa,
                                encoding="unicode"
                            )
                        )
                    )

            except ValueError:
                continue

        return anteriores

    except Exception as error:
        print("No se pudo leer el XML anterior:", error)
        return []


# ============================================================
# GENERAR XML COMPLETO
# ============================================================

def generar_xml():

    ahora = datetime.now(ZONA)
    hoy = ahora.date()

    print("=" * 55)
    print("GENERADOR EPG WARNER CHANNEL")
    print("Fecha:", ahora.strftime("%d/%m/%Y %H:%M:%S"))
    print("=" * 55)

    # Iniciar una sola sesión DIRECTV.
    iniciar_sesion_directv()

    todos_programas = []

    # Hoy y los próximos 6 días.
    for desplazamiento in range(7):

        fecha = hoy + timedelta(days=desplazamiento)

        programas = consultar_directv(fecha)

        if programas:
            todos_programas.extend(programas)

    if not todos_programas:
        raise RuntimeError(
            "DIRECTV no devolvió programación válida. "
            "Se conserva el XML anterior."
        )

    # TVmaze y TMDb
    datos_tvmaze = cargar_tvmaze()
    datos_tmdb = cargar_episodios_tmdb()

    cache = cargar_cache_peliculas()

    # XML anterior
    anteriores = cargar_xml_anterior()

    raiz = ET.Element("tv")

    canal = ET.SubElement(
        raiz,
        "channel",
        {"id": CANAL_ID}
    )

    texto_xml(
        canal,
        "display-name",
        CANAL_NOMBRE
    )

    programas_xml = anteriores

    # Evitar duplicados.
    claves = set()

    for elemento in programas_xml:

        claves.add((
            elemento.get("start"),
            elemento.get("stop"),
            elemento.findtext("title")
        ))

    nuevos = 0

    for programa in todos_programas:

        clave = (
            fecha_xml(programa["inicio"]),
            fecha_xml(programa["fin"]),
            programa["titulo"]
        )

        if clave in claves:
            continue

        elemento = crear_programa(
            programa,
            datos_tvmaze,
            datos_tmdb,
            cache
        )

        programas_xml.append(elemento)
        claves.add(clave)
        nuevos += 1

    programas_xml.sort(
        key=lambda p: p.get("start", "")
    )

    for programa in programas_xml:
        raiz.append(programa)

    arbol = ET.ElementTree(raiz)

    ET.indent(
        arbol,
        space="    "
    )

    arbol.write(
        ARCHIVO_XML,
        encoding="utf-8",
        xml_declaration=True
    )

    guardar_cache_peliculas(cache)

    print("=" * 55)
    print("PROGRAMAS OBTENIDOS:", len(todos_programas))
    print("PROGRAMAS NUEVOS:", nuevos)
    print("PROGRAMAS CONSERVADOS:", len(anteriores))
    print("PELÍCULAS EN CACHÉ:", len(cache))
    print("XML GENERADO:", ARCHIVO_XML)
    print("=" * 55)


if __name__ == "__main__":
    generar_xml()
