"""Leitura de preços nas páginas das lojas.

Cada loja tem uma função dedicada. Quando ela não acha o preço, cai na leitura
genérica (JSON-LD schema.org e meta tags), que funciona na maioria dos e-commerces.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlparse

try:  # curl_cffi imita o TLS do Chrome e passa por bloqueios simples de bot
    from curl_cffi import requests as http

    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # fallback para requests puro
    import requests as http

    _IMPERSONATE = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}


@dataclass
class Leitura:
    url: str
    loja: str
    preco: float | None  # preço à vista (PIX)
    disponivel: bool | None
    titulo: str | None = None
    erro: str | None = None
    imagem: str | None = None  # URL da foto do produto


# ---------------------------------------------------------------- utilidades

def loja_da_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for nome in ("pichau", "kabum", "terabyte", "amazon", "mercadolivre", "chipart"):
        if nome in host:
            return nome
    return host.replace("www.", "")


def preco_br(texto: str) -> float | None:
    """'R$ 1.699,99' -> 1699.99 ; '1,699.99' (formato da Pichau) -> 1699.99"""
    t = texto.strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if not re.search(r"\d", t):
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}", t):  # 1.699,99
        return float(t.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(,\d{3})*\.\d{2}", t):  # 1,699.99
        return float(t.replace(",", ""))
    if re.fullmatch(r"\d+,\d{1,2}", t):  # 699,9
        return float(t.replace(",", "."))
    try:
        return float(t)
    except ValueError:
        return None


def _json_ld(html: str) -> list[dict]:
    blocos = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.S | re.I,
    )
    saida: list[dict] = []
    for b in blocos:
        try:
            dado = json.loads(unescape(b.strip()))
        except json.JSONDecodeError:
            continue
        pilha = dado if isinstance(dado, list) else [dado]
        while pilha:
            d = pilha.pop()
            if isinstance(d, dict):
                saida.append(d)
                if "@graph" in d and isinstance(d["@graph"], list):
                    pilha.extend(d["@graph"])
    return saida


def _oferta_json_ld(html: str) -> tuple[float | None, bool | None, str | None]:
    for d in _json_ld(html):
        if "offers" not in d:
            continue
        ofertas = d["offers"]
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else {}
        preco = ofertas.get("price") or ofertas.get("lowPrice")
        disp = ofertas.get("availability")
        disponivel = None if disp is None else ("InStock" in str(disp))
        try:
            preco = float(preco) if preco is not None else None
        except (TypeError, ValueError):
            preco = preco_br(str(preco))
        return preco, disponivel, d.get("name")
    return None, None, None


def _imagem(html: str, url: str) -> str | None:
    """Foto do produto: og:image, depois o campo image do JSON-LD."""
    candidatos: list[str] = []
    for padrao in (
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
    ):
        candidatos += re.findall(padrao, html, re.I)
    for d in _json_ld(html):
        img = d.get("image")
        if isinstance(img, list) and img:
            img = img[0]
        if isinstance(img, dict):
            img = img.get("url") or img.get("contentUrl")
        if isinstance(img, str):
            candidatos.append(img)
    for c in candidatos:
        c = unescape(c.strip())
        if c.startswith("//"):
            c = "https:" + c
        elif c.startswith("/"):
            base = urlparse(url)
            c = f"{base.scheme}://{base.netloc}{c}"
        if c.startswith("https://") and not re.search(r"logo|placeholder|sem-imagem", c, re.I):
            return c
    return None


def _titulo(html: str) -> str | None:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.S | re.I)
    if m:
        return re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip()
    m = re.search(r"<title>(.*?)</title>", html, flags=re.S | re.I)
    return unescape(m.group(1)).strip() if m else None


def _texto(html: str) -> str:
    sem_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", sem_script)))


def _esgotado(texto: str) -> bool:
    return bool(re.search(r"esgotad|indispon[ií]vel|avise[- ]me quando|todos vendidos", texto, re.I))


# ---------------------------------------------------------------- por loja

def ler_pichau(html: str) -> tuple[float | None, bool | None]:
    # Na Pichau o JSON-LD traz o preço parcelado; o à vista aparece no texto:
    # "à vista R$ 1,699.99 no PIX com 15% desconto"
    texto = _texto(html)
    m = re.search(r"à vista\s*R\$\s*([\d.,]+)\s*no PIX", texto, re.I)
    preco = preco_br(m.group(1)) if m else None
    _, disp, _ = _oferta_json_ld(html)
    if disp is None:
        disp = not _esgotado(texto)
    return preco, disp


def ler_kabum(html: str) -> tuple[float | None, bool | None]:
    # Na Kabum o JSON-LD traz o preço do PIX
    preco, disp, _ = _oferta_json_ld(html)
    if preco is None:
        m = re.search(r'"priceWithDiscount"\s*:\s*([\d.]+)', html)
        preco = float(m.group(1)) if m else None
    if preco is None:
        m = re.search(r"R\$\s*([\d.]+,\d{2})\s*(?:-\d+%)?\s*à vista no PIX", _texto(html), re.I)
        preco = preco_br(m.group(1)) if m else None
    if disp is None:
        disp = not _esgotado(_texto(html))
    return preco, disp


def ler_terabyte(html: str) -> tuple[float | None, bool | None]:
    # Na Terabyte o preço à vista fica em #valVista; o JSON-LD é a segunda opção
    m = re.search(r'id=["\']valVista["\'][^>]*>\s*R?\$?\s*([\d.,]+)', html, re.I)
    preco = preco_br(m.group(1)) if m else None
    jl_preco, disp, _ = _oferta_json_ld(html)
    if preco is None:
        preco = jl_preco
    if disp is None:
        disp = not _esgotado(_texto(html))
    return preco, disp


def ler_generico(html: str) -> tuple[float | None, bool | None]:
    preco, disp, _ = _oferta_json_ld(html)
    if preco is None:
        m = re.search(
            r'<meta[^>]+(?:property|itemprop)=["\'](?:product:price:amount|price)["\'][^>]+content=["\']([\d.,]+)',
            html,
            re.I,
        )
        preco = preco_br(m.group(1)) if m else None
    return preco, disp


LEITORES = {"pichau": ler_pichau, "kabum": ler_kabum, "terabyte": ler_terabyte}


def interpretar(html: str, url: str) -> Leitura:
    loja = loja_da_url(url)
    preco, disp = LEITORES.get(loja, ler_generico)(html)
    if preco is None and loja in LEITORES:
        preco, disp2 = ler_generico(html)
        disp = disp if disp is not None else disp2
    if preco is not None and preco <= 0:  # produto esgotado aparece como R$ 0,00 em algumas lojas
        return Leitura(url=url, loja=loja, preco=None, disponivel=False, titulo=_titulo(html),
                       erro="esgotado (sem preço)", imagem=_imagem(html, url))
    return Leitura(url=url, loja=loja, preco=preco, disponivel=disp, titulo=_titulo(html),
                   erro=None if preco else "preço não encontrado na página", imagem=_imagem(html, url))


def buscar(url: str, tentativas: int = 2, timeout: int = 25) -> Leitura:
    ultimo_erro = ""
    for i in range(tentativas):
        try:
            r = http.get(url, headers=HEADERS, timeout=timeout, **_IMPERSONATE)
            if r.status_code == 200:
                return interpretar(r.text, url)
            ultimo_erro = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):  # bloqueio ou página removida: tentar de novo não adianta
                break
        except Exception as e:  # rede, TLS, timeout
            ultimo_erro = f"{type(e).__name__}: {e}"
        time.sleep(3 * (i + 1))
    return Leitura(url=url, loja=loja_da_url(url), preco=None, disponivel=None, erro=ultimo_erro)
