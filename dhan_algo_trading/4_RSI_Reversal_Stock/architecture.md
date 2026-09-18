# RSI Reversal Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity on completed candles using Wilder's RSI reversal. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the mathematics, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Parameter tuning, backtesting, and paper trading exist to improve robustness and risk-adjusted behaviour. They do not make live results certain.

---

## 1. Introduction

The program watches one configured stock, computes Wilder's RSI on **completed** candles, and looks for RSI to leave an oversold or overbought zone. After optional candle confirmation and a full risk check, it places at most one position at a time. Software-polled take-profit and stop-loss (or session end) close that position. Take-profit and stop-loss are **terminal** for the current process: the bot exits instead of hunting for a second trade.

The design constraints are deliberate:

- Python 3.10+, local laptop or AWS Linux with about 1 GB RAM
- No database, Redis, Docker, web server, or multiprocessing
- All runtime logic in `main.py`
- Secrets in `.env`, tunables in `config.yaml`
- Graceful stop via `stop.py`, Ctrl+C, or SIGTERM

---

## 2. Strategy Objective

Identify a short-term exhaustion of selling (oversold) or buying (overbought) and trade the **reversal**, not the extreme itself.

Default objective for a day-trading session:

1. Wait until the session starts.
2. Wait for a new completed candle.
3. If RSI crosses back above oversold (and a bullish candle confirms), go LONG.
4. If RSI crosses back below overbought (and a bearish candle confirms), go SHORT.
5. Manage the open position with TP/SL.
6. After TP, SL, or session flatten, stop the process.

Default `max_trades_per_day` is 1. That is a risk choice, not a claim that one trade per day is optimal.

---

## 3. What Is RSI?

The Relative Strength Index, introduced by J. Welles Wilder Jr. (1978), measures the speed and magnitude of recent directional price changes. It is bounded between 0 and 100.

- High RSI means recent closes have been dominated by gains.
- Low RSI means recent closes have been dominated by losses.

RSI does **not** measure valuation, volume, or trend regime. An oversold reading can persist in a strong downtrend. That is why this bot does not buy “RSI is 28” by itself; it waits for RSI to cross back through the threshold.

---

## 4. RSI Formula

After average gain and average loss are known:

```text
RS  = Average Gain / Average Loss
RSI = 100 - (100 / (1 + RS))
```

Special cases implemented in `_rsi_from_averages()`:

- Average gain and average loss both 0 → RSI = 50 (no movement)
- Average loss is 0 → RSI = 100 (only gains)
- Average gain is 0 → RSI = 0 (only losses)

---

## 5. Wilder's RSI Calculation

Wilder does **not** use a simple moving average of all gains on every bar after the seed. He seeds with a simple mean of the first `period` gains/losses, then smooths:

```text
avg_gain = (prev_avg_gain * (period - 1) + current_gain) / period
avg_loss = (prev_avg_loss * (period - 1) + current_loss) / period
```

Implementation: `calculate_rsi(closes, period)` in `main.py`.

- Change[i] = close[i] − close[i−1]
- Gain = max(change, 0), Loss = max(−change, 0)
- First RSI appears at index `period` (the `period + 1`th close)
- Earlier slots are `None` (warmup)

This matches common charting platforms more closely than a fresh SMA of gains on every bar.

---

## 6. RSI Period

Configured as `strategy.rsi_period` (default 14).

| Period | Typical behaviour |
|--------|-------------------|
| Lower (for example 7) | Faster, more crosses, more noise, more false reversals |
| 14 | Wilder's original default; used unless you have evidence otherwise |
| Higher (for example 21) | Smoother, fewer signals, slower, may miss short reversals |

There is no universally best period. Changing it changes signal frequency; it does not guarantee a better win rate.

---

## 7. Oversold and Overbought Levels

Configured as `strategy.oversold` (default 30) and `strategy.overbought` (default 70). Validation rejects `oversold >= overbought`.

- **Oversold:** RSI has been dominated by losses. A LONG setup may be forming.
- **Overbought:** RSI has been dominated by gains. A SHORT setup may be forming.

`20 / 80` is more extreme than `30 / 70`: fewer signals, often after larger moves. Neither pair is “more profitable” in general. Tighter bands increase activity and false breaks; wider bands reduce activity and can miss mean reversion that never reaches 20 or 80.

---

## 8. RSI Reversal Concept

An extreme RSI value is a **condition**, not a **trigger**.

Example (LONG):

```text
Previous RSI = 28  (still at or below 30)
Current RSI  = 32  (now above 30)
```

Selling pressure, as measured by RSI, has started to ease. That is the reversal this strategy trades.

