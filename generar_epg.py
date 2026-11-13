
import os
import re
import json
import time
import unicodedata
import requests
import xml.etree.ElementTree as ET

from html.parser import HTMLParser
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


# =========================================================
# CONFIGURACION
# =========================================================

CANAL_ID = "WarnerChannel.us@Colombia"
ZONA = ZoneInfo("America/Guayaquil")

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

TVMAZE_URL = "https://api.tvmaze.com"
TMDB_URL = "https://api.themoviedb.org/3"

ARCHIVO_DOCX = "WARNER.docx"
ARCHIVO_XML = "epg.xml"
ARCHIVO_SERIES = "series.json"
ARCHIVO_PELICULAS = "peliculas.json"

IDIOMAS_BUSQUEDA = [
    "es-ES", "en-US", "pt-BR",
    "fr-FR", "de-DE", "it-IT"
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

EPISODIOS_MANUALES = {
    "Adoptando chicas": ("Two and a Half Men", 4, 23),
    "Chicas y helado": ("Two and a Half Men", 4, 24),
    "Aves grandes, arañas y mamá": ("Two and a Half Men", 5, 1),
    "Creo que ofendiste a Don": ("Two and a Half Men", 6, 13),
    "Primero estar de pie": ("Cobra Kai", 4, 2),
}

SERIES_SIN_EPISODIO = {
    "Viento a favor": "Two and a Half Men",
}

PELICULAS_MANUALES = {
    "Un jefe en pañales": 295693,
}

TITULOS_NO_BUSCAR = {
    "Hollywood One on One",
    "El Buzz",
}

SESION = requests.Session()
SESION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
})


# =========================================================
# ARCHIVOS JSON
# =========================================================

def cargar_json(ruta, clave):
    if not os.path.exists(ruta):
        datos = {"version": 1, clave: {}}
        guardar_json(ruta, datos)
        return datos

    with open(ruta, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    if not isinstance(datos, dict):
        raise ValueError(f"El archivo {ruta} no tiene un formato válido.")

    if not isinstance(datos.get(clave), dict):
        raise ValueError(
            f"El archivo {ruta} no contiene el apartado '{clave}'."
        )

    return datos


def guardar_json(ruta, datos):
    temporal = ruta + ".tmp"

    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)

    os.replace(temporal, ruta)


BASE_SERIES = cargar_json(ARCHIVO_SERIES, "series")
BASE_PELICULAS = cargar_json(ARCHIVO_PELICULAS, "peliculas")


def guardar_serie(nombre, show, tmdb_id=None, nombre_es=""):
    clave = normalizar(nombre)

    registro = {
        "nombre": nombre,
        "tvmaze_id": show.get("id"),
        "tmdb_id": tmdb_id,
        "nombre_es": nombre_es or NOMBRES_SERIES_ES.get(clave, "")
    }

    anterior = BASE_SERIES["series"].get(clave, {})

    for campo, valor in anterior.items():
        if valor and not registro.get(campo):
            registro[campo] = valor

    BASE_SERIES["series"][clave] = registro
    guardar_json(ARCHIVO_SERIES, BASE_SERIES)


def guardar_pelicula(titulo_origen, datos):
    clave = normalizar(titulo_origen)

    BASE_PELICULAS["peliculas"][clave] = {
        "titulo_origen": titulo_origen,
        "tmdb_id": datos["id"],
        "titulo_es": datos["titulo"],
        "sinopsis_es": datos["sinopsis"],
        "verificada": True
    }

    guardar_json(ARCHIVO_PELICULAS, BASE_PELICULAS)


# =========================================================
# UTILIDADES
# =========================================================

def normalizar(texto):
    texto = str(texto or "").strip().lower()

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
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

    return re.sub(r"<[^>]+>", "", str(texto)).strip()


def solicitar_json(url, params=None, timeout=25):
    respuesta = SESION.get(url, params=params, timeout=timeout)
    respuesta.raise_for_status()
    return respuesta.json()


