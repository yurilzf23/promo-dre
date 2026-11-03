# Promo Dre

Monitor de preços dos upgrades do PC com alertas no Discord. Ele consulta direto as páginas da Pichau, Kabum e Terabyte (e qualquer loja com JSON-LD), guarda o histórico e só avisa quando o preço cai de verdade.

## Como funciona

- **Coleta a cada 2 horas** (GitHub Actions): lê o preço à vista (PIX) de cada URL do `produtos.yaml` e grava em `data/historico.csv`.
- **Alerta na hora** quando o preço:
  - fica igual ou abaixo do **alvo** do item
  - cai **8% abaixo do melhor preço típico dos últimos 30 dias** (mediana do menor preço de cada dia, a partir de 5 dias de histórico)
  - bate o **menor preço já registrado** (também a partir de 5 dias)
- **Não repete** o mesmo alerta (item + loja + preço) por 7 dias. Se o preço cair mais, avisa de novo na hora.
- **Foto do produto** no card do alerta, puxada da página da loja.
- Produto esgotado não conta como falha: aparece separado no log.
- **Resumo diário às 08:41**: menor preço de cada item no dia, alvo e mediana de 30 dias, um card por fase (fica verde quando algum item da fase está no alvo).
- **Telegram opcional**: se você cadastrar também os secrets do Telegram, os avisos saem nos dois.

## Configuração (uns 10 minutos)

1. **Crie um servidor só seu no Discord**: botão **+** na barra da esquerda → *Criar o meu* → *Para mim e meus amigos*. Dê o nome que quiser (ex.: Promo Dre).
2. **Crie o canal dos alertas**, por exemplo `#promocoes`.
3. **Gere o webhook**: engrenagem do canal (*Editar canal*) → *Integrações* → *Webhooks* → *Novo webhook* → *Copiar URL do webhook*.
   - Trate essa URL como senha: quem tiver ela consegue postar no canal.
4. **Crie o repositório** `promo-dre` no GitHub (privado) e suba estes arquivos.
5. **Cadastre o secret** em *Settings → Secrets and variables → Actions → New repository secret*:
   - nome `DISCORD_WEBHOOK_URL`, valor a URL copiada
6. **Teste**: em *Actions → Promo Dre → Run workflow*, rode com `testar`. Deve chegar um card verde no canal. Depois rode com `coletar`.
7. **No celular**: instale o app do Discord e deixe as notificações do canal em *Todas as mensagens* pra receber o alerta na hora.

## Comandos locais

```bash
pip install -r requirements.txt
python -m promodre.main coletar
python -m promodre.main resumo
python -m promodre.main testar
python -m pytest -q
```

No Windows, defina a variável antes: `set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...`

## Editando a lista

Tudo fica no `produtos.yaml`. Para cada item: `id`, `nome`, `fase`, `alvo` e as `urls` das páginas de produto.

**Regra usada nos alvos iniciais:** o menor valor entre o mais barato encontrado na varredura e 92% da mediana, arredondado para baixo em R$ 10. Depois de umas semanas de histórico, vale ajustar com base na mediana real.

## Histórico inicial

O arquivo `data/varredura_2026-11-03.json` tem a varredura manual que originou os alvos (60 preços, 9 itens). Ele já está importado no `historico.csv`. Para reimportar:

```bash
python -m promodre.main importar-varredura data/varredura_2026-11-03.json
```

## Se alguma loja bloquear

Pichau e Terabyte usam proteção anti-bot e podem recusar acessos vindos dos servidores do GitHub. O projeto usa `curl_cffi` (imita o navegador Chrome) para reduzir isso. Se no log aparecer `HTTP 403` repetido para uma loja:

- rode a coleta no seu PC com o **Agendador de Tarefas do Windows** (`python -m promodre.main coletar` a cada 2 h). IP residencial quase nunca é bloqueado
- ou mantenha só as lojas que funcionam no GitHub

## Estrutura

```
produtos.yaml            lista de itens, alvos e URLs
promodre/scraper.py      leitura de preço por loja (Pichau, Kabum, Terabyte, genérico)
promodre/alertas.py      regras de alerta e anti-repetição
promodre/historico.py    histórico CSV e estado dos alertas
promodre/discord.py      cards de alerta e resumo no Discord
promodre/notificar.py    escolhe o canal (Discord, Telegram ou só log)
promodre/telegram.py     envio opcional pelo Telegram
promodre/main.py         comandos coletar / resumo / importar-varredura
data/                    histórico, estado e varredura inicial
.github/workflows/       agendamento
```
