# SRP Dhan Helper

Portable reference for using `Dhan_SRP.py` as a single broker/data layer in any algo repo.

**Module version:** 2.8  
**Class:** `Dhansrp`  
**Source file:** `Dhan_SRP.py`

---

## What This File Is For

Copy `Dhan_SRP.py` (and optionally this guide) into another repo and import `Dhansrp` from your algo scripts. Keep all Dhan login, instrument lookup, market data, validation, margin checks, and order placement inside this module. Your algo files should only contain signal logic, risk rules, and orchestration.

`Dhan_SRP.py` handles:

- Dhan login and SDK client setup
- Security master / instrument file loading and caching
- Symbol and derivative contract resolution
- Order preview, validation, and placement (`dry_run` supported)
- Stock and option order helpers
- Multi-leg and strategy helpers (straddle, strangle, iron condor)
- Margin checks
- Option-chain fetch and analysis
- Historical data and basic indicators
- Portfolio, funds, positions, and order book
- Forever orders, super orders, position conversion
- WebSocket market feed and order-update feed (SDK-dependent)

---

## Copy Into Another Repo

### Files to copy

| File | Required | Notes |
|------|----------|-------|
| `Dhan_SRP.py` | Yes | Single portable module |
| `srp_dhan_helper.md` | Optional | This reference |
| `security_id/api-scrip-master.csv` | Optional | Local cache; module can also fetch from Dhan |

### Suggested folder layout

```text
my_algo_repo/
  algos/
    breakout.py
    straddle.py
  broker/
    Dhan_SRP.py
    security_id/
      api-scrip-master.csv    # optional local instrument cache
  config/
    dhan_config.json          # credentials (do not commit)
  requirements.txt
```

Import pattern:

```python
from broker.Dhan_SRP import Dhansrp
```

If `Dhan_SRP.py` sits at the repo root:

```python
from Dhan_SRP import Dhansrp
```

### Dependencies

Minimum packages for `Dhan_SRP.py`:

```bash
pip install dhanhq pandas numpy requests pytz mibian
```

Recommended `requirements.txt` snippet:

```text
dhanhq
pandas
numpy
requests
pytz
mibian
```

If your installed `dhanhq` SDK exposes `DhanContext`, `MarketFeed`, and `OrderUpdate`, the advanced feed helpers will work. Older SDK versions still work for REST order and data calls.

### First-run checklist (new repo)

1. Copy `Dhan_SRP.py` into `broker/` (or repo root).
2. Install dependencies in a virtualenv.
3. Set credentials (env vars, JSON config, or constructor args).
4. Initialize with `dry_run=True` and confirm login succeeds.
5. Run one `resolve_symbol()` or `get_option_chain_snapshot()` call.
6. Run one `prepare_equity_limit_order()` or `place_stock_order(dry_run=True)`.
7. Only then switch to `dry_run=False` for live orders.

---

## Credentials

`Dhansrp` resolves credentials in this priority order:

1. Constructor args: `ClientCode`, `token_id`
2. Environment variables: `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`
3. Config file paths tried in order:
   - `config_path` argument
   - `self.config_path` from constructor
   - `DHAN_CONFIG_PATH` env var
   - `config.json` in the working directory

### Option 1 — Direct credentials

```python
from broker.Dhan_SRP import Dhansrp

dhan = Dhansrp(ClientCode="YOUR_CLIENT_ID", token_id="YOUR_ACCESS_TOKEN")
```

### Option 2 — Environment variables

```bash
export DHAN_CLIENT_ID="YOUR_CLIENT_ID"
export DHAN_ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
```

```python
from broker.Dhan_SRP import Dhansrp

dhan = Dhansrp()
```

### Option 3 — JSON config file

`Dhan_SRP.py` reads **JSON only** (not YAML). Top-level keys:

```json
{
  "client_id": "YOUR_CLIENT_ID",
  "access_token": "YOUR_ACCESS_TOKEN"
}
```

