# Volume Breakout Scalping Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity using **price breakout plus abnormal volume**. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the formulas, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Historical performance is not a guarantee. Live execution differs from backtests. Slippage, brokerage, taxes, liquidity, and gaps matter. Parameters should be validated with out-of-sample testing. Risk management is essential. The objective is a robust, configurable engine, not a guaranteed-profit system.

---

## 1. Strategy Overview

A **volume breakout** is a price move beyond a recent high or low that is accompanied by unusually high trading volume. Price alone can print a false break — a single tick through a prior high with no participation. Volume is used as a participation filter: if many shares changed hands while the level broke, the move is more likely to be a real inventory transfer rather than a thin print.

**Why volume matters**

- Breakouts fail when they are not accepted by the other side of the book.
- A volume spike versus a recent average is a simple, inspectable proxy for that acceptance.
- The bot does not claim that high volume predicts direction. It only requires that a breakout is not occurring on silent tape.

**Why breakouts can occur**

- A prior N-bar high or low is a visible reference that resting orders often cluster around.
- When that level is taken out, short-covering or long-covering can accelerate the move.
- The same mechanism produces **false breakouts**: the level is probed, volume fades, and price returns inside the range.

**How this bot identifies a setup**

1. Fetch a bounded candle history via `dhan.intraday_minute_data` (or daily history for `DAY`).
2. Keep **completed** candles when `require_candle_confirmation` is true (default). The forming bar is display-only.
3. Compute the prior high/low from earlier bars only (no look-ahead).
4. Compute average volume from earlier bars only.
5. Compare the evaluation candle’s close and volume against those references.
6. Apply optional body / range / EMA filters.
7. If risk limits allow and no position is open, place the configured Dhan order.

**LONG setup**

```text
completed close > previous N-candle high
AND
breakout % in [min_breakout_percent, max_breakout_percent]
AND
volume ratio >= volume_multiplier  (when volume confirmation is on)
AND
optional candle-quality filters pass
AND
optional EMA trend filter passes
AND
risk limits permit a new trade
AND
no existing position / pending order
AND
this candle and this breakout level have not already been consumed
```

**SHORT setup** is the mirror below the previous N-candle low.

**When no trade is taken**

The CLI prints `SIGNAL: NONE` and a reason, for example:

- Volume below threshold
- Breakout not confirmed
- EMA trend filter rejected the side
- Cooldown still active
- Maximum trades for today have been reached

The primary signal remains **price breakout + abnormal volume**. Extra filters are optional and off-able.

---

## 2. Strategy Formula

All math uses **completed** bars unless `volume_breakout.require_candle_confirmation` is false.

```text
Average Volume = mean(previous volume_ma_period completed candle volumes)
                 (the evaluation candle is excluded)

Volume Ratio   = Current Volume / Average Volume

Long breakout level  = max(high of previous N candles)
Short breakout level = min(low of previous N candles)

N = 1 when use_previous_candle_high_low is true and rolling is false
N = breakout_lookback when use_rolling_high_low is true (default 20)

Long breakout %  = (close - high) / high * 100
Short breakout % = (low - close) / low * 100   (absolute distance used in code)

LONG:
  close > prior high
  AND volume_ratio >= max(volume_multiplier, min_volume_ratio)
  AND min_breakout_percent <= breakout % <= max_breakout_percent (max 0 = off)

SHORT:
  close < prior low
  AND the same volume and distance filters
```

**EMA trend filter** (optional)

```text
EMA seeded with SMA of the first period closes
k = 2 / (period + 1)
EMA[t] = close[t] * k + EMA[t-1] * (1 - k)

Long  only if close > EMA_slow and EMA_fast > EMA_slow
Short only if close < EMA_slow and EMA_fast < EMA_slow
```

**Take profit / stop loss** from the **actual fill**, not the intended price:

