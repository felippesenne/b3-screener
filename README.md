# B3 Strategy Builder — Streamlit

Screener técnico para ações da B3 com construtor visual de estratégias, presets clássicos e filtros independentes de contexto.

## Recursos

- Três universos predefinidos: todos os ativos da B3, carteira do Ibovespa e lista pessoal de 23 ativos
- Lista de tickers continua editável após carregar qualquer universo
- Timeframes diário, semanal e mensal
- Strategy Builder com múltiplas condições AND/OR
- IFR/RSI, MME/EMA, MMS/SMA, MACD, Bollinger, Estocástico, ADX/DI, ATR, Volume e Preço
- Comparações com valor fixo, preço ou outro indicador
- Cruzamentos e inclinação ascendente/descendente
- Presets Stormer: PFR, Setup 123, IFR2 clássico e Éden dos Traders
- Família MME9/Larry Williams: Setup 9.1, 9.2 e 9.3, compra e venda
- Inside Bar como preset de price action
- Filtros de contexto independentes e combináveis por AND
- Auditoria separando aprovação da estratégia e do contexto
- Entrada/gatilho, stop e status exibidos quando o setup possui esses níveis
- Exportação CSV

## Presets clássicos

### Stormer

- PFR — Compra e Venda
- Setup 123 — Compra e Venda
- IFR2 clássico — IFR(2) abaixo de 5, entrada no fechamento e stop de referência pela expansão de 130% da amplitude
- Éden dos Traders — Compra e Venda com MME8/MME80

### Larry Williams / família MME9

- Setup 9.1 — Compra e Venda
- Setup 9.2 — Compra e Venda
- Setup 9.3 — Compra e Venda

### Outros

- Inside Bar
- IFR2 < 25 + MME50 ascendente
- MME9 / MME80 ascendentes

## Filtros de contexto

O filtro de contexto é independente do preset e também funciona junto ao Strategy Builder. É possível selecionar mais de um; todos são aplicados por **AND** à estratégia principal.

Filtros disponíveis:

- Éden dos Traders — Compra
- Éden dos Traders — Venda
- MME80 ascendente
- MME80 descendente
- Stormer MME49 — Compra
- Stormer MME49 — Venda
- Preço acima da MME200
- Preço abaixo da MME200
- Inside Bar atual

Exemplos de combinações:

- PFR Compra + Éden dos Traders Compra
- Setup 123 Compra + Éden + Inside Bar
- IFR2 Stormer + Stormer MME49 Compra
- Inside Bar + Éden dos Traders Venda

## Universos

- **Todos os ativos da B3:** a lista de ações e units é descoberta dinamicamente e mantida em cache por 24 horas.
- **Ativos do Ibovespa:** carteira configurada no app.
- **Meus 23 ativos:** universo pessoal originalmente usado no screener.

A lista do universo amplo é independente das fontes de preços. Cada ativo tem sua série e data verificadas antes dos cálculos.

## Fonte de dados de preço

O **Screener e o Checklist EOD** usam **brapi v2 como fonte principal**, com **Yahoo Finance/yfinance como reserva automática por ativo**. O Backtesting e a Carteira mantêm seus provedores existentes.

- Cada execução consulta dados novos. O Yahoo só recebe os ativos ausentes, inválidos, com histórico curto ou defasados na fonte principal.
- Um ativo só entra no cálculo quando tem OHLCV válido até o último pregão encerrado esperado. Se ambas as fontes falham, ele aparece na auditoria de dados e fica fora dos sinais.
- O calendário `BVMF` de `exchange-calendars` considera feriados e finais de semana. Antes de **18h30 de Brasília**, o candle diário do dia é excluído. Esse é um corte conservador de disponibilidade, não uma afirmação sobre o horário oficial de fechamento.
- Fonte, data efetiva do último pregão e motivo da falha aparecem por ativo. O CSV dos resultados inclui a fonte e a data diária, inclusive em consultas semanais/mensais.
- As séries das fontes não são concatenadas. São usados os campos OHLC do provedor escolhido, sem substituir apenas o fechamento por `adjustedClose`. Diferenças de ajustes do provedor podem alterar os indicadores quando há troca de fonte.
- Respostas 401, 403, 429, falhas do servidor e timeouts suspendem novas chamadas à brapi naquela execução. As chamadas têm timeout; o Yahoo usa concorrência limitada. Não há retentativa em massa do mesmo lote.
- Se o plano brapi encurtar a janela solicitada, ou a série começar mais de 14 dias após o início esperado, a fonte é rejeitada e a reserva é tentada. Ativos recém-listados também podem exigir uma janela menor. Essa verificação não garante continuidade de todas as sessões de um ativo ilíquido.

### Configurar a brapi

Configure `BRAPI_TOKEN` nos **Secrets** do Streamlit Community Cloud (Settings → Secrets) ou em variável de ambiente:

```toml
BRAPI_TOKEN = "seu_token"
```

Também é possível usar o campo **Fonte de dados → Token brapi** na lateral do app. Nesse caso, ele permanece apenas na sessão. Não coloque o token no código, no GitHub ou em URLs. O token é enviado à brapi pelo cabeçalho `Authorization`.

Sem token, somente **PETR4, VALE3, ITUB4 e MGLU3** têm acesso de demonstração à brapi. Os demais dependem da reserva Yahoo e podem continuar indisponíveis enquanto o Yahoo limitar as consultas. Configure um token e um plano com cobertura e histórico suficientes para o universo selecionado. A integração não contrata planos automaticamente.

Fontes da implementação: [histórico brapi v2](https://brapi.dev/docs/acoes/historico), [acesso de demonstração brapi](https://brapi.dev/docs/acoes), [calendário oficial da B3](https://www.b3.com.br/pt_br/solucoes/plataformas/puma-trading-system/para-participantes-e-traders/calendario-de-negociacao/feriados/) e [exchange-calendars](https://github.com/gerrymanoim/exchange_calendars).

Não há banco PostgreSQL nem rotina agendada nesta versão.

### Verificação

```bash
python -m unittest tests_market_data tests_market_data_ui tests_navigation_smoke tests_eod_checklist tests_backtest_streamlit_smoke
```

Os testes usam respostas controladas para falhas, dados defasados, feriados e candles em formação; não exigem token nem dependem das cotações ao vivo.

## Rodar localmente

Requer Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

No Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy no Streamlit Community Cloud

Use:

- Repository: `felippesenne/b3-screener`
- Branch: `main`
- Main file: `app.py`

O Streamlit instalará automaticamente as dependências de `requirements.txt`.
