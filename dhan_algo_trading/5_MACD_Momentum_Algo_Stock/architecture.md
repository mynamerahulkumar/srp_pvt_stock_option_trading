# MACD Momentum Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity on **completed** candles using a MACD / Signal Line crossover. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the mathematics, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Parameter tuning, backtesting, and paper trading exist to improve robustness and risk-adjusted behaviour. They do not make live results certain.

---

## 1. Strategy Overview

MACD (Moving Average Convergence Divergence) measures the distance between a fast exponential moving average and a slow one. When that distance itself is smoothed, the result is a second line called the Signal Line. The difference between MACD and Signal is the Histogram.

```text
MACD      = EMA(fast) − EMA(slow)
Signal    = EMA(MACD, signal)
Histogram = MACD − Signal
```

Default periods in `config.yaml` are the common 12 / 26 / 9 set. Those numbers are not magic. They are a starting point.

**Why MACD can be used for momentum trading**

- When the fast EMA pulls away above the slow EMA, recent prices have been rising faster than the longer average. That is one definition of bullish momentum.
- When the fast EMA falls below the slow EMA, recent prices have been falling faster. That is one definition of bearish momentum.
- The Signal Line is a slower version of that momentum. A cross of MACD through Signal is a change in the *rate* of the move, not just in price.

**What a crossover means**

A crossover is an **event**, not a standing condition. `detect_crossover()` requires:

```text
Bullish: previous MACD <= previous Signal  AND  current MACD > current Signal
Bearish: previous MACD >= previous Signal  AND  current MACD < current Signal
```

`MACD > Signal` on every 5-second poll is **not** a new signal. The same completed candle is processed once (`last_processed_candle`).

**MACD line vs Signal line**

- MACD line: faster, more noise, earlier.
- Signal line: slower, later, used as the trigger.

**Histogram**

- Histogram > 0: MACD is above Signal (bullish momentum as defined here).
- Histogram < 0: MACD is below Signal.
- Histogram shrinking toward zero: momentum is fading, even if the last cross has not reversed yet.

Optional YAML filters can require histogram sign, a trend SMA, RSI confirmation, or a minimum volume. They are gates, not a second strategy.

---

## 2. Strategy Rules

### Long Entry

```text
MACD crosses above Signal
+ optional histogram > 0
+ optional close > trend SMA
+ optional RSI >= rsi_min
+ optional volume >= minimum_volume
+ validate_trade() allows the order
= LONG entry (BUY)
```

### Short Entry

```text
MACD crosses below Signal
+ optional histogram < 0
+ optional close < trend SMA
+ optional RSI <= rsi_max
+ optional volume >= minimum_volume
+ validate_trade() allows the order
= SHORT entry (SELL)
```

`generate_signal()` never calls Dhan. Orders happen only after `validate_trade()` in `process_new_candle()`.

`execution.allow_short: false` blocks shorts even when the crossover fires (`SHORT_DISABLED`). The same exists for longs.

Startup behaviour is `WAIT_FOR_SIGNAL`. The bot never places an entry just because it started.

---

## 3. Example Trade Walkthrough

These numbers are **illustrative**. They are not a forecast.

```text
Instrument : example stock
Timeframe  : 5 minutes
Quantity   : 100
Entry      : ₹500
Stop loss  : 1%
Take profit: 2%
```

For a LONG:

```text
Entry = ₹500
SL    = 500 × (1 − 0.01) = ₹495
TP    = 500 × (1 + 0.02) = ₹510
```

If take-profit is reached:

```text
Gross P&L = (510 − 500) × 100
          = ₹1,000
```

For a SHORT at the same entry:

```text
SL    = 500 × (1 + 0.01) = ₹505
TP    = 500 × (1 − 0.02) = ₹490
Gross P&L at TP = (500 − 490) × 100 = ₹1,000
```

If `risk.estimated_cost_per_trade` is 40, the CLI labels the result as an **estimate**: ₹960. The program does not invent brokerage or tax tables.

A 0.75% trailing stop on a LONG whose high since entry is ₹508:

```text
Trailing SL = 508 × (1 − 0.0075) ≈ ₹504.19
Effective SL = max(fixed 495, trail 504.19) = ₹504.19
```

Actual fills depend on liquidity, slippage, gaps, and Dhan converting some MARKET orders to limit-with-MPP. Software-polled exits are not exchange stop orders.

After TP, SL, or trailing stop the **process stops**. It does not hunt for a second trade.

---

## 4. Complete Architecture

