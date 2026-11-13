
import os
import re
import json
import unicodedata
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from docx import Document
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache


# =========================================================
# CONFIGURACIÓN
# =========================================================

CANAL_ID = "WarnerChannel.us@Colombia"
ZONA = ZoneInfo("America/Guayaquil")

ARCHIVO_DOCX = "WARNER.docx"
ARCHIVO_XML = "epg.xml"
ARCHIVO_SERIES = "series.json"
ARCHIVO_PELICULAS = "peliculas.json"

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

TVMAZE_URL = "https://api.tvmaze.com"
TMDB_URL = "https://api.themoviedb.org/3"

# mi.tv - Warner Channel Colombia
MITV_BASE = "https://mi.tv"
MITV_PAIS = "co"
MITV_CANAL = "warner"
MITV_OFFSET = "-300"
MITV_REFERER = "https://mi.tv/co/canales/warner"

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
    ),
    "Accept": "text/html,application/json,*/*",
    "Referer": MITV_REFERER,
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
        raise ValueError(f"El archivo {ruta} no tiene formato válido.")

    if not isinstance(datos.get(clave), dict):
        raise ValueError(f"Falta el apartado '{clave}' en {ruta}.")

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


def limpiar_texto(texto):
    if not texto:
        return ""

    texto = BeautifulSoup(str(texto), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", texto).strip()


def solicitar_json(url, params=None, timeout=30):
    respuesta = SESION.get(
        url,
        params=params,
        timeout=timeout
    )
    respuesta.raise_for_status()
    return respuesta.json()


def obtener_texto(programa, campos):
    for campo in campos:
        valor = programa.get(campo)

        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    return ""


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
        raise Exception(f"No se encontró {ARCHIVO_DOCX}.")

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
                and any(c == "titulo" for c in celdas)
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

        encabezados = [normalizar(c) for c in filas[encabezado]]

        try:
            if tipo_tabla == "completa":
                col_inicio = next(
                    i for i, c in enumerate(encabezados)
                    if "hora inicio" in c
                )
                col_fin = next(
                    i for i, c in enumerate(encabezados)
                    if "hora fin" in c
                )
                col_titulo = next(
                    i for i, c in enumerate(encabezados)
                    if "programa" in c
                )
            else:
                col_inicio = encabezados.index("hora")
                col_titulo = encabezados.index("titulo")
                col_fin = None

        except (StopIteration, ValueError):
            continue

        for fila in filas[encabezado + 1:]:
            if not fila or all(not c.strip() for c in fila):
                continue

            if any(convertir_fecha_docx(c) for c in fila):
                continue

            max_col = max(
                col_inicio,
                col_titulo,
                col_fin if col_fin is not None else 0
            )

            if len(fila) <= max_col:
                continue

            hora_inicio = convertir_hora_docx(fila[col_inicio])
            titulo = fila[col_titulo].strip()

            if not hora_inicio or not titulo:
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
                "tipo": tipo_tabla
            })

    if not registros:
        raise Exception("No se encontraron programas válidos en WARNER.docx.")

    registros.sort(key=lambda p: p["inicio"])

    for indice, programa in enumerate(registros):
        if programa["tipo"] != "inicio":
            continue

        siguiente = next(
            (
                p for p in registros[indice + 1:]
                if p["inicio"] > programa["inicio"]
            ),
            None
        )

        if siguiente:
            programa["fin"] = siguiente["inicio"]

        elif programas_anterior:
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
            print("Último programa sin finalización:", programa["title"])

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
        raise Exception("No quedaron programas con horarios válidos.")

    print("---------------------------------------")
    print("Tablas procesadas:", len(documento.tables))
    print("Programas leídos:", len(registros))
    print("Programas válidos:", len(resultado))
    print("---------------------------------------")

    return resultado


# =========================================================
# FECHAS XMLTV
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
# MI.TV: CONSULTA DE PROGRAMACIÓN
# =========================================================

def obtener_html_mitv(fecha):
    fecha_texto = fecha.strftime("%Y-%m-%d")

    url = (
        f"{MITV_BASE}/{MITV_PAIS}/async/channel/"
        f"{MITV_CANAL}/{fecha_texto}/{MITV_OFFSET}"
    )

    try:
        respuesta = SESION.get(
            url,
            headers={"Referer": MITV_REFERER},
            timeout=30
        )

        respuesta.raise_for_status()
        return respuesta.text

    except requests.RequestException as error:
        print(f"Error consultando mi.tv para {fecha_texto}:", error)
        return ""


