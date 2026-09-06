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

A fonte externa usada para descobrir o universo amplo não fornece os preços ao screener. As séries OHLCV continuam vindo do Yahoo Finance.

## Fonte de dados de preço

O app usa `yfinance` / Yahoo Finance diretamente.

Cada vez que o usuário roda o screener, o sistema consulta o histórico disponível no Yahoo Finance, calcula os indicadores e aplica a estratégia e os filtros de contexto. Universos amplos usam download em lotes para reduzir o tempo de consulta.

Não há banco PostgreSQL nem rotina agendada nesta versão.

O Yahoo Finance é adequado para prototipação e estudos, mas não é uma fonte oficial da B3 e não oferece SLA de disponibilidade.

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
