# VWAP Intraday Momentum Algo

A configuration-driven, single-process Dhan bot that trades one NSE equity using session VWAP plus confirmation scoring on completed candles. This document is the technical chapter for the implementation in `main.py`. It explains the idea, the mathematics, the broker path, the safety rules, and how to operate the program on a 1 GB Linux VM.

**No trading strategy can guarantee profit.** Parameter tuning, paper trading, and walk-forward testing exist to improve robustness and risk-adjusted behaviour. They do not make live results certain. Actual realized P&L differs from the examples after brokerage, STT, exchange charges, GST, SEBI charges, stamp duty, slippage, and taxes.

The examples in this chapter are hypothetical. They are for explaining arithmetic, not for promising results.

---

## 1. Introduction

**VWAP** (Volume Weighted Average Price) is the average traded price of a session, weighted by volume:

```text
typical = (high + low + close) / 3
VWAP    = Σ (typical × volume) / Σ volume
```

Traders use VWAP as an intraday fair-value line. Institutions often try to buy below it and sell above it. Price holding **above** a rising VWAP is commonly read as buyers accepting higher prices.

**Momentum** here means price has moved a configured percent over a short lookback of completed bars. It is not a guarantee that the move continues.

This bot combines the two: it looks for **bullish momentum above session VWAP**, then asks volume, EMA trend, and a small breakout buffer to confirm. That is a **trend-following / momentum** stance, not mean-reversion.

| Style | Idea | This bot |
|-------|------|----------|
| Mean-reversion | Fade an extreme back toward a mean | No. A sibling Bollinger bot does that. |
| Momentum | Join strength in the direction of the move | Yes. Long when several conditions agree above VWAP. |

Default objective for a day-trading session:

1. Wait until `trading_hours.start_time` (default 09:20 IST).
2. Wait for a newly completed candle.
3. Score enabled conditions. If `score >= confirmation.minimum_conditions`, consider LONG.
4. After risk checks, enter once.
5. Manage the open position with fill-based TP/SL, optional trailing stop, optional strategy exits, and EOD square-off.
6. After a verified exit, stop the process when `risk.stop_bot_after_exit` is true (default).

---

## 2. Strategy Rules

Enabled conditions (each independently togglable):

```text
Price > session VWAP  and  VWAP flat-to-rising
+
Price momentum >= minimum_price_change_percent
+
Volume > average_volume × multiplier
+
Close > EMA  and  EMA slope > 0
+
Close > VWAP × (1 + breakout_buffer_percent / 100)
=
BUY when score >= minimum_conditions
```

Default `minimum_conditions` is **3**. A single true condition is not enough unless the operator sets the minimum to 1.

Every evaluation records ticks for the dashboard:

```text
VWAP        ✓
Momentum    ✓
Volume      ✓
EMA Trend   ✓
Breakout    ✗

Score: 4/5
Minimum: 3
Signal: BUY
```

If the score fails:

```text
SIGNAL: NO TRADE
Reason: Volume confirmation failed
Score: 2/5
Required: 3/5
```

---

## 3. Mathematical Formulas

### Session VWAP

Reset on each calendar date in `Asia/Kolkata`. Prior-day bars are ignored for the cumulative sums.

```text
typical[t] = (H[t] + L[t] + C[t]) / 3
VWAP[t]    = Σ typical[i] × V[i]  /  Σ V[i]
             for i on today's session with V[i] accumulated so far
```

Implementation: `calculate_vwap()`. If cumulative volume is 0, VWAP is unavailable and the signal is `NO_TRADE`.

### EMA

```text
k      = 2 / (period + 1)
seed   = SMA of the first `period` closes
EMA[t] = C[t] × k + EMA[t-1] × (1 − k)
```

EMA may use lookback bars from prior sessions so it is warm near the open. VWAP does not.

### Momentum %

```text
momentum % = (close[t] − close[t − N]) / close[t − N] × 100
```

`N` is `strategy.momentum.lookback_bars` (default 3).

### Volume ratio

```text
average_volume = SMA of the previous `volume_lookback` bars (excludes current)
ratio          = current_volume / average_volume
pass           = ratio > minimum_volume_multiplier
```

