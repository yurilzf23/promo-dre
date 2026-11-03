"""Promo Dre: coleta preços, guarda histórico e avisa no Discord.

Uso:
  python -m promodre.main coletar        # lê todas as URLs, grava histórico, manda alertas
  python -m promodre.main resumo         # manda o resumo diário (menor preço de cada item)
  python -m promodre.main testar         # manda uma mensagem de teste pro canal
  python -m promodre.main importar-varredura data/varredura_2026-11-03.json
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path

import yaml

from . import alertas, historico as h, notificar
from .scraper import buscar

RAIZ = Path(__file__).resolve().parent.parent
LOJAS = {"pichau": "Pichau", "kabum": "Kabum", "terabyte": "Terabyte", "amazon": "Amazon",
         "mercadolivre": "Mercado Livre", "chipart": "Chipart"}
LEGENDA = "🟢 = no alvo ou abaixo · preços à vista no PIX"


def brl(v: float | None) -> str:
    if v is None:
        return "-"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def carregar_itens(caminho: Path = RAIZ / "produtos.yaml") -> list[dict]:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))["itens"]


# ---------------------------------------------------------------- coleta

def coletar(pausa: tuple[float, float] = (2.0, 5.0)) -> list[dict]:
    itens = carregar_itens()
    hist = h.carregar()
    estado = h.carregar_estado()
    quando = h.agora()
    registros, avisos, falhas = [], [], []

    for item in itens:
        hist_total = h.precos_do_item(hist, item["id"])
        hist_30d = h.precos_do_item(hist, item["id"], dias=30)
        for url in item["urls"]:
            leitura = buscar(url)
            time.sleep(random.uniform(*pausa))
            if leitura.preco is None:
                falhas.append((item["nome"], LOJAS.get(leitura.loja, leitura.loja), leitura.erro))
                continue
            registros.append({"data_hora": quando, "item": item["id"], "loja": leitura.loja, "url": url,
                              "preco": leitura.preco, "disponivel": leitura.disponivel, "origem": "coleta"})
            if leitura.disponivel is False:
                continue
            m = alertas.motivos(leitura.preco, item.get("alvo"), hist_total, hist_30d)
            if m and not alertas.ja_avisado(estado, item["id"], url, leitura.preco, quando):
                avisos.append(dados_alerta(item, leitura, m))
                alertas.marcar_avisado(estado, item["id"], url, leitura.preco, quando)

    h.registrar(registros)
    h.salvar_estado(estado)

    for a in avisos:
        notificar.alerta(a)
    print(f"{len(registros)} preços lidos, {len(avisos)} alertas, {len(falhas)} falhas")
    for f in falhas:
        print("  falha:", *f)
    return registros


def dados_alerta(item: dict, leitura, motivos: list[str]) -> dict:
    return {
        "nome": item["nome"],
        "preco_fmt": brl(leitura.preco),
        "loja": LOJAS.get(leitura.loja, leitura.loja),
        "url": leitura.url,
        "motivos": motivos,
        "titulo_pagina": leitura.titulo,
        "fase": item.get("fase"),
    }


# ---------------------------------------------------------------- resumo diário

def montar_resumo(itens: list[dict], hist: list[dict], hoje: datetime) -> list[dict]:
    """Agrupa o menor preço do dia de cada item por fase."""
    fases: dict[int, list[dict]] = {}
    for item in sorted(itens, key=lambda i: (i.get("fase", 9), i["id"])):
        do_dia = [x for x in hist if x["item"] == item["id"] and x["preco"]
                  and x["data_hora"].date() == hoje.date() and x.get("disponivel") not in ("False", False)]
        med30 = h.mediana(h.precos_do_item(hist, item["id"], dias=30))
        linha = {"nome": item["nome"], "alvo_fmt": brl(item.get("alvo")), "med_fmt": brl(med30) if med30 else None,
                 "preco_fmt": None, "no_alvo": False}
        if do_dia:
            melhor = min(do_dia, key=lambda x: x["preco"])
            linha.update(preco_fmt=brl(melhor["preco"]), url=melhor["url"],
                         loja=LOJAS.get(melhor["loja"], melhor["loja"]),
                         no_alvo=bool(item.get("alvo") and melhor["preco"] <= item["alvo"]))
        fases.setdefault(item.get("fase", 9), []).append(linha)
    return [{"fase": f, "linhas": ls} for f, ls in sorted(fases.items())]


def resumo() -> list[dict]:
    hoje = h.agora()
    fases = montar_resumo(carregar_itens(), h.carregar(), hoje)
    notificar.resumo(f"📊 Promo Dre · resumo de {hoje:%d/%m/%Y}", fases, LEGENDA)
    return fases


# ---------------------------------------------------------------- importar varredura manual

def importar_varredura(caminho: str) -> int:
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    quando = datetime.fromisoformat(dados["data_varredura"] + "T12:00").replace(tzinfo=h.TZ)
    regs = [
        {"data_hora": quando, "item": it["id"], "loja": o["loja"].lower(), "url": o["fonte"],
         "preco": o["preco"], "disponivel": True, "origem": "varredura"}
        for it in dados["itens"] for o in it["ofertas"]
    ]
    h.registrar(regs)
    print(f"{len(regs)} preços da varredura importados para o histórico")
    return len(regs)


def main() -> None:
    p = argparse.ArgumentParser(prog="promodre")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("coletar")
    sub.add_parser("resumo")
    sub.add_parser("testar")
    imp = sub.add_parser("importar-varredura")
    imp.add_argument("arquivo")
    a = p.parse_args()
    if a.cmd == "coletar":
        coletar()
    elif a.cmd == "resumo":
        resumo()
    elif a.cmd == "importar-varredura":
        importar_varredura(a.arquivo)
    elif a.cmd == "testar":
        print("enviado" if notificar.teste() else "falhou")


if __name__ == "__main__":
    main()
