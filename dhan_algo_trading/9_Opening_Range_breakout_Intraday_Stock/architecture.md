# Opening Range Breakout Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity using an **Opening Range Breakout (ORB)** on the first minutes of the Indian cash session. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the range math, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Historical performance is not a guarantee. Live execution differs from backtests. Slippage, brokerage, taxes, liquidity, and gaps matter. Parameters should be validated with out-of-sample testing. Risk management is essential. The objective is a robust, configurable engine, not a guaranteed-profit system.

---

## 1. Strategy Overview

An **opening range** is the high and low printed during a fixed window after the cash market opens. Default Indian session:

```text
Market session:  09:15 – 15:30 IST
Opening range:   09:15 – 09:30 IST
```

**Why the opening range matters**

- The first minutes often concentrate overnight inventory, gap reaction, and the first institutional prints.
- The high and low of that window become a simple, inspectable reference: a later print above the high is a *breakout*; a later print below the low is a *breakdown*.
- The range is **frozen** at the configured end time. The bot must not keep rewriting the high/low as the day develops.

**How this bot identifies the range**

1. Fetch today’s 1-minute candles via `dhan.intraday_minute_data(..., interval=1)`.
2. Keep bars whose IST timestamp is in `[opening_range.start_time, opening_range.end_time)`.
3. `ORB high = max(high)`, `ORB low = min(low)`.
4. While the window is still open, also fold the live LTP into the running high/low so the dashboard moves.
5. After `end_time`, freeze. Compute breakout levels once.

**How breakouts are detected**

A breakout is an **event**, not a standing condition. Price remaining above the high for fifty polls is still one event.

- `confirmation_candles = 0`: the first LTP print beyond the level fires the signal, then that side is locked for the day.
- `confirmation_candles = N` (default 1): the last N **completed** 1-minute candles after the range ends must all close beyond the level.

**LONG setup**

```text
price / confirmed close > opening_range_high + buffer
```

**SHORT setup**

```text
price / confirmed close < opening_range_low - buffer
```

**Take profit / stop loss**

Software levels from the **actual fill price**. `PERCENT` or `POINTS`. Monitored on LTP every poll. After a verified TP or SL exit the process **stops**. It does not hunt for a second ORB trade.

**Force exit**

When `day_trading.enabled` and `force_exit_enabled` are true, the bot flattens at `force_exit_time` (default 15:15 IST) and stops. Disabling day-trading mode turns off only this clock; TP/SL and `stop.py` still apply.

**Strengths**

- One instrument, one idea, few knobs.
- Range is visible on the CLI (`ORB HIGH` / `ORB LOW`).
- Event lock prevents the poll loop from re-entering the same breakout.

**Weaknesses**

- False breaks in a wide, two-sided open.
- Software TP/SL is polled, not an exchange stop. Gaps can overshoot.
- No volume, VWAP, or higher-timeframe filter in this build.
- One trade per default `max_trades_per_day` — a failed morning ends the day.

---

## 2. Example Trade (hypothetical)

This example is **hypothetical**. It does not guarantee profit.

```text
Stock: Example Stock
Quantity: 10
Opening range: 09:15–09:30 IST
ORB High = ₹1,000
ORB Low  = ₹980
Buffer   = 0
Confirmation candles = 1
Stop loss = 1%   → ₹992.00
Take profit = 2% → ₹1,022.00
```

Timeline:

```text
09:15  Market opens. Bot is BUILDING_ORB. No entries.
09:20  Running high 998, low 982. Still forming.
09:30  Range frozen. HIGH 1000, LOW 980. Levels = 1000 / 980.
09:35  09:34–09:35 1-minute bar closes at 1002. Long event.
09:35  Risk checks pass. BUY 10 submitted.
09:35  Order FILLED at ₹1,002.
09:35  TP armed at 1,022.04 (2% of 1002). SL armed at 991.98 (1%).
09:40  Price moves up. Bot is MONITOR.
09:45  LTP prints 1,022.10. TAKE PROFIT.
09:45  SELL 10 submitted and confirmed flat.
09:45  Gross P&L = (1022.10 − 1002.00) × 10 = ₹201.00
09:45  Bot stops. No second trade.
```

