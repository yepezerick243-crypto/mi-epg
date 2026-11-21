
import os
import re
import time
import requests
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# =========================================================
# CONFIGURACION
# =========================================================

API_BASE = (
    "https://d3ur398j0yj7gx.cloudfront.net/"
    "ajax/program_guide/feed/block"
)

CANAL_ID = "Telemundo.us"
NOMBRE_CANAL = "Telemundo"

ZONA = ZoneInfo("America/Guayaquil")

ARCHIVO_XML = "epg.xml"

DIAS_PROGRAMACION = 7

INTENTOS = 4
ESPERA = 10

SESION = requests.Session()

SESION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*"
})


# =========================================================
# CONSULTAR API DE TELEMUNDO
# =========================================================

def solicitar_programacion(fecha):

    fecha_texto = fecha.strftime("%Y/%m/%d")

    url = f"{API_BASE}/{fecha_texto}"

    for intento in range(1, INTENTOS + 1):

        try:
            print(
                f"Consultando Telemundo: "
                f"{fecha_texto} ({intento}/{INTENTOS})"
            )

            respuesta = SESION.get(
                url,
                timeout=(20, 60)
            )

            respuesta.raise_for_status()

            datos = respuesta.json()

            if not isinstance(datos, list):
                raise ValueError(
                    "La API no devolvió una lista JSON."
                )

            if not datos:
                raise ValueError(
                    f"Telemundo no entregó programas para {fecha_texto}."
                )

            print(
                f"Programas recibidos: {len(datos)}"
            )

            return datos

        except (
            requests.RequestException,
            ValueError
        ) as error:

            print("Error consultando Telemundo:", error)

            if intento < INTENTOS:
                print(f"Esperando {ESPERA} segundos...")
                time.sleep(ESPERA)

            else:
                raise Exception(
                    f"No se pudo obtener la programación "
                    f"del {fecha_texto}."
                ) from error


# =========================================================
# CONVERTIR TIME_FULL A FECHA LOCAL
# =========================================================

def convertir_hora(fecha, hora_texto):

    if not isinstance(hora_texto, str):
        raise ValueError("time_full no contiene una hora válida.")

    hora_texto = hora_texto.strip().lower()

    hora_texto = re.sub(
        r"\s+",
        "",
        hora_texto
    )

    formatos = [
        "%I:%M%p",
        "%I%p"
    ]

    hora_convertida = None

    for formato in formatos:

        try:
            hora_convertida = datetime.strptime(
                hora_texto,
                formato
            )

            break

        except ValueError:
            continue

    if hora_convertida is None:
        raise ValueError(
            f"Formato de hora no reconocido: {hora_texto}"
        )

    return datetime(
        fecha.year,
        fecha.month,
        fecha.day,
        hora_convertida.hour,
        hora_convertida.minute,
        tzinfo=ZONA
    )


# =========================================================
# EXTRAER PROGRAMAS
# =========================================================

def extraer_programas(fecha, datos):

    programas = []

    for registro in datos:

        if not isinstance(registro, dict):
            continue

        nombre = registro.get("name")

        if not isinstance(nombre, str) or not nombre.strip():
            continue

        hora_texto = registro.get("time_full")

        try:
            inicio = convertir_hora(
                fecha,
                hora_texto
            )

        except (ValueError, TypeError) as error:

            print(
                f"Horario descartado: {nombre} - {error}"
            )

            continue

        programa = {
            "inicio": inicio,
            "nombre": nombre.strip(),
            "descripcion": registro.get("description") or "",
            "imagen": registro.get("image_url") or "",
            "url": registro.get("url") or "",
            "rating": registro.get("rating") or "",
            "show_id": registro.get("nbcu_showid") or ""
        }

        programas.append(programa)

    return programas


# =========================================================
# DESCARGAR PROGRAMACION DE VARIOS DIAS
# =========================================================

def obtener_programacion():

    hoy = datetime.now(ZONA).date()

    fecha_final = hoy + timedelta(
        days=DIAS_PROGRAMACION
    )

    programas = []

    print("=" * 60)
    print("GENERADOR EPG EXCLUSIVO DE TELEMUNDO")
    print("=" * 60)

    print("Fecha inicial:", hoy)
    print("Último día incluido:", fecha_final - timedelta(days=1))
    print("Días de programación:", DIAS_PROGRAMACION)
    print("Zona horaria:", ZONA)

    # Se consulta un día adicional para calcular
    # la finalización del último programa.

    for desplazamiento in range(DIAS_PROGRAMACION + 1):

        fecha = hoy + timedelta(
            days=desplazamiento
        )

        datos = solicitar_programacion(fecha)

        registros = extraer_programas(
            fecha,
            datos
        )

        if not registros:
            raise Exception(
                f"No se encontraron horarios válidos "
                f"para el {fecha}."
            )

        programas.extend(registros)

    # Eliminar posibles registros duplicados.

    unicos = {}

    for programa in programas:

        clave = programa["inicio"]

        if clave not in unicos:
            unicos[clave] = programa

    programas = sorted(
        unicos.values(),
        key=lambda p: p["inicio"]
    )

    # Conservar solamente los siete días solicitados.
    # El día adicional sirve como referencia de finalización.

    limite = datetime(
        fecha_final.year,
        fecha_final.month,
        fecha_final.day,
        0,
        0,
        tzinfo=ZONA
    )

    programas = [
        p for p in programas
        if p["inicio"] < limite
    ]

    if not programas:
        raise Exception(
            "No se obtuvo programación válida."
        )

    print("---------------------------------------")
    print("Total de programas:", len(programas))
    print("---------------------------------------")

    return programas


