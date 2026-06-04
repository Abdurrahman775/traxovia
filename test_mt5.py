import MetaTrader5 as mt5

path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
r = mt5.initialize(path=path)
print("Result:", r)
print("Error:", mt5.last_error())
mt5.shutdown()