```text
percentage 0.40 means 0.40% of fill
points     value is a rupee distance
absolute   value is the exact price

LONG:  TP = entry + distance    SL = entry - distance
SHORT: TP = entry - distance    SL = entry + distance
```

Default example at ₹1,003:

```text
TP = 1003 * (1 + 0.40/100) = ₹1,007.012  → tick-rounded ₹1,007.01
SL = 1003 * (1 - 0.20/100) = ₹1,000.994  → tick-rounded ₹1,000.99
```

These numbers are hypothetical. They do not guarantee a fill at that price.

---

## 3. Architecture

```text
Configuration (.env + config.yaml)
     ↓
Environment / validation
     ↓
Dhan connection
     ↓
Recover existing positions
     ↓
Polling loop
     ↓
Stop signal / day-trading clock
     ↓
Market data (candles + LTP)
     ↓
Volume analysis
     ↓
Breakout detection
     ↓
Trend filter
     ↓
Risk management
     ↓
Signal
     ↓
Order execution
     ↓
Position monitoring
     ↓
TP / SL / trail / max-hold
     ↓
Trade statistics (in memory)
     ↓
CLI
```

| File | Role |
|------|------|
| `main.py` | Entire engine. Does not import `docs/`. |
| `config.yaml` | All non-secret knobs. Every key is read in `validate_config()`. |
| `.env` | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` only. |
| `stop.py` | Writes `.stop`. No Dhan import, no network. |
| `requirements.txt` | `dhanhq`, `PyYAML`, `python-dotenv`, `rich`. |
| `architecture.md` | This chapter. Not required at runtime. |

Live orders require **both** `system.dry_run: false` and `system.allow_live_trading: true`.

Strategy functions never call Dhan. Broker functions never decide the signal. They share `BotState`.

---

## 4. Function-by-Function Notes

Only functions that exist in `main.py` are listed. Helpers such as `_safe_float` are omitted.

### Configuration and process

| Function | Purpose | Input | Output | Trading note |
|----------|---------|-------|--------|--------------|
| `load_environment` | Load secrets | — | `os.environ` | Never prints the token |
| `load_config` | Parse YAML | path | dict | Invalid YAML stops the bot |
| `validate_config` | Type-check every section; build aliases | config | mutates config | First fatal field raises `ConfigError` |
| `validate_safety_config` | Double-lock live mode | config | — | Live without `allow_live_trading` is refused |
| `setup_logging` | Console + optional log file | config | handlers | Drops lines containing `access_token` / `client_id` |
| `is_dry_run` / `is_live_mode` | Order gate | config | bool | Dry-run never calls `place_order` |
| `initialize_dhan_client` / `create_dhan_client` | SDK client | env | client | Supports `DhanContext` and older constructors |

### Time and session

| Function | Purpose |
|----------|---------|
| `session_timezone` / `now_in_session_tz` | Default `Asia/Kolkata`. Never uses the VM local zone for session math. |
| `check_trading_window` | Allow / deny new entries. Skipped entirely when day-trading is disabled. |
| `is_after_close_positions` | True only when day-trading flatten is enabled and `force_exit_time` is reached. |
| `check_stop_signal` / `process_stop_signal` / `stop_requested` | `.stop` file or SIGINT/SIGTERM. |
| `interruptible_sleep` | Sleep in 250 ms slices so a stop is noticed quickly. |

### Market data

| Function | Purpose |
|----------|---------|
| `get_market_data` / `load_market_data` | Bounded candle history. Retries use `execution.retry_*`. Empty list on failure. |
| `validate_candles` | Drop corrupted OHLC so a bad bar cannot invent a breakout. |
| `get_current_price` / `get_ltp` | Last traded price. Quote API ~1 req/sec. Falls back to last good LTP. |

### Volume, breakout, trend

| Function | Purpose |
|----------|---------|
| `calculate_volume_metrics` / `calculate_volume_ratio` | Current vs prior average. Evaluation bar excluded. |
| `calculate_breakout_levels` | Prior high/low. Evaluation bar excluded. |
| `calculate_ema` / `calculate_trend_filter` | Optional trend confirmation. |
| `generate_signal` | Pure BUY / SELL / NONE. No Dhan calls. |
| `apply_signal_to_state` | Copy indicators onto the dashboard. |

### Risk and P&L

| Function | Purpose |
|----------|---------|
| `calculate_trade_levels` / `calculate_stop_loss` / `calculate_take_profit` | Pure. Modes: percentage, points, absolute. |
| `update_trailing_stop` / `effective_stop_loss` / `check_trailing_stop` | Optional trail after activation. |
| `check_max_holding_time` | Optional time stop. |
| `calculate_pnl` | LONG `(current-entry)*qty`, SHORT `(entry-current)*qty`. Unrealized until exit. |
| `check_risk_limits` | Daily loss, profit target, consecutive losses, max trades. |
| `check_entry_conditions` / `validate_trade` | All entry vetoes including cooldown and same-breakout lock. |
| `monitor_tpsl` | SL first, then TP. Returns an exit reason. |

### Orders and positions

| Function | Purpose |
|----------|---------|
| `submit_order` | Single place. Never retries `place_order` on timeout. Dry-run never calls Dhan. |
| `wait_for_order_completion` / `monitor_order` | Poll until terminal / timeout. HTTP success is not treated as a fill. |
| `finalize_submitted_order` | Fill vs reject vs partial. |
| `place_entry_order` / `place_exit_order` / `exit_position` | Intent wrappers. |
| `close_all_positions` | Flatten managed symbol only. Dedupes exits. Verifies the book. |
| `get_positions` / `get_current_position` | Broker is authoritative. Failed read ≠ flat. |
| `reconcile_state` / `recover_existing_state` | Restart safety. Adopts an existing position and re-arms TP/SL. |
| `cancel_pending_orders` | Optional on shutdown. |
| `update_trade_statistics` | In-memory wins / losses / consecutive losses. No database. |

### CLI and shutdown

| Function | Purpose |
|----------|---------|
| `render_startup_banner` / `render_dashboard` / `render_cli` / `render_exit_banner` | Rich panels. |
| `run_strategy_cycle` / `run_one_poll_cycle` / `run_trading_loop` / `run_bot` | Poll vs dashboard refresh are independent. |
| `safe_shutdown` / `graceful_shutdown` | Stop entries, optional flatten, print P&L. |
| `main` | Checklist, recover, loop, exit code. |

---

## 5. Complete Trade Example (hypothetical)

These numbers are **hypothetical**. They do not guarantee profit.

```text
Stock: Example Stock
Quantity: 100
Candle: 5-minute, lookback 50
Volume MA period: 20
Volume multiplier: 2.0
Breakout lookback: 20
Min breakout: 0.05%
Max breakout: 1.0%
TP: 0.40%    SL: 0.20%
```

```text
Previous 20-candle high: ₹1,000.00
Previous 20-candle low:  ₹992.00
Average volume:          100,000
Evaluation candle close: ₹1,003.00
Evaluation candle volume: 250,000
Volume ratio:            2.50x
Breakout %:              0.30%
```

Signal path:

```text
1,003 > 1,000                         → price breakout long
0.30% is inside [0.05, 1.0]           → distance OK
2.50x >= 2.0                          → volume confirmation
EMA filter (if on) sees close > slow  → trend OK
Risk: flat, under max trades, no cooldown
→ BUY 100
```

Fill and levels (software, from actual fill ₹1,003):

```text
Entry = ₹1,003.00
Quantity = 100
TP = ₹1,007.01
SL = ₹1,000.99
Entry value = 1,003 × 100 = ₹100,300
```

**Winning path**

```text
LTP later prints ₹1,007.05
TAKE PROFIT
Exit value ≈ 1,007.05 × 100 = ₹100,705
Gross P&L = (1,007.05 − 1,003.00) × 100 = ₹405.00
```

Brokerage, STT, GST, exchange charges, and slippage are **not** subtracted unless `risk.estimated_cost_per_trade` is set. That subtracted figure is labelled an estimate. If `trading.stop_bot_after_tp` is true (default), the process then stops.

**Losing path**

```text
Breakout fails. Price slips back through the prior high and the stop.
LTP prints ₹1,000.90
STOP LOSS
Gross P&L = (1,000.90 − 1,003.00) × 100 = −₹210.00
```

If `trading.stop_bot_after_sl` is true (default), the process stops. If false, a cooldown starts and the bot may scan for a **new** breakout level. The consumed level stays locked so the same breakout is not re-entered.

A breakout system is late by construction. The first push can be the entire move. The stop exists to bound the loss, not to make the idea “right.”

---

## 6. Trade Lifecycle

```text
Signal
→ Risk check (session, position, pending, cooldown, daily limits, same-breakout)
→ Order submitted (or dry-run simulation)
→ Fill confirmed (order status + position book)
→ Position opened; TP/SL armed from fill
→ Every poll: LTP, unrealized P&L, trail, max-hold
→ Exit on TP / SL / trail / hold / force-exit / stop.py
→ Confirm flat
→ Record realized P&L in memory
→ Stop the process or continue (configurable)
```

Duplicate-entry layers:

1. Internal `current_position != FLAT`
2. Broker position book
3. In-flight / pending order
4. Last signal candle timestamp
5. Consumed `(side, breakout_level)`
6. Cooldown after exit
7. `max_trades_per_day`

---

## 7. What Happens Every Polling Cycle

Default `system.polling_seconds` is 5. The value is not hard-coded.

```text
T+0  Check .stop / SIGINT / SIGTERM
T+0  Check force-exit clock (day-trading mode only)
T+0  Sync any in-flight order
T+0  Reconcile local vs Dhan every N cycles
T+0  Fetch LTP (rate-limited)
T+0  Update unrealized P&L / trailing extremes
T+0  If in position: evaluate SL, trail, TP, max hold
T+0  If flat: fetch candles, compute volume ratio, check breakout
T+0  Risk check; place at most one entry
T+0  Refresh CLI from memory
T+5  Sleep, then repeat
```

Dashboard redraw (`cli.refresh_seconds`, default 1s) does **not** call Dhan by itself.

---

## 8. TP / SL

| Mode | Meaning of `value` | Long TP | Long SL |
|------|--------------------|---------|---------|
| `percentage` | Percent of fill. `0.40` = 0.40% | entry × (1 + v/100) | entry × (1 − v/100) |
| `points` | Rupee distance | entry + v | entry − v |
| `absolute` | Exact price | configured price | configured price |

Short sides invert the distance.

**Why fill price matters:** a MARKET order can fill away from the signal close. Arming TP/SL from the intended price would place the stop on the wrong side of reality.

**Software vs exchange stops:** these levels are polled. A gap can overshoot. Dhan may convert MARKET to limit-with-MPP. Slippage, rejection, and partial fills are expected failure modes, not bugs.

Optional trailing stop: after price moves `activation_percent` in favor, the stop trails by `distance_percent` from the extreme. The effective SL is the more protective of the fixed SL and the trail.

---

## 9. Day-Trading Mode

```yaml
trading:
  day_trading:
    enabled: true
    start_time: "09:20"
    stop_entry_time: "15:15"
    force_exit_time: "15:20"
    close_all_positions_at_end: true