If `use_reversal_confirmation` is `false`, the bot instead signals while RSI is still inside the zone (current RSI ≤ oversold for LONG). That is more aggressive and catches falling knives more often. The default is `true`.

---

## 9. Long Entry Rules

Default LONG (`generate_signal()` + `confirm_reversal(..., "LONG")`):

```text
Previous RSI <= oversold
AND
Current RSI  >  oversold
AND
optional bullish candle (close > open)
AND
validate_trade() allows the order
```

`generate_signal()` never calls Dhan. Orders happen only after `validate_trade()` in `process_new_candle()`.

---

## 10. Short Entry Rules

Default SHORT:

```text
Previous RSI >= overbought
AND
Current RSI  <  overbought
AND
optional bearish candle (close < open)
AND
validate_trade() allows the order
```

`trading.allow_short: false` blocks shorts even when the signal fires (`SHORT_DISABLED`).

---

## 11. Candle Confirmation

`confirm_candle()` is intentionally simple:

- LONG: completed close > open
- SHORT: completed close < open
- Doji (close == open) is **not** confirmation

It is a body-direction filter, not a second indicator. Disable it with `strategy.use_candle_confirmation: false` if you want RSI-only entries.

---

## 12. Completed Candle Principle

Dhan minute timestamps are candle **start** times. A 5-minute bar that starts at 10:00 is complete at 10:05 (`_is_candle_complete()`).

Every poll:

1. Fetch history (`get_market_data()`).
2. Drop the in-progress bar.
3. Compare the latest completed timestamp with `state.last_processed_candle`.
4. If already processed, do **not** generate another entry signal.

This prevents duplicate orders from the same unfinished or already-handled candle while the loop runs every few seconds.

---

## 13. Strategy Flow

```text
MARKET DATA
     ↓
COMPLETED CANDLE
     ↓
RSI CALCULATION
     ↓
OVERSOLD / OVERBOUGHT
     ↓
REVERSAL CONFIRMATION
     ↓
CANDLE CONFIRMATION
     ↓
LONG / SHORT SIGNAL
     ↓
RISK VALIDATION
     ↓
ORDER EXECUTION
     ↓
ORDER VERIFICATION
     ↓
POSITION MONITORING
     ↓
TP / SL / SESSION EXIT
     ↓
POSITION CLOSED
     ↓
BOT STOPS
```

---

## 14. Example Long Trade

Assumptions: RELIANCE, qty 10, RSI 14, oversold 30, TP 1%, SL 0.5%.

| Step | Value |
|------|--------|
| Previous completed RSI | 28.40 |
| Current completed RSI | 32.10 |
| Candle | open 998.50, close 1000.00 (bullish) |
| Signal | LONG |
| Fill (example) | ₹1,000.00 |
| Quantity | 10 |
| TP | ₹1,010.00 |
| SL | ₹995.00 |

Gross P&L if TP is reached: (1010 − 1000) × 10 = **₹100** before costs.

Gross P&L if SL is reached: (995 − 1000) × 10 = **−₹50** before costs.

Brokerage, taxes, fees, and slippage mean realized net P&L will differ. This example is not a forecast.

---

## 15. Example Short Trade

Same quantity and percentages. Fill at ₹1,000.

| Step | Value |
|------|--------|
| Previous RSI | 72.10 |
| Current RSI | 67.80 |
| Candle | open 1001.00, close 999.50 (bearish) |
| Signal | SHORT |
| TP | ₹990.00 (entry − 1%) |
| SL | ₹1,005.00 (entry + 0.5%) |

Gross P&L at TP: (1000 − 990) × 10 = **₹100** before costs.

Gross P&L at SL: (1000 − 1005) × 10 = **−₹50** before costs.

---

## 16. Example Trade Execution

LIVE path after a LONG signal:

1. `validate_trade()` checks session, flat book, pending orders, direction flags, daily limits.
2. `place_entry_order()` → `submit_order()` with a unique correlation tag (`R` + 12 hex chars).
3. Dhan `place_order` is called **once**. Timeouts are **not** retried.
4. `wait_for_order_completion()` polls `get_order_by_id` until FILLED / REJECTED / timeout.
5. `confirm_position_after_fill()` prefers the broker position book over the fill payload.
6. `arm_risk_levels()` stores TP/SL from the **fill** price, rounded to tick size.

PAPER path skips `place_order` and fills locally at LTP. Strategy and risk functions are the same.

---

## 17. Example Position Monitoring

Each trading poll while LONG:

```text
GET LTP (quote API, ≥1.05s spacing)
SYNC POSITION (LIVE: Dhan position book)
CALCULATE P&L  = (LTP − entry) × qty
CHECK SL first, then TP
```

