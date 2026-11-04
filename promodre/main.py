"""Promo Dre: coleta preços, guarda histórico e avisa no Discord.

Uso:
  python -m promodre.main coletar        # lê todas as URLs, grava histórico, manda alertas
  python -m promodre.main resumo         # manda o resumo diário (menor preço de cada item)
  python -m promodre.main testar         # manda uma mensagem de teste pro canal
  python -m promodre.main testar-alerta  # lê um anúncio real e manda um card de alerta de teste
  python -m promodre.main importar-varredura data/varredura_2026-11-03.json
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import alertas, historico as h, notificar
from .scraper import buscar, loja_da_url

RAIZ = Path(__file__).resolve().parent.parent
LOJAS = {"pichau": "Pichau", "kabum": "Kabum", "terabyte": "Terabyte", "amazon": "Amazon",
         "mercadolivre": "Mercado Livre", "chipart": "Chipart"}
LEGENDA = "🟢 no alvo · ⛔ esgotado · 🔻🔺 variação desde ontem · preços à vista no PIX"


def brl(v: float | None) -> str:
    if v is None:
        return "-"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def carregar_itens(caminho: Path = RAIZ / "produtos.yaml") -> list[dict]:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))["itens"]


def carregar_combos(caminho: Path = RAIZ / "produtos.yaml") -> list[dict]:
    return yaml.safe_load(caminho.read_text(encoding="utf-8")).get("combos") or []


# ---------------------------------------------------------------- coleta

BLOQUEIOS_PARA_PULAR = 2  # depois de 2 HTTP 403 seguidos, pula o resto da loja nesta coleta


def filtrar_urls(urls: list[str], so: set[str] | None, sem: set[str] | None) -> list[str]:
    return [u for u in urls
            if (not so or loja_da_url(u) in so) and (not sem or loja_da_url(u) not in sem)]


def coletar(pausa: tuple[float, float] = (2.0, 5.0), so: set[str] | None = None,
            sem: set[str] | None = None) -> list[dict]:
    itens = carregar_itens()
    hist = h.carregar()
    estado = h.carregar_estado()
    quando = h.agora()
    registros, avisos, falhas, esgotados = [], [], [], []
    fotos: dict[str, str] = {}
    bloqueios: dict[str, int] = {}
    total = sum(len(filtrar_urls(i["urls"], so, sem)) for i in itens)
    n = 0
    print(f"Coletando {total} páginas...", flush=True)

    for item in itens:
        hist_total = h.minimos_diarios(hist, item["id"])
        hist_30d = h.minimos_diarios(hist, item["id"], dias=30)
        for url in filtrar_urls(item["urls"], so, sem):
            loja = loja_da_url(url)
            if bloqueios.get(loja, 0) >= BLOQUEIOS_PARA_PULAR:
                falhas.append((item["nome"], LOJAS.get(loja, loja), "pulado: a loja bloqueou esta coleta"))
                continue
            n += 1
            print(f"[{n}/{total}] {LOJAS.get(loja, loja)} · {item['nome']} ... ", end="", flush=True)
            inicio = time.time()
            leitura = buscar(url)
            situacao = brl(leitura.preco) if leitura.preco else (leitura.erro or "sem preço")
            print(f"{situacao} ({time.time() - inicio:.0f}s)", flush=True)
            time.sleep(random.uniform(*pausa))
            bloqueios[loja] = bloqueios.get(loja, 0) + 1 if leitura.erro == "HTTP 403" else 0
            if leitura.imagem and item["id"] not in fotos:
                fotos[item["id"]] = leitura.imagem
            if leitura.preco is None:
                lista = esgotados if leitura.disponivel is False else falhas
                lista.append((item["nome"], LOJAS.get(leitura.loja, leitura.loja), leitura.erro))
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
    h.salvar_imagens(fotos)

    for a in avisos:
        notificar.alerta(a)
    print(f"{len(registros)} preços lidos, {len(avisos)} alertas, {len(esgotados)} esgotados, {len(falhas)} falhas")
    for f in esgotados:
        print("  esgotado:", *f[:2])
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
        "imagem": leitura.imagem,
    }


# ---------------------------------------------------------------- resumo diário

NOMES_FASE = {1: "plataforma", 2: "placa de vídeo", 3: "memória, SSD e monitor",
              4: "gabinete e ventilação", 5: "periféricos", 6: "outros"}
MIN_DIAS_MEDIANA = 5


def _melhor_do_dia(hist: list[dict], item_id: str, dia) -> tuple[dict | None, bool]:
    """Melhor oferta disponível do dia (só coletas reais) e se houve leitura com tudo esgotado."""
    lidas = [x for x in hist if x["item"] == item_id and x["preco"] and x["data_hora"].date() == dia
             and x.get("origem", "coleta") != "varredura"]
    disp = [x for x in lidas if x.get("disponivel") not in ("False", False)]
    return (min(disp, key=lambda x: x["preco"]) if disp else None), bool(lidas) and not disp


def montar_resumo(itens: list[dict], hist: list[dict], hoje: datetime,
                  combos: list[dict] | None = None) -> list[dict]:
    """Menor preço do dia de cada item, agrupado por fase, com distância do alvo e variação desde ontem."""
    ontem = hoje.date() - timedelta(days=1)
    fases: dict[int, dict] = {}
    precos_hoje: dict[str, float] = {}
    for item in sorted(itens, key=lambda i: i.get("fase", 9)):  # mantém a ordem do produtos.yaml dentro da fase
        fase = fases.setdefault(item.get("fase", 9), {"fase": item.get("fase", 9), "linhas": [],
                                                      "soma": 0.0, "soma_alvo": 0.0, "faltando": []})
        alvo = item.get("alvo")
        alternativa = item.get("recomendado", True) is False
        melhor, esgotado = _melhor_do_dia(hist, item["id"], hoje.date())
        linha = {"nome": item.get("curto") or item["nome"], "alternativa": alternativa, "esgotado": esgotado,
                 "preco_fmt": None, "no_alvo": False, "variacao": "", "detalhe": ""}
        if melhor:
            preco = melhor["preco"]
            precos_hoje[item["id"]] = preco
            linha.update(preco_fmt=brl(preco), url=melhor["url"], loja=LOJAS.get(melhor["loja"], melhor["loja"]),
                         no_alvo=bool(alvo and preco <= alvo))
            if alvo:
                dif = preco - alvo
                pct = dif / preco * 100
                pct_txt = f"{pct:.1f}".replace(".", ",") if pct < 1 else f"{pct:.0f}"
                linha["detalhe"] = (f"{brl(-dif)} abaixo do alvo de {brl(alvo)}" if dif <= 0
                                    else f"falta {brl(dif)} ({pct_txt}%) pro alvo de {brl(alvo)}")
            minimos = h.minimos_diarios(hist, item["id"], dias=30)
            if len(minimos) >= MIN_DIAS_MEDIANA:
                linha["detalhe"] += f" · típico 30d {brl(h.mediana(minimos))}"
            antes, _ = _melhor_do_dia(hist, item["id"], ontem)
            if antes and abs(preco - antes["preco"]) >= 0.01:
                seta = "🔻" if preco < antes["preco"] else "🔺"
                linha["variacao"] = f"{seta} {brl(abs(preco - antes['preco']))}"
        if not alternativa:
            if melhor:
                fase["soma"] += melhor["preco"]
                fase["soma_alvo"] += alvo or 0
            else:
                fase["faltando"].append(linha["nome"])
        fase["linhas"].append(linha)

    por_id = {i["id"]: i for i in itens}
    combos_fase: dict[int, list[dict]] = {}
    for c in combos or []:
        faltam = [por_id[i].get("curto") or por_id[i]["nome"] for i in c["itens"] if i in por_id and i not in precos_hoje]
        total_c = sum(precos_hoje.get(i, 0) for i in c["itens"])
        alvo_c = sum(por_id[i].get("alvo") or 0 for i in c["itens"] if i in por_id)
        combos_fase.setdefault(c.get("fase", 1), []).append(
            {"nome": c["nome"], "total": None if faltam else total_c, "alvo": alvo_c, "faltam": faltam})

    saida = []
    for n, f in sorted(fases.items()):
        titulo = f"Fase {n}" + (f" · {NOMES_FASE[n]}" if n in NOMES_FASE else "")
        linhas_combo = []
        lista = sorted(combos_fase.get(n, []), key=lambda c: (c["total"] is None, c["total"] or 0))
        for k, c in enumerate(lista):
            if c["total"] is None:
                linhas_combo.append(f"{c['nome']}: sem preço hoje ({', '.join(c['faltam'])})")
            else:
                marca = "💰 " if k == 0 else ""
                linhas_combo.append(f"{marca}{c['nome']}: {brl(c['total'])} · alvo {brl(c['alvo'])}")
        total = ""
        if f["soma"] and not linhas_combo:
            total = f"Hoje {brl(f['soma'])} · alvo {brl(f['soma_alvo'])}"
            if f["faltando"]:
                total += f" (sem {', '.join(f['faltando'])})"
        saida.append({"fase": n, "titulo": titulo, "total": total, "combos": linhas_combo, "linhas": f["linhas"]})
    return saida


def resumo() -> list[dict]:
    hoje = h.agora()
    fases = montar_resumo(carregar_itens(), h.carregar(), hoje, carregar_combos())
    notificar.resumo(f"📊 Promo Dre · resumo de {hoje:%d/%m/%Y}", fases, LEGENDA)
    return fases


# ---------------------------------------------------------------- alerta de teste

URL_TESTE = "https://www.kabum.com.br/produto/459144"


def testar_alerta(url: str | None = None) -> dict | None:
    """Lê um anúncio de verdade e mostra no log o alerta marcado como TESTE (não mexe no histórico)."""
    url = url or URL_TESTE
    item = next((i for i in carregar_itens() if url in i["urls"]),
                {"nome": "Produto de teste", "fase": None, "alvo": None})
    print(f"Lendo {url} ...", flush=True)
    leitura = buscar(url)
    if leitura.preco is None:
        print(f"Não consegui ler o preço: {leitura.erro}")
        return None
    dados = dados_alerta({**item, "nome": f"[TESTE] {item['nome']}"}, leitura,
                         ["🧪 Mensagem de teste para conferir o card. Não é uma promoção.",
                          "esgotado na loja" if leitura.disponivel is False else "em estoque na loja"])
    print(f"Preço {dados['preco_fmt']} · foto: {leitura.imagem or 'não encontrada'}")
    notificar.alerta(dados)
    return dados


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
    col = sub.add_parser("coletar")
    col.add_argument("--so", help="só estas lojas, separadas por vírgula (ex.: pichau)")
    col.add_argument("--sem", help="pula estas lojas, separadas por vírgula (ex.: pichau)")
    sub.add_parser("resumo")
    sub.add_parser("site")
    ta = sub.add_parser("testar-alerta")
    ta.add_argument("--url", help="anúncio a usar no teste (padrão: RX 7600 da Kabum)")
    imp = sub.add_parser("importar-varredura")
    imp.add_argument("arquivo")
    a = p.parse_args()
    if a.cmd == "coletar":
        lista = lambda v: {x.strip().lower() for x in v.split(",")} if v else None
        coletar(so=lista(a.so), sem=lista(a.sem))
    elif a.cmd == "resumo":
        resumo()
    elif a.cmd == "importar-varredura":
        importar_varredura(a.arquivo)
    elif a.cmd == "testar-alerta":
        testar_alerta(a.url)
    elif a.cmd == "site":
        from .site import gerar
        gerar()


if __name__ == "__main__":
    main()