Real-world P&L will differ after brokerage, STT, GST, exchange charges, and slippage.

---

## 3. Losing Trade Example (hypothetical)

```text
Entry  ₹1,002 LONG × 10
Breakout fails. Price slips back into the range and through the stop.
LTP prints ₹991.90
STOP LOSS fires.
Exit confirmed.
Gross P&L = (991.90 − 1002.00) × 10 = −₹101.00
Bot stops.
```

Why this matters: a breakout system is late by construction. The first push can be the entire move. The stop exists to bound the loss, not to make the idea “right.” After SL the process terminates so a frustrated second entry cannot be placed automatically.

---

## 4. P&L Explanation

### LONG

```text
P&L = (Exit Price − Entry Price) × Quantity
```

### SHORT

```text
P&L = (Entry Price − Exit Price) × Quantity
```

The CLI shows this gross figure. If `risk.estimated_cost_per_trade` is set, the dashboard labels the subtracted result as an **estimate**.

Live P&L can differ after:

- brokerage
- STT
- GST
- exchange and SEBI charges
- slippage
- partial fills

The bot prefers the broker average fill when the position book is available. It never treats “order submitted” as “order filled.”

---

## 5. Signal Priority

If both long and short conditions appear on the **same poll** (unusual market-data glitch):

1. Take **LONG** when `strategy.direction.allow_long` is true.
2. Otherwise take **SHORT**.

Once a side fires, that side is locked for the rest of the calendar day (`long_breakout_fired` / `short_breakout_fired`). The poll loop cannot re-enter the same breakout.

---

## 6. Parameter Tuning

None of these knobs make the strategy profitable by themselves. Change one variable at a time. Paper-trade after every change.

| Parameter | What it controls | If increased | If decreased | Possible benefit | Possible drawback | When it may be useful |
|-----------|------------------|--------------|--------------|------------------|-------------------|------------------------|
| Opening range duration | How long high/low are collected | Wider, later freeze | Tighter, earlier freeze | More complete open | Misses early trend / noisier range | Liquid names vs thin opens |
| `buffer_points` / `buffer_percent` | Extra distance beyond the range | Fewer, later entries | More, earlier entries | Filters ticks through the high | Misses clean breaks | Fast, tick-noisy stocks |
| `apply_both` | Stack percent then points | Larger buffer | — | Conservative | Can make the level unreachable | Only when you explicitly want both |
| `confirmation_candles` | Closed bars required beyond the level | Fewer false breaks | Faster, noisier | Avoids one-tick spikes | Late fills | 0 for LTP-only; 1–2 for cash |
| Stop loss | Distance from fill to SL | Larger loss if wrong | Tighter, more stops | Survives noise | Death by scratch | Match average true range |
| Take profit | Distance from fill to TP | Larger target, fewer hits | Quicker exits | Lets a runner work | Gives back open profit | Pair with SL for a ratio you accept |
| Risk/reward | TP vs SL distance | Asymmetric payoff | Near 1:1 | Fewer wins can still pay | Overfitting a ratio | After you have a sample of trades |
| `polling_seconds` | How often Dhan is called | Slower TP/SL | Faster, more API use | Lower CPU on 1 GB | Misses intra-poll spikes | 5s default is a compromise |
| `quantity` | Shares per order | Larger P&L and risk | Smaller | — | Notional and daily-loss breach | Size from rupee risk, not hope |
| `max_trades_per_day` | Entry cap | More attempts | Stops after N | One-and-done default | Overtrading if raised | Keep at 1 until you have evidence |
| `max_daily_loss` | Realized-loss halt | Allows a larger hole | Stops sooner | Hard daily bound | Stops a later winner | Always keep enabled live |
| Entry cutoff | Last time a new entry is allowed | Later entries | Earlier stop | Catch afternoon break | Late-day chop | 15:00 default for cash |
| Force-exit time | Flatten clock | Later hold | Earlier flatten | Avoids last-hour gap | Cuts a runner | 15:15 default |
| Long/short filters | Which side may trade | — | — | Skip a structurally hard side | Miss the only good direction | Turn shorts off on strong uptrends |

