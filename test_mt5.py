import MetaTrader5 as mt5

r = mt5.initialize(
    path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
    login=436208369,
    password="309612.Aa",
    server="Exness-MT5Trial9"
)
print("Init:", r, mt5.last_error())

# Find all symbols matching our pairs
targets = ["EUR", "GBP", "JPY", "XAU", "AUD"]
all_symbols = mt5.symbols_get()
if all_symbols:
    for s in all_symbols:
        if any(t in s.name for t in targets):
            print(s.name)
else:
    print("No symbols returned:", mt5.last_error())

mt5.shutdown()