```text
Configuration (.env + config.yaml)
     ↓
Dhan API client
     ↓
Market Data (completed candles + LTP)
     ↓
Candle Engine (one bar, once)
     ↓
Indicator Engine (EMA / MACD / optional SMA / RSI)
     ↓
Signal Engine (crossover + filters)
     ↓
Risk Engine (session, cooldown, daily caps, flat check)
     ↓
Execution Engine (dry-run fill or place_order once)
     ↓
Position Manager (broker is authoritative)
     ↓
Exit Engine (TP / SL / trail / day-end / manual / risk)
     ↓
CLI
```

| Component | What it does | Why it exists |
|-----------|----------------|---------------|
| Configuration | YAML tunables, `.env` secrets | Secrets never sit next to strategy numbers |
| Dhan API | REST candles, LTP, positions, orders | One SDK client, no invented endpoints |
| Market Data | Bounded lookback, completed bars only | 1 GB RAM; no in-progress MACD |
| Candle Engine | `last_processed_candle` | Stops the 5s poll from re-firing one cross |
| Indicator Engine | Pure Python EMA / MACD / SMA / RSI | No pandas on a small VM |
| Signal Engine | Event crossover + optional gates | Strategy stays testable without Dhan |
| Risk Engine | Session clocks, caps, cooldown | A good signal is not always a legal trade |
| Execution Engine | Single `submit_order()` | No duplicate `place_order` on timeout |
| Position Manager | Reconcile to broker book | Never assume a submit was a fill |
| Exit Engine | Software TP/SL/trail; then stop | Spec requires a terminal session after TP/SL |
| CLI | Rich Live panel | Operator sees *why* it is not trading |

There is no database, Redis, Docker, or second process. `stop.py` only writes `.stop`.

---

## 5. Function-by-Function Explanation

This list matches `main.py`. Helpers with a leading underscore are grouped.

### Startup and configuration

| Function | Purpose |
|----------|---------|
| `parse_cli_args()` | Optional `--config` path. |
| `load_config()` | Read YAML. No network. |
| `validate_config()` | Fail before any order if MACD periods, quantity, clocks, or product/segment are illegal. `fast_period >= slow_period` is fatal. |
| `validate_safety_config()` | Live needs **both** `bot.dry_run: false` and `bot.allow_live_trading: true`. |
| `load_environment()` | `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN`. Never logs tokens. |
| `is_dry_run()` / `is_live_mode()` | Dry-run is anything that is not fully unlocked live. |
| `normalize_timeframe()` | `5m` → `5`, `1D` → `DAY`. Dhan intervals: 1, 5, 15, 25, 60, DAY. |
| `setup_logging()` | Stderr + in-memory event ring. Filters lines that mention tokens. |

### Stop and time

| Function | Purpose |
|----------|---------|
| `consume_leftover_stop_file()` | Delete a stale `.stop` once at startup. |
| `stop_requested()` | `.stop` exists or SIGINT/SIGTERM. |
| `announce_manual_stop_if_needed()` | Prints `MANUAL STOP REQUEST RECEIVED` once. |
| `check_trading_window()` | Three clocks + weekend + `bot.enabled`. |
| `is_before_session_start()` / `is_after_stop_entry()` / `is_after_close_positions()` | Day-trading gates. Weekends do not auto-flatten. |
| `is_market_expected_open()` | Weekday and inside the session when hours are enabled. |
| `interruptible_sleep()` | 250 ms slices so `stop.py` is noticed quickly. |

### Dhan and market data

| Function | Purpose |
|----------|---------|
| `create_dhan_client()` | `DhanContext` when present; legacy fallback otherwise. |
| `get_market_data()` | `intraday_minute_data` or `historical_daily_data`. Drops the in-progress bar. Caps lookback. |
| `validate_candles()` | Rejects non-positive or inconsistent OHLC. |
| `get_ltp()` | `ticker_data`, ≥1.05 s apart. Keeps last good LTP on a blip. |
| `get_positions()` / `get_open_position()` | `None` on read failure so an API error is never treated as flat. |

### Indicators and signal

| Function | Purpose |
|----------|---------|
| `calculate_ema()` | SMA seed, then `k = 2/(period+1)`. |
| `calculate_sma()` | Trend filter. |
| `calculate_rsi()` | Wilder RSI, optional confirmation only. |
| `calculate_macd()` | MACD, Signal, Histogram. |
| `detect_crossover()` | Event test on two completed bars. |
| `calculate_indicators()` | Bundle for one candle list. |
| `generate_signal()` | LONG / SHORT / NONE after filters. **No Dhan calls.** |

### Risk, P&L, exits

