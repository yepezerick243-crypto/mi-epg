
import requests
import re
import json

URL = "https://intv.com.co/inicio/television/parrilla-de-television/"

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


def inspeccionar_warner():
    respuesta = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    respuesta.raise_for_status()

    print("PAGINA:", respuesta.status_code)

    inicio = respuesta.text.find("var tvGuideData")

    if inicio == -1:
        print("No se encontró tvGuideData.")
        return

    contenido = extraer_json(respuesta.text, inicio)

    if not contenido:
        print("No se pudo extraer el objeto JSON.")
        return

    datos = json.loads(contenido)
    canales = datos.get("scheduleData", {})

    print("CANALES ENCONTRADOS:", len(canales))

    encontrados = False

    for nombre, informacion in canales.items():
        if "warner" in nombre.lower():
            encontrados = True
            programas = informacion.get("programs", [])

            print("\nCANAL:", nombre)
            print("PROGRAMAS:", len(programas))

            for programa in programas:
                print(
                    programa.get("date"),
                    programa.get("title"),
                    programa.get("start"),
                    programa.get("end")
                )

    if not encontrados:
        print("No se encontró Warner Channel en scheduleData.")
        print("Canales disponibles:", list(canales.keys()))


if __name__ == "__main__":
    inspeccionar_warner()