Dashboard fields come from `monitor_position()`. CLI refresh does **not** call Dhan; only the poll cycle does.

---

## 18. Example TP Exit

LTP prints ₹1,010.20 against TP ₹1,010.00.

1. `should_trigger_tp()` is true.
2. `monitor_tpsl()` returns `TAKE_PROFIT`.
3. `place_exit_order()` sells the open quantity.
4. Pending orders are cancelled if configured.
5. `run_trading_loop()` sets `shutdown_reason = TAKE_PROFIT`.
6. `graceful_shutdown()` verifies flat and **stops the bot**.

The next poll does not look for another RSI signal.

Software TP can fill worse than ₹1,010 because of polling interval, latency, gaps, and slippage. The bot never claims a guaranteed exact TP price.

---

## 19. Example SL Exit

LTP prints ₹994.80 against SL ₹995.00.

Stop-loss is evaluated **before** take-profit so a gap through both levels prefers capital protection. Flow matches TP: exit, verify, stop. Reason: `STOP_LOSS`.

---

## 20. Example P&L Calculation

Direction-aware (`calculate_pnl()`):

```text
LONG  P&L = (LTP − entry) × quantity
SHORT P&L = (entry − LTP) × quantity
P&L %     = P&L / (entry × quantity) × 100
```

FLAT displays ₹0.00. LIVE P&L prefers broker quantity and average when the position book can be read, so the CLI is not driven only by stale local fields.

Gross P&L is not net profit. Costs are not subtracted in the dashboard.

---

## 21. System Architecture

Single process, in-memory `BotState`, no persistence except the `.stop` file.

```text
config.yaml + .env
        ↓
      main.py
        ├── Wilder RSI + signals (pure functions)
        ├── Risk / session / daily limits
        ├── Dhan REST (candles, LTP, positions, orders)
        ├── Paper fill simulator (when mode is PAPER)
        ├── Rich Live dashboard (TTY) or stderr logs (AWS/nohup)
        └── stop.py  →  .stop file  →  graceful shutdown
```

---

## 22. Project File Structure

Runtime files (the application still works if `docs/` is deleted):

| File | Role |
|------|------|
| `main.py` | All application and trading logic |
| `config.yaml` | Non-secret settings |
| `.env` | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` |
| `stop.py` | Creates `.stop` |
| `requirements.txt` | `dhanhq`, `PyYAML`, `python-dotenv`, `rich` |
| `architecture.md` | This document |
| `setup_readme.md` | venv / pip / run notes |

Temporary references only: `docs/project_requirements1.md`, `docs/Dhan_SRP.py`, `docs/srp_dhan_helper.md`. `main.py` does not import them.

---

## 23. main.py Architecture

Logical sections match the requirements:

1. Module documentation
2. Imports
3. Constants
4. `Candle` / `BotState`
5. Configuration and environment loading
6. Logging and event ring
7. Stop-file and signals
8. Session time helpers
9. Dhan client and SDK mapping
10. Market data
11. RSI, reversal, candle, signal
12. Positions and P&L
13. LTP
14. TP/SL math
15. Order status and execution
16. Close-all and cancel
17. Recovery and reconciliation
18. `validate_trade` / `compute_next_action`
19. Rich dashboard
20. Poll loop and shutdown
21. `main()` entry

---

## 24. Configuration Architecture

Everything reasonably tunable lives in `config.yaml`. `validate_config()` normalizes types and rejects unsafe combinations before any order.

Important groups: `environment`, `api`, `strategy`, `trading`, `runtime`, `session`, `risk_management`, `shutdown`, `recovery`, `safety`, `cli`.

Live orders require **both**:

```yaml
environment:
  mode: "LIVE"
  allow_live_trading: true
```

A single flag is too easy to flip by accident on a VM that can place real orders.

---

## 25. Environment Variables

```text
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Names are configurable via `api.dhan_client_id_env` and `api.dhan_access_token_env`. Tokens are never logged. `EventHistoryHandler` also drops lines that contain `access_token` or `client_id`.

---

## 26. Dhan API Integration

`create_dhan_client()` supports current `DhanContext` and older positional constructors.

| Need | SDK method |
|------|------------|
| Minute candles | `intraday_minute_data` |
| Daily candles | `historical_daily_data` |
| LTP | `ticker_data` (≈1 request/sec) |
| Positions | `get_positions` |
| Place | `place_order` |
| Status | `get_order_by_id` |
| Order book | `get_order_list` |
| Recover by tag | `get_order_by_correlationID` |
| Cancel | `cancel_order` |