# =========================================================
# LECTURA DE WARNER.DOCX
# =========================================================

def texto_celda(celda):
    return " ".join(
        p.text.strip()
        for p in celda.paragraphs
        if p.text.strip()
    ).strip()


def convertir_fecha_docx(texto):
    coincidencia = re.search(
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
        str(texto or "")
    )

    if not coincidencia:
        return None

    dia, mes, anio = map(int, coincidencia.groups())

    try:
        return datetime(anio, mes, dia).date()
    except ValueError:
        return None


def convertir_hora_docx(texto):
    texto = str(texto or "").strip().lower()
    texto = texto.replace(".", "")
    texto = re.sub(r"\s+", " ", texto)

    coincidencia = re.search(
        r"\b(\d{1,2}):(\d{2})\s*(a\s*m|p\s*m|am|pm)?\b",
        texto
    )

    if not coincidencia:
        return None

    hora = int(coincidencia.group(1))
    minuto = int(coincidencia.group(2))
    periodo = (coincidencia.group(3) or "").replace(" ", "")

    if minuto > 59:
        return None

    if periodo:
        if hora < 1 or hora > 12:
            return None

        if periodo == "pm" and hora != 12:
            hora += 12
        elif periodo == "am" and hora == 12:
            hora = 0

    elif hora > 23:
        return None

    return hora, minuto


