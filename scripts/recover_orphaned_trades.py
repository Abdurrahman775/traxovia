"""
One-time script: finds MT5 positions with comment='PAPER' that are NOT yet
in the trades table and inserts them so the monitor can track them properly.
Run once from C:\traxovia:
  python scripts/recover_orphaned_trades.py
"""
import asyncio
import sys
import os
import uuid

sys.path.insert(0, r"C:\traxovia")
os.chdir(r"C:\traxovia")

from dotenv import load_dotenv
load_dotenv(os.path.join(r"C:\traxovia", ".env"))

import MetaTrader5 as mt5
import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql://")
USER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "paper-demo-106464235"))


async def main():
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}")
        return

    positions = mt5.positions_get()
    if not positions:
        print("No open MT5 positions found.")
        mt5.shutdown()
        return

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        for pos in positions:
            if pos.comment != "PAPER":
                continue

            existing = await conn.fetchval(
                "SELECT id FROM trades WHERE mt5_ticket=$1", pos.ticket
            )
            if existing:
                print(f"  ticket={pos.ticket} {pos.symbol} already in DB — skip")
                continue

            direction = "buy" if pos.type == 0 else "sell"
            await conn.execute(
                """INSERT INTO trades
                   (user_id, mt5_ticket, pair, direction, lot_size,
                    entry_price, stop_loss, take_profit, status, is_paper, entry_time)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'open',TRUE,to_timestamp($9))
                   ON CONFLICT DO NOTHING""",
                USER_ID,
                pos.ticket,
                pos.symbol,
                direction,
                pos.volume,
                pos.price_open,
                pos.sl,
                pos.tp,
                pos.time,
            )
            print(f"  RECOVERED ticket={pos.ticket} {pos.symbol} {direction} lot={pos.volume}")
    finally:
        await conn.close()
        mt5.shutdown()

    print("Done.")

asyncio.run(main())
