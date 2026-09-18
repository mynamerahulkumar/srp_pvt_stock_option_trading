# EMA + VWAP Scalping Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity using **fast/slow EMA alignment** plus **session VWAP**. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the mathematics, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Parameter tuning, paper trading, and walk-forward testing exist to improve robustness and risk-adjusted behaviour. They do not make live results certain. Actual realized P&L differs from the examples after brokerage, STT, exchange charges, GST, SEBI charges, stamp duty, slippage, and taxes.

The examples in this chapter are hypothetical. They are for explaining arithmetic, not for promising results.

---

## 1. Strategy Overview

**EMA** (Exponential Moving Average) is a moving average that gives more weight to recent closes:

```text
k      = 2 / (period + 1)
seed   = SMA of the first `period` closes
EMA[t] = close[t] × k + EMA[t-1] × (1 − k)
```

A **fast** EMA (default 9) reacts sooner than a **slow** EMA (default 21). When the fast line is above the slow line, short-term price is leading the medium-term average — commonly read as a bullish bias. The reverse is a bearish bias.

**VWAP** (Volume Weighted Average Price) is the average traded price of the **current session**, weighted by volume:

```text
typical = (high + low + close) / 3
VWAP    = Σ (typical × volume) / Σ volume
```

Traders use VWAP as an intraday fair-value line. Price **above** session VWAP is commonly read as buyers accepting higher prices. Price **below** it is commonly read as sellers accepting lower prices.

**Why combine them for scalping**

EMA alignment describes *trend*. Session VWAP describes *where the day's volume has transacted*. Requiring both reduces entries that fight the session mean or that fire on a noisy EMA flip against VWAP.

This is a **scalping / intraday alignment** framework, not a mean-reversion fade and not a one-bar crossover event. The same alignment can stay true for many five-second polls. Duplicate-order protection and position state prevent re-entry.

**Limitations**

- Alignment can persist in a choppy range and produce late entries.
- Session VWAP is undefined or unstable in the first few bars if volume is thin.
- Software-polled TP/SL is not an exchange stop. Gaps and latency can overshoot the exact price.
- Short selling is not valid for every product type (CNC / MTF are rejected).
- No strategy is robust in every regime.

---

## 2. Strategy Rules

Signals are evaluated on the **last completed candle only**. The forming bar is never used for EMA, VWAP, or the candle filter.

| Condition | Long | Short |
| --------- | ---- | ----- |
| Fast EMA vs Slow EMA | Fast > Slow (when `require_ema_alignment`) | Fast < Slow |
| Price vs session VWAP | Above (when `require_vwap_confirmation`) | Below |
| Last completed candle | Bullish close > open (when `candle_confirmation`) | Bearish close < open |
| Volume | Optional: volume ≥ average × `minimum_volume_multiplier` | Same |
| Position | Flat, no pending order | Flat, no pending order |
| Session | Entries allowed | Entries allowed |
| Daily risk | Limits not reached | Limits not reached |

`generate_signal()` returns `LONG`, `SHORT`, or `NONE` plus diagnostics. It never places an order.

Default `execution.entry_side` is `BOTH`. CNC / MTF shorts are rejected at validation.

---

## 3. Complete Architecture

```text
Dhan API
   ↓
Market Data (completed candles + LTP)
   ↓
Indicator Engine (fast EMA, slow EMA, session VWAP, volume)
   ↓
Signal Engine (LONG / SHORT / NONE + reasons)
   ↓
Risk Engine (session, daily limits, flat, pending)
   ↓
Execution Engine (paper or live, one submit, verify fill)
   ↓
Position Manager
   ↓
TP / SL (percentage or points from fill)
   ↓
P&L Monitor
   ↓
CLI
```

The process is a single Python file. Runtime state lives in `BotState`. There is no database, Redis, Docker, or web server.

```text
MARKET DATA
     ↓
INDICATORS
     ↓
EMA + VWAP SIGNAL
     ↓
SIGNAL VALIDATION
     ↓
RISK VALIDATION
     ↓
ORDER SAFETY CHECK
     ↓
DHAN EXECUTION
     ↓
FILL CONFIRMATION
     ↓
POSITION MANAGEMENT
     ↓
TP / SL
     ↓
EXIT CONFIRMATION
     ↓
P&L
     ↓
BOT STOP  (after confirmed TP or SL)
```

