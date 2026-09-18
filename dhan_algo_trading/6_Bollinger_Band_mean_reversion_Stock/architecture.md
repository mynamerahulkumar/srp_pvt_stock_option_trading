# Bollinger Band Mean-Reversion Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity using Bollinger Band mean-reversion on completed candles. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the mathematics, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Parameter tuning, paper trading, and walk-forward testing exist to improve robustness and risk-adjusted behaviour. They do not make live results certain. Actual realized P&L differs from the examples after brokerage, STT, exchange charges, GST, SEBI charges, stamp duty, slippage, and taxes.

---

## 1. Strategy Overview

The program watches one configured stock, computes Bollinger Bands on **completed** candles, and looks for price to reach an extreme band. After risk checks it may open one position at a time. The natural target is the middle band (the moving average). Protective take-profit and stop-loss remain available. Any verified exit — take-profit, stop-loss, middle-band, or intraday square-off — **stops the process**. The bot does not hunt for a second trade after a completed exit.

Default objective for a day-trading session:

1. Wait until `trading.start_time` (default 09:20 IST).
2. Wait for a new completed candle.
3. If close is at or below the lower band (`entry_mode: touch`), consider LONG.
4. If close is at or above the upper band, consider SHORT.
5. Manage the open position with SL, then TP / middle-band according to `strategy.exit.mode`.
6. After a verified exit or square-off, stop the process.

`max_trades_per_day` and `cooldown_seconds` only block extra **entries** before that first completed exit (for example a rejected order plus a later retry).

---

## 2. What Are Bollinger Bands?

Bollinger Bands, introduced by John Bollinger, wrap a moving average with two volatility envelopes.

- **Middle band:** simple moving average of closes.
- **Upper / lower bands:** middle ± a multiple of the standard deviation of the same window.

When volatility expands, the bands widen. When volatility contracts, they squeeze. Price spending time near a band is a **condition**, not a promise that it will revert. Strong trends can “walk the band” for many bars. That is why this bot always keeps a stop-loss and why mean-reversion can perform poorly in directional markets.

---

## 3. Mathematical Formula

For a window of `N` completed closes (`strategy.bollinger_period`, default 20):

```text
Middle = SMA(N) = (C1 + C2 + ... + CN) / N

Population stdev:
    variance = Σ (Ci − Middle)² / N
    σ        = sqrt(variance)

Upper = Middle + k × σ
Lower = Middle − k × σ
```

`k` is `strategy.bollinger_stddev` (default 2.0).

This implementation uses **population** standard deviation (divide by N, not N−1). That matches the common TradingView / charting convention. Sample stdev (N−1) would make the bands slightly wider.

Implementation: `calculate_bollinger_bands()` and `_population_stdev()` in `main.py`. Early bars are `None` until the first full window exists. The function never looks at future candles.

---

## 4. How Mean Reversion Works

Mean reversion assumes that an extended move away from a local average tends, on average, to travel back toward that average — not that it must, and not that it will do so before a stop is hit.

In this bot:

- A lower-band touch is treated as a potential **oversold** extreme → LONG toward the middle.
- An upper-band touch is treated as a potential **overbought** extreme → SHORT toward the middle.
- The middle band is the strategy’s natural target (`exit.mode: middle_band`).
- Protective TP/SL are computed from the fill price and remain armed.

If price keeps trending after a band touch, the stop-loss is what limits the loss. Increasing TP or tightening SL is not automatically an improvement; it changes the payoff distribution.

---

## 5. Long Entry Logic

Default LONG (`strategy.entry_mode: touch`, `signal_on_closed_candle: true`):

```text
Latest completed close <= lower band
AND
validate_trade() / check_entry_conditions() allows the order
```

Optional `close_back_inside_band`:

```text
Prior completed candle touched or broke the lower band
    (close <= lower OR low <= lower)
AND
Current completed close is back inside the bands
    (lower < close < upper)
```

`generate_signal()` never calls Dhan. Orders happen only after `check_entry_conditions()` in `process_new_candle()`.

`trading.allow_long: false` blocks longs even when the signal fires.

---

## 6. Short Entry Logic

Default SHORT (`touch`):

```text
Latest completed close >= upper band
AND
check_entry_conditions() allows the order
```

Optional `close_back_inside_band`:

