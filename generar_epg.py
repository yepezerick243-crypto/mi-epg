
import os
import re
import time
import copy
import requests
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse


# =========================================================
# CONFIGURACION
# =========================================================

API_BASE = (
    "https://d3ur398j0yj7gx.cloudfront.net/"
    "ajax/program_guide/feed/block"
)

CANAL_ID = "Telemundo.us"
CANAL_NOMBRE = "Telemundo"

ZONA = ZoneInfo("America/Guayaquil")

ARCHIVO_XML = "epg.xml"

# SOLO 6 DIAS DE PROGRAMACION
DIAS_A_GENERAR = 6

# Conservar historial reciente
HORAS_HISTORIAL = 24

INTENTOS = 4
ESPERA_REINTENTO = 10

SESION = requests.Session()

SESION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.telemundo.com/",
    "Origin": "https://www.telemundo.com",
})


# =========================================================
# UTILIDADES
# =========================================================

def limpiar_texto(texto):
    if texto is None:
        return ""

    texto = str(texto)
    texto = re.sub(r"<[^>]*>", "", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def url_valida(url):
    if not url:
        return False

    try:
        resultado = urlparse(str(url))

        return (
            resultado.scheme in ("http", "https")
            and bool(resultado.netloc)
        )
    except Exception:
        return False


def convertir_hora(texto):
    texto = limpiar_texto(texto).lower()
    texto = texto.replace(" ", "")

    formatos = [
        "%I:%M%p",
        "%I%p",
    ]

    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).time()
        except ValueError:
            continue

    raise ValueError(
        f"No se pudo interpretar la hora: {texto}"
    )


def fecha_xml(fecha):
    return fecha.strftime("%Y%m%d%H%M%S %z")


def fecha_desde_xml(texto):
    return datetime.strptime(
        texto,
        "%Y%m%d%H%M%S %z"
    ).astimezone(ZONA)


# =========================================================
# CONSULTA API TELE​​MUNDO
# =========================================================

def solicitar_programacion(fecha):

    fecha_url = fecha.strftime("%Y/%m/%d")

    url = f"{API_BASE}/{fecha_url}"

    for intento in range(1, INTENTOS + 1):

        try:
            print(
                f"Consultando Telemundo: "
                f"{fecha_url} ({intento}/{INTENTOS})"
            )

            respuesta = SESION.get(
                url,
                timeout=(20, 45)
            )

            respuesta.raise_for_status()

            datos = respuesta.json()

            if not isinstance(datos, list):
                raise ValueError(
                    "La API no devolvió una lista de programas."
                )

            if not datos:
                raise ValueError(
                    "La API devolvió una programación vacía."
                )

            print(
                "Programas recibidos:",
                len(datos)
            )

            return datos

        except Exception as error:

            print(
                "Error consultando Telemundo:",
                error
            )

            if intento < INTENTOS:

                print(
                    f"Esperando {ESPERA_REINTENTO} segundos..."
                )

                time.sleep(ESPERA_REINTENTO)

    raise Exception(
        f"No se pudo obtener la programación del {fecha_url}."
    )


# =========================================================
# PROCESAR PROGRAMACION
# =========================================================

def procesar_programas(datos, fecha):

    programas = []

    for elemento in datos:

        titulo = limpiar_texto(
            elemento.get("name")
        )

        hora_texto = elemento.get("time_full")

        if not titulo or not hora_texto:
            continue

        try:
            hora = convertir_hora(hora_texto)

            inicio = datetime(
                fecha.year,
                fecha.month,
                fecha.day,
                hora.hour,
                hora.minute,
                tzinfo=ZONA
            )

        except Exception as error:

            print(
                f"Programa omitido: {titulo}. "
                f"Error de horario: {error}"
            )

            continue

        descripcion = limpiar_texto(
            elemento.get("description", "")
        )

        imagen = limpiar_texto(
            elemento.get("image_url", "")
        )

        enlace = limpiar_texto(
            elemento.get("url", "")
        )

        rating = limpiar_texto(
            elemento.get("rating", "")
        )

        programas.append({
            "inicio": inicio,
            "titulo": titulo,
            "descripcion": descripcion,
            "imagen": imagen,
            "url": enlace,
            "rating": rating,
        })

    return programas


