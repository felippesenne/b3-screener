# B3 Strategy Builder — Streamlit

Screener técnico para ações da B3 com construtor visual de estratégias e camada própria de dados.

## Recursos

- Universo de tickers editável
- Timeframes diário, semanal e mensal
- Strategy Builder com múltiplas condições AND/OR
- IFR/RSI, MME/EMA, MMS/SMA, MACD, Bollinger, Estocástico, ADX/DI, ATR, Volume e Preço
- Comparações com valor fixo, preço ou outro indicador
- Cruzamentos e inclinação ascendente/descendente
- Auditoria das condições por ativo
- Exportação CSV
- PostgreSQL para histórico próprio de candles
- Backfill automático de até 10 anos para ativos novos
- Atualização incremental automática às 20h de Brasília, de segunda a sexta

## Rodar localmente

Requer Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Banco PostgreSQL

Defina a variável `DATABASE_URL` com uma conexão PostgreSQL, por exemplo:

```text
postgresql+psycopg://usuario:senha@host:5432/database?sslmode=require
```

As tabelas são criadas automaticamente na primeira conexão.

### Streamlit Community Cloud

Em **Manage app → Settings → Secrets**, adicione:

```toml
DATABASE_URL = "postgresql+psycopg://usuario:senha@host:5432/database?sslmode=require"
```

O app passará a ler os candles do PostgreSQL. Um ticker que ainda não exista no banco recebe backfill automático e passa a ser monitorado.

### GitHub Actions

Em **Repository → Settings → Secrets and variables → Actions**, crie um secret chamado `DATABASE_URL` com a mesma conexão.

O workflow `.github/workflows/update-market-data.yml` roda automaticamente às **20:00 de Brasília**, de segunda a sexta, e também pode ser disparado manualmente em **Actions → Atualizar dados B3 → Run workflow**.

Em feriados ou dias sem pregão, a fonte simplesmente continuará retornando o último pregão disponível; não é criada uma data fictícia no banco.

## Arquitetura de dados

- `market_prices`: OHLCV histórico por ticker/data
- `tracked_tickers`: ativos que devem ser atualizados diariamente
- `data_updates`: auditoria de cada rotina de atualização
- `update_market_data.py`: ingestão incremental
- `data_provider.py`: leitura do PostgreSQL e backfill controlado

O Yahoo Finance continua sendo a fonte externa de ingestão nesta versão. O banco próprio resolve persistência, velocidade, histórico e auditoria, mas não transforma o Yahoo em fonte oficial. A arquitetura permite trocar o fornecedor externo depois sem alterar o Strategy Builder.

## Deploy

No Streamlit Community Cloud use:

- Repository: `felippesenne/b3-screener`
- Branch: `main`
- Main file: `app.py`