| Function | Purpose |
|----------|---------|
| `calculate_stop_loss()` / `calculate_take_profit()` / `calculate_exit_levels()` | PERCENT or POINTS, rounded to tick. |
| `arm_risk_levels()` | Store TP/SL after a fill. |
| `update_trailing_stop()` | LONG: `highest × (1 − trail%)`. SHORT: `lowest × (1 + trail%)`. |
| `effective_stop_loss()` | More protective of fixed and trailing. |
| `calculate_pnl()` | LONG `(px − entry) × qty`. SHORT `(entry − px) × qty`. Gross. |
| `estimated_net_pnl()` | Subtracts `estimated_cost_per_trade` only when > 0, and labels it. |
| `check_risk_limits()` / `daily_risk_blocked()` | Max trades / daily loss / daily profit. |
| `validate_trade()` | Vetoes a signal. Never places an order. |
| `monitor_tpsl()` | SL (or trail) before TP. Returns a reason code. |
| `exit_position(reason=...)` | Named exit used by the CLI. |

### Orders

| Function | Purpose |
|----------|---------|
| `submit_order()` | **Only** `place_order` call site. Never retries on timeout. Recovers via tag `M…`. Dry-run returns `DRYRUN`. |
| `place_entry_order()` / `place_exit_order()` | Configured quantity and order type. |
| `finalize_submitted_order()` | Wait, interpret fill/reject/partial. Partials are not topped up. |
| `find_order_id_after_uncertain_place()` | Correlation ID then order book. |
| `close_all_positions()` | Only the configured security when `safety.manage_only_configured_symbol` is true. |
| `reconcile_state()` / `recover_existing_state()` | Broker book wins. Restart does not add a second entry. |

### Loop and CLI

| Function | Purpose |
|----------|---------|
| `process_new_candle()` | One completed bar → signal → maybe entry. |
| `run_one_poll_cycle()` | Stop, flatten clock, pending order, reconcile, LTP, TP/SL, then candles. |
| `run_trading_loop()` | Poll interval ≠ CLI refresh. |
| `graceful_shutdown()` | Stop entries, optional flatten, cancel pendings, print daily P&L. |
| `render_startup_banner()` / `render_dashboard()` / `render_exit_banner()` | Spec banners and in-place dashboard. |
| `main()` | Wire the above. Exit code 0/1. |

Dataclasses: `Candle`, `MacdPoint`, `BotState`. Exceptions: `ConfigError`, `SafetyError`, `CredentialError`.

---

## 6. Main Loop Walkthrough

Every trading API cycle (`bot.polling_seconds`, default 5):

```text
1. Wake up
2. Check stop request (.stop / signal) → MANUAL_STOP
3. If weekday past close_positions_time → TRADING_DAY_END
4. Sync any in-flight order (no new signal while pending)
5. Reconcile broker position every N cycles
6. Fetch LTP; update trailing extrema and unrealized P&L
7. If in position: evaluate TP / SL / trail; on hit, exit, show banner, stop
8. If flat: check daily risk and cooldown
9. Fetch completed candles (not every CLI redraw)
10. If this candle was already processed: update displayed MACD only
11. Else calculate MACD, detect crossover, apply filters
12. validate_trade(); if allowed, submit one entry
13. Refresh CLI from memory
14. Sleep in interruptible slices
```

The dashboard can redraw every `cli.refresh_seconds` (default 1) **without** calling Dhan.

---

## 7. TP/SL Lifecycle

```text
Entry fill
 ↓
arm_risk_levels() stores TP, fixed SL, seeds high/low
 ↓
Each poll: update high/low, trailing SL, unrealized P&L
 ↓
monitor_tpsl() — stop first, then take-profit
 ↓
exit_position(reason) + verify
 ↓
Boxed banner (entry, exit, qty, P&L, reason, BOT STOPPED)
 ↓
Process exits — no re-entry
```

**LONG:** price >= TP is take-profit. Price <= effective SL is stop-loss, or `TRAILING_STOP` when the trail has already moved above the fixed SL.

**SHORT:** the inequalities reverse.

Fixed SL is a hard floor (ceiling for shorts). Trailing SL can only move in the trade's favour. Take-profit does not trail.

These are software checks on LTP. A gap can fill through the level. They are not Dhan Super Orders or exchange stops.

---

## 8. Day Trading Mode

When `trading_hours.enabled: true`:

| Clock | Default | Effect |
|-------|---------|--------|
| `start_time` | 09:20 | No entries before this (IST by default) |
| `stop_entry_time` | 15:00 | No **new** entries after this; open trades still managed |
| `close_positions_time` | 15:15 | Flatten configured position, then stop the bot |