# =========================================================
# OBTENER LOS 6 DIAS
# =========================================================

def obtener_programacion():

    hoy = datetime.now(ZONA).date()

    programas = []

    print("=" * 60)
    print("GENERADOR EPG EXCLUSIVO DE TELEMUNDO")
    print("=" * 60)

    print("Fecha inicial:", hoy)

    ultimo_dia = hoy + timedelta(
        days=DIAS_A_GENERAR - 1
    )

    print("Último día incluido:", ultimo_dia)
    print("Días de programación:", DIAS_A_GENERAR)
    print("Zona horaria: America/Guayaquil")

    print("=" * 60)

    # EXACTAMENTE 6 CONSULTAS DE FECHA
    for desplazamiento in range(DIAS_A_GENERAR):

        fecha = hoy + timedelta(
            days=desplazamiento
        )

        datos = solicitar_programacion(fecha)

        registros = procesar_programas(
            datos,
            fecha
        )

        if not registros:

            raise Exception(
                f"No se encontraron programas válidos "
                f"para {fecha}."
            )

        programas.extend(registros)

        time.sleep(0.5)

    if not programas:

        raise Exception(
            "No se obtuvo programación de Telemundo."
        )

    # Ordenar cronológicamente
    programas.sort(
        key=lambda programa: programa["inicio"]
    )

    # Eliminar horarios duplicados
    unicos = {}

    for programa in programas:

        clave = programa["inicio"]

        if clave not in unicos:

            unicos[clave] = programa

        else:

            anterior = unicos[clave]

            if (
                len(programa["descripcion"])
                > len(anterior["descripcion"])
            ):

                unicos[clave] = programa

    programas = sorted(
        unicos.values(),
        key=lambda programa: programa["inicio"]
    )

    print("----------------------------------------")
    print("Días consultados:", DIAS_A_GENERAR)
    print("Total de programas:", len(programas))
    print("----------------------------------------")

    return programas


# =========================================================
# CONSERVAR HISTORIAL ANTERIOR
# =========================================================

def cargar_historial():

    if not os.path.exists(ARCHIVO_XML):

        print("No existe XML anterior.")
        return []

    try:

        arbol = ET.parse(ARCHIVO_XML)
        raiz = arbol.getroot()

        ahora = datetime.now(ZONA)

        limite = ahora - timedelta(
            hours=HORAS_HISTORIAL
        )

        historial = []

        for programa in raiz.findall("programme"):

            if programa.get("channel") != CANAL_ID:
                continue

            inicio_texto = programa.get("start")
            fin_texto = programa.get("stop")

            if not inicio_texto or not fin_texto:
                continue

            inicio = fecha_desde_xml(
                inicio_texto
            )

            fin = fecha_desde_xml(
                fin_texto
            )

            # Conservar solamente programas recientes
            if inicio < ahora and fin >= limite:

                historial.append(
                    copy.deepcopy(programa)
                )

        print(
            "Programas históricos conservados:",
            len(historial)
        )

        return historial

    except Exception as error:

        print(
            "No se pudo leer el historial anterior:",
            error
        )

        return []


# =========================================================
# CREAR ELEMENTO XMLTV
# =========================================================

def crear_elemento_programa(
    raiz,
    programa,
    inicio,
    fin
):

    elemento = ET.SubElement(
        raiz,
        "programme",
        {
            "start": fecha_xml(inicio),
            "stop": fecha_xml(fin),
            "channel": CANAL_ID
        }
    )

    titulo = ET.SubElement(
        elemento,
        "title",
        {"lang": "es"}
    )

    titulo.text = programa["titulo"]

    if programa.get("descripcion"):

        descripcion = ET.SubElement(
            elemento,
            "desc",
            {"lang": "es"}
        )

        descripcion.text = programa["descripcion"]

    if url_valida(programa.get("imagen")):

        ET.SubElement(
            elemento,
            "icon",
            {"src": programa["imagen"]}
        )

    if url_valida(programa.get("url")):

        enlace = ET.SubElement(
            elemento,
            "url"
        )

        enlace.text = programa["url"]

    if programa.get("rating"):

        rating = ET.SubElement(
            elemento,
            "rating"
        )

        valor = ET.SubElement(
            rating,
            "value"
        )

        valor.text = programa["rating"]

    return elemento


