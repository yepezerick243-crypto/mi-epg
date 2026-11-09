
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import os
import re

URL = "https://intv.com.co/inicio/television/canales/warner-channel/"
XML_FILE = "epg.xml"
CHANNEL_ID = "WarnerChannel.us@Colombia"
OFFSET = "-0500"

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12
}

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
        raise ValueError("No se encontró la fecha de programación")

    dia = int(fecha_match.group(1))
    mes_nombre = fecha_match.group(2).lower()[:3]
    anio = int(fecha_match.group(3))

    if mes_nombre not in MESES:
        raise ValueError("Mes desconocido: " + mes_nombre)

    fecha = datetime(anio, MESES[mes_nombre], dia)

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

            if not nombre or nombre.lower() == "programa":
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
        raise ValueError("No se encontraron programas en la tabla")

    return fecha, programas

def formato_xml(fecha):
    return fecha.strftime("%Y%m%d%H%M%S") + " " + OFFSET

def generar_xml(fecha, programas):
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
        ET.SubElement(canal, "display-name").text = "Warner Channel"

    # Reemplazar solamente la programación de esta fecha.
    fecha_texto = fecha.strftime("%Y%m%d")

    for elemento in list(root.findall("programme")):
        inicio = elemento.get("start", "")
        if inicio.startswith(fecha_texto):
            root.remove(elemento)

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

        ET.SubElement(elemento, "title").text = programa["nombre"]

    root[:] = sorted(
        root,
        key=lambda elemento: elemento.get("start", "")
    )

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(
        XML_FILE,
        encoding="UTF-8",
        xml_declaration=True
    )

    print("Fecha procesada:", fecha.strftime("%d/%m/%Y"))
    print("Programas guardados:", len(programas))
    print("Archivo generado:", XML_FILE)

def main():
    fecha, programas = obtener_programacion()
    generar_xml(fecha, programas)

if __name__ == "__main__":
    main()
