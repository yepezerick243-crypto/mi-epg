import requests

URL = "https://intv.com.co/inicio/television/parrilla-de-television/"

def inspeccionar_html():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    respuesta = requests.get(URL, headers=headers, timeout=30)
    respuesta.raise_for_status()

    print("PAGINA:", respuesta.status_code)
    print("TAMAÑO HTML:", len(respuesta.text))
    print("\nREFERENCIAS A JAVASCRIPT Y DATOS:")

    for numero, linea in enumerate(respuesta.text.splitlines(), 1):
        if any(palabra in linea.lower() for palabra in [
            "script", "programs-wrapper", "admin-ajax",
            "wp-json", "fetch(", "ajax", "parrilla"
        ]):
            print(f"{numero}: {linea[:1000]}")


if __name__ == "__main__":
    inspeccionar_html()