Responses are wrapped as `{status, remarks, data}`. Helpers `_dhan_ok`, `_unwrap_dhan_data`, and `DHAN_STATUS_MAP` normalize `TRADED` → `FILLED` and `PART_TRADED` → `PARTIALLY_FILLED`.

Order APIs require Dhan static-IP whitelist. Data APIs require an active data plan. This bot does not implement WebSockets; REST polling is enough and cheaper on 1 GB RAM.

---

## 27. Market Data Flow

`get_market_data()`:

1. Computes a bounded calendar lookback from `runtime.candle_lookback` (default 100).
2. Calls daily or minute history for the configured `security_id`.
3. Normalizes columnar or row-wise payloads.
4. Converts epoch timestamps into `session.timezone`.
5. Keeps only completed bars.

On failure it returns `[]` so the loop waits instead of trading garbage.

---

## 28. RSI Calculation Flow

```text
closes[]  →  calculate_rsi(period)
         →  previous_rsi, current_rsi
         →  confirm_reversal / zone check
         →  confirm_candle
         →  LONG | SHORT | NONE
```

Insufficient warmup → `WAITING_FOR_MARKET_DATA` / `RSI_WARMUP`. No order.

---

## 29. Signal Generation

`generate_signal()` also fills CLI text:

- Neutral RSI nearer oversold → `WAITING FOR RSI TO ENTER OVERSOLD`
- In oversold, waiting for cross → `RSI OVERSOLD — WAITING FOR REVERSAL`
- Cross without candle → `WAITING FOR CANDLE CONFIRMATION`

Last processed candle timestamp is stored **after** evaluation so a crash mid-function can retry the same bar rather than skip it. Duplicate protection still holds across successful cycles.

---

## 30. Risk Validation

`validate_trade()` returns `(allowed, reason)` and never places an order.

Checks include: stop request, session window, in-flight order, unexpected/unmanaged position, already open, `allow_long` / `allow_short`, `max_trades_per_day`, `max_daily_loss`, `max_daily_profit`, quantity.

`daily_risk_blocked()` is reused while flat so the dashboard can show `MAX TRADES REACHED` without a signal.

---

## 31. Order Execution

Lifecycle:

```text
SIGNAL → RISK → POSITION → PENDING → SUBMIT → STATUS → FILL → POSITION VERIFY
```

`API accepted` is not `FILLED`. MARKET is used when configured; LIMIT is never silently rewritten to MARKET. Notional above ₹50,000 logs a warning (Dhan skill threshold).

---

## 32. Order Verification

`finalize_submitted_order()`:

- REJECTED / CANCELLED with no fill → clear pending, no retry
- Partial fill → adopt filled quantity, **do not** send the remainder
- Uncertain place → `find_order_id_after_uncertain_place()`, never a second `place_order`
- LIVE confirmation reads the position book

---

## 33. Position Management

`one_trade_at_a_time` and `max_open_positions: 1` keep the bot in MONITORING while a position exists. No pyramiding. No automatic reverse.

`close_all_positions()` exits only the configured `security_id` when `safety.manage_only_configured_symbol` is true. Unrelated holdings are left alone.

---

## 34. P&L Monitoring

Updated every poll from LTP and broker (LIVE) or local paper state. Displayed as rupees and percent. Realized paper/live exit P&L is accumulated in `state.daily_realized_pnl` for daily loss/profit caps.

---

## 35. Take Profit

`risk_management.take_profit`: `PERCENT` or `POINTS`.

```text
LONG  TP = entry + distance
SHORT TP = entry − distance
```

Rounded with `round_to_tick()`. Armed from actual fill, not from the signal price.

---

## 36. Stop Loss

Same distance model, opposite direction:

```text
LONG  SL = entry − distance
SHORT SL = entry + distance
```

---

## 37. TP/SL Monitoring

Checked every position-monitoring poll using LTP, not candle close. Documented limitations:

- Polling interval (default 5s)
- Quote rate limit (~1/s) and API latency
- Network jitter
- Slippage and market gaps
- Fast prints between polls

Never treat the configured TP/SL as a guaranteed execution price. This is software polling, not an exchange native stop.

---

## 38. Why TP/SL Stops the Bot

The product is a **single-trade session helper**, not a 24×7 signal mill. After TP or SL:

```text
Exit → verify closed → cancel pendings if configured → process exit
```

That avoids immediately re-entering on the next noisy RSI cross and keeps behaviour obvious on a small VM.

---

## 39. Session Management

All clocks use `session.timezone` (default `Asia/Kolkata`) via `zoneinfo`, not the AWS instance timezone. Daily trade counting uses that calendar date.

