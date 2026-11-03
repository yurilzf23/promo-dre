"""Decide por onde os avisos saem: Discord (principal), Telegram (opcional) ou só o log."""
from __future__ import annotations

from html import escape

from . import discord, telegram


def _telegram_configurado() -> bool:
    import os

    return bool(os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def alerta(dados: dict) -> None:
    """dados: nome, preco_fmt, loja, url, motivos, titulo_pagina, fase, imagem"""
    enviado = False
    if discord.configurado():
        enviado |= discord.enviar({"embeds": [discord.embed_alerta(
            dados["nome"], dados["preco_fmt"], dados["loja"], dados["url"],
            dados["motivos"], dados.get("titulo_pagina"), dados.get("fase"), dados.get("imagem"))]})
    if _telegram_configurado():
        linhas = [f"🔥 <b>{escape(dados['nome'])}</b> por <b>{dados['preco_fmt']}</b> no PIX ({dados['loja']})",
                  *[f"• {escape(m)}" for m in dados["motivos"]],
                  f'<a href="{escape(dados["url"])}">Abrir na loja</a>']
        enviado |= telegram.enviar("\n".join(linhas))
    if not enviado:
        print(f"[alerta] {dados['nome']} {dados['preco_fmt']} ({dados['loja']}) {dados['url']} :: "
              + "; ".join(dados["motivos"]))


def resumo(titulo: str, fases: list[dict], legenda: str) -> None:
    enviado = False
    if discord.configurado():
        enviado |= discord.enviar({"embeds": discord.embed_resumo(titulo, fases, legenda)})
    if _telegram_configurado():
        enviado |= telegram.enviar(texto_resumo(titulo, fases, legenda, html=True))
    if not enviado:
        print(texto_resumo(titulo, fases, legenda, html=False))


def texto_resumo(titulo: str, fases: list[dict], legenda: str, html: bool) -> str:
    esc = escape if html else (lambda x: x)
    b = (lambda x: f"<b>{escape(x)}</b>") if html else (lambda x: x)
    out = [b(titulo), ""]
    for f in fases:
        out.append(b(f.get("titulo") or f"Fase {f['fase']}"))
        if f.get("total"):
            out.append(esc(f["total"]))
        for l in f["linhas"]:
            nome = esc(l["nome"]) + (" (alternativa)" if l.get("alternativa") else "")
            if l.get("preco_fmt") is None:
                out.append(f"⛔ {nome} · esgotado em todas as lojas" if l.get("esgotado")
                           else f"⚪ {nome} · sem leitura hoje")
                continue
            sinal = "🟢" if l["no_alvo"] else "⚪"
            preco = f'<a href="{escape(l["url"])}">{l["preco_fmt"]}</a>' if html else l["preco_fmt"]
            var = f" {l['variacao']}" if l.get("variacao") else ""
            out.append(f"{sinal} {nome} · {preco} {l['loja']}{var}")
            if l.get("detalhe"):
                out.append(f"   {esc(l['detalhe'])}")
        out.append("")
    out.append(legenda)
    return "\n".join(out)


def teste() -> bool:
    ok = False
    if discord.configurado():
        ok |= discord.enviar({"embeds": [{"title": "✅ Promo Dre conectado",
                                          "description": "Os alertas de preço e o resumo diário vão chegar neste canal.",
                                          "color": discord.COR_OK}]})
    if _telegram_configurado():
        ok |= telegram.enviar("✅ Promo Dre conectado. Os alertas de preço vão chegar aqui.")
    if not ok:
        print("Nenhum canal configurado (DISCORD_WEBHOOK_URL ou TELEGRAM_TOKEN/TELEGRAM_CHAT_ID) ou o envio falhou.")
    return ok
