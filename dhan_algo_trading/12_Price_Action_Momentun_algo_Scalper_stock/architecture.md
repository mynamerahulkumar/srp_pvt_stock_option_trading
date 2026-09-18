# Price Action Momentum Scalper

A configuration-driven, single-process Dhan bot that trades one NSE instrument using **completed-candle breakouts plus candle-body strength**. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the formulas, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Historical performance is not a guarantee. Live execution differs from backtests. Slippage, brokerage, taxes, liquidity, and gaps matter. Parameters should be validated with out-of-sample testing. Risk management is essential. The objective is a robust, configurable engine, not a guaranteed-profit system.

---

## 1. Strategy Overview

**Price-action momentum** here means: price has left a recent range on a candle that is mostly body, not wick. The bot does not stack RSI, MACD, or a large indicator suite. It asks four inspectable questions about the last **completed** candle:

1. Did the close break the prior N-bar high (long) or low (short)?
2. Was the candle itself directional (`close > open` or `close < open`)?
3. Was the body large enough versus the high–low range?
4. Do the optional volume and trend filters agree?

**Why a breakout can work**

A prior high or low is a visible reference. Resting orders often cluster there. When that level is taken out, short-covering or long-covering can accelerate the next few ticks. Scalpers try to capture that short burst and exit at a small, predefined target.

**Why candle-body strength is used**

A close that barely ticks through a high on a long-wick bar is often a probe, not acceptance. Requiring `body_ratio >= minimum_body_ratio` asks the candle to travel most of its range in the breakout direction.

**Why volume confirmation can help**

A silent break is easier to fade. Comparing the evaluation bar’s volume to a prior average is a simple participation filter. It is optional because thin names and opening minutes can distort volume.

**Why false breakouts occur**

The level is probed, liquidity is pulled, and price returns inside the range. No filter removes this. Cooldown, one-position-at-a-time, daily trade caps, and tight TP/SL exist to limit how much one failed break can cost.

**Why scalping needs strict risk**

Targets are small. A few oversized losses or a duplicate entry after a restart can erase a session. The bot stops after a verified TP/SL exit by default, persists state, and never retries `place_order` on an uncertain submit.

---

## 2. Strategy Rules

All signal math uses **completed** candles. The forming bar is never used for entry.

```text
breakout_high = max(high of the previous lookback_candles bars)
breakout_low  = min(low of the previous lookback_candles bars)
body_size     = abs(close - open)
candle_range  = high - low
body_ratio    = body_size / candle_range     (0 if range is 0)
```

The evaluation candle is **excluded** from the lookback high/low so a bar cannot break its own high.

### Long

```text
close > breakout_high
AND close > open
AND body_ratio >= minimum_body_ratio
AND (optional) current_volume >= average_volume * volume_multiplier
AND (optional) fast EMA > slow EMA
AND (optional) (close - breakout_high) / breakout_high * 100 >= minimum_price_move_percent
```

### Short

```text
close < breakout_low
AND close < open
AND body_ratio >= minimum_body_ratio
AND the same optional volume / trend / minimum-move filters (trend requires fast < slow)
```

### Numerical long example (educational)

```text
Previous 5-candle high = ₹1,000

Breakout candle:
Open  = ₹1,000
High  = ₹1,005
Low   = ₹999
Close = ₹1,004

Body  = 4
Range = 6
Body ratio = 4 / 6 = 66.7%
```

If `minimum_body_ratio` is `0.60`, this candle passes the body filter. The close is above ₹1,000, so the breakout filter also passes. That is a **setup**, not a profitable trade.

A smoke test of this exact candle against the default `config.yaml` produced `LONG`. The same mirror below a ₹995 low produced `SHORT`. Those results validate the formulas; they do not predict live P&L.

### When no trade is taken

The CLI prints `SIGNAL: NONE` and a reason, for example:

- Close has not broken the lookback high or low
- Candle body is too small versus the range
- Volume confirmation failed
- Optional trend confirmation rejected the side
- Cooldown still active
- Maximum trades for today have been reached
- Persisted state could not be trusted

Exits are **not** opposite-signal. They are TP, SL, session stop, emergency stop, or a daily-limit flatten.