```text
Prior candle touched or broke the upper band
AND
Current close is back inside the bands
```

`trading.allow_short: false` blocks shorts. NSE equity shorts require an eligible product type such as `INTRADAY` (not CNC).

---

## 7. Exit Logic

`strategy.exit.mode` selects the strategy target. Protective stop-loss is always evaluated first.

| Mode | Exit when |
|------|-----------|
| `middle_band` | LTP reaches the current middle band (and SL if hit first) |
| `fixed_tp` | Configured take-profit (and SL if hit first) |
| `middle_band_or_tp` | Whichever of middle band or TP comes first (SL still first) |

Long middle-band exit: `LTP >= middle`. Short: `LTP <= middle`. Implementation: `check_strategy_exit()` and `monitor_exits()`.

After a verified exit the process stops. It does not immediately re-enter.

---

## 8. Take Profit

Configured under `risk.take_profit`:

```yaml
enabled: true
type: percent   # or points
value: 1.0
```

```text
LONG  TP = entry + distance
SHORT TP = entry − distance
```

Distance is `entry × value/100` for percent, or `value` for points. Prices are rounded to `instrument.tick_size`. Software polling can overshoot the exact price because of interval, API latency, slippage, and gaps.

When TP is reached: exit → verify fill → verify flat (live) → display realized P&L → stop the bot.

---

## 9. Stop Loss

Configured under `risk.stop_loss`:

```yaml
enabled: true
type: percent
value: 0.5
```

```text
LONG  SL = entry − distance
SHORT SL = entry + distance
```

SL is evaluated **before** TP and middle-band so a gap through both levels prefers capital protection. Same verification and process-stop behaviour as take-profit.

---

## 10. Position Sizing

`position_sizing.mode: fixed_quantity` is implemented. Quantity is validated as a positive whole number before any order.

Reserved (rejected at startup until implemented):

- `capital_percent`
- `risk_based`

`calculate_position_size()` is the single place that returns quantity so later modes can be added without touching order placement.

---

## 11. Risk Management

| Control | Config | Behaviour |
|---------|--------|-----------|
| Max trades / day | `risk.max_trades_per_day` | Blocks new entries after N successful entries (survives restart via broker order book when possible) |
| Max daily loss | `risk.max_daily_loss` | Blocks new entries when session realized P&L ≤ −limit |
| Max open positions | `risk.max_open_positions` | Default 1; a second entry is refused while a position is open |
| Cooldown | `risk.cooldown_seconds` | Blocks a new entry for N seconds after the last attempt/fill |
| Kill switch | `safety.kill_switch` | Refuses start / stops new entries |
| Duplicate protection | candle timestamp + in-flight flag + broker pending orders | Same candle cannot fire twice |

These limits do **not** keep the bot running after a completed strategy/TP/SL/square-off exit. That exit is terminal for the process.

---

## 12. Intraday Mode

When `trading.intraday_mode: true`, clocks are `Asia/Kolkata` (never the VM timezone):

| Time | Default | Behaviour |
|------|---------|-----------|
| `start_time` | 09:20 | No entries before |
| `stop_entry_time` | 15:00 | No new entries; open positions are still managed |
| `square_off_time` | 15:15 | Flatten managed positions, verify, stop |

When `intraday_mode: false` there is no mandatory time window. Strategy and risk controls still apply.

`check_trading_window()` returns `BEFORE_START`, `ENTRIES_OPEN`, `STOP_ENTRY`, `SQUARE_OFF`, or `ALWAYS_OPEN`.

---

## 13. System Architecture

Logical layers inside `main.py` (one process, no extra packages):

```text
CONFIGURATION
      ↓
Dhan API
      ↓
MARKET DATA
      ↓
INDICATOR CALCULATION
      ↓
SIGNAL ENGINE
      ↓
RISK ENGINE
      ↓
ORDER ENGINE
      ↓
POSITION MANAGEMENT
      ↓
EXIT ENGINE
      ↓
CLI / MONITORING
```

Constraints:

- Python 3.10+, local laptop or AWS Linux with about 1 GB RAM
- No database, Redis, Docker, web server, or multiprocessing
- Secrets in `.env`, tunables in `config.yaml`
- Graceful stop via `stop.py`, Ctrl+C, or SIGTERM

---

## 14. Dhan API Flow

Preferred official SDK (`dhanhq` + `DhanContext` when available):