---

## 40. Day Trading Mode

`session.enabled: true`:

```text
Before start  → wait (dashboard: SESSION NOT STARTED)
Start         → allow entries
Stop          → no new entries; flatten if configured; stop bot
```

---

## 41. Session Disabled Mode

`session.enabled: false`: no mandatory window. TP/SL, risk caps, manual stop, and safety shutdowns still apply. Suitable for experiments; still not a profitability promise.

---

## 42. Polling Architecture

Two intervals:

| Setting | Default | Calls Dhan? |
|---------|---------|-------------|
| `runtime.polling_interval_seconds` | 5 | Yes (candles/LTP/positions/orders) |
| `cli.refresh_seconds` | 1 | No (redraws `BotState`) |

`run_trading_loop()` sleeps on the CLI interval when a TTY Live dashboard is active, and only runs `run_one_poll_cycle()` when the trading interval has elapsed.

---

## 43. Sci-Fi CLI

`render_dashboard()` is a Rich panel: system, market, strategy, position, trading, runtime, event stream.

- TTY + `cli.enabled` → `rich.live.Live`
- nohup / systemd / redirected stdout → logging on stderr only

Event history is a bounded deque (`cli.event_history_size`, default 8).

---

## 44. When Will the Algo Trade?

`compute_next_action()` always fills a human sentence, for example:

- `WAITING FOR RSI TO ENTER OVERSOLD`
- `RSI OVERSOLD — WAITING FOR REVERSAL`
- `RSI REVERSAL DETECTED — WAITING FOR CANDLE CONFIRMATION`
- `LONG SIGNAL — RISK CHECK PENDING`
- `POSITION OPEN — MONITORING TP/SL`
- `SESSION NOT STARTED`
- `MAX TRADES REACHED`
- `POSITION FLAT — SCANNING`

---

## 45. Why Is the Algo Not Trading?

Machine codes (also mapped to labels in `WHY_NO_TRADE_LABELS`):

`WAITING_FOR_MARKET_DATA`, `WAITING_FOR_NEW_CLOSED_CANDLE`, `RSI_NOT_OVERSOLD`, `RSI_NOT_OVERBOUGHT`, `WAITING_FOR_RSI_REVERSAL`, `WAITING_FOR_CANDLE_CONFIRMATION`, `LONG_DISABLED`, `SHORT_DISABLED`, `POSITION_ALREADY_OPEN`, `MAX_TRADES_REACHED`, `SESSION_NOT_STARTED`, `SESSION_ENDED`, `RISK_LIMIT_REACHED`, `PENDING_ORDER_EXISTS`, `STOP_REQUESTED`, `API_UNAVAILABLE`, `CONFIGURATION_ERROR`, `BLOCKED_UNEXPECTED_POSITION`, `MONITORING_TP_SL`, `SCANNING`.

---

## 46. Duplicate Order Prevention

Causes considered: same candle, polling, API delay, timeout, restart, partial fill, unknown state.

Rules:

- `last_processed_candle`
- `order_in_flight` / `pending_order_id`
- No `place_order` retry on exception; recover by correlation tag + order book
- Restart recovery adopts the open position instead of entering again
- Partial fills are monitored, not topped up

---

## 47. Partial Fill Handling

If 1 of 2 shares fill: local quantity becomes 1, TP/SL use the fill average, remainder is **not** re-sent. The operator can stop or flatten via config / `stop.py`.

---

## 48. Restart Recovery

`recover_existing_state()`:

1. Connect, list positions.
2. If configured symbol is open and `recovery.manage_existing_position`, adopt side/qty/avg and arm TP/SL.
3. If other symbols are open and `block_if_unexpected_position`, block new entries.
4. Count today's filled orders (`count_todays_broker_entries()`) so `max_trades_per_day` survives restart.

Never enter “because we just started.”

---

## 49. State Machine

Simple flags on `BotState.engine_state`, not a framework:

```text
STARTING
  → WAITING_FOR_SESSION
  → READY
  → SIGNAL_DETECTED
  → ENTRY_PENDING
  → POSITION_OPEN / MONITORING
  → EXIT_PENDING
  → POSITION_CLOSED
  → STOPPING
  → STOPPED
ERROR
```

---

## 50. Graceful Shutdown

Handles Ctrl+C, SIGTERM, and `stop.py`.

1. Stop new entries.
2. Optionally cancel pending orders.
3. Optionally close managed positions (depends on reason and YAML).
4. Verify broker book in LIVE.
5. Log `STOP_REASON`.
6. Exit.

