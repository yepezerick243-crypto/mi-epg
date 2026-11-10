
import requests
from datetime import datetime
from collections import Counter

url_pagina = "https://www.directv.com.ec/guia/ChannelDetail.aspx?id=1206&name=WTVHD"
url_api = "https://www.directv.com.ec/guia/ChannelDetail.aspx/GetProgramming"

sesion = requests.Session()

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": "https://www.directv.com.ec",
    "Referer": url_pagina,
    "X-Requested-With": "XMLHttpRequest"
}

sesion.get(url_pagina, headers=headers, timeout=30)

payload = {
    "filterParameters": {
        "day": 10,
        "time": 0,
        "minute": 0,
        "month": 11,
        "year": 2026,
        "offSetValue": 0,
        "homeScreenFilter": "",
        "filtersScreenFilters": [""],
        "isHd": "",
        "isChannelDetails": "Y",
        "channelName": "WTVHD",
        "channelNum": 1206
    }
}

respuesta = sesion.post(
    url_api,
    headers=headers,
    json=payload,
    timeout=30
)

print("ESTADO:", respuesta.status_code)

datos = respuesta.json()
canales = datos.get("d", [])

if not isinstance(canales, list) or not canales:
    print("No se recibieron canales.")
    raise SystemExit()

programas = canales[0].get("ProgramList", [])

print("CANAL:", canales[0].get("ChannelFullName"))
print("TOTAL DE PROGRAMAS:", len(programas))

fechas = Counter()
validos = []

for p in programas:
    inicio = p.get("startTimeString", "")
    fin = p.get("endTimeString", "")

    try:
        fecha_inicio = datetime.strptime(inicio, "%m/%d/%Y %I:%M:%S %p")
        fecha_fin = datetime.strptime(fin, "%m/%d/%Y %I:%M:%S %p")

        fechas[fecha_inicio.strftime("%d/%m/%Y")] += 1
        validos.append((fecha_inicio, fecha_fin, p.get("title", "")))
    except ValueError:
        continue

print("\nPROGRAMAS POR FECHA:")
for fecha, cantidad in sorted(fechas.items()):
    print(fecha, "-", cantidad, "programas")

print("\nPRIMEROS 5 PROGRAMAS:")
for inicio, fin, titulo in validos[:5]:
    print(inicio, "-", fin, "|", titulo)

print("\nÚLTIMOS 5 PROGRAMAS:")
for inicio, fin, titulo in validos[-5:]:
    print(inicio, "-", fin, "|", titulo)