Alternate key names also work: `ClientCode`, `token_id`.

```python
dhan = Dhansrp(config_path="config/dhan_config.json")
```

If your main app uses YAML (e.g. `config/config.yaml`), either:

- export `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` from your loader, or
- pass `ClientCode` and `token_id` from your YAML loader into `Dhansrp(...)`.

---

## Constructor

```python
Dhansrp(
    ClientCode: str = None,
    token_id: str = None,
    config_path: str = None,
    enable_file_logging: bool = False,
    instrument_cache_path: str = None,
    persist_instrument_file: bool = False,
)
```

| Parameter | Purpose |
|-----------|---------|
| `ClientCode` / `token_id` | Direct Dhan credentials |
| `config_path` | Path to JSON credentials file |
| `enable_file_logging` | Write logs under `Dependencies/log_files/` next to `Dhan_SRP.py` |
| `instrument_cache_path` | Use a fixed CSV path for the security master (avoids re-download) |
| `persist_instrument_file` | Save downloaded master to `Dependencies/all_instrument.csv` |

### Recommended init for portable algos

```python
from pathlib import Path
from broker.Dhan_SRP import Dhansrp

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "broker" / "security_id" / "api-scrip-master.csv"

dhan = Dhansrp(
    config_path=str(ROOT / "config" / "dhan_config.json"),
    enable_file_logging=False,
    instrument_cache_path=str(MASTER) if MASTER.exists() else None,
    persist_instrument_file=False,
)
```

On first login, if no cache path is set, the module fetches the security master from Dhan (or `dhanhq.fetch_security_list()` when available).

---

## Algo Architecture Pattern

Use `Dhan_SRP.py` only as the broker/data layer.

Your algo should:

1. Initialize `Dhansrp`
2. Fetch market inputs
3. Run signal logic
4. Build or validate orders
5. Place orders only when conditions pass

```python
from broker.Dhan_SRP import Dhansrp


def run_algo():
    dhan = Dhansrp(config_path="config/dhan_config.json")

    snapshot = dhan.get_option_chain_snapshot(underlying="NIFTY")
    spot = snapshot["spot"]

    if spot > 25000:
        return dhan.place_long_call(underlying="NIFTY", dry_run=True)

    return {"status": "no_trade"}


if __name__ == "__main__":
    print(run_algo())
```

**Keep in `Dhan_SRP.py`:** login, data, contract resolution, margin, orders, portfolio.  
**Keep in your algo:** entry/exit rules, time filters, SL/target, daily risk limits, re-entry logic.

---

## Security ID Lookup — Important

There are **two different** lookup methods. Use the right one.

### `resolve_symbol()` — any NSE/BSE equity from security master

Preferred for general stock algos. Searches the full instrument DataFrame.

```python
resolved = dhan.resolve_symbol("HDFCBANK", exchange_segment="NSE_EQ", instrument_name="EQUITY")
# {
#   "security_id": "1333",
#   "trading_symbol": "HDFCBANK",
#   "display_name": "...",
#   "exchange_segment": "NSE_EQ",
#   "instrument_name": "EQUITY"
# }
```

Returns `None` if not found.

### `get_security_id_by_symbol()` — static NIFTY 50 map only

Fast lookup for ~50 pre-mapped NSE symbols (`NIFTY50_SECURITY_IDS` at top of `Dhan_SRP.py`).  
Raises `ValueError` if the symbol is not in the map.

```python
security_id = dhan.get_security_id_by_symbol("RELIANCE")  # 2885
security_id = dhan.get_security_id_by_symbol("HDFCBANK")  # 1333
```

For stocks outside NIFTY 50, use `resolve_symbol()` or pass `security_id` directly to `place_order()`.

### `resolve_derivative()` — options and futures