def obtener_programacion_docx(programas_anterior=None):
    if not os.path.exists(ARCHIVO_DOCX):
        raise Exception(
            f"No se encontró el archivo {ARCHIVO_DOCX}."
        )

    documento = Document(ARCHIVO_DOCX)
    registros = []

    for numero_tabla, tabla in enumerate(documento.tables, start=1):
        filas = [
            [texto_celda(celda) for celda in fila.cells]
            for fila in tabla.rows
        ]

        fecha_tabla = None

        for fila in filas:
            for celda in fila:
                fecha = convertir_fecha_docx(celda)
                if fecha:
                    fecha_tabla = fecha
                    break
            if fecha_tabla:
                break

        if not fecha_tabla:
            print(
                f"Tabla {numero_tabla}: no se encontró fecha. "
                "Se omite."
            )
            continue

        encabezado = None
        tipo_tabla = None

        for indice, fila in enumerate(filas):
            celdas = [normalizar(c) for c in fila]

            if (
                any("hora inicio" in c for c in celdas)
                and any("hora fin" in c for c in celdas)
                and any("programa" in c for c in celdas)
            ):
                encabezado = indice
                tipo_tabla = "completa"
                break

            if (
                any(c == "hora" for c in celdas)
                and any(c in ("titulo", "título") for c in celdas)
            ):
                encabezado = indice
                tipo_tabla = "inicio"
                break

        if encabezado is None:
            print(
                f"Tabla {numero_tabla}: no se reconocieron "
                "los encabezados."
            )
            continue

        fila_encabezado = [
            normalizar(c) for c in filas[encabezado]
        ]

        if tipo_tabla == "completa":
            try:
                col_inicio = next(
                    i for i, c in enumerate(fila_encabezado)
                    if "hora inicio" in c
                )
                col_fin = next(
                    i for i, c in enumerate(fila_encabezado)
                    if "hora fin" in c
                )
                col_titulo = next(
                    i for i, c in enumerate(fila_encabezado)
                    if "programa" in c
                )
            except StopIteration:
                continue
        else:
            col_inicio = next(
                i for i, c in enumerate(fila_encabezado)
                if c == "hora"
            )
            col_titulo = next(
                i for i, c in enumerate(fila_encabezado)
                if c in ("titulo", "título")
            )
            col_fin = None

        for fila in filas[encabezado + 1:]:
            if not fila:
                continue

            if all(not celda.strip() for celda in fila):
                continue

            if any(convertir_fecha_docx(c) for c in fila):
                continue

            if len(fila) <= max(
                col_inicio,
                col_titulo,
                col_fin if col_fin is not None else 0
            ):
                continue

            hora_inicio = convertir_hora_docx(fila[col_inicio])
            titulo = fila[col_titulo].strip()

            if not hora_inicio or not titulo:
                continue

            # Ignorar separadores como Madrugada, Tarde y Noche.
            if convertir_fecha_docx(titulo):
                continue

            if normalizar(titulo) in {
                "madrugada", "manana", "tarde", "noche"
            }:
                continue

            hora, minuto = hora_inicio

            inicio = datetime(
                fecha_tabla.year,
                fecha_tabla.month,
                fecha_tabla.day,
                hora,
                minuto,
                tzinfo=ZONA
            )

            fin = None

            if tipo_tabla == "completa":
                hora_fin = convertir_hora_docx(fila[col_fin])

                if not hora_fin:
                    print("Hora de fin inválida:", titulo)
                    continue

                hora_f, minuto_f = hora_fin

                fin = datetime(
                    fecha_tabla.year,
                    fecha_tabla.month,
                    fecha_tabla.day,
                    hora_f,
                    minuto_f,
                    tzinfo=ZONA
                )

                if fin <= inicio:
                    fin += timedelta(days=1)

            registros.append({
                "title": titulo,
                "inicio": inicio,
                "fin": fin,
                "tipo": tipo_tabla,
                "tabla": numero_tabla
            })

    if not registros:
        raise Exception(
            "No se encontraron programas válidos en WARNER.docx. "
            "No se modificará el XML."
        )

    # Ordenar cronológicamente todas las tablas.
    registros.sort(key=lambda p: p["inicio"])

    # En tablas HORA/TÍTULO, el siguiente inicio es el final
    # del programa anterior.
    for indice, programa in enumerate(registros):
        if programa["tipo"] != "inicio":
            continue

        siguiente = None

        for candidato in registros[indice + 1:]:
            if candidato["inicio"] > programa["inicio"]:
                siguiente = candidato
                break

        if siguiente:
            programa["fin"] = siguiente["inicio"]

        else:
            # Si existe un programa anterior en el XML con
            # el mismo inicio, se conserva su hora de final.
            if programas_anterior:
                inicio_xml = programa["inicio"].strftime(
                    "%Y%m%d%H%M%S %z"
                )

                anterior = programas_anterior.get(
                    (CANAL_ID, inicio_xml)
                )

                if anterior is not None:
                    try:
                        programa["fin"] = fecha_xml_a_datetime(
                            anterior.get("stop")
                        )
                    except (ValueError, TypeError):
                        programa["fin"] = None

        if programa["fin"] is None:
            print(
                "Último programa sin hora de finalización; "
                "se descarta:",
                programa["title"]
            )

    resultado = []

    for programa in registros:
        inicio = programa["inicio"]
        fin = programa["fin"]

        if fin is None or fin <= inicio:
            continue

        resultado.append({
            "title": programa["title"],
            "start": int(inicio.timestamp() * 1000),
            "end": int(fin.timestamp() * 1000)
        })

    if not resultado:
        raise Exception(
            "No quedaron programas con horarios válidos."
        )

    print("---------------------------------------")
    print("Tablas procesadas:", len(documento.tables))
    print("Programas leídos:", len(registros))
    print("Programas válidos:", len(resultado))
    print("---------------------------------------")

    return resultado


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


def obtener_inicio_programa(programa):
    return datetime.fromtimestamp(
        int(programa["start"]) / 1000,
        tz=ZONA
    ).replace(second=0, microsecond=0)


# =========================================================
# TVMAZE: SERIES
# =========================================================

