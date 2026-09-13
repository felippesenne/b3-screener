from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_provider import YahooFinanceProvider
from indicators import resample_ohlcv
from .engine import BacktestConfig
from .order_engine import run_order_backtest
from .setup_orders import SUPPORTED_SETUPS, compile_setup_orders
from .signals import compile_rules_signal, run_rules_backtest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="B3 backtest engine CLI")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", default="5y")
    parser.add_argument("--timeframe", choices=["Diário", "Semanal", "Mensal"], default="Diário")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--entry-rules", help="Arquivo JSON com lista de regras de entrada")
    mode.add_argument("--setup", choices=sorted(SUPPORTED_SETUPS), help="Setup clássico com gatilho por ordem")

    parser.add_argument("--exit-rules", help="Arquivo JSON com lista de regras de saída")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--position-size-pct", type=float, default=100.0, help="Percentual do caixa por operação")
    parser.add_argument("--commission-bps", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--stop-loss-pct", type=float, help="Stop percentual, ex.: 5 = 5%%")
    parser.add_argument("--take-profit-pct", type=float, help="Alvo percentual, ex.: 10 = 10%%")
    parser.add_argument("--tick-size", type=float, default=0.01, help="Incremento mínimo usado acima/abaixo do gatilho")
    parser.add_argument("--landry-valid-bars", type=int, default=1, help="Número de candles em que o gatilho Landry Simple permanece válido")
    parser.add_argument("--bowtie-transition-bars", type=int, default=4, help="Janela máxima para a virada das médias do Bow Tie")
    parser.add_argument("--same-bar-policy", choices=["conservative", "trigger_first"], default="conservative")
    parser.add_argument("--output-dir", help="Diretório para metrics.json, trades.csv, equity.csv e orders.csv")
    return parser


def _load_rules(path: str | None) -> list[dict] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"O arquivo {path} deve conter uma lista JSON de regras.")
    return data


def main(argv: list[str] | None = None, provider=None) -> int:
    args = build_parser().parse_args(argv)
    entry_rules = _load_rules(args.entry_rules)
    exit_rules = _load_rules(args.exit_rules)

    provider = provider or YahooFinanceProvider()
    raw = provider.get_history(args.ticker, period=args.period)
    df = resample_ohlcv(raw, args.timeframe)

    periods_per_year = {"Diário": 252, "Semanal": 52, "Mensal": 12}[args.timeframe]
    config = BacktestConfig(
        initial_capital=args.capital,
        position_size_pct=args.position_size_pct / 100.0,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        stop_loss_pct=(args.stop_loss_pct / 100.0) if args.stop_loss_pct is not None else None,
        take_profit_pct=(args.take_profit_pct / 100.0) if args.take_profit_pct is not None else None,
        periods_per_year=periods_per_year,
    )

    orders = None
    if args.setup:
        orders = compile_setup_orders(
            df,
            args.setup,
            tick_size=args.tick_size,
            landry_valid_bars=args.landry_valid_bars,
            bowtie_transition_bars=args.bowtie_transition_bars,
        )
        exit_signal = compile_rules_signal(df, exit_rules) if exit_rules else None
        result = run_order_backtest(
            df,
            orders=orders,
            exit_signal=exit_signal,
            config=config,
            same_bar_policy=args.same_bar_policy,
        )
        mode_name = "setup"
    else:
        result = run_rules_backtest(df, entry_rules=entry_rules or [], exit_rules=exit_rules, config=config)
        mode_name = "rules"

    payload = {
        "ticker": args.ticker,
        "period": args.period,
        "timeframe": args.timeframe,
        "bars": int(len(df)),
        "mode": mode_name,
        "setup": args.setup,
        "orders": int(len(orders)) if orders is not None else None,
        "metrics": result.metrics,
    }

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=True),
            encoding="utf-8",
        )
        result.trades.to_csv(output_dir / "trades.csv", index=False)
        result.equity_curve.to_csv(output_dir / "equity.csv")
        if orders is not None:
            orders.to_csv(output_dir / "orders.csv", index=False)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
