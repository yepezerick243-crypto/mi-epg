
import requests
import json

url = "https://www.directv.com.ec/guia/ChannelDetail.aspx/GetProgramming"

headers = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://www.directv.com.ec",
    "Referer": "https://www.directv.com.ec/guia/ChannelDetail.aspx?id=1206&name=WTVHD",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0"
}

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

r = requests.post(url, headers=headers, json=payload, timeout=30)

print("ESTADO:", r.status_code)

datos = r.json()
canales = datos.get("d", [])

print("RESPUESTA:", json.dumps(datos, ensure_ascii=False)[:15000])

if isinstance(canales, list):
    for canal in canales:
        print("\nCANAL:", canal.get("ChannelFullName"))

        for p in canal.get("ProgramList", []):
            print(
                p.get("startTimeString"),
                "-",
                p.get("endTimeString"),
                "|",
                p.get("title")
            )
