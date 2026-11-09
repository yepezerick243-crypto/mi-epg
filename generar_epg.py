
import requests
from bs4 import BeautifulSoup
import re

URL = "https://intv.com.co/inicio/television/canales/warner-channel/"

respuesta = requests.get(URL, timeout=30)
respuesta.raise_for_status()

soup = BeautifulSoup(respuesta.text, "html.parser")

print("FECHAS ENCONTRADAS:")
for elemento in soup.find_all(["h2", "h3", "h4"]):
    texto = elemento.get_text(" ", strip=True)
    if re.search(r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}", texto, re.I):
        print(texto)

print("\nPROGRAMAS DE LA TABLA:")
for tabla in soup.find_all("table"):
    for fila in tabla.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) >= 2:
            hora = celdas[0].get_text(" ", strip=True)
            programa = celdas[1].get_text(" ", strip=True)
            if re.search(r"\d{1,2}:\d{2}\s*[AP]M", hora, re.I):
                print(hora, "-", programa)
