"""Regras que decidem quando um preço vira alerta."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import historico as h

QUEDA_SOBRE_MEDIANA = 0.92  # avisa quando fica 8% abaixo da mediana de 30 dias
MIN_AMOSTRAS = 5  # leituras mínimas para confiar na mediana
REPETIR_APOS_HORAS = 24  # não repete o mesmo alerta (item + loja + preço) antes disso


def motivos(preco: float, alvo: float | None, hist_item: list[float], hist_30d: list[float]) -> list[str]:
    """Lista os motivos que fazem deste preço uma oportunidade (vazia = sem alerta)."""
    m: list[str] = []
    if alvo and preco <= alvo:
        m.append(f"abaixo do alvo de R$ {alvo:,.0f}")
    med = h.mediana(hist_30d)
    if med and len(hist_30d) >= MIN_AMOSTRAS and preco <= med * QUEDA_SOBRE_MEDIANA:
        m.append(f"{(1 - preco / med) * 100:.0f}% abaixo da mediana de 30 dias (R$ {med:,.0f})")
    if len(hist_item) >= MIN_AMOSTRAS and preco < min(hist_item):
        m.append("menor preço já registrado")
    return [x.replace(",", ".") for x in m]


def ja_avisado(estado: dict, item: str, url: str, preco: float, quando: datetime) -> bool:
    chave = f"{item}|{url}"
    anterior = estado.get("alertas", {}).get(chave)
    if not anterior:
        return False
    momento = datetime.fromisoformat(anterior["quando"])
    caiu_mais = preco < anterior["preco"] - 0.01
    return not caiu_mais and quando - momento < timedelta(hours=REPETIR_APOS_HORAS)


def marcar_avisado(estado: dict, item: str, url: str, preco: float, quando: datetime) -> None:
    estado.setdefault("alertas", {})[f"{item}|{url}"] = {
        "preco": preco,
        "quando": quando.isoformat(timespec="minutes"),
    }
