"""
test_bridge_order.py — End-to-end bridge test: open + close a 0.01 EURUSD trade.
Run from Linux: python3 test_bridge_order.py
"""

import hashlib
import hmac
import json
import time
import requests

BRIDGE_URL = "http://127.0.0.1:8001"
API_KEY    = "309612@Aaa.."


def signed_request(method: str, path: str, body: dict | None = None):
    timestamp  = str(int(time.time()))
    body_bytes = json.dumps(body).encode() if body else b""
    message    = (method.upper() + path + timestamp + body_bytes.decode()).encode()
    signature  = hmac.new(API_KEY.encode(), message, hashlib.sha256).hexdigest()
    headers = {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }
    url = BRIDGE_URL + path
    if method.upper() == "GET":
        return requests.get(url, headers=headers, timeout=10)
    return requests.post(url, headers=headers, data=body_bytes, timeout=10)


def check(label, resp, expected_status):
    ok = resp.status_code == expected_status
    status = "PASS ✅" if ok else f"FAIL ❌ (HTTP {resp.status_code})"
    print(f"\n[{label}] {status}")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)
    return ok, resp.json() if ok else None


# ── 1. Health check ────────────────────────────────────────────────────────────
resp = signed_request("GET", "/health")
ok, data = check("Health", resp, 200)
if not ok:
    raise SystemExit("Bridge not healthy — aborting.")

# ── 2. Get live price to calculate SL/TP ──────────────────────────────────────
resp = signed_request("GET", "/spread/EURUSD")
ok, spread = check("Spread", resp, 200)
if not ok:
    raise SystemExit("Could not fetch spread — aborting.")

ask = spread["ask"]
bid = spread["bid"]
sl  = round(bid - 0.0020, 5)   # 20 pip SL below bid
tp  = round(ask + 0.0030, 5)   # 30 pip TP above ask
print(f"\nUsing ask={ask} bid={bid} → SL={sl} TP={tp}")

# ── 3. Open order ──────────────────────────────────────────────────────────────
order_body = {
    "symbol":      "EURUSD",
    "direction":   "buy",
    "lot_size":    0.01,
    "stop_loss":   sl,
    "take_profit": tp,
    "comment":     "BridgeTest",
}
resp = signed_request("POST", "/order/open", order_body)
ok, opened = check("Open Order", resp, 201)
if not ok:
    raise SystemExit("Order open failed — aborting.")

ticket = opened["ticket"]
print(f"\nTicket: {ticket} — check MT5 terminal for the open trade.")

# ── 4. Close order ─────────────────────────────────────────────────────────────
input("\nPress Enter to close the order...")
resp = signed_request("POST", "/order/close", {"ticket": ticket})
ok, closed = check("Close Order", resp, 200)

# ── Summary ────────────────────────────────────────────────────────────────────
print("\n─── Summary ───────────────────────────────")
print(f"  Open trade:  {'PASS ✅' if opened else 'FAIL ❌'}")
print(f"  Close trade: {'PASS ✅' if closed else 'FAIL ❌'}")
