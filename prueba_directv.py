
import requests

url = "https://www.directv.com.ec/guia/ChannelDetail.aspx/GetProgramming"

headers = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://www.directv.com.ec",
    "Referer": "https://www.directv.com.ec/guia/ChannelDetail.aspx?id=1206&name=WTVHD",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Accept-Language": "es-EC,es;q=0.9,en;q=0.8"
}

payload = {"filterParameters": None}

r = requests.post(url, headers=headers, json=payload, timeout=30)

print("ESTADO:", r.status_code)
print("RESPUESTA:", r.text[:12000])

datos = r.json()
canales = datos.get("d", [])

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
else:
    print("DIRECTV NO DEVOLVIÓ LA LISTA DE CANALES.")