```python
contract = dhan.resolve_derivative(
    underlying="NIFTY",
    instrument_names=("OPTIDX", "OPTSTK"),
    strike=25000,
    option_type="CE",
    expiry="2026-07-30",
    exchange="NSE",
)
# security_id, trading_symbol, lot_size, tick_size, expiry, instrument_name
```

### Index `under_security_id` for option-chain APIs

Most helpers default to **NIFTY = 13**. For other indices, pass `under_security_id` explicitly.

Common Dhan index IDs (verify once in your environment):

| Underlying | Typical `under_security_id` |
|------------|----------------------------|
| NIFTY | 13 |
| BANKNIFTY | 25 |
| FINNIFTY | 27 |
| MIDCPNIFTY | 442 |

To resolve dynamically from the security master, use the legacy helper:

```python
expiries = dhan.get_expiry_list("BANKNIFTY", "INDEX")
```

Pass `under_security_id` when calling `get_option_chain_snapshot`, `fetch_option_chain_df`, `get_atm_option_pair`, etc.

---

## Order Flow And Response Shape

### Low-level: `place_order()`

Universal order method. Resolves symbol if needed, validates, previews, then places (unless `dry_run=True`).

```python
result = dhan.place_order(
    symbol="HDFCBANK",           # or security_id="1333"
    exchange_segment="NSE_EQ",
    transaction_type="BUY",
    quantity=10,
    order_type="LIMIT",
    product_type="INTRADAY",
    price=1800.0,
    dry_run=True,
)
```

**Return structure:**

```python
{
    "status": "validation",       # dry_run success
    # "status": "failure",        # validation errors
    # response key present only on live placement
    "instrument": {...},
    "preview": "--- ORDER PREVIEW ---\n...",
    "validation": {
        "valid": True,
        "errors": [],
        "warnings": [],
    },
    "response": {...},            # only when dry_run=False and valid
}
```

### Validation rules (`validate_order_payload`)

- Required: `security_id`, `exchange_segment`, `transaction_type`, `quantity`, `order_type`, `product_type`
- Valid segments: `NSE_EQ`, `BSE_EQ`, `NSE_FNO`, `BSE_FNO`, `MCX_COMM`, `NSE_CURRENCY`, `BSE_CURRENCY`
- Equity products: `CNC`, `INTRADAY`, `MARGIN`, `MTF`
- Derivative products: `INTRADAY`, `MARGIN` only (not `CNC`/`MTF`)
- F&O quantity must be a multiple of lot size
- `LIMIT` / `STOP_LOSS` require `price > 0`
- Warns when notional > Rs. 50,000

### Safe workflow

1. Resolve contract or symbol
2. Call `prepare_equity_limit_order()` or build order dict
3. Check `validation["valid"]` and `validation["warnings"]`
4. Run `check_margin_for_orders()` for baskets
5. Place with `dry_run=True`
6. Switch to `dry_run=False` only after review

---

## Core Usage Examples

### 1. Preview equity limit order

```python
preview = dhan.prepare_equity_limit_order(
    symbol="HDFCBANK",
    price=1800.0,
    quantity=10,
    transaction_type="BUY",
    product_type="INTRADAY",
    exchange_segment="NSE_EQ",
)
print(preview["preview"])
print(preview["validation"])
```

### 2. Place stock order

```python
result = dhan.place_stock_order(
    symbol="HDFCBANK",
    quantity=10,
    transaction_type="BUY",
    order_type="LIMIT",
    product_type="INTRADAY",
    price=1800.0,
    dry_run=True,
)
```

`place_stock_order` is a thin wrapper over `place_order` with `instrument_name="EQUITY"`.

### 3. Place option order

```python
result = dhan.place_option_order(
    underlying="NIFTY",
    expiry="2026-07-30",
    strike=25000,
    option_type="CE",
    transaction_type="BUY",
    product_type="INTRADAY",
    order_type="LIMIT",
    price=120.0,
    dry_run=True,
)
```

Quantity defaults to contract lot size from the security master.

### 4. Modify / cancel