# =========================================================
# GENERAR XMLTV
# =========================================================

def generar_xml():

    programas = obtener_programacion()

    ahora = datetime.now(ZONA)

    historial = cargar_historial()

    raiz = ET.Element(
        "tv",
        {
            "generator-info-name": "EPG Telemundo API",
            "generator-info-url": "https://www.telemundo.com/"
        }
    )

    canal = ET.SubElement(
        raiz,
        "channel",
        {"id": CANAL_ID}
    )

    nombre = ET.SubElement(
        canal,
        "display-name",
        {"lang": "es"}
    )

    nombre.text = CANAL_NOMBRE

    # Registrar historial por hora de inicio
    elementos = {}

    for anterior in historial:

        inicio = anterior.get("start")

        if inicio:

            elementos[inicio] = anterior

    # Crear programación nueva
    for indice, programa in enumerate(programas):

        inicio = programa["inicio"]

        if indice + 1 < len(programas):

            fin = programas[indice + 1]["inicio"]

        else:

            # Último programa del sexto día:
            # finalizar a medianoche del día siguiente.
            fin = datetime(
                inicio.year,
                inicio.month,
                inicio.day,
                tzinfo=ZONA
            ) + timedelta(days=1)

        if fin <= inicio:

            continue

        elemento_temporal = ET.Element(
            "programme",
            {
                "start": fecha_xml(inicio),
                "stop": fecha_xml(fin),
                "channel": CANAL_ID
            }
        )

        # Construir los datos del programa
        titulo = ET.SubElement(
            elemento_temporal,
            "title",
            {"lang": "es"}
        )

        titulo.text = programa["titulo"]

        if programa.get("descripcion"):

            descripcion = ET.SubElement(
                elemento_temporal,
                "desc",
                {"lang": "es"}
            )

            descripcion.text = programa["descripcion"]

        if url_valida(programa.get("imagen")):

            ET.SubElement(
                elemento_temporal,
                "icon",
                {"src": programa["imagen"]}
            )

        if url_valida(programa.get("url")):

            enlace = ET.SubElement(
                elemento_temporal,
                "url"
            )

            enlace.text = programa["url"]

        if programa.get("rating"):

            rating = ET.SubElement(
                elemento_temporal,
                "rating"
            )

            valor = ET.SubElement(
                rating,
                "value"
            )

            valor.text = programa["rating"]

        clave = fecha_xml(inicio)

        elementos[clave] = elemento_temporal

    # Ordenar todos los programas
    lista_final = []

    for elemento in elementos.values():

        inicio_texto = elemento.get("start")

        if not inicio_texto:
            continue

        inicio = fecha_desde_xml(
            inicio_texto
        )

        lista_final.append(
            (inicio, elemento)
        )

    lista_final.sort(
        key=lambda item: item[0]
    )

    for _, elemento in lista_final:

        raiz.append(elemento)

    # Comprobar que hay programación
    cantidad = len(
        raiz.findall("programme")
    )

    if cantidad == 0:

        raise Exception(
            "El XML no contiene programas."
        )

    # Crear archivo temporal
    temporal = ARCHIVO_XML + ".tmp"

    arbol = ET.ElementTree(raiz)

    ET.indent(
        arbol,
        space="    "
    )

    arbol.write(
        temporal,
        encoding="utf-8",
        xml_declaration=True
    )

    # Reemplazar únicamente después de generar correctamente
    os.replace(
        temporal,
        ARCHIVO_XML
    )

    print("=" * 60)
    print("GENERACIÓN FINALIZADA CORRECTAMENTE")
    print("=" * 60)

    print("Canal:", CANAL_NOMBRE)
    print("ID:", CANAL_ID)
    print("Días consultados:", DIAS_A_GENERAR)
    print("Programas guardados:", cantidad)
    print("Archivo:", ARCHIVO_XML)

    print("=" * 60)


# =========================================================
# EJECUCION PRINCIPAL
# =========================================================

if __name__ == "__main__":

    try:

        generar_xml()

    except Exception as error:

        print("=" * 60)
        print("GENERACION CANCELADA")
        print("=" * 60)

        print(error)

        print(
            "El epg.xml anterior no será reemplazado."
        )

        print("=" * 60)

        raise