```

**When enabled**

- No entries before `start_time`.
- No new entries after `stop_entry_time`.
- At `force_exit_time`, flatten if `close_all_positions_at_end` is true, then stop.

**When disabled**

- The clock gates are not applied.
- The user does not have to think about session hours.
- TP, SL, trail, max-hold, daily risk, and `stop.py` still operate.

Weekend handling only applies when the session window is enabled.

---

## 10. Stop Bot

`python3 stop.py` creates `.stop` in this directory. It does not send SIGKILL and does not call Dhan.

`main.py` deletes a leftover `.stop` at startup. On detect:

1. Print `MANUAL STOP REQUEST RECEIVED`
2. Stop new entries
3. Flatten only if `trading.close_positions_on_stop` is true
4. Cancel pending orders if configured
5. Confirm the position book
6. Exit

SIGINT / SIGTERM take the same path.

After a verified **take profit**, the process stops only if `trading.stop_bot_after_tp` is true. After a verified **stop loss** (including trailing stop), it stops only if `trading.stop_bot_after_sl` is true. Both default true.

---

## 11. Risk Management

| Parameter | Effect when hit |
|-----------|-----------------|
| `max_trades_per_day` | No new entries |
| `max_consecutive_losses` | No new entries |
| `max_daily_loss` | No new entries; optional flatten + stop if `close_on_risk_limit` |
| `daily_profit_target` | Same as daily-loss halt (lock in the day) |
| `one_position_at_a_time` | Block while local or broker position is open |
| `cooldown_seconds` | Wait after an exit before the next entry |
| Take profit / stop loss | Software exit from fill |
| Trailing stop | Optional; off by default |
| `max_holding_seconds` | Time stop; 0 disables |
| `stop_bot_after_tp` / `stop_bot_after_sl` | Process exit after that exit type |

These controls bound **behavior**. They do not bound market gaps and they do not guarantee profitability.

Quantity must be a positive integer. Negative TP/SL values are rejected at startup.

---

## 12. Parameter Tuning

None of these knobs make the strategy profitable by themselves. Change one variable at a time. Paper-trade after every change. Optimize on out-of-sample data; in-sample fitting overfits.

| Parameter | Lower value | Higher value | Typical trade-off |
|-----------|-------------|--------------|-------------------|
| Volume multiplier | More trades, weaker confirmation | Fewer trades, stronger volume | Misses early breaks vs fewer false breaks |
| Breakout lookback | Faster, noisier levels | Stronger, slower levels | Late signals vs chop |
| Candle timeframe | More signals, more noise | Fewer, slower signals | Scalping vs swing-intraday |
| EMA periods | Faster trend flips | Slower, fewer trades | Lag vs whipsaw |
| Min breakout % | Earlier entries | Requires a cleaner pierce | Misses tight breaks |
| Max breakout % | Rejects already-extended bars | Allows chase | Avoids late entries vs misses runners |
| Min candle body | Requires conviction | Allows dojis | Filters weak closes |
| Max candle range | Rejects wide bars | Allows volatility | Avoids climax bars |
| Take profit | Quicker, smaller wins | Larger target, fewer hits | Gives back open profit |
| Stop loss | Tighter, more scratches | Larger loss if wrong | Death by scratch vs one big hole |
| Trailing stop | Locks sooner | Gives more room | Cuts runners vs gives back |
| Cooldown | Faster re-entry | Forces a pause | Overtrading vs missed second wave |
| Max trades | Stops earlier | Allows a scalping day | One-and-done vs overtrading |
| Polling interval | Faster TP/SL, more API use | Slower, cheaper on 1 GB | Missed intra-poll spikes |

Tune with in-sample history, a later out-of-sample window, walk-forward slices, realistic costs, and Dhan paper/dry-run.

---

## 13. Improving the Strategy

Practical suggestions. None of these are a guarantee:

- Test multiple liquid NSE names. Avoid extremely low-liquidity stocks.
- Compare 1 / 5 / 15 minute candles on the same name.
- Raise the volume multiplier until false breaks drop without killing all signals.
- Filter the first and last 15 minutes separately.
- Keep the EMA filter off until you have a baseline without it.
- Measure breakout distance versus subsequent excursion.
- Pair TP/SL so the rupee risk per share is known before you size quantity.
- Include brokerage, STT, GST, and slippage in any spreadsheet review.
- Split results by time of day and by long vs short.
- Use walk-forward and out-of-sample validation. A 20-trade “edge” is noise.

Do not add a dozen extra indicators to this file. If the idea needs that much decoration, it is no longer this strategy.

---

## 14. Common Failure Modes

| Scenario | How this build handles it |
|----------|---------------------------|
| False breakout | Volume, distance, body, and EMA filters; SL bounds the loss |
| Low-volume breakout | Rejected when volume confirmation is on |
| Sudden reversal | Software SL / trail; gap can overshoot |
| Slippage | TP/SL from fill; MARKET may become limit-with-MPP |
| API failure | Read retries + backoff; loop continues; no blind re-place |
| Order rejection | Logged, pending cleared, no automatic retry of `place_order` |
| Partial fill | Position sized to filled qty; remainder is not auto-resent |
| Stale market data | Last good LTP for one blip; empty candles skip the signal |
| Duplicate order | Seven-layer veto listed in section 6 |
| Restart with existing position | Adopt, re-arm TP/SL from broker average, do not add |
| Network failure | Same as API failure. No crash. |
| Wrong security_id / segment | Fail-fast at validation or Dhan reject |
| Wrong trading hours | Day-trading clock; disable the window if you do not want it |
| Auth / DH-902 / 806 | `CredentialError` or logged data-plan error. No trading. |
| Broker ≠ local | Follow broker. No corrective “fix” order. |

---

## 15. Operational Guide

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Edit `.env` (placeholders only in git):

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Edit `config.yaml` for symbol, candle interval, volume thresholds, TP/SL, and quantity.

**Dry-run (default, safe):**

```yaml
system:
  dry_run: true
  allow_live_trading: false