Priority: **correctness → safety → reliability → readability → performance**.

---

## 4. Function-by-Function Explanation

Major functions in `main.py`. Indicator and signal math can be understood without Dhan.

### Configuration and lifecycle

| Function | Purpose | Inputs | Outputs | When called | What can go wrong |
|----------|---------|--------|---------|-------------|-------------------|
| `load_environment` | Load `.env` | none | none; raises if missing | Startup | Missing credentials |
| `load_config` | Read YAML | path | dict | Startup | Missing / invalid YAML |
| `validate_config` | Normalize and fail fast | config | mutates config | Startup | Bad periods, times, sides |
| `validate_safety_config` | Dual live lock | config | none | Startup | Live unlocked by accident |
| `setup_logging` | Console + event ring | config | none | Startup | — |
| `create_dhan_client` | SDK client | env | dhan | Startup | Missing token |
| `resolve_instrument` | Confirm YAML IDs | config | instrument | Startup | Blank security_id |
| `main` | Orchestrate start → loop → stop | argv | exit code | Process entry | Any startup error |

### Market data

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `get_market_data` / `fetch_candles` / `fetch_market_data` | Fetch OHLC | dhan, config | completed candles |
| `validate_candles` | Drop bad OHLC | candles | clean list |
| `get_ltp` | Quote with ~1/s spacing | dhan, id, segment | last good LTP on failure |

Candle fetch uses `dhan.intraday_minute_data(...)` (or `historical_daily_data` for `DAY`). Lookback is capped so a 1 GB VM does not accumulate unbounded history.

### Indicators (pure)

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `typical_price` | VWAP representative price | candle | float |
| `calculate_vwap` | Session VWAP series | candles, date | list of optional floats |
| `calculate_ema` | EMA series | closes, period | list of optional floats |
| `calculate_volume_ratio` | vol vs prior average | volumes, lookback | current, avg, ratio |
| `calculate_indicators` | Bundle for the last bar | candles, config | dict |
| `candle_direction` | Bullish / bearish / doji | candle | str |

### Signal

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `generate_signal` | LONG / SHORT / NONE | candles, config, state | `SignalResult` |
| `display_signal_reason` | One-line explanation | result | str |
| `apply_signal_to_state` | Copy numbers to CLI | state, result | none |

### Risk and session

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `check_trading_session` / `check_trading_window` | May we enter now? | config, now | (allowed, reason) |
| `check_risk_limits` | Daily loss / trades | config, state | reason or None |
| `check_duplicate_order` | Pending / open / same bar | state, config | bool |
| `validate_trade` | All entry vetoes | config, state, signal | (ok, reason) |

### Orders and positions

| Function | Purpose | Inputs | Outputs | Safety |
|----------|---------|--------|---------|--------|
| `place_entry_order` | Open LONG/SHORT | dhan, config, state, side | bool | One in-flight order |
| `place_exit_order` | Flatten local position | dhan, config, state | bool | Opposite side only |
| `wait_for_order_completion` | Poll until terminal | dhan, config, state, id | status | No second place |
| `find_order_id_after_uncertain_place` | Recover by tag | dhan, tag, id | order id | Never re-places |
| `close_all_positions` | Idempotent flatten | dhan, config, state | bool | No duplicate exits |
| `recover_existing_state` | Adopt broker book | dhan, config, state | none | No restart entry |
| `get_positions` / `get_open_position` / `get_pending_orders` | Broker reads | dhan, config | rows | Read retries only |

### TP / SL and P&L

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `calculate_tp_price` / `calculate_sl_price` | Levels from **fill** | entry, side, config | tick-rounded price or None |
| `arm_risk_levels` | Store TP/SL on state | state, config, fill, side | none |
| `monitor_tpsl` | Compare LTP to levels | dhan, config, state, ltp | TAKE_PROFIT / STOP_LOSS |
| `calculate_pnl` / `calculate_position_pnl` | Gross P&L | side, qty, entry, ltp | (pnl, percent) |