### Take profit / stop loss (from actual fill E)

```text
TP = E × (1 + take_profit_percent / 100)
SL = E × (1 − stop_loss_percent / 100)
```

Default: TP 1.0%, SL 0.50%.

### Trailing stop (optional, off by default)

For a long, after the high has moved `activation_percent` above E:

```text
trail = highest × (1 − trail_percent / 100)
effective SL = max(fixed SL, trail)
```

### Gross P&L

```text
LONG:  (exit − entry) × quantity
SHORT: (entry − exit) × quantity
```

Displayed P&L is **gross** unless `risk.estimated_cost_per_trade` is set (then labelled as an estimate).

---

## 4. Complete Architecture

```text
Configuration (.yaml)
    ↓
Environment (.env credentials)
    ↓
Dhan Client
    ↓
Market Data (completed candles + LTP)
    ↓
Indicators (session VWAP, EMA, momentum, volume)
    ↓
Signal Engine (score + NO_TRADE reason)
    ↓
Risk Engine (session, daily limits, pending, flat)
    ↓
Order Engine (paper or live, one submit, verify fill)
    ↓
Position Monitor (TP / SL / trail / optional strategy exit / EOD)
    ↓
CLI
```

The process is a single Python file. State lives in `BotState`. There is no database.

---

## 5. Look-Ahead and Candle Roles

| Role | Used for signals? |
|------|-------------------|
| Historical completed candles | Yes (indicators) |
| Last completed candle | Yes (the decision bar) |
| Forming / in-progress candle | No (display LTP only) |

`get_market_data()` drops bars whose interval has not closed. `process_new_candle()` fires at most once per completed timestamp.

---

## 6. Function-by-Function Explanation

Major functions in `main.py`. Each is written so indicator and signal math can be called without Dhan.

### Configuration and lifecycle

| Function | Purpose | Inputs | Outputs | Safety |
|----------|---------|--------|---------|--------|
| `load_environment` | Load `.env` | none | none; raises if missing | Never logs tokens |
| `load_config` | Read YAML | path | dict | No network |
| `validate_config` | Normalize and fail fast | config | mutates config | Blocks bad live settings |
| `validate_safety_config` | Dual live lock | config | none | `dry_run` and `allow_live_trading` |
| `setup_logging` | Console + event ring | config | none | Drops token-like strings |
| `create_dhan_client` | SDK client | env | dhan | Secrets stay in env |

### Market data

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `get_market_data` | Fetch OHLC | dhan, config | completed candles |
| `validate_candles` | Drop bad OHLC | candles | clean list |
| `get_ltp` | Quote with 1/s spacing | dhan, id, segment | last good LTP on failure |

### Indicators (pure)

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `typical_price` | VWAP representative price | candle | float |
| `calculate_vwap` | Session VWAP series | candles, date | list of optional floats |
| `calculate_ema` | EMA series | closes, period | list of optional floats |
| `calculate_momentum` | % change | closes, lookback | optional float |
| `calculate_volume_ratio` | vol vs average | volumes, lookback | current, avg, ratio |

### Signal

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `evaluate_*_condition` | One scored check | numbers | `ConditionResult` |
| `generate_signal` | Score and BUY/NO_TRADE | candles, config, state | `SignalResult` |

`generate_signal` never places an order.

### Risk and exits

| Function | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| `calculate_take_profit` / `calculate_stop_loss` | Levels from fill | E, side, % | price |
| `arm_risk_levels` | Store TP/SL | state, config, fill | none |
| `update_trailing_stop` | Activation then trail | state, config | none |
| `monitor_tpsl` | LTP vs levels | dhan, config, state, ltp | reason or None |
| `check_strategy_exits` | Optional VWAP/momentum fail | config, state, signal | reason or None |
| `validate_trade` | Gate a BUY | config, state, signal | (ok, reason) |
| `check_trading_window` | Session / weekend | config, now | (ok, reason) |
| `check_risk_limits` | Daily loss / trades | config, state | reason or None |

### Orders and positions

