
import requests
import json

url = "https://www.directv.com.ec/guia/ChannelDetail.aspx/GetProgramming"

headers = {
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://www.directv.com.ec/guia/ChannelDetail.aspx?id=1206&name=WTVHD",
    "User-Agent": "Mozilla/5.0"
}

payload = {"filterParameters": None}

r = requests.post(url, headers=headers, json=payload, timeout=30)

print("ESTADO:", r.status_code)
print("TIPO:", r.headers.get("Content-Type"))
print("RESPUESTA COMPLETA:")
print(r.text[:12000])

try:
    datos = r.json()
    print("\nTIPO DE DATOS:", type(datos).__name__)
    print("CLAVES:", list(datos.keys()) if isinstance(datos, dict) else "No es diccionario")

    canales = datos.get("d", []) if isinstance(datos, dict) else []

    print("CANTIDAD DE CANALES:", len(canales))

    for canal in canales:
        programas = canal.get("ProgramList", [])
        print("CANAL:", canal.get("ChannelFullName"))
        print("CANTIDAD DE PROGRAMAS:", len(programas))

except Exception as e:
    print("ERROR AL LEER JSON:", str(e))