### CLI and loop

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `display_dashboard` / `render_dashboard` | Sci-fi panel | config, state | Rich Panel |
| `run_strategy_cycle` / `run_one_poll_cycle` | One API cycle | dhan, config, state, candles | (candles, stop reason) |
| `run_trading_loop` | Poll until stop | dhan, config, state | none |
| `check_stop_signal` | `.stop` or signal | none | bool |
| `handle_shutdown` / `graceful_shutdown` | Stop entries, optional flatten | dhan, config, state, reason | none |

---

## 5. Complete Trade Example (hypothetical)

Symbol: RELIANCE. Quantity: 10. Fast EMA: 9. Slow EMA: 21. Timeframe: 5m.

Assume the last **completed** 5-minute candle has:

```text
EMA 9  > EMA 21
Price  > session VWAP
Bullish candle (close > open)
Volume confirmation passed
```

`generate_signal()` returns `LONG`. After session and risk checks, an entry is submitted.

```text
LONG ENTRY
Fill price (actual) = ₹2500
Quantity            = 10
TP type             = percentage  0.50
SL type             = percentage  0.30
```

```text
TP = 2500 × (1 + 0.50 / 100) = ₹2512.50
SL = 2500 × (1 − 0.30 / 100) = ₹2492.50
```

Hypothetical TP exit:

```text
Entry: ₹2500 × 10 = ₹25,000
Exit:  ₹2512.50 × 10 = ₹25,125
Gross P&L: ₹125
```

Hypothetical SL exit:

```text
Entry: ₹2500 × 10
Exit:  ₹2492.50 × 10
Gross loss: ₹75
```

**These numbers are hypothetical.** Net P&L after brokerage, taxes, exchange charges, and slippage will differ. A points-mode example with the same fill: TP 12.50 points → ₹2512.50; SL 7.50 points → ₹2492.50.

---

## 6. Trade Lifecycle

```text
Signal
→ Risk validation
→ Order
→ Order confirmation
→ Fill (actual price)
→ Position
→ TP/SL monitoring
→ Exit
→ P&L
→ Bot shutdown  (if the exit was TP or SL)
```

Duplicate-order protection is critical because the strategy is evaluated every few seconds. The same alignment may remain valid across multiple polling cycles. Once an entry is submitted or a position is open, the same `LONG` does not submit again.

---

## 7. TP / SL Lifecycle

TP and SL are **not** dependent on a new opposite signal. Position management outranks the signal.

| Event | What happens |
|-------|----------------|
| LTP reaches TP | Exit the position. Confirm the fill. Display `TP HIT → EXIT EXECUTED → BOT STOPPED`. Stop the process. No new trade that run. |
| LTP reaches SL | Same as TP with `SL HIT → EXIT EXECUTED → BOT STOPPED`. |
| Opposite signal (if enabled) | Flatten. Do **not** stop the bot. Further entries still need session/risk/duplicate checks. |
| Temporary API failure | Read retries (`safety.max_api_retries`). Last good LTP is reused so one quote blip does not skip TP/SL. No second `place_order` on an uncertain submit. |
| Order rejected | Pending cleared. No blind retry. |
| Position disappears at broker | Reconciliation trusts the broker. Local state goes flat. No corrective order. |
| Bot restart | `recover_existing_state()` reads Dhan positions/orders, adopts the configured symbol, re-arms TP/SL from broker average price. Logs `RECOVERING EXISTING POSITION`. Does not open a new trade. |
| `stop.py` | Creates `.stop`. Loop stops new entries. Positions close only if `safety.close_positions_on_shutdown` is true (default false). |

We use the actual broker fill price rather than the requested order price because slippage can cause the execution price to differ.

---

## 8. Day Trading Mode

```yaml
trading_session:
  enabled: true
  start_time: "09:20"
  stop_new_entries_time: "15:00"
  close_all_positions_time: "15:15"
  timezone: "Asia/Kolkata"
```

Clocks are built in **Asia/Kolkata**. The Linux VM timezone does not matter.

| Clock | Behaviour |
|-------|-----------|
| Before `start_time` | No new entries |
| After `start_time` | Trading allowed (if risk passes) |
| After `stop_new_entries_time` | No new entries; open position still managed by TP/SL / opposite signal |
| At `close_all_positions_time` | Flatten if configured, then stop. Display day-session close. |

---

## 9. Non-Time-Restricted Mode

