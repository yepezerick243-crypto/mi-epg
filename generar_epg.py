
import requests
from bs4 import BeautifulSoup

URL = "https://intv.com.co/inicio/television/parrilla-de-television/"

def obtener_pagina():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    respuesta = requests.get(URL, headers=headers, timeout=30)
    respuesta.raise_for_status()

    return respuesta.text


def inspeccionar_parrilla():
    html = obtener_pagina()
    soup = BeautifulSoup(html, "html.parser")

    canales = soup.select(".programs-wrapper .programs")

    print("Canales encontrados:", len(canales))

    for canal in canales:
        nombre = canal.get("data-channel", "")

        if "warner" in nombre.lower():
            print("\nCANAL:", nombre)
            print(canal.prettify()[:10000])


if __name__ == "__main__":
    inspeccionar_parrilla()
