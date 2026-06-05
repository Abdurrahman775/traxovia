import MetaTrader5 as mt5

r = mt5.initialize(
    path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
    login=436208369,
    password="309612.Aa",
    server="Exness-MT5Trial9"
)
print("Init:", r, mt5.last_error())

symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]
for sym in symbols:
    sel = mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym)
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 5)
    print(f"{sym}: select={sel}, visible={info.visible if info else 'N/A'}, rates={len(rates) if rates is not None else None}, err={mt5.last_error()}")

mt5.shutdown()
