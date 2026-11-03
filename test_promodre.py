from datetime import datetime, timedelta
from pathlib import Path

import pytest

from promodre import alertas, discord, historico as h, notificar
from promodre.main import brl, carregar_itens, montar_resumo
from promodre.scraper import interpretar, loja_da_url, preco_br

FX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("entrada,esperado", [
    ("R$ 1.699,99", 1699.99),
    ("1,699.99", 1699.99),
    ("R$ 979,99", 979.99),
    ("2299.99", 2299.99),
    ("R$\xa0139,99", 139.99),
    ("sem preço", None),
])
def test_preco_br(entrada, esperado):
    assert preco_br(entrada) == esperado


def test_loja_da_url():
    assert loja_da_url("https://www.pichau.com.br/x") == "pichau"
    assert loja_da_url("https://www.terabyteshop.com.br/produto/1/x") == "terabyte"
    assert loja_da_url("https://www.kabum.com.br/produto/1") == "kabum"


def test_pichau_usa_preco_a_vista_e_nao_o_parcelado():
    l = interpretar((FX / "pichau.html").read_text(), "https://www.pichau.com.br/produto")
    assert l.preco == 1699.99  # o JSON-LD diz 1999.99 (parcelado)
    assert l.disponivel is True


def test_kabum_json_ld():
    l = interpretar((FX / "kabum.html").read_text(), "https://www.kabum.com.br/produto/320797/x")
    assert l.preco == 1199.99
    assert l.disponivel is True


def test_terabyte_val_vista_e_esgotado():
    l = interpretar((FX / "terabyte.html").read_text(), "https://www.terabyteshop.com.br/produto/21648/x")
    assert l.preco == 149.99
    assert l.disponivel is False


def test_generico_meta_tag():
    html = '<meta property="product:price:amount" content="1234.50"><h1>Algo</h1>'
    l = interpretar(html, "https://loja.exemplo.com/p")
    assert l.preco == 1234.50 and l.titulo == "Algo"


def test_pagina_sem_preco():
    l = interpretar("<html><h1>Nada</h1></html>", "https://www.pichau.com.br/x")
    assert l.preco is None and l.erro


def test_motivos_alvo_mediana_e_minima():
    hist = [2700, 2650, 2690, 2710, 2680]
    m = alertas.motivos(2300, 2350, hist, hist)
    assert len(m) == 3
    assert "alvo" in m[0] and "R$ 2.350" in m[0]
    assert alertas.motivos(2690, 2350, hist, hist) == []


def test_mediana_exige_amostras_minimas():
    assert alertas.motivos(1000, None, [2000, 2000], [2000, 2000]) == []


def test_nao_repete_alerta_em_24h_a_menos_que_caia_mais():
    est = {"alertas": {}}
    t0 = datetime(2026, 11, 3, 10, tzinfo=h.TZ)
    alertas.marcar_avisado(est, "gpu", "u", 2300, t0)
    assert alertas.ja_avisado(est, "gpu", "u", 2300, t0 + timedelta(hours=5))
    assert not alertas.ja_avisado(est, "gpu", "u", 2250, t0 + timedelta(hours=5))
    assert not alertas.ja_avisado(est, "gpu", "u", 2300, t0 + timedelta(hours=25))


def test_historico_ida_e_volta(tmp_path):
    arq = tmp_path / "h.csv"
    t = h.agora()
    h.registrar([{"data_hora": t, "item": "x", "loja": "kabum", "url": "u", "preco": 10.5,
                  "disponivel": True, "origem": "teste"}], arq)
    lido = h.carregar(arq)
    assert lido[0]["preco"] == 10.5 and lido[0]["item"] == "x"


def test_produtos_yaml_valido():
    itens = carregar_itens()
    ids = [i["id"] for i in itens]
    assert len(ids) == len(set(ids))
    for i in itens:
        assert i["urls"] and i["alvo"] > 0 and i["fase"] in (1, 2, 3)


def test_resumo_marca_item_no_alvo():
    hoje = h.agora()
    itens = [{"id": "a", "nome": "Cooler", "fase": 1, "alvo": 130, "urls": []},
             {"id": "b", "nome": "GPU", "fase": 2, "alvo": 2000, "urls": []}]
    hist = [{"data_hora": hoje, "item": "a", "loja": "pichau", "url": "u", "preco": 129.9, "disponivel": "True"}]
    fases = montar_resumo(itens, hist, hoje)
    assert [f["fase"] for f in fases] == [1, 2]
    l = fases[0]["linhas"][0]
    assert l["no_alvo"] and l["preco_fmt"] == "R$ 129,90" and l["loja"] == "Pichau"
    assert fases[1]["linhas"][0]["preco_fmt"] is None
    txt = notificar.texto_resumo("Resumo", fases, "leg", html=False)
    assert "🟢 Cooler: R$ 129,90" in txt and "GPU: sem leitura hoje" in txt


class _Resp:
    def __init__(self, code, js=None):
        self.status_code, self._js, self.text = code, js or {}, ""

    def json(self):
        return self._js


def test_discord_alerta_monta_embed(monkeypatch):
    enviados = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setattr(discord.requests, "post", lambda url, json, timeout: enviados.append(json) or _Resp(204))
    monkeypatch.setattr(discord.time, "sleep", lambda s: None)
    notificar.alerta({"nome": "RTX 5060 8 GB", "preco_fmt": "R$ 2.299,99", "loja": "Kabum",
                      "url": "https://www.kabum.com.br/p", "motivos": ["abaixo do alvo de R$ 2.350"],
                      "titulo_pagina": "Placa X", "fase": 2})
    e = enviados[0]["embeds"][0]
    assert enviados[0]["username"] == "Promo Dre"
    assert e["url"] == "https://www.kabum.com.br/p" and "RTX 5060" in e["title"]
    assert any(f["value"] == "**R$ 2.299,99**" for f in e["fields"])


def test_discord_respeita_limite_429(monkeypatch):
    respostas = [_Resp(429, {"retry_after": 0.1}), _Resp(204)]
    monkeypatch.setattr(discord.requests, "post", lambda url, json, timeout: respostas.pop(0))
    monkeypatch.setattr(discord.time, "sleep", lambda s: None)
    assert discord.enviar({"content": "oi"}, webhook="https://x") is True


def test_discord_resumo_um_embed_por_fase():
    fases = [{"fase": 1, "linhas": [{"nome": "Cooler", "preco_fmt": "R$ 129,90", "url": "u", "loja": "Pichau",
                                     "alvo_fmt": "R$ 130,00", "med_fmt": None, "no_alvo": True}]},
             {"fase": 2, "linhas": [{"nome": "GPU", "preco_fmt": None, "alvo_fmt": "R$ 2.000,00", "no_alvo": False}]}]
    embeds = discord.embed_resumo("Resumo", fases, "leg")
    assert len(embeds) == 2 and embeds[0]["color"] == discord.COR_OK
    assert "[R$ 129,90](u)" in embeds[0]["description"] and embeds[1]["footer"]["text"] == "leg"


def test_brl():
    assert brl(1699.99) == "R$ 1.699,99"
