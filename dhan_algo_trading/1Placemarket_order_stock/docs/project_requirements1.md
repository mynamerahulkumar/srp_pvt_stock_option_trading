# HDFCBANK MARKET BUY CLI — as-built reference

This document describes the **current** Dhan equity CLI in `dhan_algo_trading/1Placemarket_order`. Copy it into another repo as a writing reference. It is not a build-from-scratch brief.

Portable broker helper: `Dhan_SRP.py` class `Dhansrp` **v2.9**. This bot still imports `Dhansrp` from `trading/dhan_client.py`.

---

## Purpose

CLI that places a **MARKET BUY** for **HDFCBANK** (default) on Dhan, then monitors software take-profit / stop-loss and shows a Rich sci-fi dashboard.

- Default symbol: HDFCBANK
- Order: MARKET BUY
- Product: CNC (configurable)
- Quantity: 1 (configurable)
- Poll: every 5 seconds (configurable)
- Risk: TP 2% / SL 1% of fill (configurable; absolute prices optional)
- UI: Rich `Live` dashboard (cyan/neon)

Other NSE equity names can be added under `instruments` in `config.yaml`. Do **not** hard-code security IDs in Python.

---

## Credentials (`.env` only)

Never put client ID or access token in YAML, Python, git, or logs.

| File | Role |
|------|------|
| `.env` | Live secrets. Not committed. |
| `.env.example` | Empty keys only: `DHAN_CLIENT_ID=`, `DHAN_ACCESS_TOKEN=` |

Required keys:

```
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

`main.py` and `start.py` call `utils.env.load_project_env()` before constructing a Dhan client. `Dhansrp._resolve_credentials()` (v2.9) also tries `python-dotenv` on a sibling `.env` and cwd `.env` if the package is installed. If dotenv is missing, constructor args / already-exported env / JSON `config.json` still work. Never log tokens.

---

## `config.yaml`

IDs live here, not in Python. Example HDFCBANK NSE equity ID is `"1333"`.

```yaml
trading:
  default_symbol: HDFCBANK
  live: true
  quantity: 1
  transaction_type: BUY
  order_type: MARKET
  product_type: CNC

  polling:
    interval_seconds: 5

  risk:
    take_profit_percent: 2.0
    stop_loss_percent: 1.0
    # Optional absolute prices (override percent mode when set):
    # take_profit_price: 2000.0
    # stop_loss_price: 1900.0

instruments:
  HDFCBANK:
    exchange_segment: NSE_EQ
    security_id: "1333"
    instrument_id: "1333"
```

`utils.config.load_config()` maps `trading.live` vs CLI `--dry-run`:

- `effective_dry_run = True` if `--dry-run`, else `not live`
- `live: true` and no `--dry-run` → live MARKET BUY
- `live: false` **or** `--dry-run` → simulate fills; still poll quotes

Placeholders such as `<SECURITY_ID>` are rejected.

---

## No security-master CSV (this equity flow)

This bot does **not** download or parse Dhan’s scrip-master CSV.

- `instruments.*.security_id` / `instrument_id` in YAML are the only IDs used for orders and quotes.
- `trading/dhan_client.py` subclasses `Dhansrp` as `ConfigDrivenDhansrp` and returns an empty DataFrame with `SEM_*` columns instead of fetching the master.
- v2.9 also supports `Dhansrp(..., skip_instrument_master=True)` for the same skip without subclassing. This bot can keep the subclass; both are valid.
- Equity MARKET orders that already have a YAML `security_id` must pass `security_id` + `lot_size=1` so `place_order()` does not look up lot size from CSV.

Option / F&O algos that need symbol resolution should leave `skip_instrument_master=False` (default).

---

## Process: `start.py` / `stop.py`

| Command | Behavior |
|---------|----------|
| `python start.py` | Loads `.env`, spawns `main.py`, writes `bot.pid`, stays in the foreground. |
| `python stop.py` | Reads `bot.pid`, sends **SIGINT**. Does **not** flatten / square the live position. |
| `python main.py` | Same session as start, without the PID wrapper. |

Flags on start/main: `--symbol`, `--config`, `--dry-run`.

SIGINT / Ctrl+C / `stop.py`:

- Stop monitoring and tear down the dashboard.
- **Do not** auto-close an open broker position.
- Dashboard prints that the existing broker position was not automatically closed.

---

## Live vs dry-run

| Mode | When | Entry |
|------|------|--------|
| Live | `trading.live: true` and no `--dry-run` | Places MARKET BUY **immediately** (no y/N prompt). |
| Dry-run | `live: false` or `--dry-run` | Simulates a fill using the last quote. Confirmation prompt is used in dry-run only. |

Live path in `DhanClient.place_market_order()` calls `self.broker.Dhan.place_order` with mapped SDK constants (`security_id`, segment, BUY/SELL, qty, MARKET, product, `price=0`, `trigger_price=0`). It does not go through CSV-backed lot-size lookup.

---

## Entry, TP/SL, and exits

1. **Entry price** = broker `averageTradedPrice` (fill), not the requested/quote price.
2. TP/SL are **software** levels from that fill (percent or optional absolute prices).
3. **One exit only.** After TP or SL fires, the session submits a single opposite MARKET order and will not place another exit while in the exit-guard states.
4. State machine (see `trading/models.py`): IDLE → ORDER_PENDING → ORDER_FILLED → POSITION_OPEN → TP/SL_TRIGGERED → EXIT_* → POSITION_CLOSED. Rejects and API failures go to ORDER_REJECTED / ERROR.
5. Ctrl+C / `stop.py` **does not** auto-close.

---

## Layout

```
1Placemarket_order/
  main.py                 # argparse, load .env, run TradingSession
  start.py / stop.py      # PID + SIGINT (stop does not flatten)
  config.yaml             # live flag, qty, product, poll, TP/SL, instrument IDs
  .env / .env.example     # DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
  Dhan_SRP.py             # portable broker helper v2.9
  srp_dhan_helper.md      # optional Dhansrp API notes
  requirements.txt
  trading/
    dhan_client.py        # DhanClient + ConfigDrivenDhansrp
    order_manager.py
    position_manager.py
    market_data.py
    risk_manager.py
    session.py
    models.py
  cli/
    dashboard.py          # Rich Live sci-fi UI
    styles.py
  utils/
    config.py
    env.py
    logging.py
    process.py
    compat.py             # Python 3.9 / dhanhq SyntaxError wrapper
  tests/                  # mocked Dhan; no live orders
  docs/project_requirements.md