| Function | Purpose | Safety |
|----------|---------|--------|
| `submit_order` | One place_order | No retry on timeout; recover ID by tag |
| `wait_for_order_completion` | Poll until terminal | Timeout does not re-send |
| `finalize_submitted_order` | Apply fill from **average traded price** | Broker book wins on mismatch |
| `place_entry_order` / `place_exit_order` | Intent wrappers | Duplicate lock via `order_in_flight` |
| `recover_existing_state` | Adopt broker position | Missing avg price → fail safe, no new entry |
| `close_all_positions` | Flatten managed symbol | Does not close unrelated names by default |

### Loop and CLI

| Function | Purpose |
|----------|---------|
| `process_new_candle` | One new bar: score, optional strategy exit, optional BUY |
| `run_one_poll_cycle` | Stop → session → pending → LTP → TP/SL → candles → signal |
| `run_trading_loop` | Poll vs CLI refresh independence |
| `graceful_shutdown` | No new entries; optional flatten; log P&L |
| `render_dashboard` | Sci-fi SSH-safe Rich panel |
| `main` | Load → validate → recover → loop → shutdown |

---

## 7. Execution Lifecycle

```text
python3 main.py
    ↓
Load .env and config.yaml
    ↓
Validate configuration and live-safety locks
    ↓
Initialize logging and Dhan client
    ↓
Recover existing position if configured
    ↓
Show paper / live banner
    ↓
Poll loop (default every 5 seconds):
    Check .stop / SIGINT
    Check session and daily risk
    Fetch LTP; monitor TP/SL/trail
    Fetch completed candles
    Compute session VWAP and indicators
    Score conditions
    If flat and BUY + gates pass → one entry → confirm fill → arm TP/SL
    If open → manage exits
    Refresh CLI from memory
    ↓
On TP/SL/strategy exit/EOD/manual stop:
    Follow shutdown flags
    Log trade and daily P&L
    ↓
BOT STOPPED
```

---

## 8. Complete Trade Example (hypothetical)

```text
Stock: Example Stock
Timeframe: 5 minutes

Price: ₹500
VWAP: ₹498
EMA: ₹499
Volume ratio: 1.35
Momentum: +0.40%

Conditions:
Price above VWAP      ✓
Momentum               ✓
Volume                 ✓
EMA trend              ✓
Breakout               ✓   (500 > 498 × 1.0005)

Signal: BUY
Score: 5/5
Minimum: 3
```

Assume the live (or paper) fill is exactly ₹500, quantity 10, TP 1%, SL 0.5%:

```text
Entry = ₹500
Quantity = 10
TP = 500 × 1.01 = ₹505
SL = 500 × 0.995 = ₹497.50
```

### Scenario A — Take Profit

```text
Entry = ₹500
Exit  = ₹505
Quantity = 10

Gross P&L = ₹50
```

### Scenario B — Stop Loss

```text
Entry = ₹500
Exit  = ₹497.50
Quantity = 10

Gross P&L = −₹25
```

These numbers ignore costs and slippage. A software-polled stop can fill worse than ₹497.50 on a gap. **This example does not imply the strategy is profitable.**

---

## 9. How to Tune the Strategy

| Parameter | Purpose | Increasing it | Decreasing it | Typical trade-off |
|-----------|---------|---------------|---------------|-------------------|
| Timeframe | Bar size | Fewer, slower signals | More noise, more costs | Speed vs cost |
| Momentum lookback | How far back price is compared | Smoother, later | Faster, noisier | Lag vs false starts |
| Minimum momentum % | Strength floor | Fewer trades, stronger moves | More trades, weaker moves | Selectivity vs frequency |
| Volume lookback | Average volume window | More stable average | More reactive | Stability vs responsiveness |
| Volume multiplier | Relative-volume hurdle | Fewer, “hotter” bars | More bars pass | Quality vs count |
| EMA period | Trend filter | Slower trend | Faster trend | Whipsaw vs late entry |
| Breakout buffer % | Distance above VWAP | Stricter breakout | Easier pass | Confirmation vs missed starts |
| Minimum score | How many conditions must pass | Higher selectivity | More trades | Win-rate hunt vs opportunity |
| TP % | Target from fill | Larger wins, fewer hits | Smaller wins, more hits | Payoff vs hit rate |
| SL % | Protective stop | Wider loss, fewer stops | Tighter loss, more scratches | Survival vs death-by-stops |
| Trailing activation / trail | Lock in open profit | Later / looser trail | Earlier / tighter trail | Give-back vs premature exit |
| Polling seconds | API cycle | Less API load, slower exits | Faster exits, more quotes | Responsiveness vs limits |
| Max daily trades | Activity cap | More attempts | Harder cap | Overtrading vs missing later setups |
| Max daily loss | Circuit breaker | Allows a worse day | Stops sooner | Ruin risk vs sitting out |

