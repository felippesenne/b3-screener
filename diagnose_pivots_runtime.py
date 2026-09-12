from data_provider import YahooFinanceProvider
from scanner import scan_universe
from universes import IBOVESPA


def rules_for(op):
    return [{"left": {"kind": "PRICE", "field": "Close"}, "operator": op}]


def run(op, timeframe="Diário", period="2y"):
    provider = YahooFinanceProvider()
    result, errors = scan_universe(
        IBOVESPA,
        provider,
        timeframe,
        period,
        rules_for(op),
        context_filters=[],
    )
    print("\n===", op, timeframe, period, "===")
    print("analisados:", len(result), "erros:", len(errors))
    if result.empty:
        print("RESULTADO VAZIO")
        return
    print("selecionados:", int(result["Passou"].sum()))
    cols = [c for c in ["Ticker", "Passou", "Status setup", "Entrada / gatilho", "Stop", "Detalhes"] if c in result.columns]
    print(result[cols].head(30).to_string(index=False))
    print("\nSTATUS MAIS COMUNS:")
    if "Status setup" in result.columns:
        print(result["Status setup"].fillna("<sem status>").value_counts().head(20).to_string())
    if errors:
        print("\nERROS:")
        for ticker, msg in list(errors.items())[:20]:
            print(ticker, msg)


if __name__ == "__main__":
    for op in ["simple_pivot_buy", "simple_pivot_sell"]:
        for tf in ["Diário", "Semanal", "Mensal"]:
            run(op, timeframe=tf, period="2y")
