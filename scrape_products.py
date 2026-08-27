import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dicabolivia.com"
PER_PAGE = 80
DELAY = 1.0

CATEGORIES = [
    {"id": "xvr", "url": "/product-category/cat-xvr/", "out": "productos"},
    {"id": "hikvision", "url": "/product-category/camaras/hikvision/", "out": "camaras_hikvision"},
    {"id": "cables", "url": "/product-category/cat-redes/cat-cables/", "out": "cables_redes"},
    {"id": "accesorios", "url": "/product-category/camaras/accesorios/", "out": "accesorios_camaras"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
            print(f"  [!] HTTP {resp.status_code} en {url}")
        except requests.RequestException as exc:
            print(f"  [!] Error ({attempt + 1}/{retries}): {exc}")
        time.sleep(2 * (attempt + 1))
    return None


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_amount(text):
    match = re.search(r"([\d.,]+)", text)
    if not match:
        return None
    raw = match.group(1)
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_metros(text):
    match = re.search(r"(\d{2,4})\s*-?\s*(?:METROS?|MTS?)\b", text or "", re.I)
    if not match:
        return None
    n = int(match.group(1))
    return n if n >= 10 else None


def postprocess_category(cat_id, products):
    if cat_id != "cables":
        return products
    for p in products:
        p["unidad"] = "rollo"
        p["metros"] = None
        p["precio_metro"] = None
        metros = parse_metros(p.get("nombre")) or parse_metros(p.get("descripcion_corta"))
        base = p.get("precio_oferta") or p.get("precio_regular")
        if metros and base:
            p["metros"] = metros
            p["unidad"] = "metro"
            p["precio_metro"] = round(base / metros, 2)
    return products


def parse_prices(price_el):
    amounts = [
        parse_amount(bdi.get_text())
        for bdi in price_el.select("bdi")
        if bdi.get_text(strip=True)
    ]
    amounts = [a for a in amounts if a is not None]
    if not amounts:
        return None, None
    if len(amounts) == 1:
        return amounts[0], amounts[0]
    return max(amounts), min(amounts)


def collect_product_links(category_url):
    links, page = [], 1
    while True:
        url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        suffix = f"?per_page={PER_PAGE}"
        print(f"[Categoria] {url}{suffix}")
        html = fetch(url + suffix)
        if html is None:
            break
        soup = BeautifulSoup(html, "lxml")
        items = soup.select("div.products .product, ul.products li.product")
        new_urls = []
        for item in items:
            a = item.select_one("a.product-image-link, a.product-title-link, a.woocommerce-LoopProduct-link, h2 a, h3 a") or item.find(
                "a", href=re.compile(r"/product/")
            )
            href = a.get("href", "").split("#")[0] if a else None
            if href and href not in links and href not in new_urls:
                new_urls.append(urljoin(BASE_URL, href))
        if not new_urls:
            break
        links.extend(new_urls)
        print(f"  -> {len(new_urls)} productos (total: {len(links)})")
        page += 1
        time.sleep(DELAY)
    return links


def extract_product(url):
    html = fetch(url)
    if html is None:
        return {"url": url, "error": "no se pudo descargar"}
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("h1.product_title")
    title = clean_text(title_el.get_text()) if title_el else None

    summary = soup.select_one(".summary") or soup
    price_el = summary.select_one("p.price")
    price_regular, price_sale = (None, None)
    if price_el:
        price_regular, price_sale = parse_prices(price_el)

    sku_el = summary.select_one(".product_meta span.sku, span.sku")
    sku = clean_text(sku_el.get_text()) if sku_el else None

    short_desc_el = summary.select_one(".woocommerce-product-details__short-description")
    short_desc = clean_text(short_desc_el.get_text(" ", strip=True)) if short_desc_el else None

    desc_el = soup.select_one("#tab-description")
    description = clean_text(desc_el.get_text(" ", strip=True)) if desc_el else None

    stock_el = summary.select_one(".availability-text") or summary.select_one(".stock")
    stock_text = clean_text(stock_el.get_text(" ", strip=True)) if stock_el else ""
    stock_qty_match = re.search(r"(\d+)", stock_text)
    stock_qty = int(stock_qty_match.group(1)) if stock_qty_match else None
    stock_class = soup.select_one(".availability.stock")
    classes = " ".join(stock_class.get("class", [])) if stock_class else ""
    if stock_text:
        in_stock = "out-of-stock" not in classes
    else:
        in_stock = None

    post_id = None
    id_input = soup.select_one('input[name="comment_post_ID"]')
    if id_input and id_input.get("value", "").isdigit():
        post_id = int(id_input["value"])
    else:
        dp = soup.select_one("[data-product_id]")
        if dp and dp.get("data-product_id", "").isdigit():
            post_id = int(dp["data-product_id"])

    categories, tags, brand = [], [], None
    meta = soup.select_one(".product_meta")
    if meta:
        cat_links = meta.select(".posted_in a")
        tag_links = meta.select(".tagged_as a")
        categories = [clean_text(a.get_text()) for a in cat_links]
        tags = [clean_text(a.get_text()) for a in tag_links]
    brand_el = summary.select_one('a[href*="/product-brand/"]')
    if brand_el:
        brand = clean_text(brand_el.get_text())

    images = []
    gallery = soup.select(
        ".woocommerce-product-gallery__wrapper .woocommerce-product-gallery__image img, "
        "div.products figure img, ul.products li.product img"
    )
    for img in gallery:
        src = (
            img.get("data-large_image")
            or img.get("data-src")
            or img.get("src")
        )
        if src and "logo" not in src and src not in images:
            images.append(urljoin(BASE_URL, src))

    return {
        "id": post_id,
        "url": url,
        "nombre": title,
        "sku": sku,
        "precio_regular": price_regular,
        "precio_oferta": price_sale,
        "moneda": "Bs.",
        "en_stock": in_stock,
        "stock_cantidad": stock_qty,
        "stock_texto": stock_text,
        "marca": brand,
        "categorias": categories,
        "tags": tags,
        "descripcion_corta": short_desc,
        "descripcion_larga": description,
        "imagenes": images,
    }


def save_outputs(products, out_json, out_csv):
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(products, fh, ensure_ascii=False, indent=2)

    fieldnames = [
        "id",
        "url",
        "nombre",
        "sku",
        "precio_regular",
        "precio_oferta",
        "precio_metro",
        "unidad",
        "metros",
        "moneda",
        "en_stock",
        "stock_cantidad",
        "marca",
        "categorias",
        "tags",
        "descripcion_corta",
        "descripcion_larga",
        "imagenes",
    ]

    def flatten(value):
        if isinstance(value, list):
            return "; ".join(str(v) for v in value)
        return value

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow({k: flatten(v) for k, v in product.items()})

    print(f"\n[OK] Guardado: {out_json} y {out_csv} ({len(products)} productos)")


def scrape_category(cat, category_url, out_json, out_csv):
    links = collect_product_links(category_url)
    if not links:
        print(f"[X] No se encontraron productos en {category_url}")
        return

    print(f"\n[Scraping] {len(links)} productos...")
    products = []
    for i, link in enumerate(links, 1):
        print(f"  [{i}/{len(links)}] {link}")
        products.append(extract_product(link))
        time.sleep(DELAY)

    products = postprocess_category(cat["id"] if isinstance(cat, dict) else cat, products)
    save_outputs(products, out_json, out_csv)


def upload_jsons(files):
    from upload_to_api import login, upload_products
    import requests as _requests

    session = _requests.Session()
    login(session)
    for path in files:
        if os.path.exists(path):
            upload_products(session, path)


def main():
    upload = "--upload" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--upload"]

    scraped_files = []

    if args:
        arg = args[0]
        cat = next((c for c in CATEGORIES if c["id"] == arg), None)
        if cat:
            out = f"{cat['out']}.json"
            scrape_category(cat, BASE_URL + cat["url"], out, f"{cat['out']}.csv")
            scraped_files.append(out)
        else:
            category_url = arg if arg.startswith("http") else BASE_URL + arg
            out_json, out_csv = "productos.json", "productos.csv"
            if len(args) > 1:
                base = args[1].strip("/")
                out_json = f"{base}.json"
                out_csv = f"{base}.csv"
            scrape_category(None, category_url, out_json, out_csv)
            scraped_files.append(out_json)
    else:
        for cat in CATEGORIES:
            print("=" * 60)
            print(f"[Categoria] {cat['id']} -> {cat['out']}.json / {cat['out']}.csv")
            print("=" * 60)
            out = f"{cat['out']}.json"
            scrape_category(cat, BASE_URL + cat["url"], out, f"{cat['out']}.csv")
            scraped_files.append(out)
        print("\n[Terminado] Categorias scrapeadas:", ", ".join(c["id"] for c in CATEGORIES))

    if upload and scraped_files:
        print("\n" + "=" * 60)
        print("[Upload] Subiendo productos a la API...")
        print("=" * 60)
        upload_jsons(scraped_files)


if __name__ == "__main__":
    main()
