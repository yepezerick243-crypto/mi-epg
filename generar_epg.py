import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import xml.etree.ElementTree as ET
import os
import re
import unicodedata
import json
import time

URL = "https://intv.com.co/inicio/television/canales/warner-channel/"

XML_FILE = "epg.xml"
CHANNEL_ID = "WarnerChannel.us@Colombia"
OFFSET = "-0500"

SERIES_FILE = "series.json"
MOVIES_FILE = "peliculas.json"

TMDB_API_KEY = os.getenv("TMDB_API_KEY")


# ==============================
# CONFIGURACIÓN
# ==============================

# Episodios identificados y confirmados manualmente.
# Estos datos tienen prioridad sobre las búsquedas automáticas.

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


# Episodios que todavía pueden identificarse
# mediante coincidencias aproximadas.

EPISODIOS_CONOCIDOS = {
    "Then Learn Fly": "Cobra Kai",
    "Award Tour": "All American"
}


PROGRAMAS_NO_PELICULAS = {
    "Buzz",
    "El Buzz"
}


PELICULAS_ID_DIRECTO = {
    "La purga: El año de la elección": 316727
}


# Idiomas que se consultarán en TMDb.

IDIOMAS_SERIES = [
    "es-419",
    "es-ES",
    "en-US",
    "pt-BR",
    "fr-FR"
]


# ==============================
# CARGAR SERIES
# ==============================

def cargar_series():

    with open(
        SERIES_FILE,
        "r",
        encoding="utf-8"
    ) as archivo:

        datos = json.load(archivo)

    return {
        int(show_id): nombre
        for show_id, nombre in datos.items()
    }


SERIES = cargar_series()


MESES = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12
}


# ==============================
# NORMALIZAR TÍTULOS
# ==============================

def normalizar(texto):

    texto = unicodedata.normalize(
        "NFKD",
        texto
    )

    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )

    return re.sub(
        r"[^a-z0-9]",
        "",
        texto.lower()
    )


# ==============================
# EPISODIOS CONFIRMADOS
# ==============================

def identificar_episodio_confirmado(nombre):

    clave = normalizar(nombre)

    for titulo, datos in EPISODIOS_CONFIRMADOS.items():

        if normalizar(titulo) != clave:
            continue

        show_id = next(
            (
                sid
                for sid, nombre_serie in SERIES.items()
                if normalizar(nombre_serie) == normalizar(
                    datos["serie"]
                )
            ),
            None
        )

        if show_id is None:

            print(
                "Error: serie no encontrada en series.json:",
                datos["serie"]
            )

            return None

        resultado = {
            "show_id": show_id,
            "serie": datos["serie"],
            "temporada": datos["temporada"],
            "numero": datos["numero"],
            "episodio": datos["episodio"]
        }

        print(
            "Episodio identificado por registro confirmado:",
            nombre,
            "->",
            resultado["serie"],
            "| T",
            resultado["temporada"],
            "E",
            resultado["numero"]
        )

        return resultado

    return None


# ==============================
# TVMAZE: IDENTIFICAR SERIES
# ==============================

def obtener_episodios_tvmaze():

    indice = {}

    for show_id, nombre_serie in SERIES.items():

        url = (
            f"https://api.tvmaze.com/shows/"
            f"{show_id}/episodes"
        )

        try:

            respuesta = requests.get(
                url,
                headers={
                    "User-Agent": "WarnerEPG/1.0"
                },
                timeout=30
            )

            respuesta.raise_for_status()

            episodios = respuesta.json()

            for episodio in episodios:

                nombre = episodio.get("name")
                temporada = episodio.get("season")
                numero = episodio.get("number")

                if (
                    not nombre
                    or temporada is None
                    or numero is None
                ):
                    continue

                clave = normalizar(nombre)

                indice.setdefault(
                    clave,
                    []
                ).append({
                    "show_id": show_id,
                    "serie": nombre_serie,
                    "temporada": temporada,
                    "numero": numero,
                    "episodio": nombre
                })

            print(
                "TVmaze consultado:",
                nombre_serie
            )

        except requests.RequestException as error:

            print(
                "Aviso: no se pudo consultar",
                nombre_serie,
                error
            )

    return indice