def extraer_temporada_episodio(texto):
    texto = limpiar_texto(texto).lower()

    patrones = [
        r"temporada\s*(\d+)\s*[,.\-:]?\s*episodio\s*(\d+)",
        r"temporada\s*(\d+)\s*[,.\-:]?\s*cap[ií]tulo\s*(\d+)",
        r"\bs(\d{1,2})\s*e(\d{1,3})\b",
        r"\bt(\d{1,2})\s*e(\d{1,3})\b",
        r"(\d+)[ªa]?\s*temporada\s*[,.\-:]?\s*episodio\s*(\d+)",
    ]

    for patron in patrones:
        coincidencia = re.search(patron, texto, re.IGNORECASE)

        if coincidencia:
            return (
                int(coincidencia.group(1)),
                int(coincidencia.group(2))
            )

    return None, None


def extraer_programas_mitv(html, fecha):
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    elementos = soup.select("ul.broadcasts > li")

    if not elementos:
        elementos = soup.select("li.broadcast")

    resultados = []
    fecha_actual = fecha
    hora_anterior = None

    for elemento in elementos:
        clases = elemento.get("class", [])

        if "native" in clases:
            continue

        elemento_hora = elemento.select_one(".time")
        elemento_titulo = elemento.select_one("h2")

        if not elemento_hora or not elemento_titulo:
            continue

        texto_hora = limpiar_texto(elemento_hora.get_text(" ", strip=True))

        coincidencia = re.search(
            r"(\d{1,2}):(\d{2})",
            texto_hora
        )

        if not coincidencia:
            continue

        hora = int(coincidencia.group(1))
        minuto = int(coincidencia.group(2))

        if hora > 23 or minuto > 59:
            continue

        minutos_dia = hora * 60 + minuto

        if hora_anterior is not None and minutos_dia < hora_anterior:
            fecha_actual += timedelta(days=1)

        hora_anterior = minutos_dia

        inicio = datetime(
            fecha_actual.year,
            fecha_actual.month,
            fecha_actual.day,
            hora,
            minuto,
            tzinfo=ZONA
        )

        titulo = limpiar_texto(
            elemento_titulo.get_text(" ", strip=True)
        )

        subtitulo_elemento = elemento.select_one(".sub-title")
        sinopsis_elemento = elemento.select_one(".synopsis")

        subtitulo = (
            limpiar_texto(subtitulo_elemento.get_text(" ", strip=True))
            if subtitulo_elemento else ""
        )

        sinopsis = (
            limpiar_texto(sinopsis_elemento.get_text(" ", strip=True))
            if sinopsis_elemento else ""
        )

        enlace = elemento.select_one("a[href]")
        url = enlace.get("href", "") if enlace else ""

        temporada, episodio = extraer_temporada_episodio(
            subtitulo + " " + titulo
        )

        titulo_episodio = subtitulo

        # Quitar la identificación de temporada del subtítulo.
        titulo_episodio = re.sub(
            r"temporada\s*\d+\s*[,.\-:]?\s*"
            r"(episodio|cap[ií]tulo)\s*\d+",
            "",
            titulo_episodio,
            flags=re.IGNORECASE
        ).strip(" -:,.")
        
        resultados.append({
            "inicio": inicio,
            "title": titulo,
            "subtitulo": subtitulo,
            "titulo_episodio": titulo_episodio,
            "sinopsis": sinopsis,
            "temporada": temporada,
            "episodio": episodio,
            "url": url
        })

    return resultados


def obtener_programacion_mitv(programas_docx):
    if not programas_docx:
        return {}

    fechas = []

    for programa in programas_docx:
        inicio = obtener_inicio_programa(programa)
        fechas.append(inicio.date())

    fecha_inicio = min(fechas) - timedelta(days=1)
    fecha_fin = max(fechas) + timedelta(days=1)

    resultados = {}
    fecha = fecha_inicio

    print("Consultando programación de Warner en mi.tv...")
    print("Desde:", fecha_inicio)
    print("Hasta:", fecha_fin)

    while fecha <= fecha_fin:
        print("Consultando mi.tv:", fecha)

        html = obtener_html_mitv(fecha)
        programas = extraer_programas_mitv(html, fecha)

        for programa in programas:
            clave = programa["inicio"].strftime("%Y%m%d%H%M")

            resultados[clave] = programa

        print("Programas encontrados en mi.tv:", len(programas))
        fecha += timedelta(days=1)

    print("Total de registros recuperados de mi.tv:", len(resultados))

    return resultados


