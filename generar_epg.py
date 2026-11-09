import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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

# Cargar series desde series.json
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

        # Compatibilidad con el archivo anterior que tenía una lista vacía
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




def buscar_pelicula_tmdb(titulo, cache):
    clave = normalizar(titulo)

    # Conservar resultados positivos, pero volver a intentar los fallidos
    if clave in cache and cache[clave] is not None:
        return cache[clave]

    if not TMDB_API_KEY:
        print("Aviso: falta la clave TMDB_API_KEY")
        return None

    url = "https://api.themoviedb.org/3/search/movie"
    idiomas = ["es-419", "es-ES", "en-US"]

    resultados_unidos = {}

    try:
        # Buscar la película en varios idiomas
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

        # Primero comprobar los títulos principales
        coincidencias = []

        for pelicula in resultados:
            titulos = [
                pelicula.get("title", ""),
                pelicula.get("original_title", "")
            ]

            if any(normalizar(nombre) == clave for nombre in titulos):
                coincidencias.append(pelicula)

        # Si no hay coincidencia, consultar títulos alternativos
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

        # No escoger películas al azar
        if not coincidencias:
            print("Película no encontrada:", titulo)
            cache[clave] = None
            return None

        # Eliminar posibles duplicados
        coincidencias_unicas = {
            pelicula["id"]: pelicula
            for pelicula in coincidencias
        }

        if len(coincidencias_unicas) > 1:
            print("Varias coincidencias posibles:", titulo)
            cache[clave] = None
            return None

        pelicula = list(coincidencias_unicas.values())[0]
        pelicula_id = pelicula["id"]

        # Obtener la sinopsis en español latino
        detalle_respuesta = requests.get(
            f"https://api.themoviedb.org/3/movie/{pelicula_id}",
            params={
                "api_key": TMDB_API_KEY,
                "language": "es-419"
            },
            timeout=30
        )
        detalle_respuesta.raise_for_status()

        detalle = detalle_respuesta.json()
        sinopsis = detalle.get("overview", "").strip()

        # Si no existe, probar español de España
        if not sinopsis:
            detalle_respuesta = requests.get(
                f"https://api.themoviedb.org/3/movie/{pelicula_id}",
                params={
                    "api_key": TMDB_API_KEY,
                    "language": "es-ES"
                },
                timeout=30
            )
            detalle_respuesta.raise_for_status()
            sinopsis = detalle_respuesta.json().get(
                "overview", ""
            ).strip()

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



    # Consultar primero la caché
    if clave in cache:
        return cache[clave]

    if not TMDB_API_KEY:
        print("Aviso: falta la clave TMDB_API_KEY")
        return None

    url = "https://api.themoviedb.org/3/search/movie"

    parametros = {
        "api_key": TMDB_API_KEY,
        "query": titulo,
        "language": "es-ES",
        "include_adult": "false",
        "page": 1
    }

    try:
        respuesta = requests.get(
            url,
            params=parametros,
            timeout=30
        )
        respuesta.raise_for_status()

        resultados = respuesta.json().get("results", [])

        coincidencias = []

        for pelicula in resultados:
            titulo_espanol = pelicula.get("title", "")
            titulo_original = pelicula.get("original_title", "")

            if (
                normalizar(titulo_espanol) == clave
                or normalizar(titulo_original) == clave
            ):
                coincidencias.append(pelicula)

        # Aceptar únicamente coincidencias únicas
        if len(coincidencias) != 1:
            cache[clave] = None
            print("Película no identificada con seguridad:", titulo)
            return None

        pelicula = coincidencias[0]
        sinopsis = pelicula.get("overview", "").strip()

        if not sinopsis:
            cache[clave] = None
            print("Película sin sinopsis:", titulo)
            return None

        resultado = {
            "id": pelicula.get("id"),
            "sinopsis": sinopsis
        }

        cache[clave] = resultado

        print("Película identificada:", titulo)

        return resultado

    except requests.RequestException as error:
        print("Aviso: error consultando TMDb para", titulo, error)
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

    # Reemplazar la fecha consultada sin borrar días anteriores
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

        # Primero comprobar si es un episodio de una serie
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
            # Si no es una serie, buscar como película
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

    # Guardar la caché de películas
    guardar_peliculas(cache)

    # Mantener el canal primero y ordenar los programas por hora
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
