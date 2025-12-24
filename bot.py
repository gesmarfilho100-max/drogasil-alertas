import os, json, time, re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

QUERIES = [
    "venvanse 70mg",
    "lisdexanfetamina 70mg",
    "metilfenidato 10mg",
]

PCT_DROP_ALERT = float(os.environ.get("PCT_DROP_ALERT", "0.08"))
TARGET_PRICES = json.loads(os.environ.get("TARGET_PRICES", "{}"))

DB_FILE = "prices.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

def brl_to_float(text: str):
    if not text:
        return None
    m = re.search(r"(\d{1,3}(\.\d{3})*,\d{2})", text)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))

def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": False}, timeout=30)
    r.raise_for_status()

def load_db():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=35)
    r.raise_for_status()
    return r.text

def extract_price_from_text(text):
    m = re.search(r"R\$\s*\d{1,3}(\.\d{3})*,\d{2}", text)
    if not m:
        return None
    return brl_to_float(m.group(0))

def drogasil_search(query: str):
    search_url = f"https://www.drogasil.com.br/search?w={quote_plus(query)}"
    html = fetch(search_url)
    soup = BeautifulSoup(html, "lxml")

    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if "/produto/" in href or "/p/" in href:
            full = href if href.startswith("http") else f"https://www.drogasil.com.br{href}"
            links.append(full)

    seen = set()
    uniq = []
    for l in links:
        if l in seen:
            continue
        seen.add(l)
        uniq.append(l)

    results = []
    for link in uniq[:10]:
        try:
            phtml = fetch(link)
            psoup = BeautifulSoup(phtml, "lxml")
            h1 = psoup.find("h1")
            name = h1.get_text(" ", strip=True) if h1 else link
            text = psoup.get_text("\n", strip=True)
            price = extract_price_from_text(text)
            results.append({"query": query, "name": name, "price": price, "link": link})
            time.sleep(0.8)
        except Exception:
            continue

    return results

def should_alert(item, db):
    link = item["link"]
    price = item["price"]
    query = item["query"]
    name = item["name"]

    if price is None:
        return None

    old = db.get(link, {}).get("price")

    target = TARGET_PRICES.get(query)
    if target is not None and price <= float(target):
        return f"🎯 Preço alvo atingido!\nBusca: {query}\nPreço: R$ {price:.2f} (≤ R$ {float(target):.2f})\nProduto: {name}\n{link}"

    if old is not None and old > 0:
        drop = (old - price) / old
        if drop >= PCT_DROP_ALERT:
            return f"📉 Queda de preço!\nBusca: {query}\nDe: R$ {old:.2f}\nPara: R$ {price:.2f}\nQueda: {drop*100:.1f}%\nProduto: {name}\n{link}"

    return None

def main():
    db = load_db()
    alerts = 0
    checked = 0

    for q in QUERIES:
        items = drogasil_search(q)
        for it in items:
            checked += 1
            msg = should_alert(it, db)
            if msg:
                send_telegram(msg)
                alerts += 1

            if it["price"] is not None:
                db[it["link"]] = {
                    "price": it["price"],
                    "name": it["name"],
                    "query": it["query"],
                    "last_seen": int(time.time()),
                }

    save_db(db)
    send_telegram(f"✅ Varredura finalizada.\nItens checados: {checked}\nAlertas enviados: {alerts}")

if __name__ == "__main__":
    main()