```python
dhan.modify_order_request(
    order_id="YOUR_ORDER_ID",
    order_type="LIMIT",
    quantity=10,
    price=1801.0,
)

dhan.cancel_order_request(order_id="YOUR_ORDER_ID")
```

### 5. Order and trade queries

```python
dhan.get_order_list_v2()
dhan.get_order_by_id_v2("ORDER_ID")
dhan.get_trade_book_v2()
dhan.get_orderbook()
dhan.get_trade_book()
dhan.cancel_all_orders()
```

---

## Options Strategy Helpers

### ATM pair

```python
atm = dhan.get_atm_option_pair(underlying="NIFTY")
# spot, strike, call_security_id, put_security_id, call_price, put_price, lot_size, expiry
```

### Single leg

```python
dhan.place_long_call(underlying="NIFTY", strike=25000, dry_run=True)
dhan.place_long_put(underlying="NIFTY", strike=25000, dry_run=True)
```

### Call + put pair (straddle-style)

```python
pair = dhan.buy_call_put_pair(underlying="NIFTY", dry_run=True)

pair = dhan.buy_call_put_pair(
    underlying="NIFTY",
    call_strike=25000,
    put_strike=25000,
    dry_run=True,
)
```

### Straddle / strangle

```python
dhan.place_atm_straddle(underlying="NIFTY", dry_run=True)

dhan.place_strangle(
    underlying="NIFTY",
    call_offset=2,
    put_offset=2,
    dry_run=True,
)
```

### Iron condor

```python
analysis = dhan.analyze_iron_condor(underlying="NIFTY")
execution = dhan.place_iron_condor(underlying="NIFTY", dry_run=True)
orders = dhan.build_iron_condor_orders(underlying="NIFTY")
```

---

## Multi-Leg / Basket Orders

Build leg dicts yourself, check margin, then execute:

```python
reliance = dhan.resolve_symbol("RELIANCE")
infy = dhan.resolve_symbol("INFY")

orders = [
    {
        "security_id": reliance["security_id"],
        "symbol": "RELIANCE",
        "exchange_segment": "NSE_EQ",
        "transaction_type": "BUY",
        "quantity": 1,
        "order_type": "LIMIT",
        "product_type": "CNC",
        "price": 2880.0,
        "instrument_name": "EQUITY",
    },
    {
        "security_id": infy["security_id"],
        "symbol": "INFY",
        "exchange_segment": "NSE_EQ",
        "transaction_type": "BUY",
        "quantity": 1,
        "order_type": "LIMIT",
        "product_type": "CNC",
        "price": 1500.0,
        "instrument_name": "EQUITY",
    },
]

margin = dhan.check_margin_for_orders(orders)
# total_margin, available_balance, sufficient, shortfall

result = dhan.place_multi_leg_orders(orders, dry_run=True)
```

Each leg in `place_multi_leg_orders` accepts the same fields as `place_order`.

---

## Market Data

### Option chain snapshot

```python
snapshot = dhan.get_option_chain_snapshot(underlying="NIFTY")
print(snapshot["spot"])
print(snapshot["atm_strike"])
print(snapshot["chain"])  # DataFrame: strike, ce_ltp, pe_ltp, OI, IV, ...
```

### Full option-chain DataFrame

```python
expiries = dhan.get_expiry_dates(13)  # NIFTY
chain_df, spot = dhan.fetch_option_chain_df(
    under_security_id=13,
    expiry=expiries[0],
)
atm_row = dhan.find_atm_row(chain_df, spot)
```

### LTP and quotes

```python
dhan.get_ltp_data(["NIFTY", "RELIANCE"])
dhan.get_quote(["NIFTY", "HDFCBANK"])
```

### Historical data