```yaml
trading_session:
  enabled: false
```

- No start-time wait.
- No entry cutoff.
- No automatic flatten at `close_all_positions_time`.
- Strategy, risk, TP/SL, and exchange/API rules still apply.

---

## 10. CLI

The dashboard is a Rich Live panel titled **◈ EMA × VWAP QUANT ENGINE :: DHAN ◈**. It redraws from memory. It does not call Dhan by itself.

| Section | Contents |
|---------|----------|
| SYSTEM | Status, paper/live, symbol, security id, engine, API, stop file |
| MARKET DATA | LTP, VWAP, EMA 9, EMA 21, trend, VWAP side, volume |
| SIGNAL | LONG / SHORT / NONE, check ticks, reasons, next action, why-no-trade |
| POSITION | Side, qty, entry, TP, SL, unrealized P&L |
| ORDERS / RISK | Last order, trades today, daily P&L, last error |
| RUNTIME | Uptime, next poll, stop flag |
| EVENT STREAM | Recent `[DATA] [ANALYSIS] [SIGNAL] [RISK] [ORDER] [POSITION] [EXIT] [SYSTEM] [ERROR]` lines |

Log tokens and access credentials are never printed.

---

## 11. Risk Management

| Control | Default | Effect |
|---------|---------|--------|
| `dry_run` + `allow_live_trading` | true / false | Live `place_order` only when both are unlocked |
| `max_daily_loss` | 1000 | New entries disabled when realized P&L ≤ −limit |
| `max_trades_per_day` | 10 | Cap on entries |
| `max_open_positions` | 1 | No add-on |
| Duplicate-order protection | true | Same alignment across polls does not re-submit |
| Broker-state recovery | on | Restart adopts existing position |
| Uncertain order state | — | Recheck by tag. Do not submit a duplicate |
| Read retries | 3 × 2s | Finite. Never infinite |

There is no martingale, no revenge sizing, and no automatic quantity increase after losses. SL is never removed because a trade is losing.

---

## 12. Parameter Tuning Guide

Optimization should follow:

```text
Backtesting
→ Out-of-sample testing
→ Paper trading
→ Small live deployment
→ Monitoring
```

Avoid overfitting a short sample. No parameter set is guaranteed to be profitable.

### EMA pairs

| Pair | Typical behaviour |
|------|-------------------|
| 5 / 13 | Faster, more trades, more noise |
| 9 / 21 | Default. Moderate responsiveness |
| 20 / 50 | Slower, fewer trades, later entries, longer holds |

Shorter pairs increase trade frequency and transaction costs. Longer pairs miss short scalp moves.

### TP / SL

Small TP + large SL can produce a high win rate with negative expectancy. Prefer a coherent risk/reward (here default TP 0.50% vs SL 0.30% is **not** a promise — it is a starting point to evaluate). `points` mode is useful when you think in rupees per share instead of percent.

### VWAP filter

Enabling VWAP confirmation cuts trades that fight the session mean and also cuts trade count. Disabling it makes the bot closer to a pure EMA-alignment scalper.

### Timeframe

| Interval | Noise | Responsiveness |
|----------|-------|----------------|
| 1m | High | Highest |
| 3m / 5m | Medium | Default scalp |
| 15m | Lower | Fewer, slower signals |

Dhan minute codes include `1`, `5`, `15`, `25` (30-minute quirk), `60`, `DAY`. `config.yaml` also accepts `5m`.

### Volume filter

`minimum_volume_multiplier` > 1 requires the signal bar to be heavier than recent average volume. That can reduce weak breakouts and also reduce trade count. `1.0` is a light filter; `0` disables the check.

### Session times

A later `start_time` skips the open. An earlier `stop_new_entries_time` avoids late-day entries. Flatten time should stay before the cash-market close.

### Polling

Default 5 seconds. Faster polling uses more quote quota (about 1 request/sec) without creating new completed candles.

---

## 13. Strategy Improvement Section

Test each idea **independently**. Do not enable everything at once.

- ATR-based TP/SL
- Trailing stop / break-even stop
- Volatility or market-regime filter
- Higher-timeframe trend filter
- Opening-range filter
- Volume profile
- Dynamic position sizing
- Maximum consecutive-loss protection
- Cooldown after a trade
- Spread / slippage filter
- Index or sector trend confirmation
- News / event filters
- Options-specific adaptations