@lru_cache(maxsize=100)
def buscar_serie_tvmaze(nombre):
    clave = normalizar(nombre)
    guardada = BASE_SERIES["series"].get(clave, {})

    if guardada.get("tvmaze_id"):
        try:
            show = solicitar_json(
                f"{TVMAZE_URL}/shows/{guardada['tvmaze_id']}"
            )

            if normalizar(show.get("name")) == clave:
                return show

        except Exception as error:
            print("No se pudo recuperar la serie guardada:", error)

    try:
        resultados = solicitar_json(
            f"{TVMAZE_URL}/search/shows",
            params={"q": nombre}
        )

        for resultado in resultados:
            show = resultado.get("show", {})

            if normalizar(show.get("name")) == clave:
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
        print("No se pudieron obtener alias:", error)

    return aliases


# =========================================================
# TMDb: SERIES
# =========================================================

@lru_cache(maxsize=100)
def buscar_serie_tmdb(nombre_original):
    if not TMDB_API_KEY:
        return None

    clave = normalizar(nombre_original)
    guardada = BASE_SERIES["series"].get(clave, {})
    tmdb_id = guardada.get("tmdb_id")

    if tmdb_id:
        try:
            serie = solicitar_json(
                f"{TMDB_URL}/tv/{tmdb_id}",
                params={
                    "api_key": TMDB_API_KEY,
                    "language": "en-US"
                }
            )

            nombres = [
                serie.get("name", ""),
                serie.get("original_name", "")
            ]

            if any(normalizar(n) == clave for n in nombres if n):
                return serie

        except Exception as error:
            print("No se pudo recuperar serie de TMDb:", error)

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

            for resultado in resultados:
                nombres = [
                    resultado.get("name", ""),
                    resultado.get("original_name", "")
                ]

                if any(normalizar(n) == clave for n in nombres if n):
                    return resultado

        except Exception as error:
            print(f"Error buscando serie en TMDb ({idioma}):", error)

    return None


@lru_cache(maxsize=100)
def obtener_nombre_serie_es(nombre_original):
    serie = buscar_serie_tmdb(nombre_original)

    if serie and TMDB_API_KEY:
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
            print("Error obteniendo nombre español:", error)

    return NOMBRES_SERIES_ES.get(
        normalizar(nombre_original),
        ""
    )


# =========================================================
# TMDb: EPISODIOS
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
        print("Error obteniendo temporadas:", error)
        return {}


@lru_cache(maxsize=500)
def obtener_episodios_temporada_tmdb(tmdb_id, temporada, idioma):
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

    if clave not in catalogo:
        catalogo[clave] = informacion
        return

    existente = catalogo[clave]

    if existente is None:
        return

    misma = (
        existente["serie"] == informacion["serie"]
        and existente["temporada"] == informacion["temporada"]
        and existente["numero"] == informacion["numero"]
    )

    if not misma:
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

        nombre_es = obtener_nombre_serie_es(nombre)

        guardar_serie(nombre, show, tmdb_id, nombre_es)

        episodios_por_numero = {}

        for episodio in episodios_tvmaze:
            temporada = episodio.get("season")
            numero = episodio.get("number")
            titulo = episodio.get("name")

            if temporada is None or numero is None or not titulo:
                continue

            clave = (temporada, numero)

            informacion = {
                "serie": nombre,
                "episodio": titulo,
                "temporada": temporada,
                "numero": numero,
                "show_id": show_id,
                "idioma": "en"
            }

            episodios_por_numero[clave] = informacion
            agregar_coincidencia(catalogo, titulo, informacion)

        episodios_por_serie[normalizar(nombre)] = episodios_por_numero

        cantidad = len(episodios_por_numero)

        if tmdb_id:
            detalles = obtener_detalles_serie_tmdb(tmdb_id)

            for temporada_info in detalles.get("seasons", []):
                numero_temporada = temporada_info.get("season_number")

                if numero_temporada is None:
                    continue

                for idioma in IDIOMAS_BUSQUEDA:
                    traducidos = obtener_episodios_temporada_tmdb(
                        tmdb_id,
                        numero_temporada,
                        idioma
                    )

                    for episodio_tmdb in traducidos:
                        numero = episodio_tmdb.get("episode_number")
                        titulo = episodio_tmdb.get("name", "")

                        if numero is None or not titulo:
                            continue

                        clave = (numero_temporada, numero)

                        if clave in episodios_por_numero:
                            agregar_coincidencia(
                                catalogo,
                                titulo,
                                episodios_por_numero[clave]
                            )

        print(
            f"{nombre}: {cantidad} episodios de TVmaze"
            + (" y traducciones de TMDb" if tmdb_id else "")
        )

        aliases = obtener_aliases_tvmaze(show_id)

        if aliases:
            print(
                f"Alias adicionales encontrados para {nombre}:",
                len(aliases)
            )

    print("Aplicando identificaciones manuales...")

    for titulo, datos in EPISODIOS_MANUALES.items():
        nombre_serie, temporada, numero = datos

        episodios = episodios_por_serie.get(
            normalizar(nombre_serie),
            {}
        )

        informacion = episodios.get((temporada, numero))

        if informacion:
            agregar_coincidencia(catalogo, titulo, informacion)

            print(
                f"Identificado: {titulo} -> "
                f"{nombre_serie} S{temporada:02d}E{numero:02d}"
            )
        else:
            print("Episodio manual no encontrado:", titulo)

    return catalogo, episodios_por_serie


