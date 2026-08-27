import json
import os
import sys
from urllib.parse import urljoin

import requests

API_BASE = os.environ.get("API_URL", "http://localhost:3001")
API_EMAIL = os.environ.get("API_EMAIL", "")
API_PASSWORD = os.environ.get("API_PASSWORD", "")

CATEGORY_MAP = {
    "productos": {"fuente": "dicabolivia", "categoria": "xvr"},
    "camaras_hikvision": {"fuente": "dicabolivia", "categoria": "camaras_hikvision"},
    "cables_redes": {"fuente": "dicabolivia", "categoria": "cables_redes"},
    "accesorios_camaras": {"fuente": "dicabolivia", "categoria": "accesorios_camaras"},
}

KNOWN_JSONS = [f"{name}.json" for name in CATEGORY_MAP]


def login(session):
    if not API_EMAIL or not API_PASSWORD:
        print("[X] Defina API_EMAIL y API_PASSWORD (variables de entorno)")
        sys.exit(1)
    resp = session.post(
        f"{API_BASE}/auth/login",
        json={"email": API_EMAIL, "password": API_PASSWORD},
    )
    if resp.status_code not in (200, 201):
        print(f"[X] Login fallido ({resp.status_code}): {resp.text}")
        sys.exit(1)
    token = resp.json().get("token")
    if not token:
        print("[X] Login no devolvió token")
        sys.exit(1)
    session.headers["Authorization"] = f"Bearer {token}"
    print(f"[OK] Autenticado como {API_EMAIL}")


def normalize(product):
    def str_or(val, default=""):
        return val if val else default

    def num_or(val, default=0):
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def bool_or(val, default=True):
        return bool(val) if val is not None else default

    return {
        "id": product.get("id", 0),
        "url": str_or(product.get("url")),
        "nombre": str_or(product.get("nombre"), "Sin nombre"),
        "sku": str_or(product.get("sku"), f"SKU-{product.get('id', 0)}"),
        "precio_regular": num_or(product.get("precio_regular")),
        "precio_oferta": num_or(product.get("precio_oferta")),
        "precio_metro": num_or(product.get("precio_metro")) if product.get("precio_metro") else None,
        "unidad": product.get("unidad"),
        "metros": product.get("metros"),
        "moneda": str_or(product.get("moneda"), "Bs."),
        "en_stock": bool_or(product.get("en_stock")),
        "stock_cantidad": num_or(product.get("stock_cantidad"), 0),
        "stock_texto": str_or(product.get("stock_texto")),
        "marca": str_or(product.get("marca"), "Sin marca"),
        "categorias": product.get("categorias") or [],
        "tags": product.get("tags") or [],
        "descripcion_corta": str_or(product.get("descripcion_corta")),
        "descripcion_larga": str_or(product.get("descripcion_larga")),
        "imagenes": product.get("imagenes") or [],
    }


def detect_source(json_path):
    basename = os.path.splitext(os.path.basename(json_path))[0]
    if basename in CATEGORY_MAP:
        return CATEGORY_MAP[basename]
    return {"fuente": "dicabolivia", "categoria": basename}


def upload_products(session, json_path, fuente=None, categoria=None):
    with open(json_path, "r", encoding="utf-8") as fh:
        products = json.load(fh)

    if not isinstance(products, list):
        print(f"[X] {json_path} no es una lista de productos")
        return

    source = detect_source(json_path)
    fuente = fuente or source["fuente"]
    categoria = categoria or source["categoria"]

    normalized = [normalize(p) for p in products]
    payload = {
        "fuente": fuente,
        "categoria": categoria,
        "productos": normalized,
    }

    print(f"[Subiendo] {len(normalized)} productos -> {fuente}/{categoria}")
    resp = session.post(f"{API_BASE}/scraping/save", json=payload)

    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"[OK] Guardados: {data.get('nuevosGuardados', 0)} nuevos, "
              f"{data.get('imagenesDescargadas', 0)} imágenes descargadas "
              f"(run {data.get('runId', '?')})")
    else:
        print(f"[X] Error ({resp.status_code}): {resp.text}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Sube productos scrapeados a la API NestJS"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Archivos JSON a subir (ej: productos.json camaras_hikvision.json). "
             "Si se omiten, sube todos los archivos conocidos.",
    )
    parser.add_argument("--fuente", help="Sobrescribir fuente (default: dicabolivia)")
    parser.add_argument("--categoria", help="Sobrescribir categoría")
    args = parser.parse_args()

    session = requests.Session()
    login(session)

    files = args.files
    if not files:
        files = [f for f in KNOWN_JSONS if os.path.exists(f)]
        if not files:
            print("[X] No se encontraron JSON de productos. Ejecute scrape_products.py primero.")
            sys.exit(1)

    for path in files:
        if not os.path.exists(path):
            print(f"[X] Archivo no encontrado: {path}")
            continue
        upload_products(session, path, args.fuente, args.categoria)

    print("\n[Done] Upload completado")


if __name__ == "__main__":
    main()
