
import requests

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

pagina = sesion.get(url_pagina, headers=headers, timeout=30)
print("PÁGINA:", pagina.status_code)
print("SESIÓN INICIADA:", bool(sesion.cookies))

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

print("ESTADO API:", respuesta.status_code)
print("TIPO:", respuesta.headers.get("Content-Type"))
print("TAMAÑO:", len(respuesta.content))
print("URL FINAL:", respuesta.url)
print("RESPUESTA:")
print(repr(respuesta.text[:5000]))