def identificar_episodio(nombre, indice):

    coincidencias = indice.get(
        normalizar(nombre),
        []
    )

    if len(coincidencias) == 1:
        return coincidencias[0]

    return None


def identificar_episodio_conocido(nombre, indice):

    clave = normalizar(nombre)

    serie = None

    for titulo, nombre_serie in EPISODIOS_CONOCIDOS.items():

        if normalizar(titulo) == clave:

            serie = nombre_serie
            break

    if not serie:
        return None

    show_id = next(
        (
            sid
            for sid, nombre_serie in SERIES.items()
            if normalizar(nombre_serie) == normalizar(serie)
        ),
        None
    )

    if show_id is None:

        print(
            "Serie sin ID en series.json:",
            serie
        )

        return None

    candidatos = []

    for episodios in indice.values():

        for episodio in episodios:

            if episodio["show_id"] == show_id:
                candidatos.append(episodio)

    exactos = [
        episodio
        for episodio in candidatos
        if normalizar(episodio["episodio"]) == clave
    ]

    if len(exactos) == 1:
        return exactos[0]

    puntuaciones = []

    for episodio in candidatos:

        puntuacion = SequenceMatcher(
            None,
            clave,
            normalizar(episodio["episodio"])
        ).ratio()

        puntuaciones.append(
            (puntuacion, episodio)
        )

    puntuaciones.sort(
        key=lambda x: x[0],
        reverse=True
    )

    if not puntuaciones:

        print(
            "No hay episodios disponibles para:",
            serie
        )

        return None

    mejor_puntuacion, mejor_episodio = puntuaciones[0]

    segunda_puntuacion = (
        puntuaciones[1][0]
        if len(puntuaciones) > 1
        else 0
    )

    if (
        mejor_puntuacion >= 0.82
        and mejor_puntuacion - segunda_puntuacion >= 0.08
    ):

        print(
            "Coincidencia aproximada en TVmaze:",
            nombre,
            "->",
            mejor_episodio["episodio"]
        )

        return mejor_episodio

    print(
        "Episodio sin coincidencia segura en TVmaze:",
        nombre
    )

    return None


# ==============================
# TMDB: EPISODIOS MULTILINGÜES
# ==============================

def obtener_episodios_tmdb():

    if not TMDB_API_KEY:

        print(
            "TMDb: no se pueden consultar episodios"
        )

        return []

    registros = {}

    for show_id, nombre_serie in SERIES.items():

        try:

            respuesta = requests.get(
                "https://api.themoviedb.org/3/search/tv",
                params={
                    "api_key": TMDB_API_KEY,
                    "query": nombre_serie,
                    "language": "en-US"
                },
                timeout=30
            )

            respuesta.raise_for_status()

            resultados = respuesta.json().get(
                "results",
                []
            )

            coincidencias = [
                serie
                for serie in resultados
                if (
                    normalizar(serie.get("name", "")) ==
                    normalizar(nombre_serie)
                    or
                    normalizar(serie.get("original_name", "")) ==
                    normalizar(nombre_serie)
                )
            ]

            if len(coincidencias) != 1:

                print(
                    "TMDb: serie no identificada de forma segura:",
                    nombre_serie
                )

                continue

            tmdb_id = coincidencias[0]["id"]

            print(
                "TMDb: serie encontrada:",
                nombre_serie,
                "| ID:",
                tmdb_id
            )

            respuesta = requests.get(
                f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                params={
                    "api_key": TMDB_API_KEY,
                    "language": "en-US"
                },
                timeout=30
            )

            respuesta.raise_for_status()

            temporadas = respuesta.json().get(
                "seasons",
                []
            )

            for temporada in temporadas:

                numero_temporada = temporada.get(
                    "season_number"
                )

                if numero_temporada is None:
                    continue

                for idioma in IDIOMAS_SERIES:

                    try:

                        respuesta = requests.get(
                            f"https://api.themoviedb.org/3/tv/"
                            f"{tmdb_id}/season/{numero_temporada}",
                            params={
                                "api_key": TMDB_API_KEY,
                                "language": idioma
                            },
                            timeout=30
                        )

                        respuesta.raise_for_status()

                        episodios = respuesta.json().get(
                            "episodes",
                            []
                        )

                        for episodio in episodios:

                            numero = episodio.get(
                                "episode_number"
                            )

                            titulo = episodio.get(
                                "name",
                                ""
                            ).strip()

                            if numero is None or not titulo:
                                continue

                            clave = (
                                show_id,
                                numero_temporada,
                                numero
                            )

                            if clave not in registros:

                                registros[clave] = {
                                    "show_id": show_id,
                                    "serie": nombre_serie,
                                    "temporada": numero_temporada,
                                    "numero": numero,
                                    "episodio": "",
                                    "titulos": set()
                                }

                            registros[clave]["titulos"].add(
                                titulo
                            )

                            if idioma == "en-US":

                                registros[clave]["episodio"] = (
                                    titulo
                                )

                        time.sleep(0.15)

                    except requests.RequestException as error:

                        print(
                            "Aviso TMDb:",
                            nombre_serie,
                            "temporada",
                            numero_temporada,
                            idioma,
                            error
                        )

            print(
                "TMDb: episodios consultados:",
                nombre_serie
            )

        except requests.RequestException as error:

            print(
                "Error consultando serie en TMDb:",
                nombre_serie,
                error
            )

    lista_episodios = []

    for registro in registros.values():

        if (
            not registro["episodio"]
            and registro["titulos"]
        ):

            registro["episodio"] = sorted(
                registro["titulos"]
            )[0]

        lista_episodios.append(registro)

    print(
        "TMDb: episodios y traducciones cargados:",
        len(lista_episodios)
    )

    return lista_episodios


