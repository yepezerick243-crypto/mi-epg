
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

# Cargar series desde series.json
SERIES_FILE = "series.json"

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

    # Solo aceptar coincidencias únicas
    if len(coincidencias) == 1:
        return coincidencias[0]

    return None

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

def formato_xml(fecha):
    return fecha.strftime("%Y%m%d%H%M%S") + " " + OFFSET

def generar_xml(fecha, programas, indice):
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

        episodio = identificar_episodio(
            programa["nombre"], indice
        )

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
            ET.SubElement(
                elemento, "title"
            ).text = programa["nombre"]

        nuevos += 1

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
    print("Archivo generado:", XML_FILE)

def main():
    print("Series cargadas:", len(SERIES))

    for show_id, nombre in SERIES.items():
        print(f"Serie: {nombre} | ID: {show_id}")

    fecha, programas = obtener_programacion()
    indice = obtener_episodios_tvmaze()
    generar_xml(fecha, programas, indice)

if __name__ == "__main__":
    main()