Manual stop default: **do not** flatten (`shutdown.close_positions_on_manual_stop: false`). Session end and TP/SL default to flatten when those flags are true.

---

## 51. stop.py

Standard library only. Writes `BASE_DIR/.stop`. Another SSH session can run `python3 stop.py` without killing PID 9.

`main.py` deletes a leftover `.stop` **once at startup**, then never deletes it while trading, so a stop during a sleep cannot be lost.

---

## 52. Risk Management

Enabled block in YAML:

- TP / SL
- `max_trades_per_day`
- `max_daily_loss` / `max_daily_profit` (0 = disabled)
- One position at a time
- Session window
- Manual stop
- Unexpected-position block

When a daily cap is hit, new entries stop. An already-open position is still monitored for TP/SL.

---

## 53. Paper Trading

`environment.mode: PAPER` (default):

- Real candles and LTP
- **No** `place_order`
- Local fill at LTP, local TP/SL, local flatten
- Same `generate_signal` / `validate_trade` as LIVE

Use paper until the dashboard, session, and stop path are familiar. Paper fills still ignore live spread and rejection.

---

## 54. Live Trading

Startup prints:

```text
⚠ LIVE TRADING ENABLED ⚠
REAL ORDERS MAY BE PLACED
REAL MONEY MAY BE AT RISK
```

Every live entry still runs the chain: configuration → session → position → pending → risk → signal → safety → order → verify. Any failure means **do not place**.

---

## 55. Error Handling

Covered: missing YAML, bad RSI levels, missing credentials, auth failure, network/API errors, empty candles, reject/partial/unknown orders, position mismatch, unexpected exceptions.

Important errors are logged. Credentials are not. A failed position **read** is never treated as flat.

---

## 56. Retry Strategy

Safe to retry: market data, positions, order **status**.

Unsafe to retry: `place_order` after timeout or unknown success.

Ambiguous submit → query order + position → reconcile → only then consider a new order on a **later** clean cycle if still flat and no in-flight tag.

---

## 57. Parameter Tuning

| Parameter | If you raise it | If you lower it |
|-----------|-----------------|-----------------|
| RSI period | Fewer, slower signals | More noise |
| Oversold (e.g. 30 → 20) | Fewer LONG setups, more extreme | More LONG setups |
| Overbought (70 → 80) | Fewer SHORT setups | More SHORT setups |
| Timeframe 1 vs 15 | 1m: more bars, more costs | 15m: fewer decisions |
| Candle confirmation on | Fewer entries, cleaner bodies | More entries |
| TP distance | Higher average win, lower hit rate | More TP hits, smaller wins |
| SL distance | Survives noise, larger losses | Tighter risk, more stops |
| Quantity | Linear P&L and notional | Smaller money at risk |
| Polling interval | Less API use, worse TP/SL drift | More API use, tighter software stops |
| max_trades_per_day | More activity | Hard cap |
| Session window | Longer trading day | Avoid open/close chaos |

**Robustness > historical maximum profit.** Fitting RSI 11 / OS 27 / TP 1.37% on last month is curve fitting until you prove it out of sample.

---

## 58. Backtesting and Validation

This repo is a **live/paper engine**, not a full backtester. Before LIVE:

```text
Historical data
    → Generate the same signals (closed candles, Wilder RSI)
    → Simulate fills (include slippage)
    → Apply TP/SL (bar-level vs poll-level will differ from live)
    → Apply brokerage and taxes
    → Net P&L, drawdown, expectancy
    → Out-of-sample / walk-forward
    → Paper trade the same YAML
```

Live results differ because of poll granularity, rejects, partials, gaps, and regime change.

---

## 59. Improving Strategy Quality

Responsible process: define risk first, then measure, then change **one** parameter family, then re-paper. Do not stack a trend filter, ATR stop, and new RSI period in the same weekend and call the equity curve “alpha.”

---

## 60. AWS 1 GB Deployment

No Docker. No database. No web server.

1. Amazon Linux: `sudo dnf install -y python3.11 python3.11-pip python3.11-devel`
2. Copy this directory to the VM.
3. `python3.11 -m venv .venv && source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. Put real values in `.env` (never commit them).
6. Review `config.yaml` (start with `PAPER`).
7. `python main.py` (or under `systemd` / `tmux`).
8. Watch the dashboard if you have a TTY; otherwise read stderr logs.
9. From another shell: `python stop.py`
10. Confirm positions on Dhan if you were LIVE.

Whitelist the VM's public IP for order APIs. Keep lookback at 100 candles; do not load multi-year frames into RAM.

---

## 61. Complete Program Execution Flow

```text
START
 ↓
LOAD CONFIG
 ↓
