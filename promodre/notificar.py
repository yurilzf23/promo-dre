"""Saída dos avisos. Por enquanto sem notificações: tudo vai para o log e o site mostra os preços."""
from __future__ import annotations


def alerta(dados: dict) -> None:
    """dados: nome, preco_fmt, loja, url, motivos, titulo_pagina, fase, imagem"""
    print(f"[alerta] {dados['nome']} {dados['preco_fmt']} ({dados['loja']}) {dados['url']} :: "
          + "; ".join(dados["motivos"]))


def resumo(titulo: str, fases: list[dict], legenda: str) -> None:
    print(texto_resumo(titulo, fases, legenda))


def texto_resumo(titulo: str, fases: list[dict], legenda: str, html: bool = False) -> str:
    out = [titulo, ""]
    for f in fases:
        out.append(f.get("titulo") or f"Fase {f['fase']}")
        if f.get("total"):
            out.append(f["total"])
        if f.get("combos"):
            out.append("Combos hoje:")
            out += [f"  {c}" for c in f["combos"]]
        for l in f["linhas"]:
            nome = l["nome"] + (" (alternativa)" if l.get("alternativa") else "")
            if l.get("preco_fmt") is None:
                out.append(f"⛔ {nome} · esgotado em todas as lojas" if l.get("esgotado")
                           else f"⚪ {nome} · sem leitura hoje")
                continue
            sinal = "🟢" if l["no_alvo"] else "⚪"
            var = f" {l['variacao']}" if l.get("variacao") else ""
            out.append(f"{sinal} {nome} · {l['preco_fmt']} {l['loja']}{var}")
            if l.get("detalhe"):
                out.append(f"   {l['detalhe']}")
        out.append("")
    out.append(legenda)
    return "\n".join(out)
