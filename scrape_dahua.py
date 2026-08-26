import csv
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dicabolivia.com"
CATEGORY_URL = "/product-category/camaras/dahua/"
OUT_JSON = "camaras_dahua.json"
OUT_CSV = "camaras_dahua.csv"
PER_PAGE = 80
DELAY = 1.0

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


def save_outputs(products):
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(products, fh, ensure_ascii=False, indent=2)

    fieldnames = [
        "id", "url", "nombre", "sku",
        "precio_regular", "precio_oferta", "moneda",
        "en_stock", "stock_cantidad", "marca",
        "categorias", "tags", "descripcion_corta",
        "descripcion_larga", "imagenes",
    ]

    def flatten(value):
        if isinstance(value, list):
            return "; ".join(str(v) for v in value)
        return value

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow({k: flatten(v) for k, v in product.items()})

    print(f"\n[OK] Guardado: {OUT_JSON} y {OUT_CSV} ({len(products)} productos)")


def main():
    category_url = BASE_URL + CATEGORY_URL
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

    save_outputs(products)


if __name__ == "__main__":
    main()
