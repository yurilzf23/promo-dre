from datetime import datetime, timedelta
from pathlib import Path

import pytest

from promodre import alertas, historico as h, notificar
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
        assert i["urls"] and i["alvo"] > 0 and i["fase"] in (1, 2, 3, 4, 5)


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
    assert "🟢 Cooler · R$ 129,90 Pichau" in txt and "GPU · sem leitura hoje" in txt
    assert "R$ 0,10 abaixo do alvo" in txt


class _Resp:
    def __init__(self, code, js=None):
        self.status_code, self._js, self.text = code, js or {}, ""

    def json(self):
        return self._js





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


def test_testar_alerta_marca_como_teste(monkeypatch):
    import promodre.main as m
    from promodre.scraper import Leitura
    enviados = []
    monkeypatch.setattr(m, "buscar", lambda u: Leitura(u, "kabum", 1899.99, True, "RX 7600 Challenger",
                                                        imagem="https://images.kabum.com.br/x.jpg"))
    monkeypatch.setattr(m.notificar, "alerta", enviados.append)
    d = m.testar_alerta()
    assert d["nome"].startswith("[TESTE] RX 7600") and d["imagem"].endswith("x.jpg")
    assert "teste" in d["motivos"][0].lower() and enviados == [d]


def test_resumo_ignora_varredura_como_preco_do_dia():
    hoje = h.agora()
    itens = [{"id": "g", "nome": "RTX 5060", "fase": 2, "alvo": 2350, "urls": []}]
    hist = [{"data_hora": hoje, "item": "g", "loja": "kabum", "url": "v", "preco": 2359.0, "disponivel": "True", "origem": "varredura"},
            {"data_hora": hoje, "item": "g", "loja": "kabum", "url": "u", "preco": 2899.99, "disponivel": "True", "origem": "coleta"}]
    assert montar_resumo(itens, hist, hoje)[0]["linhas"][0]["preco_fmt"] == "R$ 2.899,99"


def test_resumo_total_da_fase_variacao_e_distancia():
    hoje = h.agora()
    ontem = hoje - timedelta(days=1)
    itens = [{"id": "cpu", "nome": "CPU", "curto": "CPU", "fase": 1, "alvo": 1000, "urls": []},
             {"id": "mb", "nome": "Placa", "fase": 1, "alvo": 500, "urls": []},
             {"id": "alt", "nome": "CPU alt", "fase": 1, "alvo": 900, "recomendado": False, "urls": []}]
    reg = lambda t, i, p, d="True": {"data_hora": t, "item": i, "loja": "kabum", "url": i, "preco": p,
                                     "disponivel": d, "origem": "coleta"}
    hist = [reg(ontem, "cpu", 1150.0), reg(hoje, "cpu", 1100.0), reg(hoje, "mb", 520.0), reg(hoje, "alt", 950.0)]
    f = montar_resumo(itens, hist, hoje)[0]
    assert f["titulo"] == "Fase 1 · plataforma"
    assert f["total"] == "Hoje R$ 1.620,00 · alvo R$ 1.500,00"  # a alternativa não entra
    cpu = f["linhas"][0]
    assert cpu["variacao"] == "🔻 R$ 50,00"
    assert cpu["detalhe"] == "falta R$ 100,00 (9%) pro alvo de R$ 1.000,00"
    assert f["linhas"][2]["alternativa"] is True


def test_total_avisa_item_recomendado_sem_preco():
    hoje = h.agora()
    itens = [{"id": "cpu", "nome": "CPU", "fase": 1, "alvo": 1000, "urls": []},
             {"id": "mb", "nome": "Placa", "fase": 1, "alvo": 500, "urls": []}]
    hist = [{"data_hora": hoje, "item": "mb", "loja": "kabum", "url": "u", "preco": 520.0, "disponivel": "True", "origem": "coleta"},
            {"data_hora": hoje, "item": "cpu", "loja": "kabum", "url": "v", "preco": 999.0, "disponivel": "False", "origem": "coleta"}]
    f = montar_resumo(itens, hist, hoje)[0]
    assert f["total"] == "Hoje R$ 520,00 · alvo R$ 500,00 (sem CPU)"
    assert f["linhas"][0]["esgotado"] is True


def test_combos_comparam_plataformas():
    hoje = h.agora()
    itens = [{"id": "a_cpu", "nome": "Ryzen", "fase": 1, "alvo": 900, "urls": []},
             {"id": "a_mb", "nome": "B550M", "fase": 1, "alvo": 500, "urls": []},
             {"id": "i_cpu", "nome": "i5", "fase": 1, "alvo": 1000, "recomendado": False, "urls": []},
             {"id": "i_mb", "nome": "B760M", "fase": 1, "alvo": 700, "recomendado": False, "urls": []},
             {"id": "x_cpu", "nome": "X3D", "fase": 1, "alvo": 1500, "recomendado": False, "urls": []}]
    reg = lambda i, p: {"data_hora": hoje, "item": i, "loja": "kabum", "url": i, "preco": p, "disponivel": "True", "origem": "coleta"}
    hist = [reg("a_cpu", 979.0), reg("a_mb", 499.99), reg("i_cpu", 1029.99), reg("i_mb", 752.88)]
    combos = [{"nome": "AMD", "fase": 1, "itens": ["a_cpu", "a_mb"]},
              {"nome": "Intel", "fase": 1, "itens": ["i_cpu", "i_mb"]},
              {"nome": "AMD X3D", "fase": 1, "itens": ["x_cpu", "a_mb"]}]
    f = montar_resumo(itens, hist, hoje, combos)[0]
    assert f["combos"] == ["💰 AMD: R$ 1.478,99 · alvo R$ 1.400,00",
                           "Intel: R$ 1.782,87 · alvo R$ 1.700,00",
                           "AMD X3D: sem preço hoje (X3D)"]
    assert f["total"] == ""  # com combos, o total genérico da fase sai


def test_site_monta_melhor_oferta_e_combos():
    from datetime import timedelta
    from promodre import site
    agora = h.agora()
    itens = [{"id": "cpu", "nome": "CPU X", "fase": 1, "alvo": 900, "urls": ["https://a/1", "https://b/1"]},
             {"id": "mb", "nome": "Placa Y", "fase": 1, "alvo": 500, "urls": ["https://a/2"]}]
    reg = lambda i, u, p, disp=True, dt=agora, loja="kabum": {"data_hora": dt, "item": i, "loja": loja, "url": u,
                                                         "preco": p, "disponivel": str(disp), "origem": "coleta"}
    hist = [reg("cpu", "https://a/1", 950.0, dt=agora - timedelta(days=1)),
            reg("cpu", "https://a/1", 899.0), reg("cpu", "https://b/1", 850.0, disp=False, loja="pichau"),
            reg("mb", "https://a/2", 520.0, dt=agora - timedelta(hours=60))]  # velha demais
    d = site.montar(itens, hist, [{"nome": "Combo", "itens": ["cpu", "mb"]}], {"cpu": "https://img/x.jpg"}, agora)
    cpu, mb = d["itens"]
    assert cpu["melhor"]["preco"] == 899.0 and cpu["melhor"]["loja"] == "Kabum"  # esgotada não vale
    assert cpu["variacao"] == -51.0 and cpu["imagem"] == "https://img/x.jpg" and len(cpu["ofertas"]) == 2
    assert mb["melhor"] is None and not mb["esgotado"]
    assert d["combos"][0]["total"] is None and d["combos"][0]["faltam"] == ["Placa Y"]
