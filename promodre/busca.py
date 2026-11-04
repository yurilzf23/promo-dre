"""Busca sob demanda: o site abre uma issue "Buscar: <termo>" e o GitHub Actions roda isto.

- `pedido "<título da issue>"`: pesquisa o termo (ou lê a URL colada) na Kabum e na Terabyte,
  grava o resultado em docs/buscas.json e escreve comentario.md para responder na issue.
- Título "Monitorar: <url> | <termo>": coloca a página na lista fixa (produtos.yaml, fase 6).

A Pichau fica de fora porque bloqueia os servidores do GitHub.
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, quote_plus

import yaml

from . import historico as h
from .scraper import HEADERS, _IMPERSONATE, buscar, http, loja_da_url

RAIZ = Path(__file__).resolve().parent.parent
ARQ_BUSCAS = RAIZ / "docs" / "buscas.json"
ARQ_PRODUTOS = RAIZ / "produtos.yaml"
ARQ_COMENTARIO = RAIZ / "comentario.md"
LOJAS = {"kabum": "Kabum", "terabyte": "Terabyte", "pichau": "Pichau"}
MAX_BUSCAS = 15          # quantas buscas ficam guardadas no site
CANDIDATOS_POR_LOJA = 6  # páginas de produto abertas por loja em cada busca
FASE_EXTRAS = 6


# ---------------------------------------------------------------- texto

def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def tokens(t: str) -> list[str]:
    """Palavras que importam para comparar o termo com o título do anúncio."""
    ignorar = {"de", "da", "do", "com", "para", "e", "o", "a", "placa", "video", "gamer"}
    return [w for w in re.findall(r"[a-z0-9]+", normalizar(t)) if w not in ignorar]


def relevancia(termo: str, titulo: str | None) -> float:
    """Fração das palavras do termo que aparecem no título (aceita '16gb' ~ '16 gb')."""
    pedidas = tokens(termo)
    if not pedidas or not titulo:
        return 0.0
    tit = normalizar(titulo)
    compacto = re.sub(r"[^a-z0-9]", "", tit)
    achadas = sum(1 for w in pedidas if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", tit) or w in compacto)
    return achadas / len(pedidas)


def slug(t: str, limite: int = 40) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", normalizar(t))).strip("_")[:limite].strip("_") or "item"


def eh_url(t: str) -> bool:
    return bool(re.match(r"https?://", t.strip()))


# ---------------------------------------------------------------- lojas

def _baixar(url: str) -> str | None:
    try:
        r = http.get(url, headers=HEADERS, timeout=20, **_IMPERSONATE)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def links_kabum(html: str) -> list[str]:
    vistos, saida = set(), []
    for pid in re.findall(r"/produto/(\d{4,})", html):
        if pid not in vistos:
            vistos.add(pid)
            saida.append(f"https://www.kabum.com.br/produto/{pid}")
    return saida


def links_terabyte(html: str) -> list[str]:
    vistos, saida = set(), []
    for caminho in re.findall(r'(?:https://www\.terabyteshop\.com\.br)?(/produto/\d+/[a-z0-9\-]+)', html):
        if caminho not in vistos:
            vistos.add(caminho)
            saida.append("https://www.terabyteshop.com.br" + caminho)
    return saida


def candidatos(termo: str) -> tuple[list[str], list[str]]:
    """URLs de produto encontradas nas páginas de busca das lojas, mais avisos de falha."""
    urls, avisos = [], []
    kabum = _baixar(f"https://www.kabum.com.br/busca/{quote(normalizar(termo).strip().replace(' ', '-'))}")
    if kabum is None:
        avisos.append("Kabum não respondeu à busca")
    else:
        urls += links_kabum(kabum)[:CANDIDATOS_POR_LOJA]
    tera = _baixar(f"https://www.terabyteshop.com.br/busca?str={quote_plus(termo.strip())}")
    if tera is None:
        avisos.append("Terabyte não respondeu à busca")
    else:
        urls += links_terabyte(tera)[:CANDIDATOS_POR_LOJA]
    return urls, avisos


def ler_paginas(urls: list[str], termo: str | None, pausa: tuple[float, float] = (1.0, 2.5)) -> list[dict]:
    resultados = []
    for u in urls:
        l = buscar(u, tentativas=1)
        time.sleep(random.uniform(*pausa))
        if l.preco is None or l.disponivel is False:
            continue  # o site só mostra anúncio que dá para comprar
        rel = relevancia(termo, l.titulo) if termo else 1.0
        if termo and rel < 0.6:
            continue
        resultados.append({"titulo": (l.titulo or "").strip()[:140], "preco": l.preco,
                           "loja": LOJAS.get(l.loja, l.loja), "url": u, "imagem": l.imagem,
                           "relevancia": round(rel, 2)})
    resultados.sort(key=lambda r: (r["relevancia"] < 1, r["preco"]))  # todas as palavras batendo primeiro, depois preço
    return resultados


# ---------------------------------------------------------------- pedidos

def ler_titulo(titulo: str) -> tuple[str, str]:
    """'Buscar: rx 9060 xt' -> ('buscar', 'rx 9060 xt')"""
    m = re.match(r"\s*(buscar|monitorar)\s*:\s*(.+)", titulo, re.I | re.S)
    if not m:
        raise ValueError("título precisa começar com 'Buscar:' ou 'Monitorar:'")
    return m.group(1).lower(), m.group(2).strip()[:200]


def carregar_buscas() -> list[dict]:
    try:
        return json.loads(ARQ_BUSCAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def salvar_buscas(buscas: list[dict]) -> None:
    ARQ_BUSCAS.parent.mkdir(parents=True, exist_ok=True)
    ARQ_BUSCAS.write_text(json.dumps(buscas[:MAX_BUSCAS], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fazer_busca(termo: str) -> dict:
    if eh_url(termo):
        urls, avisos = [termo.strip()], []
        if loja_da_url(termo) == "pichau":
            avisos.append("A Pichau bloqueia o GitHub; cole o link da Kabum ou da Terabyte")
        resultados = ler_paginas(urls, None)
    else:
        urls, avisos = candidatos(termo)
        resultados = ler_paginas(urls, termo)
    busca = {"termo": termo, "quando": h.agora().isoformat(timespec="minutes"),
             "paginas_lidas": len(urls), "avisos": avisos, "resultados": resultados[:10]}
    salvar_buscas([busca] + [b for b in carregar_buscas() if b.get("termo", "").lower() != termo.lower()])
    return busca


def comentario_busca(b: dict) -> str:
    linhas = [f"### Resultado para \"{b['termo']}\"", ""]
    if b["resultados"]:
        linhas += ["| Preço (PIX) | Loja | Anúncio |", "|---|---|---|"]
        linhas += [f"| {brl(r['preco'])} | {r['loja']} | [{r['titulo'].replace('|', '/')}]({r['url']}) |" for r in b["resultados"]]
    else:
        linhas.append("Nenhum anúncio disponível encontrado com esse termo. Tente outro nome ou cole o link do produto.")
    if b["avisos"]:
        linhas += ["", *[f"- ⚠️ {a}" for a in b["avisos"]]]
    linhas += ["", "O resultado também aparece em **Minhas buscas** no site."]
    return "\n".join(linhas)


def monitorar(conteudo: str) -> str:
    """'<url> | <termo>' -> adiciona a URL ao item extra do termo (cria se não existir)."""
    url, _, termo = (p.strip() for p in conteudo.partition("|"))
    if not eh_url(url):
        raise ValueError("Monitorar precisa de um link de produto")
    dados = yaml.safe_load(ARQ_PRODUTOS.read_text(encoding="utf-8"))
    for item in dados["itens"]:
        if url in item["urls"]:
            return f"Esse anúncio já está monitorado em **{item.get('curto') or item['nome']}**."

    achado = next((r for b in carregar_buscas() for r in b["resultados"] if r["url"] == url), None)
    if achado is None:
        l = buscar(url, tentativas=1)
        achado = {"titulo": l.titulo or termo or url, "preco": l.preco}
    nome = termo or achado["titulo"]
    item_id = f"extra_{slug(nome)}"
    existente = next((i for i in dados["itens"] if i["id"] == item_id), None)
    texto = ARQ_PRODUTOS.read_text(encoding="utf-8")
    if existente:
        # acrescenta a URL na lista do item que já existe
        bloco = re.search(rf"(  - id: {re.escape(item_id)}\n(?:    .*\n|\n)*?    urls:\n(?:      - .*\n)+)", texto)
        if not bloco:
            raise ValueError("não achei o item no produtos.yaml")
        texto = texto.replace(bloco.group(1), bloco.group(1) + f"      - {url}\n")
        msg = f"Adicionei mais uma loja em **{existente.get('curto') or existente['nome']}**."
    else:
        alvo = math.floor(achado["preco"] * 0.92 / 10) * 10 if achado.get("preco") else 100
        titulo = json.dumps(achado["titulo"][:90], ensure_ascii=False)
        curto = json.dumps(nome[:40], ensure_ascii=False)
        if "# =============== Fase 6" not in texto:
            texto = texto.rstrip("\n") + "\n\n  # =============== Fase 6: adicionados pela busca do site ===============\n"
        texto = texto.rstrip("\n") + (
            f"\n\n  - id: {item_id}\n    nome: {titulo}\n    curto: {curto}\n    categoria: Outros\n    fase: {FASE_EXTRAS}\n"
            f"    alvo: {alvo}  # 8% abaixo do preço do dia em que foi adicionado\n    urls:\n      - {url}\n")
        msg = f"**{nome}** entrou no monitoramento (categoria Outros), com alvo de {brl(alvo)}. Ajuste o alvo no produtos.yaml se quiser."
    yaml.safe_load(texto)  # garante que o arquivo continua válido
    ARQ_PRODUTOS.write_text(texto, encoding="utf-8")
    return msg + "\n\nO preço dele aparece no site a partir da próxima coleta."


def pedido(titulo: str) -> int:
    try:
        tipo, conteudo = ler_titulo(titulo)
        if tipo == "buscar":
            b = fazer_busca(conteudo)
            texto = comentario_busca(b)
            print(f"{len(b['resultados'])} resultados para {conteudo!r} ({b['paginas_lidas']} páginas lidas)")
        else:
            texto = monitorar(conteudo)
            print(texto)
        ARQ_COMENTARIO.write_text(texto, encoding="utf-8")
        return 0
    except Exception as e:  # responde na issue em vez de só falhar
        ARQ_COMENTARIO.write_text(f"Não consegui processar o pedido: {e}", encoding="utf-8")
        print(f"erro: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(pedido(" ".join(sys.argv[1:])))