```python
resolved = dhan.resolve_symbol("RELIANCE")

history = dhan.get_history_df(
    security_id=resolved["security_id"],
    exchange_segment="NSE_EQ",
    instrument_type="EQUITY",
    from_date="2026-01-01",
    to_date="2026-07-01",
    interval="daily",
)
history = dhan.add_basic_indicators(history)  # SMA 20/50
```

Legacy helpers (symbol + exchange string style) also exist: `get_historical_data`, `get_intraday_data`, `resample_timeframe`.

### Option Greeks

```python
dhan.get_option_greek(strike=25000, expiry=..., asset="NIFTY", interest_rate=6.5, flag="c", scrip_type="idx")
```

---

## Portfolio And Funds

```python
summary = dhan.get_portfolio_summary()
# summary, funds, positions, holdings

dhan.get_balance()
dhan.get_holdings()
dhan.get_positions()
dhan.get_live_pnl()
dhan.margin_calculator(tradingsymbol, exchange, transaction_type, quantity, trade_type, price)
dhan.check_margin_requirement(security_id, exchange_segment, transaction_type, quantity, product_type, price)
```

---

## Advanced Order Types

| Method | Purpose |
|--------|---------|
| `place_forever_order()` | GTT-style forever order |
| `get_forever_orders()` | List forever orders |
| `cancel_forever_order(order_id)` | Cancel forever order |
| `place_super_order()` | Super order with target/SL |
| `modify_super_order()` | Modify super order |
| `cancel_super_order()` | Cancel super order |
| `get_super_orders()` | List super orders |
| `convert_position()` | Convert position product type |
| `place_slice_order()` | Slice large orders |
| `kill_switch()` | Emergency kill switch |

---

## WebSocket Feeds (SDK-dependent)

```python
feed = dhan.create_market_feed(
    instruments=[...],
    on_message=lambda msg: print(msg),
)
feed.run()

order_feed = dhan.create_order_update_feed(on_update=lambda u: print(u))
```

Requires `DhanContext` and `MarketFeed` / `OrderUpdate` from a recent `dhanhq` install.

---

## Complete Method Index

### Auth and instruments

| Method | Description |
|--------|-------------|
| `get_login()` | Internal; called from `__init__` |
| `get_instrument_file()` | Load or download security master |
| `get_security_master(refresh=False)` | Return instrument DataFrame |
| `resolve_symbol()` | Equity lookup from master |
| `get_security_id_by_symbol()` | NIFTY 50 static map only |
| `resolve_derivative()` | Option/future contract lookup |
| `get_lot_size_from_master()` | Lot size by security_id / symbol / underlying |

### Orders

| Method | Description |
|--------|-------------|
| `place_order()` | Generic order with validation + dry_run |
| `place_stock_order()` | Equity shortcut |
| `place_option_order()` | Option by underlying/expiry/strike |
| `prepare_equity_limit_order()` | Preview + validate equity limit |
| `preview_order()` | Human-readable order preview |
| `validate_order_payload()` | Validation dict |
| `modify_order_request()` | Modify open order |
| `cancel_order_request()` | Cancel order |
| `place_multi_leg_orders()` | Sequential multi-leg execution |
| `check_margin_for_orders()` | Basket margin summary |

### Options strategies

| Method | Description |
|--------|-------------|
| `get_expiry_dates()` | Expiry list for index |
| `fetch_option_chain_df()` | Normalized chain DataFrame |
| `get_option_chain_snapshot()` | Spot + ATM + nearby strikes |
| `get_atm_option_pair()` | ATM CE/PE security IDs and LTPs |
| `place_long_call()` / `place_long_put()` | Single-leg long options |
| `buy_call_put_pair()` | CE + PE pair |
| `place_atm_straddle()` | ATM straddle |
| `place_strangle()` | OTM strangle |
| `analyze_iron_condor()` | Iron condor payoff analysis |
| `build_iron_condor_orders()` | Leg dicts for iron condor |
| `place_iron_condor()` | Execute iron condor |
| `build_option_legs()` | Build legs from chain + config |
| `option_payoff()` | Payoff array for spot range |