Weekends: no entries, no automatic Saturday flatten. The process idles until Monday or until the operator stops it.

When `trading_hours.enabled: false`, those clocks are ignored. The bot still stops after TP/SL/trail, a risk halt, `stop.py`, or a signal.

---

## 9. Risk Management

| Control | Config | Behaviour |
|---------|--------|-----------|
| Max trades / day | `risk.max_trades_per_day` | Default 3. Survives restart via broker order count when live. |
| Max daily loss / profit | `max_daily_loss` / `max_daily_profit` | `0` disables. Explained in the CLI; never a silent halt. |
| Position limit | `max_open_positions` | One open position. Flat required before entry. |
| Cooldown | `execution.cooldown_seconds` | Blocks a new entry after the last trade time. |
| Duplicate protection | `prevent_duplicate_orders` plus code | Broker position, pending orders, in-flight flag, same-candle lock. |
| Unexpected position | `safety.block_if_unexpected_position` | Other symbols block new entries. |
| Notional warning | code constant ₹50,000 | Logs a warning; does not block. |
| Dual live lock | `dry_run` + `allow_live_trading` | Prevents an accidental live flip. |

`place_order` is never retried after a timeout. The bot looks up tag `M…` instead.

---

## 10. Parameter Tuning

### MACD parameters

| Setting | Typical effect |
|---------|----------------|
| Faster (e.g. 6/13/5) | More crosses, more noise, earlier, more false flips |
| 12/26/9 | Common default; used unless you have evidence otherwise |
| Slower (e.g. 19/39/9) | Fewer, later signals; can miss short bursts |

Faster is not “more profitable”. It is more active.

### Timeframe

| Interval | Trade-off |
|----------|-----------|
| 1-minute | Very responsive, a lot of noise, more API history |
| 5-minute | Default balance for this bot |
| 15-minute | Fewer signals, later, calmer |
| 30-minute | Dhan has no 30; `normalize_timeframe()` maps `30m` to `25` and documents that |
| DAY | One completed bar per session; crossover is rare |

Polling every 5 seconds does **not** create a 5-second strategy. The strategy timeframe is the candle.

### Histogram confirmation

Turning it on requires the histogram sign to match the cross. At the exact cross the histogram has usually just changed sign, so this often agrees with the cross. It can reject messy equal-prints. It can also delay a trade if you add extra rules later.

### Trend filter

A 50-period SMA of close blocks longs below the average and shorts above it. That reduces counter-trend crosses. It also skips the start of a reversal that the MACD sees first.

### RSI filter

RSI here is confirmation, not the signal. Example: require RSI >= 50 for longs so you only take momentum that is already on the upper half of the oscillator. That is a choice, not a proof.

### Stop-loss

Tight SL: smaller average loss, more frequent stops, death by noise. Wide SL: fewer stops, larger damage when wrong. Neither is universally better.

### Take-profit

A 1:2 SL:TP (1% / 2%) is the sample default. Higher win rate with a tiny TP is not automatically a better expectancy. Expectancy is `win% × avg win − loss% × avg loss` after costs.

### Trailing stop

Helps when a trend runs past the fixed TP and you would rather lock a high. Hurts when normal noise tags the trail and you are stopped out before the move. Default sample has it **off**.

---

## 11. Strategy Improvement Process

```text
Baseline (this config)
 ↓
Backtest on historical completed candles (same formulas)
 ↓
Measure
 ↓
Change ONE parameter
 ↓
Backtest again
 ↓
Out-of-sample period
 ↓
Dry-run / paper on live data
 ↓
Small live size
 ↓
Monitor
```

Useful metrics: net P&L after costs, max drawdown, win rate, average win, average loss, profit factor, expectancy, trade count, and Sharpe only if you understand the assumptions.

Optimizing every knob on the same two weeks of data is overfitting. A curve-fit MACD will look brilliant in-sample and fail on Monday.

This repository does not ship a backtester. The indicator functions are pure so you can add one later without touching `submit_order()`.

---

## 12. Example Parameter Profiles

Examples only. **Not** guaranteed profitable.

| Profile | Idea | Sketch |
|---------|------|--------|
| Conservative | Slower MACD, trend on, 1 trade/day, wider SL | 19/39/9, trend 50 on, `max_trades_per_day: 1`, SL 1.5%, TP 2.5% |
| Balanced | Sample defaults | 12/26/9, histogram on, SL 1%, TP 2%, 3 trades/day |
| Aggressive | Faster MACD, shorts on, no trend | 6/13/5, filters off, SL 0.6%, TP 1.0% |
| Scalping-oriented | 1-minute, tight trail | timeframe `1`, trail 0.4%, SL 0.4%, TP 0.6% |
| Trend-following | Slow MACD + trend SMA + trail | 12/26/9, trend 50, trail 0.75%, wider TP |

