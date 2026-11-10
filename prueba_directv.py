
import requests

url = "https://www.directv.com.ec/guia/ChannelDetail.aspx/GetProgramming"

headers = {
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://www.directv.com.ec/guia/ChannelDetail.aspx?id=1206&name=WTVHD"
}

payload = {"filterParameters": None}

r = requests.post(url, headers=headers, json=payload, timeout=30)

print("Estado HTTP:", r.status_code)

datos = r.json()

for canal in datos.get("d", []):
    print("\nCANAL:", canal.get("ChannelFullName"))

    for p in canal.get("ProgramList", []):
        print(
            p.get("startTimeString"),
            "-",
            p.get("endTimeString"),
            "|",
            p.get("title")
        )