# =========================================================
# TMDb: PELICULAS
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

    clave = normalizar(titulo)

    guardada = BASE_PELICULAS["peliculas"].get(clave)

    if guardada and guardada.get("verificada"):
        return {"id": guardada["tmdb_id"]}

    for titulo_manual, tmdb_id in PELICULAS_MANUALES.items():
        if normalizar(titulo_manual) == clave:
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

                posibles = [
                    resultado.get("title", ""),
                    resultado.get("original_title", "")
                ]

                if any(
                    normalizar(nombre) == clave
                    for nombre in posibles if nombre
                ):
                    return resultado

        except Exception as error:
            print(f"Error buscando película ({idioma}):", error)

    for tmdb_id, resultado in candidatos.items():
        alternativos = obtener_titulos_alternativos_pelicula(tmdb_id)

        if clave in alternativos:
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

        for pais in ["MX", "ES"]:
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
    clave = normalizar(titulo)

    guardada = BASE_PELICULAS["peliculas"].get(clave)

    if guardada and guardada.get("verificada"):
        return {
            "id": guardada["tmdb_id"],
            "titulo": guardada["titulo_es"],
            "sinopsis": guardada.get("sinopsis_es", "")
        }

    resultado = buscar_pelicula_tmdb(titulo)

    if not resultado:
        return None

    tmdb_id = resultado.get("id")

    if not tmdb_id:
        return None

    traduccion = obtener_traduccion_es("movie", tmdb_id)

    titulo_es = traduccion.get("title", "").strip()
    sinopsis_es = limpiar_texto(traduccion.get("overview", ""))

    for idioma in ["es-MX", "es-ES"]:
        if titulo_es and sinopsis_es:
            break

        try:
            detalles = solicitar_json(
                f"{TMDB_URL}/movie/{tmdb_id}",
                params={
                    "api_key": TMDB_API_KEY,
                    "language": idioma
                }
            )

            if not titulo_es:
                titulo_es = detalles.get("title", "").strip()

            if not sinopsis_es:
                sinopsis_es = limpiar_texto(
                    detalles.get("overview", "")
                )

        except Exception as error:
            print(f"Error obteniendo detalles {idioma}:", error)

    if not titulo_es:
        return None

    datos = {
        "id": tmdb_id,
        "titulo": titulo_es,
        "sinopsis": sinopsis_es
    }

    guardar_pelicula(titulo, datos)

    return datos


# =========================================================
# CREACION DE PROGRAMAS XMLTV
# =========================================================

def agregar_texto(elemento, etiqueta, texto, idioma=None):
    if texto is None or texto == "":
        return None

    atributos = {}

    if idioma:
        atributos["lang"] = idioma

    nuevo = ET.SubElement(elemento, etiqueta, atributos)
    nuevo.text = str(texto)

    return nuevo


