import requests
from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET
import os
import re

URL = "https://intv.com.co/inicio/television/canales/warner-channel/"
XML_FILE = "epg.xml"
CHANNEL_ID = "WarnerChannel.us@Colombia"

def obtener_programacion():
    respuesta = requests.get(URL, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")
    return soup.get_text(" ", strip=True)

def cargar_xml():
    if os.path.exists(XML_FILE):
        return ET.parse(XML_FILE)
    root = ET.Element("tv")
    canal = ET.SubElement(root, "channel", id=CHANNEL_ID)
    ET.SubElement(canal, "display-name").text = "Warner Channel"
    return ET.ElementTree(root)

def main():
    texto = obtener_programacion()
    print("Página consultada correctamente.")
    print(texto[:3000])

if __name__ == "__main__":
    main()
