from data_provider import YahooFinanceProvider
from scanner import scan_universe
from universes import FAVORITE_23


def rules_for(op):
    return [{"left": {"kind": "PRICE", "field": "Close"}, "operator": op}]


def run(op):
    provider = YahooFinanceProvider()
    result, errors = scan_universe(
        FAVORITE_23,
        provider,
        "Diário",
        "2y",
        rules_for(op),
        context_filters=[],
    )
    print("\n===", op, "Diário 2y / FAVORITE_23", "===")
    print("analisados:", len(result), "erros:", len(errors))
    if result.empty:
        print("RESULTADO VAZIO")
        return
    print("selecionados:", int(result["Passou"].sum()))
    cols = [c for c in ["Ticker", "Passou", "Status setup", "Entrada / gatilho", "Stop", "Detalhes"] if c in result.columns]
    print(result[cols].to_string(index=False))
    if errors:
        print("\nERROS:")
        for ticker, msg in errors.items():
            print(ticker, msg)


if __name__ == "__main__":
    run("simple_pivot_buy")
    run("simple_pivot_sell")
