
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import xml.etree.ElementTree as ET
import os
import re
import unicodedata
import json

URL = "https://intv.com.co/inicio/television/canales/warner-channel/"
XML_FILE = "epg.xml"
CHANNEL_ID = "WarnerChannel.us@Colombia"
OFFSET = "-0500"

SERIES_FILE = "series.json"
MOVIES_FILE = "peliculas.json"

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

# Programas que no deben buscarse como películas.
# Los cinco episodios se relacionan con sus respectivas series.
EPISODIOS_CONOCIDOS = {
    "The Next Episode": "Cobra Kai",
    "Then Learn Fly": "Cobra Kai",
    "Lo mejor que se puede comprar": "Two and a Half Men",
    "Primero estar de pie": "Cobra Kai",
    "Award Tour": "All American"
}

# Noticias o segmentos que tampoco son películas.
PROGRAMAS_NO_PELICULAS = {
    "Buzz",
    "El Buzz"
}

# Película identificada directamente mediante su ID de TMDb.
PELICULAS_ID_DIRECTO = {
    "La purga: El año de la elección": 316727
}


# ==============================
# CARGAR SERIES
# ==============================

def cargar_series():
    with open(SERIES_FILE, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    return {
        int(show_id): nombre
        for show_id, nombre in datos.items()
    }


SERIES = cargar_series()

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12
}


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]", "", texto.lower())


# ==============================
# TVMAZE: IDENTIFICAR SERIES
# ==============================

def obtener_episodios_tvmaze():
    indice = {}

    for show_id, nombre_serie in SERIES.items():
        url = f"https://api.tvmaze.com/shows/{show_id}/episodes"

        try:
            respuesta = requests.get(
                url,
                headers={"User-Agent": "WarnerEPG/1.0"},
                timeout=30
            )
            respuesta.raise_for_status()

            episodios = respuesta.json()

            for episodio in episodios:
                nombre = episodio.get("name")
                temporada = episodio.get("season")
                numero = episodio.get("number")

                if not nombre or temporada is None or numero is None:
                    continue

                clave = normalizar(nombre)
indice.setdefault(clave, []).append({
    "show_id": show_id,
    "serie": nombre_serie,
    "temporada": temporada,
    "numero": numero,
    "episodio": nombre
})
            print("TVmaze consultado:", nombre_serie)

        except requests.RequestException as error:
            print("Aviso: no se pudo consultar", nombre_serie, error)

    return indice


def identificar_episodio(nombre, indice):
    coincidencias = indice.get(normalizar(nombre), [])

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

    # Obtener el ID de TVmaze de la serie correspondiente
    show_id = next(
        (
            sid for sid, nombre_serie in SERIES.items()
            if normalizar(nombre_serie) == normalizar(serie)
        ),
        None
    )

    if show_id is None:
        return None

    # Reunir episodios únicamente de esa serie
    candidatos = []

    for episodios in indice.values():
        for episodio in episodios:
            if episodio["show_id"] == show_id:
                candidatos.append(episodio)

    # Buscar coincidencia exacta
    exactos = [
        episodio for episodio in candidatos
        if normalizar(episodio["episodio"]) == clave
    ]

    if len(exactos) == 1:
        return exactos[0]

    # Buscar coincidencias aproximadas
    puntuaciones = []

    for episodio in candidatos:
        puntuacion = SequenceMatcher(
            None,
            clave,
            normalizar(episodio["episodio"])
        ).ratio()

        puntuaciones.append((puntuacion, episodio))

    puntuaciones.sort(key=lambda x: x[0], reverse=True)

    if not puntuaciones:
        return None

    mejor_puntuacion, mejor_episodio = puntuaciones[0]

    # Evitar coincidencias dudosas
    segunda_puntuacion = (
        puntuaciones[1][0]
        if len(puntuaciones) > 1
        else 0
    )

    if mejor_puntuacion >= 0.82 and (
        mejor_puntuacion - segunda_puntuacion >= 0.08
    ):
        print(
            "Coincidencia aproximada en TVmaze:",
            nombre,
            "->",
            mejor_episodio["episodio"]
        )
        return mejor_episodio

    print("Episodio sin coincidencia segura en TVmaze:", nombre)
    return None


def es_programa_no_pelicula(nombre):
    clave = normalizar(nombre)

    return any(
        normalizar(titulo) == clave
        for titulo in PROGRAMAS_NO_PELICULAS
    )


# ==============================
# TMDB: IDENTIFICAR PELICULAS
# ==============================

def cargar_peliculas():
    if not os.path.exists(MOVIES_FILE):
        return {}

    try:
        with open(MOVIES_FILE, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)

        peliculas = datos.get("peliculas", {})

        if isinstance(peliculas, list):
            return {}

        return peliculas

    except (json.JSONDecodeError, OSError):
        print("Aviso: no se pudo leer peliculas.json")
        return {}