def identificar_episodio_multilingue(
    nombre,
    indice_tmdb
):

    clave = normalizar(nombre)

    serie_forzada = None

    for titulo, serie in EPISODIOS_CONOCIDOS.items():

        if normalizar(titulo) == clave:

            serie_forzada = normalizar(serie)
            break

    candidatos = []

    for episodio in indice_tmdb:

        if serie_forzada:

            if normalizar(
                episodio["serie"]
            ) != serie_forzada:

                continue

        puntuacion = max(
            (
                SequenceMatcher(
                    None,
                    clave,
                    normalizar(titulo)
                ).ratio()
                for titulo in episodio["titulos"]
            ),
            default=0
        )

        candidatos.append(
            (puntuacion, episodio)
        )

    if not candidatos:
        return None

    exactos = [
        episodio
        for puntuacion, episodio in candidatos
        if puntuacion == 1
    ]

    identidades_exactas = {
        (
            episodio["show_id"],
            episodio["temporada"],
            episodio["numero"]
        )
        for episodio in exactos
    }

    if len(identidades_exactas) == 1:

        resultado = exactos[0]

        print(
            "Episodio identificado por traducción:",
            nombre,
            "->",
            resultado["episodio"]
        )

        return resultado

    candidatos.sort(
        key=lambda x: x[0],
        reverse=True
    )

    mejor_puntuacion, mejor_episodio = candidatos[0]

    segunda_puntuacion = (
        candidatos[1][0]
        if len(candidatos) > 1
        else 0
    )

    if (
        mejor_puntuacion >= 0.90
        and mejor_puntuacion - segunda_puntuacion >= 0.08
    ):

        print(
            "Episodio identificado por similitud multilingüe:",
            nombre,
            "->",
            mejor_episodio["episodio"]
        )

        return mejor_episodio

    print(
        "TMDb: no hay coincidencia multilingüe segura:",
        nombre
    )

    return None


# ==============================
# PROGRAMAS QUE NO SON PELÍCULAS
# ==============================

def es_programa_no_pelicula(nombre):

    clave = normalizar(nombre)

    return any(
        normalizar(titulo) == clave
        for titulo in PROGRAMAS_NO_PELICULAS
    )


# ==============================
# TMDB: IDENTIFICAR PELÍCULAS
# ==============================

