"""Envio de mensagens pelo bot do Telegram."""
from __future__ import annotations

import os

import requests

LIMITE = 4000  # o Telegram aceita até 4096 caracteres por mensagem


def enviar(texto: str, token: str | None = None, chat_id: str | None = None) -> bool:
    token = token or os.environ.get("TELEGRAM_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID não configurados; mensagem só no log:\n" + texto)
        return False
    ok = True
    for parte in _quebrar(texto):
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": parte, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[telegram] erro {r.status_code}: {r.text[:200]}")
            ok = False
    return ok


def _quebrar(texto: str) -> list[str]:
    partes, atual = [], ""
    for linha in texto.splitlines(keepends=True):
        if len(atual) + len(linha) > LIMITE:
            partes.append(atual)
            atual = ""
        atual += linha
    if atual:
        partes.append(atual)
    return partes