Tune with:

- in-sample history
- out-of-sample history
- walk-forward windows
- realistic costs and slippage
- paper trading on Dhan (`safety.dry_run: true`)

---

## 7. How to Improve the Probability of a Profitable ORB System

Practical improvements (none of these are a guarantee):

- Trade liquid NSE names. Avoid extremely low-liquidity stocks.
- Control rupee risk per trade (`quantity` × SL distance).
- Do not oversize so one gap exceeds `max_daily_loss`.
- Assume slippage on MARKET orders (Dhan may convert MARKET to limit-with-MPP).
- Keep `max_trades_per_day` low. ORB is not a scalper.
- Test 5 / 15 / 30 minute opening windows.
- Test a small breakout buffer.
- Test volume or trend filters before you add them to this file (this build has none).
- Test volatility filters (wide opening range vs tight).
- Respect the daily-loss halt.
- Use the configured force-exit. Do not hold INTRADAY into the auction by accident.

**No trading algorithm can guarantee profit.**

---

## 8. Backtesting and Optimization

This repository does **not** ship a backtester. If you build one, measure:

- In-sample period and a later out-of-sample period
- Walk-forward windows
- Transaction costs and slippage
- Gap risk through software SL
- Regime changes (trend day vs range day)
- Parameter sensitivity
- Maximum drawdown, win rate, average win, average loss
- Profit factor, expectancy
- Sharpe only if the trade sample is large enough
- Number of trades (a 20-trade “edge” is noise)

Optimizing only on historical data overfits. The opening range that “worked” last quarter can fail the next gap-up open.

---

## 9. Architecture

```text
                  ┌──────────────────┐
                  │    config.yaml   │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │     main.py      │
                  │ Trading Engine   │
                  └────────┬─────────┘
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
       Market Data      Strategy       Risk
       (1-min + LTP)    (ORB event)    (TP/SL/day)
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                    Order Management
                           │
                           ▼
                         Dhan
                           │
                           ▼
                       Position
                           │
                           ▼
                      TP / SL / Exit
                           │
                           ▼
                       Shutdown
```

| File | Role |
|------|------|
| `main.py` | Entire engine. Does not import `docs/`. |
| `config.yaml` | All non-secret knobs. Every key is read in `validate_config()`. |
| `.env` | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` only. |
| `stop.py` | Writes `.stop`. No Dhan import, no network. |
| `requirements.txt` | `dhanhq`, `PyYAML`, `python-dotenv`, `rich`. |
| `architecture.md` | This chapter. Not required at runtime. |

Live orders require **both** `safety.dry_run: false` and `safety.allow_live_trading: true`.

---

## 10. Complete Trade Lifecycle

```text
START
 ↓
Load .env
 ↓
Load config.yaml
 ↓
Validate configuration
 ↓
Initialize Dhan
 ↓
Reconcile broker positions
 ↓
Wait for trading session (WAITING FOR MARKET SESSION)
 ↓
Build opening range (BUILDING_ORB)
 ↓
Freeze ORB + compute levels
 ↓
Monitor breakout (event, not standing condition)
 ↓
Risk checks
 ↓
Place order (dry-run simulates; live confirms fill)
 ↓
Arm TP/SL from fill
 ↓
Monitor LTP every poll
 ↓
Exit on TP, SL, force-exit, or stop.py
 ↓
Confirm flat
 ↓
Record P&L
 ↓