**More trades vs higher selectivity:** raising `minimum_conditions`, momentum %, or the volume multiplier usually cuts trade count. That can raise the fraction of “clean” setups and still lose money if the remaining trades have poor payoff after costs.

**Higher win rate vs lower frequency:** tightening TP and loosening SL can raise win rate while shrinking average win. The reverse can do the opposite. Neither change is automatically an improvement.

Tuning does not guarantee profit.

---

## 10. Improving the Strategy (research, not promises)

Possible research directions. None of these make live results certain:

- Better symbol selection (liquidity, spread, event calendar)
- Volatility / ATR-based stops instead of a fixed percent
- Index or market-breadth confirmation
- Opening-range or relative-volume filters
- Avoiding the first minutes and lunch liquidity pockets
- Spread and slippage filters
- Position sizing from risk-per-trade rather than a fixed quantity
- Maximum drawdown halt
- Walk-forward testing and out-of-sample validation
- Long paper-trading before any live unlock

Distinguish **strategy research** from **guaranteed profitability**. Historical or paper results are not future performance.

---

## 11. Risk Management

Implemented controls:

- Take-profit and stop-loss from **actual average fill**, not the request price
- Optional trailing stop after an activation move
- `max_daily_trades` / `max_daily_loss` (optional profit halt)
- `max_open_positions` (default 1)
- Duplicate-order lock (`order_in_flight`, pending ID, same-candle guard)
- Session start / entry cutoff / square-off (`Asia/Kolkata`)
- Manual stop via `stop.py` (`.stop` file, not SIGKILL)
- End-of-day flatten when configured
- Recover existing Dhan position; fail safe if average price is missing
- Bounded read retries; **no** `place_order` retry after an uncertain submit
- Paper by default: `bot.dry_run: true` and `bot.allow_live_trading: false`

HTTP success is not a fill. The bot waits for a terminal order status and then trusts the position book.

---

## 12. Order State Machine

```text
STARTING
  → WAITING_FOR_SESSION
  → WAITING_FOR_SIGNAL
  → ENTRY_PENDING
  → POSITION_OPEN
  → EXIT_PENDING
  → TRADE_COMPLETED
  → DAILY_LIMIT_REACHED
  → STOP_REQUESTED
  → SHUTTING_DOWN
  → STOPPED
  → ERROR
```

Simple string states. No extra framework.

---

## 13. Paper vs Live

Default is paper:

```yaml
bot:
  dry_run: true
  allow_live_trading: false
```

- Real market data is fetched.
- Signals, theoretical fills, and simulated P&L are shown.
- The CLI shows `MODE: PAPER`.
- `place_order` is never called.

Live requires **both** `dry_run: false` and `allow_live_trading: true`. The banner then shows `⚠ LIVE TRADING ENABLED ⚠`. Optional `safety.require_confirmation_for_live_trading` demands typing `YES`.

Never treat a paper fill as a broker fill after a restart.

---

## 14. AWS 1 GB VM Deployment

The process is designed to stay small:

