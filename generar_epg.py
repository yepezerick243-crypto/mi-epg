
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

URL = "https://intv.com.co/inicio/television/parrilla-de-television/"

def inspeccionar_scripts():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    respuesta = requests.get(URL, headers=headers, timeout=30)
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "html.parser")

    print("PAGINA:", respuesta.status_code)
    print("ARCHIVOS JAVASCRIPT ENCONTRADOS:")

    for script in soup.find_all("script", src=True):
        url_script = urljoin(URL, script["src"])
        print(url_script)


if __name__ == "__main__":
    inspeccionar_scripts()
