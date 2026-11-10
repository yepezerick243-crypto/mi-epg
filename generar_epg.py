
import requests
import re
import json

URL = "https://intv.com.co/inicio/television/parrilla-de-television/"

def inspeccionar_warner():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    respuesta = requests.get(URL, headers=headers, timeout=30)
    respuesta.raise_for_status()

    print("PAGINA:", respuesta.status_code)

    patron = r'var tvGuideData\s*=\s*(\{.*?\})\s*;'
    coincidencia = re.search(patron, respuesta.text, re.DOTALL)

    if not coincidencia:
        print("No se encontró tvGuideData.")
        return

    datos = json.loads(coincidencia.group(1))
    canales = datos.get("scheduleData", {})

    print("CANALES ENCONTRADOS:", len(canales))

    for nombre, informacion in canales.items():
        if "warner" in nombre.lower():
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

if __name__ == "__main__":
    inspeccionar_warner()
