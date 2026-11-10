
import json
import requests
from collections import Counter

URL_INTV = "https://intv.com.co/inicio/television/parrilla-de-television/"


def extraer_json(texto, inicio):
    posicion = texto.find("{", inicio)

    if posicion == -1:
        return None

    profundidad = 0
    dentro_texto = False
    escape = False

    for i in range(posicion, len(texto)):
        caracter = texto[i]

        if dentro_texto:
            if escape:
                escape = False
            elif caracter == "\\":
                escape = True
            elif caracter == '"':
                dentro_texto = False
        else:
            if caracter == '"':
                dentro_texto = True
            elif caracter == "{":
                profundidad += 1
            elif caracter == "}":
                profundidad -= 1

                if profundidad == 0:
                    return texto[posicion:i + 1]

    return None


def inspeccionar():
    print("=" * 55)
    print("TITULOS UNICOS WARNER CHANNEL")
    print("=" * 55)

    respuesta = requests.get(
        URL_INTV,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=(20, 60)
    )
    respuesta.raise_for_status()

    inicio = respuesta.text.find("var tvGuideData")

    if inicio == -1:
        raise Exception("No se encontró tvGuideData.")

    contenido = extraer_json(respuesta.text, inicio)

    if not contenido:
        raise Exception("No se pudo extraer el JSON.")

    datos = json.loads(contenido)
    canales = datos.get("scheduleData", {})

    programas = []

    for nombre, informacion in canales.items():
        if nombre.strip().lower() == "warner channel":
            programas = informacion.get("programs", [])
            break

    if not programas:
        raise Exception("No se encontraron programas.")

    titulos = Counter(
        p.get("title", "").strip()
        for p in programas
        if p.get("title", "").strip()
    )

    print("Registros recibidos:", len(programas))
    print("Titulos diferentes:", len(titulos))
    print("-" * 55)

    for numero, (titulo, cantidad) in enumerate(
        sorted(titulos.items()),
        1
    ):
        print(f"{numero}. {titulo} | Apariciones: {cantidad}")

    print("-" * 55)
    print("INSPECCION FINALIZADA")


if __name__ == "__main__":
    inspeccionar()
