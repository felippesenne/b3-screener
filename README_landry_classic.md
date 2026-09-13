# Dave Landry — Simple Pullback Clássico (Backtesting Lab)

Modelo determinístico usado pelo backtester para tornar reproduzível uma metodologia que, na gestão do runner, possui componente discricionário.

## Formação

- Compra: tendência de alta confirmada por MME20 > MME50, ambas ascendentes, com o candle anterior ao pullback marcando nova máxima na janela configurada.
- Venda: lógica inversa.
- Pullback clássico: por padrão, 3 a 7 máximas descendentes na compra ou 3 a 7 mínimas ascendentes na venda.
- A partir da 3ª barra do pullback, o gatilho é recalculado diariamente acima da máxima anterior (compra) ou abaixo da mínima anterior (venda).
- Stop técnico no extremo acumulado do pullback.
- Se a invalidação ocorrer antes do gatilho numa barra ambígua de OHLC, a política conservadora cancela a entrada.

## Gestão após entrada

- R = distância entre entrada e stop técnico inicial.
- Realização de 50% da posição em 1R.
- Stop do restante movido para breakeven.
- Depois, trailing stop usando por padrão as 2 barras anteriores já encerradas.
- O trailing de 2 barras é uma convenção mecânica explícita do backtest, não uma regra textual rígida atribuída a Dave Landry.

## Presets

O Backtesting Lab mantém os dois modelos separados:

- `Dave Landry — Simple Pullback Clássico`: versão mais fiel à estrutura tendência → pullback → retomada.
- `Dave Landry Simple (simplificado)`: detector curto legado, mantido para comparação histórica.