def guardar_peliculas(peliculas):
    datos = {
        "peliculas": peliculas
    }

    with open(MOVIES_FILE, "w", encoding="utf-8") as archivo:
        json.dump(
            datos,
            archivo,
            ensure_ascii=False,
            indent=2
        )


def obtener_sinopsis_tmdb(pelicula_id):
    # Intentar primero español latino
    respuesta = requests.get(
        f"https://api.themoviedb.org/3/movie/{pelicula_id}",
        params={
            "api_key": TMDB_API_KEY,
            "language": "es-419"
        },
        timeout=30
    )
    respuesta.raise_for_status()

    sinopsis = respuesta.json().get("overview", "").strip()

    # Si no existe, probar español de España
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

        sinopsis = respuesta.json().get("overview", "").strip()

    return sinopsis


def buscar_pelicula_tmdb(titulo, cache):
    clave = normalizar(titulo)

    # No buscar noticias ni episodios como películas
    if es_programa_no_pelicula(titulo):
        print("Programa omitido (no es película):", titulo)
        return None

    if normalizar(titulo) in {
        normalizar(nombre)
        for nombre in EPISODIOS_CONOCIDOS
    }:
        print("Episodio omitido de búsqueda de películas:", titulo)
        return None

    if not TMDB_API_KEY:
        print("Aviso: falta la clave TMDB_API_KEY")
        return None

    try:
        # Consultar directamente las películas con ID conocido
        for nombre, pelicula_id in PELICULAS_ID_DIRECTO.items():
            if normalizar(nombre) == clave:

                if clave in cache and cache[clave] is not None:
                    return cache[clave]

                sinopsis = obtener_sinopsis_tmdb(pelicula_id)

                if not sinopsis:
                    print("Película sin sinopsis:", titulo)
                    return None

                resultado = {
                    "id": pelicula_id,
                    "sinopsis": sinopsis
                }

                cache[clave] = resultado

                print("Película identificada por ID:", titulo)
                return resultado

        # Consultar la caché de resultados anteriores
        if clave in cache and cache[clave] is not None:
            return cache[clave]

        url = "https://api.themoviedb.org/3/search/movie"
        idiomas = ["es-419", "es-ES", "en-US"]

        resultados_unidos = {}

        # Buscar en varios idiomas
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

            for pelicula in respuesta.json().get("results", [])[:8]:
                resultados_unidos[pelicula["id"]] = pelicula

        resultados = list(resultados_unidos.values())

        # Buscar coincidencias con títulos principales
        coincidencias = []

        for pelicula in resultados:
            titulos = [
                pelicula.get("title", ""),
                pelicula.get("original_title", "")
            ]

            if any(normalizar(nombre) == clave for nombre in titulos):
                coincidencias.append(pelicula)

        # Buscar títulos alternativos si no hay coincidencias
        if not coincidencias:
            for pelicula in resultados[:15]:
                pelicula_id = pelicula["id"]

                respuesta = requests.get(
                    f"https://api.themoviedb.org/3/movie/{pelicula_id}/alternative_titles",
                    params={"api_key": TMDB_API_KEY},
                    timeout=30
                )
                respuesta.raise_for_status()

                titulos_alternativos = respuesta.json().get("titles", [])

                for alternativo in titulos_alternativos:
                    nombre = alternativo.get("title", "")

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
            print("Película no encontrada:", titulo)
            cache[clave] = None
            return None

        # Eliminar duplicados
        coincidencias_unicas = {
            pelicula["id"]: pelicula
            for pelicula in coincidencias
        }

        # Evitar seleccionar películas al azar
        if len(coincidencias_unicas) > 1:
            print("Varias coincidencias posibles:", titulo)
            cache[clave] = None
            return None

        pelicula = list(coincidencias_unicas.values())[0]
        pelicula_id = pelicula["id"]

        sinopsis = obtener_sinopsis_tmdb(pelicula_id)

        if not sinopsis:
            print("Película sin sinopsis:", titulo)
            cache[clave] = None
            return None

        resultado = {
            "id": pelicula_id,
            "sinopsis": sinopsis
        }

        cache[clave] = resultado

        print("Película identificada:", titulo)
        return resultado

    except requests.RequestException as error:
        print("Aviso: error consultando TMDb:", titulo, error)
        return None


# ==============================
# OBTENER PROGRAMACION DE INTV
# ==============================