---

## 14. How to Improve the Probability of a Positive Trading Outcome

Do not promise profits. The objective is to improve:

```text
Expectancy
Risk-adjusted returns
Drawdown control
Execution quality
Consistency
```

```text
Expectancy =
(Win Rate × Average Win)
−
(Loss Rate × Average Loss)
```

Hypothetical example (before real-world costs unless included):

```text
Win rate     = 55%
Average win  = ₹100
Loss rate    = 45%
Average loss = ₹80

Expectancy = 0.55 × 100 − 0.45 × 80 = ₹19 per trade
```

A positive backtest expectancy can become negative after brokerage, taxes, and slippage. Measure costs explicitly.

---

## 15. Testing Guide

### Dry run

```yaml
bot:
  dry_run: true
  allow_live_trading: false
```

Fetches real candles and LTP. Simulates fills locally. Logs `[PAPER ORDER]`.

### Paper trading

Leave dry-run on for several sessions. Watch why-no-trade reasons, duplicate protection, TP/SL banners, and `stop.py`.

### Small live deployment

Unlock both flags. Start with quantity 1. Confirm static IP whitelist and an active Dhan data plan. Live market orders still carry slippage.

### Failure testing

| Case | Expected |
|------|----------|
| API unavailable | Retry reads; no crash; no duplicate place |
| Network interruption | Same |
| Order rejected | Pending cleared; no blind retry |
| Order pending | In-flight blocks new entries |
| Duplicate signal | One order |
| Bot restart | Recover / do not add |
| `python3 stop.py` | Graceful stop; flatten only if configured |
| TP / SL | Exit then **bot stopped** |
| Session close | Flatten then stop (when enabled) |
| Daily loss limit | New entries disabled |

---

## 16. AWS 1 GB RAM Deployment

No Docker, database, Redis, PostgreSQL, or web server.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `.env` in this directory (never commit real values):

```text
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Edit `config.yaml` (symbol, quantity, EMA, VWAP, TP, SL, session, `dry_run`). Then:

```bash
python3 main.py
```

Stop from another shell:

```bash
python3 stop.py
```

Keep `bot.candle_lookback` modest (default 80). Polling sleeps; the process does not busy-loop.

---

## 17. Security

- Never commit `.env`.
- Never log or print the access token.
- Restrict SSH on the VM.
- Use least-privilege AWS security groups.
- Keep `dhanhq` and other dependencies updated.
- Live order APIs require Dhan static IP whitelisting.
- Market data requires an active Dhan data plan.

Suggested ignore entries (repo-level `.gitignore` already covers `.env`):

```text
.env
.stop
```

---

## 18. Usage

```bash
pip install -r requirements.txt
python3 main.py
python3 stop.py
```

Change these only in `config.yaml`:

| Setting | Key |
|---------|-----|
| Symbol / ID | `instrument.symbol`, `instrument.security_id` |
| Quantity | `instrument.quantity` |
| EMA periods | `strategy.ema.fast_period`, `slow_period` |
| VWAP filter | `strategy.vwap.enabled`, `strategy.entry.require_vwap_confirmation` |
| Candle / volume | `strategy.entry.candle_confirmation`, `minimum_volume_multiplier` |
| TP / SL | `risk.take_profit`, `risk.stop_loss` (`type`: percentage or points) |
| Polling | `bot.polling_seconds` |
| Session | `trading_session.*` |
| Risk limits | `risk.max_daily_loss`, `max_trades_per_day` |
| Paper vs live | `bot.dry_run`, `bot.allow_live_trading` |
| Entry side | `execution.entry_side` (`BOTH` / `LONG` / `SHORT`) |

---

## 19. Files

| File | Role |
|------|------|
| `main.py` | Entire application |
| `config.yaml` | Tunable parameters (no secrets) |
| `.env` | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` |
| `stop.py` | Creates `.stop` |
| `requirements.txt` | `dhanhq`, `PyYAML`, `python-dotenv`, `rich` |
| `architecture.md` | This chapter |

`docs/` is a reference only. The runtime does not import it. You can delete `docs/` after development and the algo still runs.