def crear_programa(
    programa,
    catalogo_series,
    episodios_por_serie
):
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

        clave = normalizar(titulo)

        episodio = catalogo_series.get(clave)

        if episodio:
            nombre_serie = episodio["serie"]

            agregar_texto(
                elemento,
                "title",
                nombre_serie,
                "en"
            )

            temporada = episodio["temporada"]
            numero = episodio["numero"]
            titulo_episodio = episodio.get("episodio", "")

            identificacion = (
                f"Temporada {temporada} Episodio {numero}"
            )

            subtitulo = identificacion

            if titulo_episodio:
                subtitulo += f" - {titulo_episodio}"

            agregar_texto(
                elemento,
                "sub-title",
                subtitulo
            )

            numero_episodio = ET.SubElement(
                elemento,
                "episode-num",
                {"system": "onscreen"}
            )

            numero_episodio.text = identificacion

            print(
                f"Identificado: {nombre_serie} - "
                f"{identificacion} - {titulo_episodio}"
            )

            return elemento

        serie_sin_episodio = None

        for titulo_manual, nombre_serie in SERIES_SIN_EPISODIO.items():
            if normalizar(titulo_manual) == clave:
                serie_sin_episodio = nombre_serie
                break

        if serie_sin_episodio:
            agregar_texto(
                elemento,
                "title",
                serie_sin_episodio,
                "en"
            )

            agregar_texto(
                elemento,
                "sub-title",
                titulo,
                "es"
            )

            print(
                "Serie identificada, episodio pendiente:",
                titulo
            )

            return elemento

        pelicula = obtener_datos_pelicula(titulo)

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
                f"Película identificada: {titulo} "
                f"(TMDb ID: {pelicula['id']})"
            )

            return elemento

        agregar_texto(elemento, "title", titulo, "es")

        if titulo not in TITULOS_NO_BUSCAR:
            print("Sin coincidencia verificada:", titulo)

        return elemento

    except (ValueError, TypeError, OSError) as error:
        print("Error creando programa:", titulo, error)
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

                programas[(canal, inicio)] = elemento

            except (ValueError, TypeError):
                continue

        print(
            "Programas recuperados del XML anterior:",
            len(programas)
        )

    except ET.ParseError as error:
        raise Exception(
            "El XML anterior está dañado. Se cancela la generación."
        ) from error

    return programas


# =========================================================
# GENERAR XMLTV
# =========================================================

def generar_xml():
    print("=" * 55)
    print("GENERADOR EPG WARNER CHANNEL DESDE DOCX")
    print("=" * 55)

    programas_finales = cargar_programas_anterior()

    # Leer la programación directamente desde WARNER.docx.
    programas_docx = obtener_programacion_docx(
        programas_finales
    )

    print("Registros recibidos de WARNER.docx:", len(programas_docx))

    # Consultar TVmaze y TMDb.
    catalogo_series, episodios_por_serie = construir_catalogo_series()

    print(
        "Episodios identificables en catálogo:",
        sum(1 for valor in catalogo_series.values() if valor)
    )

    nuevos = 0
    actualizados = 0
    descartados = 0

    for programa in programas_docx:
        elemento = crear_programa(
            programa,
            catalogo_series,
            episodios_por_serie
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
        {"generator-info-name": "EPG Warner Channel DOCX"}
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
    print("Programas nuevos:", nuevos)
    print("Programas actualizados:", actualizados)
    print("Registros descartados:", descartados)
    print("Total conservado:", len(lista_ordenada))
    print("Archivo generado:", ARCHIVO_XML)
    print("Zona horaria: America/Guayaquil")
    print("TVmaze integrado.")
    print("TMDb:", "Configurado" if TMDB_API_KEY else "Sin clave")
    print("Series guardadas:", len(BASE_SERIES["series"]))
    print("Películas guardadas:", len(BASE_PELICULAS["peliculas"]))
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
