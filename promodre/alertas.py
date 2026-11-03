"""Regras que decidem quando um preço vira alerta."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import historico as h

QUEDA_SOBRE_MEDIANA = 0.92  # avisa quando fica 8% abaixo da mediana dos melhores preços diários (30 dias)
MIN_DIAS = 5  # dias de histórico mínimos para confiar na mediana e na mínima
REPETIR_APOS_HORAS = 24 * 7  # mesmo preço na mesma loja só volta a avisar depois de 7 dias


def motivos(preco: float, alvo: float | None, minimos_total: list[float], minimos_30d: list[float]) -> list[str]:
    """Lista os motivos que fazem deste preço uma oportunidade (vazia = sem alerta).

    minimos_*: menor preço de cada dia do histórico. Comparar com o melhor preço do dia (e não com
    todas as ofertas) evita que a loja mais barata dispare alerta todo dia só por ser a mais barata.
    """
    m: list[str] = []
    if alvo and preco <= alvo:
        m.append(f"abaixo do alvo de R$ {alvo:,.0f}")
    med = h.mediana(minimos_30d)
    if med and len(minimos_30d) >= MIN_DIAS and preco <= med * QUEDA_SOBRE_MEDIANA:
        m.append(f"{(1 - preco / med) * 100:.0f}% abaixo do melhor preço típico dos últimos 30 dias (R$ {med:,.0f})")
    if len(minimos_total) >= MIN_DIAS and preco < min(minimos_total):
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