| Need | Method |
|------|--------|
| Minute history | `intraday_minute_data(...)` |
| Daily history | `historical_daily_data(...)` |
| Last price | `ticker_data(...)` (1 request/sec) |
| Positions | `get_positions()` |
| Order book | `get_order_list()`, `get_order_by_id()` |
| Place / cancel | `place_order()`, `cancel_order()` |

Response wrapper is `{"status": "success"|"failure", "remarks": ..., "data": ...}`. Accept is not a fill. Quote APIs are rate-limited; the bot spaces ticker calls by ~1.05s and reuses the last good LTP on a transient failure.

`docs/Dhan_SRP.py` was a development reference only. Runtime does not import it.

---

## 15. Main.py Function Architecture

Representative functions (each has a docstring covering purpose, inputs, outputs, and safety):

| Layer | Functions |
|-------|-----------|
| Config | `load_environment`, `load_config`, `validate_config`, `validate_safety_config` |
| Dhan | `create_dhan_client`, `check_api_connection` |
| Data | `get_market_data`, `get_historical_candles`, `get_ltp` |
| Indicator | `calculate_bollinger_bands` |
| Signal | `generate_signal` |
| Risk | `check_risk_limits`, `check_entry_conditions`, `check_trading_window` |
| Sizing / levels | `calculate_position_size`, `calculate_stop_loss`, `calculate_take_profit` |
| Orders | `place_entry_order`, `place_exit_order`, `get_order_status`, `wait_for_order_fill` |
| Position | `get_current_position`, `manage_open_position`, `reconcile_position_state` |
| Exits | `check_take_profit`, `check_stop_loss`, `check_strategy_exit`, `square_off_all_positions` |
| Loop | `process_trading_cycle`, `run_trading_loop`, `handle_shutdown`, `main` |
| CLI | `render_startup_banner`, `display_terminal_dashboard` |

---

## 16. Complete Trading Cycle

Every `runtime.polling_seconds` (default 5):

1. Check stop file / kill switch.
2. Classify the trading window.
3. Check risk limits.
4. Sync any in-flight order (never place a second one).
5. Reconcile with Dhan every N cycles.
6. Fetch LTP and a bounded candle window.
7. Recalculate Bollinger Bands.
8. If a position is open, manage exits (SL → TP → middle).
9. If flat and entries are allowed, evaluate one new candle.
10. Place an order only if every safety check passes.
11. Verify fill before treating a position as active.
12. Update state and redraw the dashboard.
13. Sleep.

---

## 17. Order Lifecycle

```text
SIGNAL
  → check_entry_conditions
  → submit_order (or DRY RUN simulate)
  → wait_for_order_fill
  → confirm_position_after_fill (broker book wins)
  → arm TP/SL
  → monitor_exits
  → place_exit_order
  → verify flat
  → stop process
```

Rules:

- Never retry `place_order` after an uncertain timeout; recover by correlation tag / order book.
- Partial fills are kept; the remainder is not automatically re-sent.
- Rejected orders do not create a local position.
- LIMIT is never rewritten to MARKET.

---

## 18. Startup Sequence

1. Load `.env`.
2. Load `config.yaml`.
3. Validate configuration.
4. Enforce live locks (`environment: live` + `allow_live_trading` + `dry_run: false`).
5. Clear a leftover `.stop`.
6. Create the Dhan client and check connectivity.
7. Fetch positions and orders; reconcile.
8. Adopt an existing configured position if recovery is enabled.
9. Display the banner and start the loop.

Live orders require all three live locks. The bot will not silently switch from dry-run to live.

---

## 19. Shutdown Sequence

`stop.py` writes `.stop`. `main.py` also handles SIGINT and SIGTERM.

If `safety.close_positions_on_shutdown: false` (default):

```text
STOP REQUESTED
→ STOP NEW ENTRIES
→ LEAVE POSITIONS UNCHANGED
→ BOT OFFLINE
```

If true:

```text
STOP REQUESTED
→ STOP NEW ENTRIES
→ CLOSE ALL OPEN POSITIONS
→ VERIFY POSITIONS CLOSED
→ BOT OFFLINE
```

Pending orders are cancelled when `shutdown.cancel_pending_orders` is true.

---

## 20. Square-Off Sequence

At `square_off_time` (intraday mode):