Change one thing at a time. Record the reason.

---

## 13. Failure Scenarios

| Situation | What the bot does |
|-----------|-------------------|
| Dhan API fails / timeout | Log, backoff on **reads**, skip the cycle. No new `place_order`. |
| Order rejected | Clear pending; do not retry blindly. |
| Uncertain `place_order` | Recover by correlation tag / order book. Never send a second order. |
| Internet drop | Last good LTP kept briefly; candles empty → wait. |
| Process restart | Reconcile positions; adopt or refuse; count today's fills. |
| Existing position | Understand it first. Do not add a duplicate. |
| `python stop.py` | `MANUAL STOP REQUEST RECEIVED`. Flatten only if `shutdown.close_positions_on_manual_stop` is true (default false). |
| TP / SL / trail | Exit, banner, **stop the bot**. |
| `close_positions_time` | Flatten, stop. |
| Weekend | Idle, no entries. |
| Insufficient candles | `MACD_WARMUP` / no trade. |
| Invalid config | Process never starts; CLI error. |
| Unexpected exception | `ERROR` shutdown; optional flatten only if configured. |

When something is uncertain, the bot **does not trade more**. It waits or stops.

---

## 14. Deployment

### Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Put real values in .env — never commit them
python main.py
# or
python main.py --config config.yaml
```

From another terminal in the same directory:

```bash
python stop.py
```

Default `bot.dry_run: true` fetches **real** candles and LTP, so credentials are still required. It does not send orders.

### AWS Linux (~1 GB RAM)

- Python 3.10+ (dhanhq 2.2+ uses syntax that needs 3.10).
- No Docker required.
- Run under a lightweight supervisor (`systemd` user unit, or `tmux`). Do not start two copies against the same account and symbol.
- Keep `bot.candle_lookback` modest (sample 120).
- Dependencies are only `dhanhq`, `PyYAML`, `python-dotenv`, `rich`.
- Live **order** APIs need Dhan static-IP whitelist. Data APIs need an active data plan.
- Logs go to stderr. No extra log files are created.

Example systemd idea: `WorkingDirectory=` this folder, `ExecStart=` the venv `python main.py`, `Restart=on-failure` only if you accept that a restart after TP will **not** open a second trade the same way unless a new signal appears — and `max_trades_per_day` plus broker reconcile still apply.

---

## 15. Safety Checklist

Before enabling live trading:

```text
[ ] API credentials verified (profile / data plan / token validity)
[ ] Security ID verified for the intended symbol (do not guess)
[ ] Quantity verified
[ ] Product type verified (CNC vs INTRADAY vs MARGIN; F&O is not CNC)
[ ] Dry-run tested on a live session
[ ] Strategy / crossover tested on completed candles
[ ] TP tested (including the stop-the-bot behaviour)
[ ] SL tested
[ ] Trailing stop tested if you will enable it
[ ] python stop.py tested
[ ] Trading hours tested (start, entry cutoff, flatten)
[ ] Position reconciliation tested (restart with an open fill)
[ ] Risk limits configured and visible in the CLI
[ ] Duplicate-order protection tested (same candle, pending order)
[ ] bot.dry_run: false AND bot.allow_live_trading: true set deliberately
[ ] Static IP whitelisted if you will send live orders
```

---

## 16. Practical Lessons

A strategy that works **logically** (MACD crossed, filters passed, SL is 1%) is not the same as a strategy that works **after** brokerage, STT, exchange charges, slippage, partial fills, and the fact that Dhan may convert a MARKET API order into a limit with MPP.

Live trading requires:

1. Dry-run on the same machine and hours you will use live.
2. A quantity you can afford to be wrong about.
3. Watching the first live session. This is not a “set and forget” product.
4. Accepting that TP/SL here are polled. A gap can skip the exact rupee.
5. Changing one parameter at a time, or you will not know what broke.

The CLI `WHY NO TRADE` line exists so an operator can see *blocked by cooldown* versus *no crossover* versus *API degraded*. If you cannot explain the last decision from the dashboard, do not increase size.

---

## Commands

```bash
python main.py
python main.py --config config.yaml
python stop.py
```

## Live-mode reminder

Real orders require **both**:

```yaml
bot:
  dry_run: false
  allow_live_trading: true
```

Anything else stays dry-run even if market data is live.
