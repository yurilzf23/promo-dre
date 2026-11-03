"""Histórico de preços em CSV (versionado no próprio repositório)."""
from __future__ import annotations

import csv
import json
import os
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
RAIZ = Path(__file__).resolve().parent.parent
# Perfil "pc": a coleta feita no seu computador grava em arquivos próprios
# (historico_pc.csv / estado_pc.json) para nunca dar conflito com a do GitHub.
PERFIL = os.environ.get("PROMODRE_PERFIL", "").strip().lower()
_SUFIXO = f"_{PERFIL}" if PERFIL else ""
ARQ_HISTORICO = RAIZ / "data" / f"historico{_SUFIXO}.csv"
ARQ_ESTADO = RAIZ / "data" / f"estado{_SUFIXO}.json"
CAMPOS = ["data_hora", "item", "loja", "url", "preco", "disponivel", "origem"]


def agora() -> datetime:
    return datetime.now(TZ)


def carregar(caminho: Path | None = None) -> list[dict]:
    """Sem caminho, junta todos os históricos (GitHub + PC) para médias e resumo."""
    arquivos = [caminho] if caminho else sorted((RAIZ / "data").glob("historico*.csv"))
    linhas: list[dict] = []
    for arq in arquivos:
        if not arq.exists():
            continue
        with arq.open(encoding="utf-8") as f:
            linhas += list(csv.DictReader(f))
    for l in linhas:
        l["preco"] = float(l["preco"]) if l["preco"] else None
        l["data_hora"] = datetime.fromisoformat(l["data_hora"])
    return linhas


def registrar(registros: list[dict], caminho: Path = ARQ_HISTORICO) -> None:
    novo = not caminho.exists()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        for r in registros:
            linha = dict(r)
            linha["data_hora"] = r["data_hora"].isoformat(timespec="minutes")
            w.writerow({k: linha.get(k, "") for k in CAMPOS})


def precos_do_item(hist: list[dict], item: str, dias: int | None = None) -> list[float]:
    limite = agora() - timedelta(days=dias) if dias else None
    return [
        h["preco"]
        for h in hist
        if h["item"] == item and h["preco"] and (limite is None or h["data_hora"] >= limite)
        and h.get("disponivel") not in ("False", False)
    ]


def minimos_diarios(hist: list[dict], item: str, dias: int | None = None) -> list[float]:
    """Menor preço disponível de cada dia: é a referência de 'quanto essa peça costuma custar no melhor lugar'."""
    limite = agora() - timedelta(days=dias) if dias else None
    por_dia: dict = {}
    for x in hist:
        if (x["item"] != item or not x["preco"] or x.get("disponivel") in ("False", False)
                or (limite and x["data_hora"] < limite)):
            continue
        d = x["data_hora"].date()
        por_dia[d] = min(por_dia.get(d, x["preco"]), x["preco"])
    return [por_dia[d] for d in sorted(por_dia)]


def mediana(valores: list[float]) -> float | None:
    return statistics.median(valores) if valores else None


# ---------------------------------------------------------------- estado dos alertas

def carregar_estado(caminho: Path = ARQ_ESTADO) -> dict:
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {"alertas": {}}


def salvar_estado(estado: dict, caminho: Path = ARQ_ESTADO) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