---

## 3. Complete Trade Example

These numbers are **hypothetical**. They do not guarantee a fill or a profit.

```text
Long entry fill = ₹1,000
Quantity        = 100
TP type         = PERCENT  0.30
SL type         = PERCENT  0.20
```

```text
TP = 1000 * (1 + 0.30/100) = ₹1,003.00
SL = 1000 * (1 - 0.20/100) = ₹998.00
```

**If TP is hit at ₹1,003**

```text
Gross P&L = (1003 - 1000) * 100 = +₹300
```

**If SL is hit at ₹998**

```text
Gross P&L = (998 - 1000) * 100 = −₹200
```

**Short mirror at the same fill**

```text
TP = 1000 * (1 - 0.30/100) = ₹997.00
SL = 1000 * (1 + 0.20/100) = ₹1,002.00
SL hit P&L = (1000 - 1002) * 100 = −₹200
```

The bot uses the **actual average fill** from Dhan when the broker provides it, then tick-rounds levels. Software-polled exits can overshoot the printed price. Brokerage and taxes are not subtracted unless `risk.estimated_cost_per_trade` is set (labelled as an estimate).

A verified TP or SL exit **closes the position and stops the bot** when `risk.stop_bot_after_exit` is true (the default).

---

## 4. Execution Lifecycle

```text
Signal
 → validate_trade (session, cooldown, limits, flat, no pending order)
 → execute_signal / place_entry_order
 → submit_order (or dry-run simulation)
 → wait_for_order_fill
 → FILLED → arm TP/SL from actual fill
 → monitor_position + monitor_tpsl every poll
 → TP HIT or SL HIT
 → exit_position / close_all_positions
 → persist state
 → shutdown
```

HTTP success on `place_order` is **not** a fill. Status is normalized to SUBMITTED / PENDING / FILLED / REJECTED / CANCELLED / UNKNOWN. An ambiguous submit is treated as UNKNOWN. The bot queries the order book / correlation tag and **does not place another entry** until the state is understood.

```text
Configuration (.env + config.yaml)
     ↓
Validate config / unlock live only with two flags
     ↓
Load state/bot_state.json
     ↓
Dhan connection
     ↓
Recover existing positions
     ↓
Polling loop
     ↓
state/STOP / schedule / daily limits
     ↓
If position: LTP → P&L → TP/SL
     ↓
If flat: completed candles → generate_signal → execute_signal
     ↓
CLI
```

