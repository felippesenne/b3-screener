# B3 Screener — Streamlit

MVP de screener técnico para ações da B3.

## Recursos

- Universo de tickers editável
- Timeframes diário, semanal e mensal
- IFR(2)
- MME 9, 50, 80 e 200
- Inclinação das MMEs
- Filtro preço > MME200
- Preset IFR2 < 25 + MME50 ascendente
- Preset MME9 / MME80
- Exportação CSV
- Arquitetura preparada para trocar a fonte de dados

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

Use este repositório, branch `main`, com `app.py` como arquivo principal.

O Streamlit instalará automaticamente as dependências listadas em `requirements.txt`.

## Fonte de dados

O MVP usa `yfinance` / Yahoo Finance.

Isso é adequado para prototipação e estudos, mas não deve ser considerado uma fonte oficial da B3, nem uma infraestrutura de produção com garantia de disponibilidade.

A classe `MarketDataProvider` em `data_provider.py` permite trocar o Yahoo por outro fornecedor sem alterar a lógica principal do scanner.

## Próximas versões sugeridas

1. Universo automático do Ibovespa / B3
2. Banco PostgreSQL
3. Cache de cotações
4. Histórico de sinais
5. Gráficos por ativo
6. Backtest
7. Scanner agendado
8. Alertas por e-mail
9. Login
10. Deploy em produção com fonte de dados profissional