- Stop new entries.
- Close managed strategy positions (`square_off_all_positions`).
- Verify the broker book.
- Display realized P&L.
- Stop the bot.

If already flat, the bot simply stops after square-off. Only the configured security is flattened when `safety.manage_only_configured_symbol` is true.

---

## 21. Error Handling

Handled without crashing the process when the error is recoverable:

- Invalid YAML / missing env vars (fail at startup with a clear message)
- API timeout / connection failure (bounded retries + backoff)
- Malformed payloads (treat as no-data, do not order)
- Order rejection / partial fill
- Stale LTP (reuse last good tick; do not disarm exits blindly)
- Unexpected position (block new entries if configured)
- Keyboard interrupt / stop request

Critical safety conditions stop trading rather than continuing blindly. Recoverable data errors wait for the next poll.

---

## 22. Duplicate Order Protection

Mechanisms used together:

- One evaluation per candle timestamp (`last_processed_candle`)
- `order_in_flight` / pending order id
- Broker pending-order scan
- Flat-before-entry
- Restart recovery of an existing Dhan position
- No `place_order` retry after an uncertain submit

The same lower-band condition staying true for many 5-second polls must not produce many BUY orders.

---

## 23. Restart Recovery

```text
Dhan Position
      ↓
Read current position
      ↓
Reconcile local strategy state
      ↓
Adopt and manage the existing position (if configured)
      ↓
Continue safely — never open a second entry because memory was lost
```

Today’s trade count is estimated from the broker order book so `max_trades_per_day` is not reset by a crash.

---

## 24. Dry Run Mode

Default: `safety.dry_run: true` and `bot.environment: paper`.

- Real market data is fetched.
- Signals, theoretical entry/exit, and simulated P&L are shown.
- The CLI displays `MODE: DRY RUN`.
- `place_order` is never called.

Live mode is explicit and noisy. Do not treat paper fills as broker fills after a restart.

---

## 25. CLI Dashboard

A lightweight Rich terminal (SSH-safe) shows:

- System / engine / API / mode
- Symbol, LTP, Bollinger upper / middle / lower
- Current signal and why-no-trade
- Position, quantity, entry, SL, TP, unrealized and realized P&L
- Next scan countdown
- Recent event stream

Dashboard refresh (`cli.refresh_seconds`) does not call Dhan by itself. Trading API calls stay on `runtime.polling_seconds`.

---

## 26. Example Trade

```text
Stock: Example Stock
Timeframe: 5 minutes
Bollinger Period: 20
Standard Deviation: 2

Middle Band: ₹1,000
Upper Band: ₹1,030
Lower Band: ₹970

Price closes at ₹968.
The lower-band entry condition is satisfied.

Bot:
→ verifies no existing position
→ verifies session, risk, cooldown, pending orders
→ quantity = 100 (example; default config uses 1)
→ SL and TP from config
→ submits BUY
→ waits for fill
→ confirms position
```

If price later returns to the middle band, `exit.mode: middle_band` exits around ₹1,000.

---

## 27. Example Profit Calculation

```text
Entry = ₹968
Exit  = ₹1,000  (middle band)
Quantity = 100

Gross P&L:
₹32 × 100 = ₹3,200
```

This is **gross**. After brokerage, STT, exchange charges, GST, SEBI charges, stamp duty, slippage, and taxes the net result is smaller. The bot’s displayed P&L is an estimate from prices, not a contract note.

---

## 28. Example Loss Calculation

```text
Entry = ₹968
SL    = ₹963
Quantity = 100

Gross loss:
₹5 × 100 = ₹500
```

A gap through the stop can be worse than ₹500. Software-polled SL is not an exchange stop-loss order. Do not assume the fill equals the stop price.

---

## 29. Parameter Tuning

| Parameter | Smaller / tighter | Larger / wider |
|-----------|-------------------|----------------|
| Bollinger period | More responsive, more noise, more false touches | Smoother, fewer signals, slower |
| Standard deviation | Bands closer, more touches, more noise | Fewer extremes, fewer trades |
| Timeframe | Faster decisions, more costs | Slower, fewer trades |
| `touch` vs `close_back_inside_band` | `touch` is earlier; re-entry waits for confirmation | Re-entry misses some moves, filters some falling knives |
| Closed-candle confirmation | On (default): no look-ahead on the forming bar | Off: uses the in-progress bar (still one signal per timestamp) |
| Stop loss | Tighter: more scratches, smaller average loss | Wider: fewer stops, larger average loss |
| Take profit / middle-band | Closer target: higher hit rate, smaller wins | Farther: fewer completions, larger wins when they happen |
| Position size | Linearly scales P&L and risk | Does not improve expectancy |
| Max trades / cooldown | Caps activity before the first completed exit | Does not create edge |