def obtener_programacion():
    respuesta = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "html.parser")
    texto = soup.get_text(" ", strip=True)

    fecha_match = re.search(
        r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})",
        texto,
        re.I
    )

    if not fecha_match:
        raise ValueError("No se encontró la fecha")

    dia = int(fecha_match.group(1))
    mes = fecha_match.group(2).lower()[:3]
    anio = int(fecha_match.group(3))

    if mes not in MESES:
        raise ValueError("Mes desconocido: " + mes)

    fecha = datetime(anio, MESES[mes], dia)
    programas = []

    for tabla in soup.find_all("table"):
        for fila in tabla.find_all("tr"):
            celdas = fila.find_all(["td", "th"])

            if len(celdas) < 2:
                continue

            hora = celdas[0].get_text(" ", strip=True)
            nombre = celdas[1].get_text(" ", strip=True)

            if not re.fullmatch(
                r"\d{1,2}:\d{2}\s*[AP]M",
                hora,
                re.I
            ):
                continue

            inicio = datetime.strptime(
                hora.upper(), "%I:%M %p"
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
        raise ValueError("No se encontraron programas")

    return fecha, programas


# ==============================
# GENERAR XMLTV
# ==============================

def formato_xml(fecha):
    return fecha.strftime("%Y%m%d%H%M%S") + " " + OFFSET


def generar_xml(fecha, programas, indice, cache):
    if os.path.exists(XML_FILE):
        arbol = ET.parse(XML_FILE)
        root = arbol.getroot()
    else:
        root = ET.Element("tv")

    canales = root.findall("channel")

    if not any(c.get("id") == CHANNEL_ID for c in canales):
        canal = ET.SubElement(
            root, "channel", {"id": CHANNEL_ID}
        )
        ET.SubElement(
            canal, "display-name"
        ).text = "Warner Channel"

    fecha_texto = fecha.strftime("%Y%m%d")

    # Reemplazar únicamente la fecha consultada
    for elemento in list(root.findall("programme")):
        if elemento.get("start", "").startswith(fecha_texto):
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

        # Primero buscar episodios en TVmaze
        episodio = identificar_episodio(nombre, indice)

        if episodio:
            ET.SubElement(
                elemento, "title"
            ).text = episodio["serie"]

            subtitulo = (
                f"Temporada {episodio['temporada']}, "
                f"Episodio {episodio['numero']} - "
                f"{episodio['episodio']}"
            )

            ET.SubElement(
                elemento, "sub-title"
            ).text = subtitulo

            identificados += 1
            print("Identificado:", subtitulo)

        else:
            # Buscar los episodios conocidos por sus títulos de INTV
           episodio_conocido = identificar_episodio_conocido(nombre, indice)

            if episodio_conocido:
    ET.SubElement(
        elemento, "title"
    ).text = episodio_conocido["serie"]

    subtitulo = (
        f"Temporada {episodio_conocido['temporada']}, "
        f"Episodio {episodio_conocido['numero']} - "
        f"{episodio_conocido['episodio']}"
    )

    ET.SubElement(
        elemento, "sub-title"
    ).text = subtitulo

    identificados += 1

    print("Episodio identificado por TVmaze:", subtitulo)

            elif es_programa_no_pelicula(nombre):
                # Mantener el programa sin tratarlo como película
                ET.SubElement(
                    elemento, "title"
                ).text = nombre

                print("Programa informativo:", nombre)

            else:
                # Si no es episodio ni segmento, buscar como película
                pelicula = buscar_pelicula_tmdb(nombre, cache)

                ET.SubElement(
                    elemento, "title"
                ).text = nombre

                if pelicula and pelicula.get("sinopsis"):
                    ET.SubElement(
                        elemento, "desc"
                    ).text = pelicula["sinopsis"]

                    peliculas_identificadas += 1

        nuevos += 1

    # Guardar caché de películas
    guardar_peliculas(cache)

    # Ordenar los programas por hora
    todos_programas = root.findall("programme")

    root[:] = canales + sorted(
        todos_programas,
        key=lambda p: p.get("start", "")
    )

    ET.indent(root, space="  ")

    ET.ElementTree(root).write(
        XML_FILE,
        encoding="UTF-8",
        xml_declaration=True
    )

    print("Fecha:", fecha.strftime("%d/%m/%Y"))
    print("Programas guardados:", nuevos)
    print("Episodios identificados:", identificados)
    print("Películas identificadas:", peliculas_identificadas)
    print("Archivo generado:", XML_FILE)


# ==============================
# INICIO
# ==============================

def main():
    print("Series cargadas:", len(SERIES))

    for show_id, nombre in SERIES.items():
        print(f"Serie: {nombre} | ID: {show_id}")

    if TMDB_API_KEY:
        print("TMDb: clave detectada")
    else:
        print("Aviso: TMDb no tiene una clave disponible")

    fecha, programas = obtener_programacion()

    indice = obtener_episodios_tvmaze()
    cache = cargar_peliculas()

    generar_xml(fecha, programas, indice, cache)


if __name__ == "__main__":
    main()