```

---

## Python 3.9 and `dhanhq`

Pin **`dhanhq==2.0.2`**. dhanhq 2.2+ uses `match`/`case` and needs Python 3.10+. On 3.9 that import raises `SyntaxError`.

`utils/compat.py` wraps that as `DhanhqCompatError` and tells the operator to install `dhanhq==2.0.2` or upgrade the interpreter.

v2.9 `get_instrument_file()`: `dhanhq.fetch_security_list('compact')` raises `'str' object has no attribute 'COMPACT_CSV_URL'` on 2.0.2. Catch `TypeError` **and** `AttributeError`, then fall back to `https://images.dhan.co/api-data/api-scrip-master.csv` **only when not skipping** the master.

Other pins used here: pandas, numpy, requests, pytz, mibian, PyYAML, rich, pytest, python-dotenv.

---

## Quote snapshot

Call **`ticker_data({exchange_segment: [int(security_id)]})` only**.

Do **not** send empty lists for unused segments (NSE_EQ, NSE_FNO, …). Empty segment lists caused empty Dhan error dicts.

Fallbacks in this bot: `ohlc_data`, then `quote_data`, same single-segment payload. Keep the last good LTP if a poll fails so the CLI does not crash.

---

## Empty Dhan remarks

A failure like `{error_code: None, error_type: None, error_message: None}` usually means:

1. Expired or invalid access token
2. EC2 / server **static IP not whitelisted** on Dhan (often `DH-911`)
3. Missing Data API plan / market-hours / feed entitlement

Quotes can succeed while order placement fails. `format_dhan_error()` in `trading/dhan_client.py` maps empty remarks to a token / IP whitelist / data-plan message.

---

## Dashboard fields

Rich live panel shows: mode (LIVE / DRY-RUN), symbol, security_id, instrument_id, market price, entry (avg fill), quantity / position qty, P&L and %, TP price, SL price, distance to TP/SL, order status, position status, last update, next poll countdown, warnings. Temporary API errors are shown as warnings; the loop keeps polling.

---

## Do / do not

**Do**

- Keep credentials in `.env` only.
- Keep `security_id` / `instrument_id` in `config.yaml`.
- Pin `dhanhq==2.0.2` on Python 3.9.
- Quote with a single exchange-segment list.
- Treat fill `averageTradedPrice` as entry.
- Stop monitoring on SIGINT without flattening.

**Do not**

- Copy secrets into another repo, YAML, or logs.
- Hard-code HDFCBANK / `"1333"` (or any ID) in Python.
- Download the security-master CSV for this equity CLI.
- Send empty ticker segment lists.
- Auto-close positions on Ctrl+C / `stop.py`.
- Upgrade dhanhq past 2.0.2 while the host is Python 3.9.

---

## Copying into another repo

1. Copy `Dhan_SRP.py` (v2.9) as the broker helper.
2. Follow this file for CLI layout, `.env`, `live`, start/stop, and no-CSV equity IDs.
3. Optionally copy `srp_dhan_helper.md` for the full `Dhansrp` method surface (option chains, F&O helpers). That surface is not used by this HDFCBANK MARKET BUY path.
4. Point instruments at YAML IDs. Pass `skip_instrument_master=True` or subclass like `ConfigDrivenDhansrp`.
5. For equity MARKET: `security_id` from config + `lot_size=1`.