| File | Role |
|------|------|
| `main.py` | Entire engine. Does not import `docs/`. |
| `config.yaml` | All non-secret knobs. Every key is read in `validate_config()`. |
| `.env` | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` only. |
| `stop.py` | Writes `state/STOP`. No Dhan import, no network. |
| `requirements.txt` | `dhanhq`, `PyYAML`, `python-dotenv`, `rich`. |
| `architecture.md` | This chapter. Not required at runtime. |

Live orders require **both** `runtime.dry_run: false` and `runtime.allow_live_trading: true`. Dry-run still fetches real market data and simulates fills locally. The CLI shows `MODE: DRY RUN`.

---

## 5. Every Important Function in main.py

Only functions that exist are listed. Tiny numeric helpers such as `_safe_float` are omitted unless they matter to trading safety.

### Configuration, secrets, logging, state

| Function | Purpose | Inputs | Outputs | Failure / safety |
|----------|---------|--------|---------|------------------|
| `load_environment` | Load `.env` | — | process env | Missing credentials raise `CredentialError`. Token is never logged. |
| `load_config` | Parse YAML | path | dict | Invalid YAML stops the bot. |
| `validate_config` | Type-check every spec section; build runtime aliases | config | mutates config | First fatal field raises `ConfigError`. Dangerous values are not silently replaced. |
| `validate_safety_config` | Double-lock live mode | config | — | Live without `allow_live_trading` is refused. |
| `setup_logging` | Console + rotating file | config | handlers | Lines containing `access_token` / `client_id` are dropped from the dashboard ring. |
| `is_dry_run` / `is_live_mode` | Order gate | config | bool | Dry-run never calls `place_order`. |
| `persist_state` | Write `state/bot_state.json` | config, state | file | No secrets. Skipped if state is untrusted. |
| `load_persisted_state` | Restore trade count, candle, pending IDs, TP/SL | config, state | mutates state | Corrupt JSON blocks new entries (`STATE_UNTRUSTED`). |

### Stop and schedule

| Function | Purpose |
|----------|---------|
| `consume_leftover_stop_file` | Deletes a leftover `state/STOP` so a new start is not halted. |
| `stop_requested` / `check_stop_signal` | `state/STOP` or SIGINT/SIGTERM. |
| `announce_manual_stop_if_needed` | Prints `MANUAL STOP REQUEST RECEIVED` once. |
| `session_timezone` / `now_in_session_tz` | Configurable timezone (default `Asia/Kolkata`). No naive local-vs-UTC compares. |
| `check_trading_window` / `check_trading_session` | Allow / deny new entries. When `schedule.enabled` is false, the clock is ignored. |
| `is_after_close_positions` | Weekday at or after `schedule.stop_time`. |
| `interruptible_sleep` | 250 ms slices so `stop.py` is noticed quickly. |

### Dhan wrappers

| Function | Purpose |
|----------|---------|
| `initialize_dhan` / `create_dhan_client` | `DhanContext` or older constructor. Secrets stay in env. |
| `get_market_data` / `get_historical_data` / `fetch_candles` | Bounded `intraday_minute_data` or `historical_daily_data`. Completed bars only. Empty list on failure. |
| `validate_candles` | Drop invalid OHLC / negative volume / bad timestamps. |
| `get_ltp` | `ticker_data`, ~1 request/sec. Falls back to last good LTP. |
| `get_positions` / `get_open_position` | Broker is authoritative. Failed read ≠ flat. |
| `get_order_status` / `get_order_list` / `pending_orders_for_symbol` | Status normalization. |
| `find_order_id_after_uncertain_place` | Recover ID by tag after timeout. Never places again. |
| `submit_order` | Exactly one `place_order`. No retry on timeout. Dry-run simulates. |
| `wait_for_order_fill` / `wait_for_order_completion` | Poll until terminal, timeout, or stop. |
| `place_entry_order` / `place_exit_order` / `exit_position` | Intent wrappers. |
| `execute_signal` | LONG/SHORT → BUY/SELL entry. Strategy never calls Dhan itself. |
| `close_all_positions` | Flatten the configured symbol only. Dedupes exits. Verifies the book. |
| `cancel_pending_orders` | Optional on shutdown. |
| `reconcile_state` / `recover_existing_state` | Restart safety. Adopts an existing position and re-arms TP/SL. Does not add a new entry. |

### Strategy (no broker calls)

| Function | Purpose |
|----------|---------|
| `calculate_candle_metrics` | Body, range, body ratio, direction. |
| `calculate_breakout_levels` | Prior N-bar high/low. Evaluation bar excluded. |
| `calculate_volume_confirmation` | Current vs prior average. Evaluation bar excluded. |
| `calculate_trend_confirmation` / `calculate_ema` | Optional fast/slow EMA. |
| `check_long_signal` / `check_short_signal` | Shared long/short rules. |
| `generate_signal` | LONG / SHORT / NONE plus reasons. |
| `apply_signal_to_state` | Copy numbers onto the dashboard. |

### Risk, TP/SL, loop, CLI

| Function | Purpose |
|----------|---------|
| `calculate_tp_price` / `calculate_sl_price` / `calculate_exit_levels` | From **fill** price. PERCENT or POINTS. Long TP above / SL below; short reversed. |
| `arm_risk_levels` | Store tick-rounded TP/SL. |
| `calculate_pnl` | LONG `(LTP-entry)*qty`, SHORT `(entry-LTP)*qty`. |
| `monitor_position` | Update unrealized P&L and extrema. |
| `monitor_tpsl` | SL first, then TP. |
| `check_risk_limits` / `daily_risk_blocked` | Daily loss / profit / max trades. |
| `cooldown_active` / `validate_trade` / `check_duplicate_order` | Entry vetoes. |
| `process_new_candle` | One completed bar, once. |
| `run_one_poll_cycle` / `run_trading_loop` / `run_strategy_cycle` | Stop → schedule → position/TP-SL → else signal. CLI refresh is independent of the API poll. |
| `render_startup_banner` / `render_dashboard` / `render_exit_banner` | Sci-fi console. |
| `graceful_shutdown` / `handle_shutdown` | Stop entries, optional flatten, persist, print daily P&L. |
| `main` | Load, validate, recover, loop, exit code. |

---

## 6. Configuration Tuning

Percentage values in YAML are **percent units**, not fractions: `0.30` means 0.30%.

| Parameter | Increasing it | Decreasing it | Benefit | Drawback |
|-----------|---------------|---------------|---------|----------|
| `strategy.lookback_candles` | Harder, later breakouts | Easier, more frequent breaks | Fewer noise pokes | Misses or late entries |
| `strategy.minimum_body_ratio` | Only strong-body candles | Accepts more dojis/wicks | Filters weak probes | Misses thin-but-real breaks |
| `strategy.volume_confirmation.volume_multiplier` | Demands more participation | Accepts quieter tape | Fewer silent breaks | Misses valid low-volume names |
| `strategy.volume_confirmation.average_period` | Smoother volume baseline | More reactive baseline | Stable filter | Slow to adapt |
| `strategy.trend_confirmation` on | Trades only with EMA tilt | — | Fewer counter-trend breaks | Fewer signals; EMA lag |
| `risk.take_profit.value` | Larger winner if it hits | Quicker cash-out | Better R if filled | Lower hit rate |
| `risk.stop_loss.value` | More room | Tighter loss | Survives noise | Larger loss per fail |
| `strategy.cooldown_seconds` | Longer wait after a trade | Faster re-entry | Less churn | Misses a second impulse |
| `runtime.polling_seconds` | Less API load | Faster TP/SL notice | Fits 1 GB / rate limits | Slower exit |
| `strategy.max_trades_per_day` | More attempts | Hard cap sooner | More samples | More commission / tilt |
| `daily_limits.max_loss` | Allows a deeper hole | Stops earlier | Stays in a recovery | Can give back more |
| `daily_limits.max_profit` | Lets winners run the day | Banks and stops | Protects a good morning | Caps a trend day |

No combination of these knobs guarantees higher profit.

---

## 7. Profitability Improvement Framework

Use the bot as a **measurement engine**, not as proof of edge.

1. **Historical backtest** on completed 1-minute (or your timeframe) bars with the same look-ahead rules.
2. **Out-of-sample** hold-out after you freeze parameters.
3. **Walk-forward** re-optimization on rolling windows.
4. **Transaction-cost analysis**: brokerage, STT, exchange fees, slippage.
5. **Slippage analysis**: compare signal close vs actual fill (`max_entry_slippage_percent` is a log/warn, not a cancel-and-replace algo).
6. **Parameter sensitivity**: change one knob at a time.
7. Track **max drawdown**, **win rate**, **average win**, **average loss**, **profit factor**, **expectancy**, **risk/reward**, and **regime** (trend vs range days).

The goal is better **risk-adjusted** expectation, not a higher win rate at any cost. Profitability cannot be guaranteed.

---

## 8. False Breakout Handling

Common situations:

- A single tick through the high that closes back inside the range (body filter should reject many of these).
- Opening-range noise on 1-minute bars (raise lookback, enable volume, or start later than 09:20).
- Thin lunch tape that prints a level with no follow-through (volume filter).
- Counter-trend pops in a falling tape (optional EMA confirmation).

Configuration can **reduce** these; it cannot eliminate them. After a loss, cooldown and `max_trades_per_day` stop the bot from immediately fading the same level.

---

## 9. Risk Management

A small, predefined stop plus a small quantity is more important than hunting more signals. The default 0.30% / 0.20% pair is a **starting template**, not an optimized edge.

The bot also enforces:

- One position at a time
- No second order while an order is pending
- One evaluation per completed candle
- Daily trade / loss / profit caps
- Broker reconcile on restart
- Flatten at `schedule.stop_time` when enabled
- Emergency flatten via `python3 stop.py` when `emergency_stop.close_position` is true

---

## 10. Live Trading Safety

- Default is **dry run**. Live needs two YAML flags.
- Start with quantity `1`.
- Temporary API / network errors are logged and retried only on **reads**. `place_order` is never blindly retried.
- Duplicate entries are blocked by position state, pending-order state, traded-candle stamp, and persisted JSON.
- Restart: query Dhan, adopt the configured symbol if a position exists, restore TP/SL from fill, do **not** enter again.
- `python3 stop.py` writes `state/STOP`. Next start deletes a leftover file.
- Daily limits can flatten and stop when `close_position_on_limit` is true.

---

## 11. Deployment

From this directory, after `pip install -r requirements.txt` and filling `.env`:

```bash
python3 main.py
python3 main.py --config config.yaml
```

From another shell:

```bash
python3 stop.py
```

Lightweight keep-alive on a 1 GB AWS Linux VM (no extra project files required):

```bash
nohup python3 main.py > logs/nohup.out 2>&1 &
```

Or a small `systemd` unit that `WorkingDirectory=` this folder and `ExecStart=/usr/bin/python3 main.py`. Do not run two copies against the same account and symbol.

Memory: candle lookback is bounded (`runtime.candle_lookback`, default 80). No extra threads. Quote calls are spaced to about 1/sec.

---

## 12. Example CLI

```text
╔══════════════════════════════════════════════════════╗
║        ◈ DHAN // PRICE ACTION MOMENTUM CORE ◈       ║
╠══════════════════════════════════════════════════════╣
║ SYSTEM       : ONLINE                                ║
║ MARKET       : NSE                                   ║
║ MODE         : DRY RUN                               ║
║ STRATEGY     : PRICE ACTION MOMENTUM                 ║
║ SYMBOL       : RELIANCE                              ║
║ SIGNAL       : LONG                                  ║
║ POSITION     : OPEN                                  ║
║ ENTRY        : 1,245.20                              ║
║ LTP          : 1,247.10                              ║
║ TARGET       : 1,248.94                              ║
║ STOP         : 1,242.71                              ║
║ P&L          : +₹190.00                              ║
║ TRADES       : 2 / 5                                 ║
║ NEXT SCAN    : 5 SEC                                 ║
╚══════════════════════════════════════════════════════╝
```

The live dashboard is a Rich panel with the same fields (breakout high/low, body ratio, volume, TP/SL, unrealized and daily realized P&L). When `cli.enabled` is false or stdout is not a TTY, the bot logs only.

---

## 13. End-to-End Example

1. `main.py` loads `.env` and `config.yaml`, validates them, and creates rotating logs.
2. It loads `state/bot_state.json` if present. A corrupt file blocks entries.
3. Dhan is initialized. Existing positions for `instrument.security_id` are adopted; TP/SL are re-armed from average price.
4. The loop waits until `schedule.start_time` in `Asia/Kolkata` when the schedule is enabled.
5. Every `runtime.polling_seconds` (default 5) it checks `state/STOP`, the clock, and daily limits.
6. `get_market_data` fetches a bounded history and keeps completed 1-minute bars.
7. The last completed candle is measured. Prior 5 highs sit at ₹1,000. Close prints ₹1,004 with body ratio 66.7%. Volume and (if enabled) trend pass.
8. `generate_signal` returns `LONG`. `validate_trade` confirms flat, cooldown, and trade cap.
9. `execute_signal` submits a BUY (or a dry-run fill at LTP).
10. Fill at ₹1,000.00 arms TP ₹1,003.00 and SL ₹998.00.
11. Each poll updates LTP and unrealized P&L. LTP 1,003.00 → TP HIT → exit SELL → bot stops.
12. Gross P&L ≈ ₹3 × quantity. State is persisted. CLI shows the exit banner.

If instead LTP falls to ₹998.00, SL HIT closes the long and the bot still stops. That is capital protection, not a failed program.

---

These examples are educational. Live trading involves market, execution, liquidity, slippage, and loss risks. Deleting the `docs/` folder does not affect the running bot.
