from dotenv import load_dotenv
from supabase_client import Supabase

load_dotenv()
sb = Supabase()

# All productIds in today's prices_daily
price_rows = sb.select("prices_daily", columns="tcgplayer_product_id", filters={"source": "eq.tcgcsv"})
price_pids = {row["tcgplayer_product_id"] for row in price_rows}

# Cards with tcgplayer_id but no price
cards = sb.select(
    "cards",
    columns="id,name,version,set_id,rarity,tcgplayer_product_id",
    filters={"tcgplayer_product_id": "not.is.null"},
)
unpriced = [c for c in cards if c["tcgplayer_product_id"] not in price_pids]

print(f"Cards with tcgplayer_id but no current price: {len(unpriced)}")
for c in unpriced:
    name = c["name"] + (" - " + c["version"] if c.get("version") else "")
    print(f"  [{c['rarity']}] {name}  (pid={c['tcgplayer_product_id']}, set={c['set_id']})")
