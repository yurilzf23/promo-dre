"""Gera docs/dados.json, lido pelo site (docs/index.html) publicado no GitHub Pages."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from . import historico as h
from .main import LOJAS, RAIZ, carregar_combos, carregar_itens

ARQ_SAIDA = RAIZ / "docs" / "dados.json"
JANELA_OFERTA_H = 48  # leitura mais velha que isso não conta como "preço atual"

# categoria de cada item pelo começo do id (ou pelo campo "categoria" no produtos.yaml); a ordem é a do menu
CATEGORIAS = [
    ("cpu_", "Processador"), ("mb_", "Placa-mãe"), ("cooler_", "Cooler"), ("gpu_", "Placa de vídeo"),
    ("ram_", "Memória RAM"), ("ssd_", "SSD"), ("monitor_", "Monitor"), ("gabinete_", "Gabinete"),
    ("fans_", "Ventoinhas"), ("teclado_", "Teclado"), ("mouse_", "Mouse"), ("mousepad_", "Mousepad"),
    ("braco_", "Microfone e acessórios"), ("extra_", "Outros"),
]


def categoria(item: dict) -> str:
    if item.get("categoria"):
        return item["categoria"]
    # "mousepad_" precisa ganhar de "mouse_": testa os prefixos mais longos primeiro
    for prefixo, nome in sorted(CATEGORIAS, key=lambda c: -len(c[0])):
        if item["id"].startswith(prefixo):
            return nome
    return "Outros"


def _ofertas_atuais(hist: list[dict], item: dict, agora) -> list[dict]:
    """Última leitura de cada página do item (só coletas das últimas 48 h)."""
    ultimas: dict[str, dict] = {}
    limite = agora - timedelta(hours=JANELA_OFERTA_H)
    for r in hist:
        if r["item"] != item["id"] or r.get("origem") == "varredura" or r["data_hora"] < limite:
            continue
        if r["url"] not in item["urls"]:
            continue
        if r["url"] not in ultimas or r["data_hora"] >= ultimas[r["url"]]["data_hora"]:
            ultimas[r["url"]] = r
    ofertas = [{
        "loja": LOJAS.get(r["loja"], r["loja"]),
        "preco": r["preco"],
        "disponivel": str(r["disponivel"]) != "False",
        "url": r["url"],
        "lido_em": r["data_hora"].isoformat(timespec="minutes"),
    } for r in ultimas.values()]
    ofertas.sort(key=lambda o: (not o["disponivel"], o["preco"]))
    return ofertas


def _serie_30d(hist: list[dict], item_id: str, agora) -> list[dict]:
    """Menor preço disponível de cada dia nos últimos 30 dias."""
    limite = agora - timedelta(days=30)
    por_dia: dict[str, float] = {}
    for r in hist:
        if r["item"] != item_id or str(r["disponivel"]) == "False" or r["data_hora"] < limite:
            continue
        dia = r["data_hora"].date().isoformat()
        por_dia[dia] = min(por_dia.get(dia, r["preco"]), r["preco"])
    return [{"dia": d, "preco": p} for d, p in sorted(por_dia.items())]


def montar(itens: list[dict], hist: list[dict], combos: list[dict], fotos: dict, agora) -> dict:
    ontem = (agora - timedelta(days=1)).date().isoformat()
    saida_itens = []
    for item in itens:
        ofertas = _ofertas_atuais(hist, item, agora)
        disponiveis = [o for o in ofertas if o["disponivel"]]
        melhor = disponiveis[0] if disponiveis else None
        serie = _serie_30d(hist, item["id"], agora)
        ontem_preco = next((s["preco"] for s in serie if s["dia"] == ontem), None)
        minimos = [s["preco"] for s in serie]
        saida_itens.append({
            "id": item["id"],
            "nome": item["nome"],
            "curto": item.get("curto") or item["nome"],
            "fase": item.get("fase"),
            "categoria": categoria(item),
            "recomendado": item.get("recomendado", True),
            "alvo": item.get("alvo"),
            "imagem": fotos.get(item["id"]),
            "melhor": melhor,
            "esgotado": bool(ofertas) and not disponiveis,
            "variacao": round(melhor["preco"] - ontem_preco, 2) if melhor and ontem_preco else None,
            "menor_30d": min(minimos) if minimos else None,
            "mediana_30d": h.mediana(minimos) if len(minimos) >= 5 else None,
            "serie": serie,
            "ofertas": disponiveis,  # o site só mostra anúncio que dá para comprar agora
            "paginas": len(item["urls"]),
        })

    por_id = {i["id"]: i for i in saida_itens}
    saida_combos = []
    for c in combos:
        partes = [por_id[i] for i in c["itens"] if i in por_id]
        faltam = [p["curto"] for p in partes if not p["melhor"]]
        saida_combos.append({
            "nome": c["nome"],
            "fase": c.get("fase", 1),
            "itens": [p["curto"] for p in partes],
            "total": None if faltam else round(sum(p["melhor"]["preco"] for p in partes), 2),
            "alvo": sum(p["alvo"] or 0 for p in partes),
            "faltam": faltam,
        })

    return {
        "atualizado": agora.isoformat(timespec="minutes"),
        "categorias": list(dict.fromkeys([n for _, n in CATEGORIAS] + [i["categoria"] for i in saida_itens])),
        "itens": saida_itens,
        "combos": saida_combos,
        "monitoradas": sorted({u for i in itens for u in i["urls"]}),
    }


def gerar(caminho: Path = ARQ_SAIDA) -> dict:
    dados = montar(carregar_itens(), h.carregar(), carregar_combos(), h.carregar_imagens(), h.agora())
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    com_preco = sum(1 for i in dados["itens"] if i["melhor"])
    print(f"Site atualizado: {com_preco}/{len(dados['itens'])} itens com preço atual -> {caminho}")
    return dados