STOP
```

---

## 11. Function-by-Function Notes

Only functions that exist in `main.py` are listed.

### Configuration and process

| Function | Purpose | Input | Output / side effects | When it runs | What can go wrong |
|----------|---------|-------|------------------------|--------------|-------------------|
| `load_environment` | Load secrets | — | `os.environ` | Startup | Missing `.env` is OK if the process already has vars |
| `load_config` | Parse YAML | path | dict | Startup | Invalid YAML stops the bot |
| `validate_config` | Type-check every section; build aliases | config | mutates config | Startup | First fatal field raises `ConfigError` |
| `validate_safety_config` | Double-lock live mode | config | — | Startup | Live without `allow_live_trading` is refused |
| `setup_logging` | Console + optional `orb_algo.log` | config | handlers | Startup | File permission errors |
| `is_dry_run` / `is_live_mode` | Order gate | config | bool | Every submit | — |
| `initialize_dhan_client` / `create_dhan_client` | SDK client | env | client | Startup | Missing credentials |

### Time and session

| Function | Purpose |
|----------|---------|
| `session_timezone` / `now_in_session_tz` | Always `Asia/Kolkata` unless configured otherwise. Never uses the VM’s local zone for session math. |
| `check_trading_window` | Allow / deny new entries (`WEEKEND`, `SESSION_NOT_STARTED`, `ENTRY_CUTOFF`, `SESSION_ENDED`). |
| `check_force_exit` / `is_after_close_positions` | True only when day-trading flatten is enabled and the clock is reached. |
| `check_stop_signal` / `stop_requested` | `.stop` file or SIGINT/SIGTERM. |
| `interruptible_sleep` | Sleep in 250 ms slices so a stop is noticed quickly. |

### Market data and ORB

| Function | Purpose |
|----------|---------|
| `get_market_data` | Today’s 1-minute candles only. Retries use `execution.retry_*`. |
| `get_opening_range_data` | Filter bars into the OR window. |
| `get_current_price` / `get_ltp` | Last traded price. Rate-limited. Falls back to last good LTP. |
| `calculate_opening_range` | Pure high/low. Optional LTP while forming. |
| `calculate_breakout_levels` | Buffer math. Points XOR percent unless `apply_both`. |
| `check_long_breakout` / `check_short_breakout` | Event detectors. |
| `update_runtime_state` | WAITING → BUILDING → freeze levels. |
| `detect_breakout_signal` | BUY / SELL / HOLD with LONG-wins-tie rule. |
| `process_breakout` | Event lock, risk gate, entry. |

### Risk and P&L

| Function | Purpose |
|----------|---------|
| `calculate_stop_loss` / `calculate_take_profit` | Pure. No Dhan. |
| `calculate_pnl` | Direction-aware gross P&L. |
| `check_entry_conditions` / `validate_trade` | All entry vetoes. |
| `check_risk_conditions` | Daily loss + max trades. |
| `monitor_tpsl` | SL first, then TP. Returns a stop reason. |

### Orders and positions

| Function | Purpose |
|----------|---------|
| `submit_order` | Single place. Never retries `place_order` on timeout. Dry-run never calls Dhan. |
| `wait_for_order_completion` | Poll until terminal / timeout. |
| `finalize_submitted_order` | Fill vs reject vs partial. |
| `place_entry_order` / `place_exit_order` / `exit_position` | Intent wrappers. |
| `close_all_positions` | Flatten managed symbol only. Dedupes exits. |
| `get_positions` / `get_current_position` | Broker is authoritative. Failed read ≠ flat. |
| `reconcile_state` / `recover_existing_state` | Restart safety. Adopts an existing position and re-arms TP/SL. |
| `cancel_pending_orders` | Optional on shutdown. |

### CLI and shutdown

| Function | Purpose |
|----------|---------|
| `render_startup_banner` / `render_dashboard` / `render_exit_banner` | Rich panels. |
| `run_one_poll_cycle` / `run_trading_loop` | Poll vs dashboard refresh are independent. |
| `safe_shutdown` / `graceful_shutdown` | Stop entries, optional flatten, print P&L. |
| `main` | Checklist, recover, loop, exit code. |

---

## 12. Runtime State

In-memory only (`BotState`). Important fields:

```text
engine_state            NO_POSITION | ENTRY_PENDING | POSITION_OPEN |
                        EXIT_PENDING | TRADE_COMPLETED | BOT_STOPPED |
                        WAITING | BUILDING_ORB