def cargar_peliculas():

    if not os.path.exists(MOVIES_FILE):
        return {}

    try:

        with open(
            MOVIES_FILE,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(archivo)

        peliculas = datos.get(
            "peliculas",
            {}
        )

        if isinstance(peliculas, list):
            return {}

        return peliculas

    except (json.JSONDecodeError, OSError):

        print(
            "Aviso: no se pudo leer peliculas.json"
        )

        return {}


def guardar_peliculas(peliculas):

    datos = {
        "peliculas": peliculas
    }

    with open(
        MOVIES_FILE,
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            datos,
            archivo,
            ensure_ascii=False,
            indent=2
        )


def obtener_sinopsis_tmdb(pelicula_id):

    respuesta = requests.get(
        f"https://api.themoviedb.org/3/movie/{pelicula_id}",
        params={
            "api_key": TMDB_API_KEY,
            "language": "es-419"
        },
        timeout=30
    )

    respuesta.raise_for_status()

    sinopsis = respuesta.json().get(
        "overview",
        ""
    ).strip()

    if not sinopsis:

        respuesta = requests.get(
            f"https://api.themoviedb.org/3/movie/{pelicula_id}",
            params={
                "api_key": TMDB_API_KEY,
                "language": "es-ES"
            },
            timeout=30
        )

        respuesta.raise_for_status()

        sinopsis = respuesta.json().get(
            "overview",
            ""
        ).strip()

    return sinopsis


def buscar_pelicula_tmdb(titulo, cache):

    clave = normalizar(titulo)

    if es_programa_no_pelicula(titulo):

        print(
            "Programa omitido (no es película):",
            titulo
        )

        return None

    titulos_episodios = (
        list(EPISODIOS_CONFIRMADOS.keys())
        + list(EPISODIOS_CONOCIDOS.keys())
    )

    if clave in {
        normalizar(nombre)
        for nombre in titulos_episodios
    }:

        print(
            "Episodio omitido de búsqueda de películas:",
            titulo
        )

        return None

    if not TMDB_API_KEY:

        print(
            "Aviso: falta la clave TMDB_API_KEY"
        )

        return None

    try:

        # Películas con ID conocido

        for nombre, pelicula_id in PELICULAS_ID_DIRECTO.items():

            if normalizar(nombre) == clave:

                if (
                    clave in cache
                    and cache[clave] is not None
                ):

                    return cache[clave]

                sinopsis = obtener_sinopsis_tmdb(
                    pelicula_id
                )

                if not sinopsis:

                    print(
                        "Película sin sinopsis:",
                        titulo
                    )

                    return None

                resultado = {
                    "id": pelicula_id,
                    "sinopsis": sinopsis
                }

                cache[clave] = resultado

                print(
                    "Película identificada por ID:",
                    titulo
                )

                return resultado

        # Consultar caché

        if (
            clave in cache
            and cache[clave] is not None
        ):

            return cache[clave]

        url = (
            "https://api.themoviedb.org/3/search/movie"
        )

        idiomas = [
            "es-419",
            "es-ES",
            "en-US"
        ]

        resultados_unidos = {}

        for idioma in idiomas:

            respuesta = requests.get(
                url,
                params={
                    "api_key": TMDB_API_KEY,
                    "query": titulo,
                    "language": idioma,
                    "include_adult": "false",
                    "page": 1
                },
                timeout=30
            )

            respuesta.raise_for_status()

            for pelicula in respuesta.json().get(
                "results",
                []
            )[:8]:

                resultados_unidos[pelicula["id"]] = pelicula

        resultados = list(
            resultados_unidos.values()
        )

        coincidencias = []

        # Coincidencias con títulos principales

        for pelicula in resultados:

            titulos = [
                pelicula.get("title", ""),
                pelicula.get("original_title", "")
            ]

            if any(
                normalizar(nombre) == clave
                for nombre in titulos
            ):

                coincidencias.append(pelicula)

        # Buscar títulos alternativos

        if not coincidencias:

            for pelicula in resultados[:15]:

                pelicula_id = pelicula["id"]

                respuesta = requests.get(
                    f"https://api.themoviedb.org/3/movie/"
                    f"{pelicula_id}/alternative_titles",
                    params={
                        "api_key": TMDB_API_KEY
                    },
                    timeout=30
                )

                respuesta.raise_for_status()

                titulos_alternativos = respuesta.json().get(
                    "titles",
                    []
                )

                for alternativo in titulos_alternativos:

                    nombre = alternativo.get(
                        "title",
                        ""
                    )

                    if normalizar(nombre) == clave:

                        coincidencias.append(pelicula)

                        print(
                            "Coincidencia por título alternativo:",
                            titulo,
                            "->",
                            pelicula.get("title", "")
                        )

                        break

        if not coincidencias:

            print(
                "Película no encontrada:",
                titulo
            )

            cache[clave] = None

            return None

        coincidencias_unicas = {
            pelicula["id"]: pelicula
            for pelicula in coincidencias
        }

        if len(coincidencias_unicas) > 1:

            print(
                "Varias coincidencias posibles:",
                titulo
            )

            cache[clave] = None

            return None

        pelicula = list(
            coincidencias_unicas.values()
        )[0]

        pelicula_id = pelicula["id"]

        sinopsis = obtener_sinopsis_tmdb(
            pelicula_id
        )

        if not sinopsis:

            print(
                "Película sin sinopsis:",
                titulo
            )

            cache[clave] = None

            return None

        resultado = {
            "id": pelicula_id,
            "sinopsis": sinopsis
        }

        cache[clave] = resultado

        print(
            "Película identificada:",
            titulo
        )

        return resultado

    except requests.RequestException as error:

        print(
            "Aviso: error consultando TMDb:",
            titulo,
            error
        )

        return None


# ==============================
# OBTENER PROGRAMACIÓN DE INTV
# ==============================

def obtener_programacion():

    respuesta = requests.get(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=30
    )

    respuesta.raise_for_status()

    soup = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    texto = soup.get_text(
        " ",
        strip=True
    )

    fecha_match = re.search(
        r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})",
        texto,
        re.I
    )

    if not fecha_match:

        raise ValueError(
            "No se encontró la fecha"
        )

    dia = int(
        fecha_match.group(1)
    )

    mes = fecha_match.group(2).lower()[:3]

    anio = int(
        fecha_match.group(3)
    )

    if mes not in MESES:

        raise ValueError(
            "Mes desconocido: " + mes
        )

    fecha = datetime(
        anio,
        MESES[mes],
        dia
    )

    programas = []

    for tabla in soup.find_all("table"):

        for fila in tabla.find_all("tr"):

            celdas = fila.find_all(
                ["td", "th"]
            )

            if len(celdas) < 2:
                continue

            hora = celdas[0].get_text(
                " ",
                strip=True
            )

            nombre = celdas[1].get_text(
                " ",
                strip=True
            )

            if not re.fullmatch(
                r"\d{1,2}:\d{2}\s*[AP]M",
                hora,
                re.I
            ):

                continue

            inicio = datetime.strptime(
                hora.upper(),
                "%I:%M %p"
            ).replace(
                year=fecha.year,
                month=fecha.month,
                day=fecha.day
            )

            programas.append({
                "inicio": inicio,
                "nombre": nombre
            })

    if not programas:

        raise ValueError(
            "No se encontraron programas"
        )

    return fecha, programas


