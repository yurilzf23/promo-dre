# Promo Dre

Monitor de preços dos upgrades do PC, com um site para consultar tudo. O bot lê direto as páginas da Pichau, Kabum e Terabyte (e qualquer loja com JSON-LD), guarda o histórico e publica um painel no GitHub Pages.

**Site:** https://yurilzf23.github.io/promo-dre/

## Como funciona

- **Coleta a cada 2 horas** (GitHub Actions): lê o preço à vista (PIX) e a foto de cada URL do `produtos.yaml` e grava em `data/historico.csv` e `data/imagens.json`.
- **Site atualizado na mesma hora**: depois de cada coleta, `python -m promodre.main site` gera `docs/dados.json`, que é lido pelo `docs/index.html`.
- **Sem notificações por enquanto**: as regras de alerta (alvo, queda de 8% sobre a mediana de 30 dias, menor preço já visto) continuam calculadas e aparecem no log da coleta.

### O que o site mostra

- Cada peça com foto, menor preço atual, loja e botão para comprar.
- Quanto falta para o alvo (ou quanto está abaixo), variação desde ontem e mini gráfico dos últimos 30 dias.
- Todas as ofertas lidas de cada peça, com as esgotadas riscadas.
- Combos de plataforma (AMD x Intel) com o total do dia.
- Resumo no topo: total do upgrade recomendado, itens no alvo, quedas e esgotados.
- Menu lateral por categoria (processador, placa de vídeo, teclado…), mostrando só as categorias com anúncio à venda.
- Filtros por busca, "só recomendados", "só no alvo", ordenação e **modo claro/escuro** (segue o sistema e lembra sua escolha).
- Preço com mais de 48 h sem leitura não aparece como atual.

## Procurar preço de qualquer produto

Na caixa **Procurar preço** do site, digite o modelo ou cole o link de um produto da Kabum ou da Terabyte. O site abre uma issue `Buscar: <termo>` no GitHub (é só clicar em *Create*), o workflow `busca.yml` pesquisa nas lojas e o resultado aparece em **Minhas buscas** em 1 a 3 minutos (também vem como comentário na issue, que é fechada sozinha).

- Cada resultado tem **+ Monitorar**, que abre uma issue `Monitorar: <link> | <termo>` e coloca o anúncio na lista fixa (categoria Outros, alvo 8% abaixo do preço do dia).
- Só pedidos do dono do repositório são atendidos.
- A Pichau fica de fora da busca porque bloqueia os servidores do GitHub.

## Ativar o site (uma vez)

*Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, pasta `/docs` → Save.*
Em 1 ou 2 minutos o site fica no ar no endereço acima.

## Comandos locais

```bash
pip install -r requirements.txt
python -m promodre.main coletar
python -m promodre.main site
python -m promodre.main resumo        # resumo em texto no terminal
python -m pytest -q
```

Para ver o site no PC: `cd docs` e `python -m http.server`, depois abra http://localhost:8000.

## Editando a lista

Tudo fica no `produtos.yaml`. Para cada item: `id`, `nome`, `curto`, `fase`, `alvo`, `recomendado` (false = alternativa) e as `urls` das páginas de produto. Os `combos` no topo do arquivo definem as comparações de plataforma.

**Regra usada nos alvos iniciais:** o menor valor entre o mais barato encontrado e 92% da mediana, arredondado para baixo em R$ 10. Depois de umas semanas de histórico, vale ajustar com base na mediana real.

## Pichau pelo seu PC

A Pichau bloqueia os servidores do GitHub (HTTP 403). O GitHub coleta só Kabum e Terabyte (`coletar --sem pichau`) e a Pichau é coletada pelo seu computador com `coletar_pc.bat` no Agendador de Tarefas, a cada 3 horas.

- A coleta do PC grava em `data/historico_pc.csv`, `data/estado_pc.json` e `data/imagens_pc.json`, sem conflito com a do GitHub.
- Quando o PC sobe a coleta, o GitHub regenera o site sozinho.

## Estrutura

```
produtos.yaml            lista de itens, alvos, URLs e combos
promodre/scraper.py      leitura de preço e foto por loja (Pichau, Kabum, Terabyte, genérico)
promodre/alertas.py      regras de alerta e anti-repetição
promodre/historico.py    histórico CSV, estado dos alertas e fotos
promodre/site.py         gera docs/dados.json para o site
promodre/busca.py        busca sob demanda e "Monitorar" (pedidos por issue)
promodre/notificar.py    saída dos avisos (hoje só o log)
promodre/main.py         comandos coletar / site / resumo / importar-varredura
docs/                    site (index.html + dados.json)
data/                    histórico, estado, fotos e varredura inicial
.github/workflows/       agendamento
```
