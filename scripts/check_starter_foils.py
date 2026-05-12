"""Are the WU starter-deck-exclusive foils captured as their own productIds?"""
import requests
from dotenv import load_dotenv
load_dotenv()

NAMES = [
    "Mrs. Incredible - Super Stretchy",
    "Buzz Lightyear - On the Way",
    "Jessie - Lively Cowgirl",
    "Jack-Jack Parr - Incredible Potential",
]

UA = {"User-Agent": "PacksInk/1.0"}
groups = requests.get("https://tcgcsv.com/tcgplayer/71/groups", headers=UA, timeout=60).json()
groups = groups.get("results") or groups

hits: list[dict] = []
for g in groups:
    prods = requests.get(
        f"https://tcgcsv.com/tcgplayer/71/{g['groupId']}/products", headers=UA, timeout=60
    ).json()
    prods = prods.get("results") or prods
    for p in prods:
        n = (p.get("name") or "").strip()
        for target in NAMES:
            if target in n:
                hits.append({"group": g["name"], "name": n, "productId": p["productId"]})

print(f"Found {len(hits)} matching TCGCSV products:\n")
for h in hits:
    print(f"  pid={h['productId']:>7d}  [{h['group']}]  {h['name']}")