# =========================================================
# FORMATO DE FECHAS XMLTV
# =========================================================

def convertir_fecha_xml(fecha):

    return fecha.strftime(
        "%Y%m%d%H%M%S %z"
    )


# =========================================================
# AGREGAR TEXTO XML
# =========================================================

def agregar_texto(
    elemento,
    etiqueta,
    texto,
    idioma="es"
):

    if texto is None:
        return

    texto = str(texto).strip()

    if not texto:
        return

    nuevo = ET.SubElement(
        elemento,
        etiqueta,
        {"lang": idioma}
    )

    nuevo.text = texto


# =========================================================
# CREAR PROGRAMA XMLTV
# =========================================================

def crear_programa(programa, siguiente):

    inicio = programa["inicio"]
    fin = siguiente["inicio"]

    if fin <= inicio:
        return None

    elemento = ET.Element(
        "programme",
        {
            "start": convertir_fecha_xml(inicio),
            "stop": convertir_fecha_xml(fin),
            "channel": CANAL_ID
        }
    )

    # Título original de Telemundo.

    agregar_texto(
        elemento,
        "title",
        programa["nombre"]
    )

    # Descripción original.

    agregar_texto(
        elemento,
        "desc",
        programa["descripcion"]
    )

    # Imagen del programa.

    if programa["imagen"]:

        icono = ET.SubElement(
            elemento,
            "icon",
            {"src": programa["imagen"]}
        )

    # Clasificación televisiva.

    if programa["rating"]:

        clasificacion = ET.SubElement(
            elemento,
            "rating",
            {"system": "MPAA"}
        )

        agregar_texto(
            clasificacion,
            "value",
            programa["rating"]
        )

    # Identificador del programa.

    if programa["show_id"]:

        agregar_texto(
            elemento,
            "episode-num",
            programa["show_id"],
            "en"
        )

    # Página del programa.

    if programa["url"]:

        enlace = ET.SubElement(
            elemento,
            "url"
        )

        enlace.text = programa["url"]

    return elemento


# =========================================================
# RECUPERAR XML ANTERIOR
# =========================================================

def cargar_xml_anterior():

    if not os.path.exists(ARCHIVO_XML):

        print(
            "No existe un XML anterior. "
            "Se generará uno nuevo."
        )

        return None

    try:

        arbol = ET.parse(ARCHIVO_XML)

        print(
            "XML anterior encontrado y válido."
        )

        return arbol

    except ET.ParseError as error:

        raise Exception(
            "El XML anterior está dañado. "
            "Se cancela la generación."
        ) from error


# =========================================================
# GENERAR XMLTV
# =========================================================

def generar_xml():

    programas = obtener_programacion()

    # Comprobar el XML anterior antes de reemplazarlo.

    cargar_xml_anterior()

    raiz = ET.Element(
        "tv",
        {
            "generator-info-name": (
                "Telemundo EPG Generator"
            ),
            "generator-info-url": (
                "https://www.telemundo.com/"
            )
        }
    )

    # Información del canal.

    canal = ET.SubElement(
        raiz,
        "channel",
        {"id": CANAL_ID}
    )

    agregar_texto(
        canal,
        "display-name",
        NOMBRE_CANAL
    )

    # Crear programas usando el siguiente horario
    # como hora de finalización.

    creados = 0
    descartados = 0

    for indice, programa in enumerate(programas):

        if indice + 1 >= len(programas):
            descartados += 1
            continue

        siguiente = programas[indice + 1]

        elemento = crear_programa(
            programa,
            siguiente
        )

        if elemento is None:

            descartados += 1
            continue

        raiz.append(elemento)

        creados += 1

    if creados == 0:
        raise Exception(
            "No se generaron programas XMLTV."
        )

    ET.indent(
        raiz,
        space="  "
    )

    # Escritura temporal para evitar dañar
    # el archivo anterior si ocurre un error.

    archivo_temporal = ARCHIVO_XML + ".tmp"

    ET.ElementTree(raiz).write(
        archivo_temporal,
        encoding="UTF-8",
        xml_declaration=True
    )

    # Comprobar el XML recién generado.

    ET.parse(archivo_temporal)

    os.replace(
        archivo_temporal,
        ARCHIVO_XML
    )

    print("=" * 60)
    print("GENERACION COMPLETADA")
    print("=" * 60)

    print("Canal:", NOMBRE_CANAL)
    print("ID:", CANAL_ID)
    print("Programas creados:", creados)
    print("Programas descartados:", descartados)
    print("Archivo generado:", ARCHIVO_XML)
    print("Horario utilizado: time_full")
    print("Zona horaria: America/Guayaquil")
    print("Días incluidos:", DIAS_PROGRAMACION)

    print("=" * 60)


# =========================================================
# EJECUCION
# =========================================================

if __name__ == "__main__":

    try:

        generar_xml()

    except Exception as error:

        print("=" * 60)
        print("GENERACION CANCELADA")
        print(error)
        print("El epg.xml anterior no será reemplazado.")
        print("=" * 60)

        raise