def buscar_programa_mitv(programa, catalogo_mitv):
    inicio = obtener_inicio_programa(programa)
    clave = inicio.strftime("%Y%m%d%H%M")

    encontrado = catalogo_mitv.get(clave)

    if not encontrado:
        # Intentar una diferencia máxima de un minuto.
        for diferencia in [-1, 1]:
            otra_hora = inicio + timedelta(minutes=diferencia)
            otra_clave = otra_hora.strftime("%Y%m%d%H%M")

            if otra_clave in catalogo_mitv:
                encontrado = catalogo_mitv[otra_clave]
                break

    if not encontrado:
        return None

    titulo_docx = normalizar(programa.get("title", ""))

    titulos_mitv = [
        normalizar(encontrado.get("title", "")),
        normalizar(encontrado.get("subtitulo", "")),
        normalizar(encontrado.get("titulo_episodio", ""))
    ]

    # Se acepta la coincidencia horaria si también coincide
    # el título, el subtítulo o una parte significativa.
    coincide_titulo = any(
        titulo_docx == titulo
        or (
            len(titulo_docx) >= 6
            and titulo_docx in titulo
        )
        or (
            len(titulo) >= 6
            and titulo in titulo_docx
        )
        for titulo in titulos_mitv
        if titulo
    )

    if coincide_titulo:
        return encontrado

    return None


# =========================================================
# TVMAZE: SERIES Y EPISODIOS
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
            print("Error recuperando serie guardada:", error)

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


