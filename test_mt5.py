import MetaTrader5 as mt5

print("MT5 version:", mt5.__version__)

# Try 1: connect to already-running terminal (no credentials)
print("\nTry 1: initialize() with no args...")
r = mt5.initialize()
print("Result:", r, "| Error:", mt5.last_error())
if r:
    print("Account:", mt5.account_info())
    mt5.shutdown()
else:
    mt5.shutdown()

    # Try 2: explicit path, no credentials
    print("\nTry 2: initialize() with path only...")
    r = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    print("Result:", r, "| Error:", mt5.last_error())
    if r:
        print("Account:", mt5.account_info())
    mt5.shutdown()