LOAD ENV
 ↓
VALIDATE CONFIG + LIVE LOCK
 ↓
CONNECT TO DHAN
 ↓
START CLI (if TTY)
 ↓
RECOVER EXISTING POSITION + TODAY'S TRADE COUNT
 ↓
LOOP:
    CHECK STOP / SESSION
    IF TIME FOR POLL:
        SYNC PENDING ORDER
        RECONCILE POSITION
        FETCH LTP
        IF OPEN → TP/SL (maybe EXIT and STOP)
        IF FLAT → CLOSED CANDLE → RSI → SIGNAL → VALIDATE → ORDER → VERIFY
    REFRESH DASHBOARD FROM MEMORY
 ↓
GRACEFUL SHUTDOWN
 ↓
STOPPED
```

---

## 62. Function-by-Function Explanation

### load_config()

**Purpose:** Read `config.yaml`.

**Why it exists:** One file owns tunables.

**Inputs:** None (path constant).

**Outputs:** dict, or `ConfigError`.

**Step-by-step:** Open file, `yaml.safe_load`, require a mapping.

**Trading use case:** Startup.

**Safety:** No Dhan calls.

### load_environment()

**Purpose:** Load credentials.

**Why it exists:** Secrets must not live in YAML or git.

**Inputs:** config (env var names).

**Outputs:** None; raises `CredentialError`.

**Safety:** Never logs tokens.

### validate_config()

**Purpose:** Normalize and reject impossible settings.

**Why it exists:** Bad RSI levels or qty 0 must not reach `place_order`.

**Inputs:** config dict (mutated).

**Outputs:** None or `ConfigError`.

**Safety:** No orders.

### validate_safety_config()

**Purpose:** Dual lock for LIVE.

**Why it exists:** Two flags must be set on purpose.

**Safety:** PAPER always passes.

### create_dhan_client()

**Purpose:** Authenticated SDK object.

**Why it exists:** SDK constructors differ by version.

**Safety:** No token logging, no orders.

### get_market_data()

**Purpose:** Completed candles for RSI warmup.

**Why it exists:** Signals must not use the in-progress bar.

**Outputs:** `list[Candle]` or `[]`.

**Safety:** Read-only.

### calculate_rsi()

**Purpose:** Wilder RSI series.

**Why it exists:** RSI is the only indicator.

**Outputs:** list aligned with closes; early `None`.

**Safety:** Pure math.

### confirm_reversal()

**Purpose:** Detect cross out of OS/OB.

**Why it exists:** Extremes persist; the cross is the event.

**Safety:** No orders.

### confirm_candle()

**Purpose:** Body direction filter.

**Safety:** No orders.

### generate_signal()

**Purpose:** LONG / SHORT / NONE.

**Why it exists:** Keep strategy independent from execution.

**Safety:** Never places an order.

### validate_trade()

**Purpose:** Permission check.

**Outputs:** `(allowed, reason_code)`.

**Safety:** No orders. Reason is shown on the CLI.

### compute_next_action()

**Purpose:** Explain wait state.

**Why it exists:** Operators should not need to tail logs to know why it is idle.

### get_ltp() / monitor_position() / calculate_pnl()

**Purpose:** Price, broker sync, direction-aware P&L.

**Safety:** Read-only except in-memory state.

### arm_risk_levels() / should_trigger_tp() / should_trigger_sl() / monitor_tpsl()

**Purpose:** Arm and poll software TP/SL.

**Safety:** SL checked first. Returns a reason; does not by itself loop forever.

### submit_order() / place_entry_order() / place_exit_order()

**Purpose:** Single choke point for PAPER fills and LIVE `place_order`.

**Safety:** No duplicate in-flight submits; no LIMIT→MARKET conversion; no place retry on timeout.

### wait_for_order_completion() / finalize_submitted_order() / confirm_position_after_fill()

**Purpose:** Verify broker truth.

**Safety:** Partial fills not completed with a second order.

### close_all_positions() / cancel_pending_orders()

**Purpose:** Flatten and cancel what this bot is allowed to touch.

**Safety:** Configured symbol only when `manage_only_configured_symbol` is true.

### recover_existing_state() / reconcile_state() / count_todays_broker_entries()

**Purpose:** Restart-safe position and daily count.

**Safety:** Trust broker; never “fix” mismatch with a new entry.

### render_dashboard() / render_startup_banner() / run_trading_loop()

**Purpose:** Operator visibility and the poll/CLI split.

### graceful_shutdown() / main()

**Purpose:** Ordered start and stop.

**Safety:** Shutdown still logs if flatten fails.

---

## 63. Configuration Reference

See comments in `config.yaml`. Critical defaults:

| Key | Default |
|-----|---------|
| `environment.mode` | PAPER |
| `environment.allow_live_trading` | false |
| `strategy.timeframe` | 5 |
| `strategy.rsi_period` | 14 |
| `strategy.oversold` / `overbought` | 30 / 70 |
| `trading.trading_symbol` | RELIANCE |
| `trading.security_id` | 2885 |
| `trading.quantity` | 1 |
| `trading.product_type` | INTRADAY |
| `trading.order_type` | MARKET |
| `session.start_time` / `stop_time` | 09:20 / 15:15 IST |
| `risk_management.take_profit` | 1% |
| `risk_management.stop_loss` | 0.5% |
| `risk_management.max_trades_per_day` | 1 |
| `runtime.polling_interval_seconds` | 5 |

---

## 64. Risk and Safety Considerations

- Equity product types only as allowed by segment; F&O cannot use CNC/MTF.
- Static IP required for live orders.
- Software TP/SL is not a broker native stop.
- `block_if_unexpected_position` avoids doubling risk you forgot about.
- Notional warning at ₹50,000 does not block the order; it alerts.
- Kill the process with SIGKILL only as a last resort; prefer `stop.py`.

---

## 65. Strategy Limitations

- RSI reversal fails in strong trends (oversold can stay oversold).
- One symbol, one timeframe, no regime filter.
- Intraday history lookback is bounded; very long RSI warmups need enough bars.
- Paper fills are optimistic.
- `max_trades_per_day` broker reconcile is conservative (filled orders today), not a perfect round-trip ledger.
- No guaranteed profit, edge, or win rate.

---

## 66. Future Improvements

Not in the current bot (do not confuse with the baseline):

- Trend or volatility filter
- Volume confirmation
- ATR or trailing / break-even stops
- Dynamic position sizing
- Multi-timeframe confirmation
- Full historical backtester with costs
- Option-leg execution

Add these only with a written hypothesis and out-of-sample tests.

---

## Code-to-concept mapping

| Concept | Functions |
|---------|-----------|
| Market data | `get_market_data`, `_is_candle_complete` |
| RSI | `calculate_rsi`, `_rsi_from_averages` |
| Reversal | `confirm_reversal` |
| Candle confirmation | `confirm_candle` |
| Signal | `generate_signal`, `process_new_candle` |
| Risk | `validate_trade`, `daily_risk_blocked` |
| Order execution | `submit_order`, `place_entry_order`, `place_exit_order` |
| Order verification | `wait_for_order_completion`, `finalize_submitted_order`, `get_order_status` |
| Position | `monitor_position`, `apply_broker_position`, `close_all_positions` |
| P&L | `calculate_pnl` |
| TP / SL | `arm_risk_levels`, `monitor_tpsl` |
| Session | `session_window`, `is_before_session_start`, `is_after_session_stop` |
| CLI | `render_dashboard`, `compute_next_action` |
| Shutdown | `stop_requested`, `graceful_shutdown`, `stop.py` |
| Recovery | `recover_existing_state`, `reconcile_state` |

---

## Parameter tuning example (hypothetical)

Compare two configs on the **same** history, **same** cost model, **same** instrument. Do not pick the winner from a single lucky week.

**Configuration A:** RSI 14, 30/70, TP 1%, SL 0.5%.

**Configuration B:** RSI 14, 25/75, TP 1.5%, SL 0.75%.

B should usually produce fewer trades and wider targets. Whether expectancy rises is an empirical question. If A has higher net profit only because of three outliers that vanish out of sample, B may be more robust — or both may have no edge.

### Expectancy (simplified, costs omitted)

```text
Expectancy = (Win Rate × Average Win) − (Loss Rate × Average Loss)
```

Example: win rate 55%, average win ₹100, loss rate 45%, average loss ₹80:

```text
(0.55 × 100) − (0.45 × 80) = ₹19 per trade
```

This is a classroom identity, not this bot's live expectancy. Add brokerage and slippage before you believe a number.

### Risk/reward sketches

| TP / SL | Typical qualitative effect |
|---------|----------------------------|
| 1% / 0.5% (R=2) | Need fewer wins than even odds if costs are small |
| 1.5% / 0.5% | Higher R, fewer TP hits |
| 2% / 1% | Similar R to the first, larger rupee swings and drawdown |

Changing TP/SL changes win rate, average win, average loss, drawdown, and trade frequency **together**. Optimizing only historical net profit is how overfit bots are born.

---

**Reminder:** Robustness beats a backtest high-score. Nothing in this repository promises profitability.