```

```bash
python3 main.py
python3 main.py --config config.yaml
```

Real quotes are fetched. `place_order` is never called. The CLI is labelled `DRY RUN`.

**Live trading** (real money):

```yaml
system:
  dry_run: false
  allow_live_trading: true
```

Startup prints `LIVE TRADING ENABLED`. Set `trading.live_trading_confirmation: true` only if you want a console `YES` prompt. Leave it false on an unattended AWS VM.

Static IP must be whitelisted on Dhan for order APIs. Data APIs need an active data plan.

**Stop from another shell:**

```bash
python3 stop.py
```

---

## 16. AWS Linux (approximately 1 GB RAM)

Keep it simple. Do not add Docker unless you later ask for it.

1. Install Python 3.10+ (`sudo yum install python3` / `apt install python3-venv`).
2. Copy this folder. Create the venv and install `requirements.txt`.
3. Put credentials in `.env` on the VM. Do not paste tokens into SSH history if you can avoid it.
4. Set `config.yaml` (`system.dry_run`, instrument, times).
5. Start under `tmux` or a systemd unit:

```bash
tmux new -s scalper
cd /path/to/10_Volume_breakout_Scalping_stock
source .venv/bin/activate
python3 main.py
```

6. Detach (`Ctrl-b d`). Stop with `python3 stop.py` from another session, or `tmux attach` then Ctrl+C.
7. Inspect `volume_breakout_algo.log`. Rotate it if you run for months.
8. `cli.enabled: true` needs a TTY. Without a TTY the bot logs only and still trades.

Memory: candle lists are capped by `candles.lookback` (default 50). There is no dataframe cache, no database, and no web server. The loop sleeps between polls.

---

## 17. Security

- Never put tokens in `config.yaml`, comments, or this file.
- Logs drop lines that contain `access_token` or `client_id`.
- Exceptions are printed without dumping environment variables.
- The committed `.env` is placeholders only.

---

## 18. Educational Disclaimer

This code is written so a Python-literate trader can read `main.py` top to bottom: volume math, breakout levels, entry vetoes, fill confirmation, and shutdown. Comments explain **why** a trading rule exists.

Paper-trade first. Size small. Expect losing days. The software can fail, the broker can reject, and the market can gap through a software stop.

**No trading algorithm can guarantee profit.**