Optimization should use out-of-sample data, walk-forward testing, transaction costs, slippage, and more than one market regime. Tuning does not guarantee profit.

---

## 30. Backtesting Considerations

Live execution must not use future information.

```text
Candle N completes
↓
Calculate bands using information available at Candle N
↓
Generate signal
↓
Execute at a realistic next available price (LTP / next bar)
```

Avoid assuming you traded Candle N’s open, high, or low using Candle N’s final close unless the execution model truly supports it.

This repository is a **live/paper poller**, not a historical backtester. If you backtest elsewhere, include costs, slippage, and session rules that match `config.yaml`.

---

## 31. Common Failure Modes

- **Trend walk:** price rides the upper or lower band; mean reversion loses until SL.
- **Gap through SL/TP:** poll interval plus overnight/news gaps.
- **Stale data:** empty candle payload; bot waits, does not order.
- **Rejected order:** local state stays flat; cooldown may apply.
- **Restart while in a trade:** recovery adopts the broker position.
- **Wrong product type:** CNC cannot short; validation warns via product rules.
- **Timezone mistakes:** all session clocks are `Asia/Kolkata`.
- **Live lock mis-set:** dry-run stays on unless all three live flags agree.

---

## 32. Practical Improvements

Ideas that may improve robustness — none guarantee profit:

- Trade liquid names; avoid wide spreads.
- Use a timeframe that matches holding time and costs.
- Avoid event windows unless the system is designed for them.
- Test high- and low-volatility regimes separately.
- Add volume or trend filters if bands fail during strong trends.
- Limit activity after a cluster of failed reversions.
- Study session-specific behaviour (open auction vs afternoon).
- Always include costs and slippage in any research.
- Use walk-forward validation.

Mean-reversion strategies can perform poorly during strong directional trends.

A trader should evaluate expectancy, win rate, average win, average loss, profit factor, maximum drawdown, Sharpe/Sortino where appropriate, trade count, costs, slippage, and regime sensitivity. Raising TP or cutting SL is not automatically better.

---

## 33. Production Deployment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# edit .env with Dhan credentials
# review config.yaml; leave dry_run: true until paper behaviour is understood
python3 main.py
```

In another shell:

```bash
python3 stop.py
```

Do not commit `.env`. Order APIs require Dhan static-IP allowlisting. Data APIs require an active Dhan data plan.

---

## 34. AWS 1GB VM Deployment

Keep the process small:

- No pandas, numpy, ML frameworks, databases, or GUI toolkits
- Bounded candle lookback (`runtime.candle_lookback`)
- Rich CLI only (works over SSH)
- Single process, in-memory state

Suggested:

- Amazon Linux or Ubuntu, 1 GB RAM, Python 3.10+
- `systemd` user service or `tmux`/`screen` to keep `python3 main.py` alive
- Timezone of the VM does not matter; the bot uses `Asia/Kolkata`
- Monitor memory; if RSS grows, reduce lookback

---

## 35. Testing Checklist

Reason through these scenarios against `process_trading_cycle()`:

1. **No position + no signal** → no order.
2. **Lower-band signal** → BUY path → risk → order → fill verify → manage.
3. **Upper-band signal** → SHORT path → same.
4. **Existing position** → no second entry; manage exits.
5. **TP reached** → exit → verify → P&L → stop.
6. **SL reached** → exit → verify → P&L → stop.
7. **Square-off time** → flatten → verify → stop.
8. **Manual stop** → follow `safety.close_positions_on_shutdown`.
9. **Daily loss limit** → no new trades.
10. **Restart with a Dhan position** → reconcile → manage, do not double-enter.
11. **API temporarily down** → bounded retry; no duplicate place.
12. **Order rejected** → no assumed position; continue safely or stop if configured critical.

Also verify: syntax, config keys, short-side math, IST clocks, dry-run never calls `place_order`, and no secrets in logs.
