Drop MT5-exported CSV files here. Name them:

  EURUSD_M15.csv
  EURUSD_M30.csv
  EURUSD_H1.csv
  EURUSD_H4.csv
  GBPUSD_M15.csv
  GBPUSD_M30.csv
  GBPUSD_H1.csv
  GBPUSD_H4.csv
  USDJPY_M15.csv  ... etc.

Supported timeframes : M15  M30  H1  H4  W1
Supported pairs      : EURUSD  GBPUSD  USDJPY  AUDUSD  XAUUSD

MT5 export columns recognised automatically:
  <DATE>  <TIME>  <OPEN>  <HIGH>  <LOW>  <CLOSE>  <TICKVOL>  <SPREAD>

Then run from the project root:
  python -m data_engine.csv_loader

Or to also trigger model retraining:
  python -m data_engine.csv_loader --retrain