### Market data (legacy + new)

| Method | Description |
|--------|-------------|
| `get_ltp_data()` | Last traded price |
| `get_quote()` | Quote data |
| `get_history_df()` | Historical OHLCV DataFrame |
| `add_basic_indicators()` | SMA columns |
| `get_historical_data()` | Legacy historical |
| `get_intraday_data()` | Legacy intraday |
| `get_option_chain()` | Legacy option chain |
| `heikin_ashi()` / `renko_bricks()` | Chart transforms |

### Portfolio

| Method | Description |
|--------|-------------|
| `get_portfolio_summary()` | Combined summary |
| `get_balance()` | Fund limits |
| `get_holdings()` | Holdings |
| `get_positions()` | Positions |
| `get_live_pnl()` | Live PnL |
| `order_report()` | Order report tuple |

---

## Example: Stock Algo In Another Repo

```python
from broker.Dhan_SRP import Dhansrp


def run_hdfcbank_intraday():
    dhan = Dhansrp(config_path="config/dhan_config.json")

    resolved = dhan.resolve_symbol("HDFCBANK")
    preview = dhan.prepare_equity_limit_order(
        symbol="HDFCBANK",
        price=1800.0,
        quantity=10,
        transaction_type="BUY",
        product_type="INTRADAY",
    )

    if not preview["validation"]["valid"]:
        return preview

    return dhan.place_stock_order(
        symbol="HDFCBANK",
        quantity=10,
        transaction_type="BUY",
        order_type="LIMIT",
        product_type="INTRADAY",
        price=1800.0,
        dry_run=True,
    )
```

## Example: Options Algo In Another Repo

```python
from broker.Dhan_SRP import Dhansrp


def run_nifty_straddle():
    dhan = Dhansrp(config_path="config/dhan_config.json")

    margin_check = dhan.get_atm_option_pair(underlying="NIFTY")
    print(f"ATM strike: {margin_check['strike']}, lot: {margin_check['lot_size']}")

    return dhan.place_atm_straddle(underlying="NIFTY", dry_run=True)
```

## Example: Pass credentials from your own config loader

```python
import yaml
from broker.Dhan_SRP import Dhansrp


def load_dhan_from_yaml(path: str) -> Dhansrp:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    dhan_cfg = cfg["dhan"]
    return Dhansrp(
        ClientCode=dhan_cfg["client_id"],
        token_id=dhan_cfg["access_token"],
        enable_file_logging=False,
    )
```

---

## Practical Notes

- **Always start with `dry_run=True`** in new algos.
- **Live orders** require Dhan static IP whitelisting on your server/VPS.
- **Market data and option chain** require an active Dhan data plan.
- **F&O:** confirm lot size and margin before live placement; quantity must be in lots.
- **Product types:** never use `CNC` or `MTF` for F&O segments.
- **Config:** `Dhan_SRP.py` reads JSON credentials natively; bridge from YAML in your app if needed.
- **Instrument file:** first init may download a large CSV; use `instrument_cache_path` in production algos to avoid repeated downloads.
- **Imports:** after copying to a new repo, verify `dhanhq` SDK version once in that environment.
- **Do not commit** `dhan_config.json` or access tokens to git.

---

## Syncing Updates From This Repo

When `Dhan_SRP.py` is updated here (currently v2.8), copy the new file into your algo repos and re-run:

1. Login test
2. One equity `resolve_symbol` + `dry_run` order
3. One option-chain call (if your algo uses F&O)

---

## Bottom Line

Treat `Dhan_SRP.py` as your portable Dhan broker adapter.

For any new repo: copy the file, initialize `Dhansrp`, keep signal logic in separate algo modules, and call this module for data, validation, margin, and execution. Use `resolve_symbol()` for general stocks, `get_security_id_by_symbol()` only for the built-in NIFTY 50 map, and `dry_run=True` until you are ready for live trading.