# ==============================
# GENERAR XMLTV
# ==============================

def formato_xml(fecha):

    return (
        fecha.strftime("%Y%m%d%H%M%S")
        + " "
        + OFFSET
    )


def generar_xml(
    fecha,
    programas,
    indice,
    indice_tmdb,
    cache
):

    if os.path.exists(XML_FILE):

        arbol = ET.parse(XML_FILE)
        root = arbol.getroot()

    else:

        root = ET.Element("tv")

    canales = root.findall("channel")

    if not any(
        c.get("id") == CHANNEL_ID
        for c in canales
    ):

        canal = ET.SubElement(
            root,
            "channel",
            {
                "id": CHANNEL_ID
            }
        )

        ET.SubElement(
            canal,
            "display-name"
        ).text = "Warner Channel"

    fecha_texto = fecha.strftime("%Y%m%d")

    # Reemplazar únicamente la fecha consultada

    for elemento in list(
        root.findall("programme")
    ):

        if elemento.get(
            "start",
            ""
        ).startswith(fecha_texto):

            root.remove(elemento)

    nuevos = 0
    identificados = 0
    peliculas_identificadas = 0

    for i, programa in enumerate(programas):

        inicio = programa["inicio"]

        if i + 1 < len(programas):

            fin = programas[i + 1]["inicio"]

        else:

            fin = fecha + timedelta(days=1)

        if fin <= inicio:
            fin += timedelta(days=1)

        elemento = ET.SubElement(
            root,
            "programme",
            {
                "start": formato_xml(inicio),
                "stop": formato_xml(fin),
                "channel": CHANNEL_ID
            }
        )

        nombre = programa["nombre"]

        # 1. Buscar primero en los episodios confirmados.

        episodio = identificar_episodio_confirmado(
            nombre
        )

        # 2. Buscar episodios en TVmaze.

        if episodio is None:

            episodio = identificar_episodio(
                nombre,
                indice
            )

        # 3. Buscar episodios conocidos en TVmaze.

        if episodio is None:

            episodio = identificar_episodio_conocido(
                nombre,
                indice
            )

        # 4. Buscar episodios en TMDb y sus traducciones.

        if episodio is None:

            episodio = identificar_episodio_multilingue(
                nombre,
                indice_tmdb
            )

        # Si se identifica un episodio.

        if episodio:

            ET.SubElement(
                elemento,
                "title"
            ).text = episodio["serie"]

            subtitulo = (
                f"Temporada {episodio['temporada']}, "
                f"Episodio {episodio['numero']} - "
                f"{episodio['episodio']}"
            )

            ET.SubElement(
                elemento,
                "sub-title"
            ).text = subtitulo

            identificados += 1

            print(
                "Episodio identificado:",
                subtitulo
            )

        # Programas informativos.

        elif es_programa_no_pelicula(nombre):

            ET.SubElement(
                elemento,
                "title"
            ).text = nombre

            print(
                "Programa informativo:",
                nombre
            )

        # Buscar películas.

        else:

            pelicula = buscar_pelicula_tmdb(
                nombre,
                cache
            )

            ET.SubElement(
                elemento,
                "title"
            ).text = nombre

            if (
                pelicula
                and pelicula.get("sinopsis")
            ):

                ET.SubElement(
                    elemento,
                    "desc"
                ).text = pelicula["sinopsis"]

                peliculas_identificadas += 1

        nuevos += 1

    # Guardar caché de películas.

    guardar_peliculas(cache)

    # Ordenar programas por hora.

    todos_programas = root.findall(
        "programme"
    )

    root[:] = canales + sorted(
        todos_programas,
        key=lambda p: p.get("start", "")
    )

    ET.indent(
        root,
        space="  "
    )

    ET.ElementTree(root).write(
        XML_FILE,
        encoding="UTF-8",
        xml_declaration=True
    )

    print(
        "Fecha:",
        fecha.strftime("%d/%m/%Y")
    )

    print(
        "Programas guardados:",
        nuevos
    )

    print(
        "Episodios identificados:",
        identificados
    )

    print(
        "Películas identificadas:",
        peliculas_identificadas
    )

    print(
        "Archivo generado:",
        XML_FILE
    )


# ==============================
# INICIO
# ==============================

def main():

    print(
        "Series cargadas:",
        len(SERIES)
    )

    for show_id, nombre in SERIES.items():

        print(
            f"Serie: {nombre} | ID: {show_id}"
        )

    if TMDB_API_KEY:

        print(
            "TMDb: clave detectada"
        )

    else:

        print(
            "Aviso: TMDb no tiene una clave disponible"
        )

    # Obtener programación.

    fecha, programas = obtener_programacion()

    # Consultar TVmaze.

    indice = obtener_episodios_tvmaze()

    # Consultar episodios y traducciones en TMDb.

    indice_tmdb = obtener_episodios_tmdb()

    # Cargar películas guardadas.

    cache = cargar_peliculas()

    # Generar XML.

    generar_xml(
        fecha,
        programas,
        indice,
        indice_tmdb,
        cache
    )


if __name__ == "__main__":

    main()
