import py7zr, json, tempfile, os
ARCHIVE = r"C:\Users\zaven\OneDrive\Desktop\Packs.Ink\scripts\backfill_cache\probe.7z"

with py7zr.SevenZipFile(ARCHIVE, "r") as a:
    targets = [n for n in a.getnames() if n.startswith("2024-02-08/71/") and n.endswith("/prices")]
    print("lorcana price files in archive:", len(targets))
    print("targets:", targets)

with tempfile.TemporaryDirectory() as td:
    with py7zr.SevenZipFile(ARCHIVE, "r") as a:
        a.extract(path=td, targets=[targets[0]])
    p = os.path.join(td, targets[0])
    with open(p, "rb") as f:
        raw = f.read()
    print(f"\n== {targets[0]} ==")
    print("size:", len(raw))
    text = raw.decode("utf-8")
    print(text[:300])
    try:
        j = json.loads(text)
        if isinstance(j, dict) and "results" in j:
            print(f"\nJSON with results[] -> {len(j['results'])} entries")
            print("first entry:")
            print(json.dumps(j["results"][0], indent=2)[:500])
        else:
            print(f"\nplain JSON, type: {type(j).__name__}")
    except Exception as e:
        print(f"\nnot JSON: {e}")
