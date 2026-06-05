import MetaTrader5 as mt5

print("MT5 version:", mt5.__version__)

r = mt5.initialize(
    path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
    login=436208369,
    password="309612.Aa",
    server="Exness-MT5Trial9"
)
print("Result:", r, "| Error:", mt5.last_error())
if r:
    info = mt5.account_info()
    print("Account:", info.login, "| Balance:", info.balance, "| Server:", info.server)
    mt5.shutdown()
