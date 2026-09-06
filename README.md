# B3 Strategy Builder — Streamlit

Screener técnico para ações da B3 com construtor visual de estratégias.

## Recursos

- Três universos predefinidos: todos os ativos da B3, carteira do Ibovespa e lista pessoal de 23 ativos
- Lista de tickers continua editável após carregar qualquer universo
- Timeframes diário, semanal e mensal
- Strategy Builder com múltiplas condições AND/OR
- IFR/RSI, MME/EMA, MMS/SMA, MACD, Bollinger, Estocástico, ADX/DI, ATR, Volume e Preço
- Comparações com valor fixo, preço ou outro indicador
- Cruzamentos e inclinação ascendente/descendente
- Setup 9.1 clássico de compra e venda
- Auditoria das condições por ativo
- Exportação CSV
- Presets mantidos como atalhos opcionais

## Universos

- **Todos os ativos da B3:** a lista de ações e units é descoberta dinamicamente e mantida em cache por 24 horas.
- **Ativos do Ibovespa:** carteira de 79 ativos configurada no app.
- **Meus 23 ativos:** universo pessoal originalmente usado no screener.

A fonte externa usada para descobrir o universo amplo não fornece os preços ao screener. As séries OHLCV continuam vindo do Yahoo Finance.

## Fonte de dados de preço

O app usa `yfinance` / Yahoo Finance diretamente.

Cada vez que o usuário roda o screener, o sistema consulta o histórico disponível no Yahoo Finance, calcula os indicadores e aplica as regras configuradas no Strategy Builder. Universos amplos usam download em lotes para reduzir o tempo de consulta.

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