- No pandas, numpy, ML frameworks, databases, or GUI toolkits
- Bounded candle lookback (`bot.candle_lookback`, default 100)
- Rich CLI only (works over SSH)
- Single process, in-memory state

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# edit .env with Dhan credentials
# leave bot.dry_run: true until paper behaviour is understood
python3 main.py
```

Keep the session alive with `tmux` or `screen`. In another shell:

```bash
python3 stop.py
```

Do not introduce Docker. Do not commit `.env`. Order APIs require Dhan static-IP allowlisting. Data APIs require an active Dhan data plan. The VM timezone does not matter; the bot uses `Asia/Kolkata`.

---

## 15. Operational Checklist

```text
☐ API credentials configured in .env (never committed)
☐ Security ID verified (Dhan security master)
☐ Symbol verified
☐ Quantity verified
☐ Paper trading tested
☐ TP percent verified
☐ SL percent verified
☐ Day-trading times verified (IST)
☐ Daily loss limit configured
☐ Daily trade limit configured
☐ Existing positions checked
☐ stop.py tested in a second shell
☐ AWS / Linux process tested (tmux or equivalent)
☐ Logs verified; no tokens printed
☐ Live locks still false until you intentionally go live
```

---

## 16. Troubleshooting

| Symptom | Likely cause | What the bot does |
|---------|--------------|-------------------|
| Authentication failure | Bad or expired token | Startup error; no orders |
| No market data | Data plan, security_id, or weekend | Wait; `NO TRADE` |
| Invalid security ID | Wrong `instrument.security_id` | Candle/LTP errors; no entry |
| Order rejected | Funds, product, freeze qty, IP | Local state stays flat; no assumed fill |
| Existing position detected | Restart or manual trade | Adopt + arm TP/SL, or fail safe |
| Stop signal received | `stop.py` or Ctrl+C | No new entries; configured flatten |
| API timeout | Network / Dhan | Bounded read retry; no second place |
| Insufficient candles | Too early or lookback too small | `NO TRADE` |
| Invalid configuration | YAML types, min score > enabled conditions | Fail at startup |
| `DH-902` / `806` | Data API subscription | Activate data plan; new token |

Critical safety conditions stop trading rather than continuing blindly. Recoverable data errors wait for the next poll.

---

## 17. Duplicate-Order Protection

Used together:

- One evaluation per completed candle timestamp
- `order_in_flight` / pending order id
- Broker pending-order scan
- Flat-before-entry
- Restart recovery of an existing Dhan position
- No `place_order` retry after an uncertain submit

A BUY score that stays true for many 5-second polls must not produce many BUY orders.

---

## 18. CLI Dashboard

A lightweight Rich terminal (SSH-safe) shows:

- Bot status, paper/live, symbol, security ID, strategy, timeframe
- LTP, session VWAP, EMA, volume, average volume, momentum
- Signal, score, condition ticks, why-no-trade
- Position, quantity, entry, target, stop, unrealized and daily P&L
- Trades today, session status, next action, last API / evaluation time
- Poll interval, stop status, event stream

Dashboard refresh (`cli.refresh_seconds`) does not call Dhan by itself. Trading API calls stay on `bot.polling_seconds`.

---

## 19. Common Failure Modes

- **VWAP fade:** price pops above VWAP and fails; SL is what limits the loss.
- **Gap through SL/TP:** poll interval plus news gaps.
- **Low-volume open:** not enough session bars for VWAP or volume average; bot waits.
- **Rejected order:** local state stays flat; cooldown may apply.
- **Restart while in a trade:** recovery adopts the broker average price.
- **Wrong product type:** F&O cannot use CNC; validation rejects it.
- **Timezone mistakes:** session clocks are `Asia/Kolkata`.
- **Live lock mis-set:** paper stays on unless both live flags agree.

Momentum strategies can perform poorly in range-bound, mean-reverting sessions.

A trader should evaluate expectancy, win rate, average win, average loss, profit factor, maximum drawdown, trade count, costs, slippage, and regime sensitivity. Raising TP or cutting SL is not automatically better.

---

## 20. Project Files

Exactly six runnable files at the project root:

| File | Role |
|------|------|
| `main.py` | Entire application |
| `config.yaml` | Non-secret knobs |
| `.env` | Credential placeholders |
| `stop.py` | Writes `.stop` |
| `requirements.txt` | `dhanhq`, `PyYAML`, `python-dotenv`, `rich` |
| `architecture.md` | This chapter |

`docs/` is reference only. The algo does not import it.
