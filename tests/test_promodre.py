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


def test_imagem_do_produto():
    l = interpretar((FX / "pichau.html").read_text(), "https://www.pichau.com.br/produto")
    assert l.imagem == "https://media.pichau.com.br/media/catalog/product/cache/x/1/0/100-100001503wof.jpg"
    l = interpretar((FX / "kabum.html").read_text(), "https://www.kabum.com.br/produto/320797/x")
    assert l.imagem == "https://images.kabum.com.br/produtos/fotos/320797/processador_g.jpg"
    l = interpretar((FX / "terabyte.html").read_text(), "https://www.terabyteshop.com.br/produto/21648/x")
    assert l.imagem == "https://img.terabyteshop.com.br/produto/g/cooler-ak400_1.jpg"
    assert interpretar("<h1>x</h1>", "https://www.kabum.com.br/p").imagem is None


def test_generico_meta_tag():
    html = '<meta property="product:price:amount" content="1234.50"><h1>Algo</h1>'
    l = interpretar(html, "https://loja.exemplo.com/p")
    assert l.preco == 1234.50 and l.titulo == "Algo"


def test_pagina_sem_preco():
    l = interpretar("<html><h1>Nada</h1></html>", "https://www.pichau.com.br/x")
    assert l.preco is None and l.erro


def test_motivos_alvo_mediana_e_minima():
    minimos = [2700, 2650, 2690, 2710, 2680]  # melhor preço de cada dia
    m = alertas.motivos(2300, 2350, minimos, minimos)
    assert len(m) == 3
    assert "alvo" in m[0] and "R$ 2.350" in m[0]
    assert alertas.motivos(2690, 2350, minimos, minimos) == []


def test_mediana_exige_dias_minimos():
    assert alertas.motivos(1000, None, [2000, 2000], [2000, 2000]) == []


def test_loja_mais_barata_de_sempre_nao_dispara_alerta():
    t = h.agora()
    hist = [{"data_hora": t - timedelta(days=d), "item": "mb", "preco": p, "disponivel": "True"}
            for d in range(6) for p in (519.99, 614.43, 856.99)]
    minimos = h.minimos_diarios(hist, "mb", dias=30)
    assert minimos == [519.99] * 6
    assert alertas.motivos(519.99, 510, minimos, minimos) == []


def test_esgotado_com_preco_zero_vira_sem_preco():
    html = '<script type="application/ld+json">{"name":"X","offers":{"price":"0.00","availability":"http://schema.org/OutOfStock"}}</script><h1>X</h1>'
    l = interpretar(html, "https://www.terabyteshop.com.br/produto/1/x")
    assert l.preco is None and l.disponivel is False and "esgotado" in l.erro


def test_nao_repete_alerta_em_7_dias_a_menos_que_caia_mais():
    est = {"alertas": {}}
    t0 = datetime(2026, 11, 3, 10, tzinfo=h.TZ)
    alertas.marcar_avisado(est, "gpu", "u", 2300, t0)
    assert alertas.ja_avisado(est, "gpu", "u", 2300, t0 + timedelta(days=3))
    assert not alertas.ja_avisado(est, "gpu", "u", 2250, t0 + timedelta(hours=5))
    assert not alertas.ja_avisado(est, "gpu", "u", 2300, t0 + timedelta(days=8))


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
                      "titulo_pagina": "Placa X", "fase": 2, "imagem": "https://img.exemplo/gpu.jpg"})
    e = enviados[0]["embeds"][0]
    assert enviados[0]["username"] == "Promo Dre"
    assert e["url"] == "https://www.kabum.com.br/p" and "RTX 5060" in e["title"]
    assert any(f["value"] == "**R$ 2.299,99**" for f in e["fields"])
    assert e["thumbnail"]["url"] == "https://img.exemplo/gpu.jpg"


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


def test_filtrar_urls_por_loja():
    from promodre.main import filtrar_urls
    urls = ["https://www.pichau.com.br/a", "https://www.kabum.com.br/produto/1", "https://www.terabyteshop.com.br/produto/2"]
    assert filtrar_urls(urls, {"pichau"}, None) == urls[:1]
    assert filtrar_urls(urls, None, {"pichau"}) == urls[1:]
    assert filtrar_urls(urls, None, None) == urls


def test_carregar_junta_historico_do_github_e_do_pc(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(h, "RAIZ", tmp_path)
    t = h.agora()
    base = {"data_hora": t, "item": "x", "url": "u", "disponivel": True, "origem": "t"}
    h.registrar([{**base, "loja": "kabum", "preco": 10.0}], tmp_path / "data" / "historico.csv")
    h.registrar([{**base, "loja": "pichau", "preco": 9.0}], tmp_path / "data" / "historico_pc.csv")
    assert sorted(l["loja"] for l in h.carregar()) == ["kabum", "pichau"]


def test_403_nao_tenta_de_novo(monkeypatch):
    from promodre import scraper
    chamadas = []

    class R:
        status_code, text = 403, ""

    monkeypatch.setattr(scraper.http, "get", lambda *a, **k: chamadas.append(1) or R())
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    l = scraper.buscar("https://www.pichau.com.br/x")
    assert l.erro == "HTTP 403" and len(chamadas) == 1


def test_resumo_avisa_quando_tudo_esgotou():
    hoje = h.agora()
    itens = [{"id": "g", "nome": "RTX 5060", "fase": 2, "alvo": 2350, "urls": []}]
    hist = [{"data_hora": hoje, "item": "g", "loja": "pichau", "url": "u", "preco": 2399.99, "disponivel": "False"}]
    fases = montar_resumo(itens, hist, hoje)
    assert fases[0]["linhas"][0]["esgotado"] is True
    assert "esgotado em todas as lojas" in notificar.texto_resumo("R", fases, "l", html=False)
    assert "esgotado em todas as lojas" in discord.embed_resumo("R", fases, "l")[0]["description"]
