"""Envio de mensagens por webhook do Discord."""
from __future__ import annotations

import os
import time

import requests

COR_ALERTA = 0xE8590C  # laranja
COR_RESUMO = 0x5865F2  # azul Discord
COR_OK = 0x2F9E44  # verde


def configurado() -> bool:
    return bool(os.environ.get("DISCORD_WEBHOOK_URL"))


def enviar(payload: dict, webhook: str | None = None, tentativas: int = 3) -> bool:
    webhook = webhook or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        return False
    payload = {"username": "Promo Dre", **payload}
    for _ in range(tentativas):
        r = requests.post(webhook, json=payload, timeout=20)
        if r.status_code in (200, 204):
            time.sleep(0.6)  # o webhook aceita ~5 mensagens a cada 2 s
            return True
        if r.status_code == 429:  # limite de envio: espera o tempo que o Discord pedir
            espera = float(r.json().get("retry_after", 2))
            time.sleep(min(espera, 30))
            continue
        print(f"[discord] erro {r.status_code}: {r.text[:200]}")
        return False
    return False


def embed_alerta(nome: str, preco_fmt: str, loja: str, url: str, motivos: list[str],
                 titulo_pagina: str | None, fase: int | None) -> dict:
    campos = [
        {"name": "Preço no PIX", "value": f"**{preco_fmt}**", "inline": True},
        {"name": "Loja", "value": loja, "inline": True},
    ]
    if fase:
        campos.append({"name": "Fase", "value": str(fase), "inline": True})
    campos.append({"name": "Por que avisei", "value": "\n".join(f"• {m}" for m in motivos)[:1024]})
    e = {
        "title": f"🔥 {nome}"[:256],
        "url": url,
        "color": COR_ALERTA,
        "fields": campos,
    }
    if titulo_pagina:
        e["footer"] = {"text": titulo_pagina[:200]}
    return e


def embed_resumo(titulo: str, fases: list[dict], legenda: str) -> list[dict]:
    """Um embed por fase. Cada fase: {'fase': n, 'linhas': [{nome, preco_fmt, loja, url, alvo_fmt, med_fmt, no_alvo}]}"""
    embeds = []
    for i, f in enumerate(fases):
        linhas = []
        for l in f["linhas"]:
            if l.get("preco_fmt") is None:
                linhas.append(f"⚪ **{l['nome']}**: sem leitura hoje")
                continue
            sinal = "🟢" if l["no_alvo"] else "⚪"
            extra = f" · mediana 30d {l['med_fmt']}" if l.get("med_fmt") else ""
            linhas.append(f"{sinal} **{l['nome']}**: [{l['preco_fmt']}]({l['url']}) ({l['loja']})\n"
                          f"　alvo {l['alvo_fmt']}{extra}")
        algum_ok = any(l.get("no_alvo") for l in f["linhas"])
        e = {
            "title": f"Fase {f['fase']}",
            "description": "\n".join(linhas)[:4000] or "Sem itens.",
            "color": COR_OK if algum_ok else COR_RESUMO,
        }
        if i == 0:
            e["author"] = {"name": titulo}
        if i == len(fases) - 1:
            e["footer"] = {"text": legenda}
        embeds.append(e)
    return embeds[:10]  # o Discord aceita até 10 embeds por mensagem
