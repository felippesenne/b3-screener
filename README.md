# B3 Strategy Builder — Streamlit

Screener técnico para ações da B3 com construtor visual de estratégias.

## Recursos

- Universo de tickers editável
- Timeframes diário, semanal e mensal
- Strategy Builder com múltiplas condições AND/OR
- IFR/RSI, MME/EMA, MMS/SMA, MACD, Bollinger, Estocástico, ADX/DI, ATR, Volume e Preço
- Comparações com valor fixo, preço ou outro indicador
- Cruzamentos e inclinação ascendente/descendente
- Auditoria das condições por ativo
- Exportação CSV
- Presets mantidos como atalhos opcionais

## Fonte de dados

O app usa `yfinance` / Yahoo Finance diretamente.

Cada vez que o usuário roda o screener, o sistema consulta o histórico disponível no Yahoo Finance, calcula os indicadores e aplica as regras configuradas no Strategy Builder.

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