opening_range_complete
opening_range_high / opening_range_low
long_breakout_level / short_breakout_level
long_breakout_fired / short_breakout_fired
entry_price, position_quantity, take_profit_price, stop_loss_price
trades_today, daily_realized_pnl
last_order_id, last_order_status
```

Broker state wins over local state on reconcile.

---

## 13. Failure Scenarios

| Scenario | Behaviour |
|----------|-----------|
| Dhan API unavailable | Read retries, then wait. No crash. No duplicate place. |
| Internet disconnect | Same. Last good LTP may hold TP/SL for one blip. |
| Entry rejected | Logged. Pending cleared. Event already consumed (no re-spam). |
| Partial fill | Position sized to filled qty. Remainder is **not** auto-resent. |
| Exit order fails | Retries the **position read**, not a blind second place. Position is not marked flat. |
| Restart with open position | Adopt, re-arm TP/SL from broker average, do not add. |
| TP reached | Exit → verify → record → **stop**. |
| SL reached | Exit → verify → record → **stop**. |
| Force-exit time | Flatten once → verify → stop. |
| `stop.py` | Detected within about one poll. Flatten only if `safety.close_positions_on_stop`. |
| Invalid config | `[FAIL]` and exit before any order. |
| Auth failure | `CredentialError`. No trading. |
| Missing market data | Cycle skipped. Dashboard shows waiting. |
| Same breakout every poll | Locked after the first event. |
| Broker ≠ local | Follow broker. No corrective “fix” order. |

---

## 14. Installation and Operation

Do not create a separate README. Use these commands from this directory.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Edit `.env`:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Edit `config.yaml` for symbol, range, buffers, TP/SL, and quantity.

**Dry-run (default, safe):**

```yaml
safety:
  dry_run: true
  allow_live_trading: false
```

```bash
python3 main.py
```

Real quotes are fetched. `place_order` is never called.

**Live trading** (real money):

```yaml
safety:
  dry_run: false
  allow_live_trading: true
app:
  environment: "live"
```

Static IP must be whitelisted on Dhan for order APIs. Data APIs need an active data plan.

**Stop from another SSH session:**

```bash
python3 stop.py
```

**AWS Linux (1 GB RAM)**

- Use the venv above.
- Run under `tmux` or `systemd`.
- `cli.enabled: true` needs a TTY; otherwise the bot logs only.
- Do not install pandas/numpy for this bot. Candle lists stay in memory for **today only**.
- `orb_algo.log` grows on disk; rotate it if you run for months.

**Troubleshooting**

| Symptom | Check |
|---------|--------|
| Bot did not start / `[FAIL]` | Read the ConfigError line. Fix `config.yaml`. |
| Credentials missing | `.env` in this folder, no quotes around values. |
| DH-902 / 806 | Data plan inactive. Refresh the access token. |
| Orders fail, data works | Static IP whitelist. |
| Immediate stop on start | Leftover `.stop` is deleted at startup. If it still stops, another process is writing the file. |
| Dashboard missing | Not a TTY (`cli.enabled` still true but Live is off). |
| No breakout | Window not frozen yet, confirmation not met, or direction disabled. |

---

## 15. Security

- Never put tokens in `config.yaml` or this file.
- Logs drop lines that contain `access_token` or `client_id`.
- `.env` is gitignored at the repo root. The committed copy is placeholders only.

---

## 16. Educational Disclaimer

This code is written so a Python-literate trader can read `main.py` top to bottom: range construction, event detection, entry vetoes, fill confirmation, and shutdown. Comments explain **why** a trading rule exists, not that `x += 1` adds one.

Paper-trade first. Size small. Expect losing days. The software can fail, the broker can reject, and the market can gap through a software stop.