def construir_catalogo_series():
    catalogo = {}
    episodios_por_serie = {}

    print("Consultando series y episodios en TVmaze...")

    for nombre in SERIES_CONOCIDAS:
        show = buscar_serie_tvmaze(nombre)

        if not show:
            print("Serie no encontrada en TVmaze:", nombre)
            continue

        episodios = obtener_episodios_tvmaze(show["id"])
        episodios_por_numero = {}

        for episodio in episodios:
            temporada = episodio.get("season")
            numero = episodio.get("number")
            titulo = episodio.get("name")

            if temporada is None or numero is None or not titulo:
                continue

            informacion = {
                "serie": nombre,
                "episodio": titulo,
                "temporada": temporada,
                "numero": numero
            }

            episodios_por_numero[(temporada, numero)] = informacion

            clave = normalizar(titulo)

            if clave not in catalogo:
                catalogo[clave] = informacion
            elif catalogo[clave] != informacion:
                catalogo[clave] = None

        episodios_por_serie[normalizar(nombre)] = episodios_por_numero

        guardar_serie(nombre, show)

        print(
            f"{nombre}: {len(episodios_por_numero)} "
            "episodios de TVmaze"
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
            catalogo[normalizar(titulo)] = informacion

            print(
                f"Identificado: {titulo} -> "
                f"{nombre_serie} S{temporada:02d}E{numero:02d}"
            )

    return catalogo, episodios_por_serie


# =========================================================
# TMDb: PELÍCULAS
# =========================================================

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
                nombres = [
                    resultado.get("title", ""),
                    resultado.get("original_title", "")
                ]

                if any(
                    normalizar(n) == clave
                    for n in nombres if n
                ):
                    return resultado

        except Exception as error:
            print(f"Error buscando película en TMDb ({idioma}):", error)

    return None


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

    titulo_es = ""
    sinopsis_es = ""

    for idioma in ["es-MX", "es-ES", "en-US"]:
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

            if titulo_es and sinopsis_es:
                break

        except Exception as error:
            print("Error obteniendo película:", error)

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
# XMLTV
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


def agregar_datos_episodio(elemento, temporada, numero, titulo_episodio=""):
    identificacion = (
        f"Temporada {temporada} Episodio {numero}"
    )

    subtitulo = identificacion

    if titulo_episodio:
        subtitulo += f" - {titulo_episodio}"

    agregar_texto(
        elemento,
        "sub-title",
        subtitulo,
        "es"
    )

    agregar_texto(
        elemento,
        "episode-num",
        identificacion,
        "es"
    )

    # XMLTV: temporada y episodio comienzan desde cero.
    numero_xmltv = ET.SubElement(
        elemento,
        "episode-num",
        {"system": "xmltv_ns"}
    )

    numero_xmltv.text = f"{int(temporada) - 1}.{int(numero) - 1}."


def crear_programa(
    programa,
    catalogo_series,
    episodios_por_serie,
    catalogo_mitv
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

        # -------------------------------------------------
        # 1. MI.TV: FUENTE PRINCIPAL
        # -------------------------------------------------

        datos_mitv = buscar_programa_mitv(
            programa,
            catalogo_mitv
        )

        if datos_mitv:
            titulo_mitv = datos_mitv.get("title", "")
            titulo_episodio = datos_mitv.get(
                "titulo_episodio",
                ""
            )
            sinopsis = datos_mitv.get("sinopsis", "")

            temporada = datos_mitv.get("temporada")
            numero = datos_mitv.get("episodio")

            if temporada and numero:
                agregar_texto(
                    elemento,
                    "title",
                    titulo_mitv or titulo,
                    "es"
                )

                agregar_datos_episodio(
                    elemento,
                    temporada,
                    numero,
                    titulo_episodio
                )

                if sinopsis:
                    agregar_texto(
                        elemento,
                        "desc",
                        sinopsis,
                        "es"
                    )

                print(
                    f"MI.TV: {titulo_mitv} "
                    f"S{temporada:02d}E{numero:02d}"
                )

                return elemento

            # Si mi.tv tiene sinopsis pero no temporada/episodio,
            # se conserva la sinopsis y se continúa con los respaldos.
            if sinopsis:
                agregar_texto(
                    elemento,
                    "desc",
                    sinopsis,
                    "es"
                )

            # Si el título de mi.tv coincide con una serie,
            # se usa para identificar el nombre de la serie.
            if titulo_mitv:
                clave_mitv = normalizar(titulo_mitv)

                if clave_mitv in {
                    normalizar(n) for n in SERIES_CONOCIDAS
                }:
                    agregar_texto(
                        elemento,
                        "title",
                        titulo_mitv,
                        "es"
                    )

        # -------------------------------------------------
        # 2. TVMAZE: RESPALDO PARA EPISODIOS
        # -------------------------------------------------

        posibles_titulos = [clave]

        if datos_mitv:
            posibles_titulos.extend([
                normalizar(datos_mitv.get("titulo_episodio", "")),
                normalizar(datos_mitv.get("subtitulo", ""))
            ])

        episodio = None

        for posible in posibles_titulos:
            if posible and catalogo_series.get(posible):
                episodio = catalogo_series[posible]
                break

        if episodio:
            nombre_serie = episodio["serie"]
            temporada = episodio["temporada"]
            numero = episodio["numero"]
            titulo_episodio = episodio.get("episodio", "")

            agregar_texto(
                elemento,
                "title",
                nombre_serie,
                "en"
            )

            agregar_datos_episodio(
                elemento,
                temporada,
                numero,
                titulo_episodio
            )

            if datos_mitv and datos_mitv.get("sinopsis"):
                agregar_texto(
                    elemento,
                    "desc",
                    datos_mitv["sinopsis"],
                    "es"
                )

            print(
                f"TVmaze: {nombre_serie} "
                f"S{temporada:02d}E{numero:02d}"
            )

            return elemento

        # -------------------------------------------------
        # 3. SERIES CONOCIDAS SIN EPISODIO IDENTIFICADO
        # -------------------------------------------------

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
                "es"
            )

            agregar_texto(
                elemento,
                "sub-title",
                titulo,
                "es"
            )

            print("Serie identificada, episodio pendiente:", titulo)
            return elemento

        # -------------------------------------------------
        # 4. TMDb: RESPALDO PARA PELÍCULAS
        # -------------------------------------------------

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

            print("Película identificada:", titulo)
            return elemento

        # -------------------------------------------------
        # 5. INFORMACIÓN BÁSICA
        # -------------------------------------------------

        if not elemento.find("title"):
            agregar_texto(
                elemento,
                "title",
                titulo,
                "es"
            )

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
    print("GENERADOR EPG WARNER CHANNEL DESDE DOCX + MI.TV")
    print("=" * 55)

    programas_finales = cargar_programas_anterior()

    programas_docx = obtener_programacion_docx(
        programas_finales
    )

    print(
        "Registros recibidos de WARNER.docx:",
        len(programas_docx)
    )

    # Consultar mi.tv para las fechas incluidas en el DOCX.
    catalogo_mitv = obtener_programacion_mitv(
        programas_docx
    )

    # Catálogo de respaldo.
    catalogo_series, episodios_por_serie = construir_catalogo_series()

    print(
        "Episodios identificables en TVmaze:",
        sum(1 for valor in catalogo_series.values() if valor)
    )

    nuevos = 0
    actualizados = 0
    descartados = 0
    coincidencias_mitv = 0

    for programa in programas_docx:
        datos_mitv = buscar_programa_mitv(
            programa,
            catalogo_mitv
        )

        if datos_mitv:
            coincidencias_mitv += 1

        elemento = crear_programa(
            programa,
            catalogo_series,
            episodios_por_serie,
            catalogo_mitv
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
        {"generator-info-name": "EPG Warner Channel DOCX mi.tv"}
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
    print("Coincidencias con mi.tv:", coincidencias_mitv)
    print("Programas nuevos:", nuevos)
    print("Programas actualizados:", actualizados)
    print("Registros descartados:", descartados)
    print("Total conservado:", len(lista_ordenada))
    print("Archivo generado:", ARCHIVO_XML)
    print("Zona horaria: America/Guayaquil")
    print("mi.tv: fuente principal")
    print("TVmaze: respaldo de episodios")
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
