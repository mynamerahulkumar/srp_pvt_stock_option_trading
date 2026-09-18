You are an expert Python algorithmic-trading engineer specializing in the Dhan trading API, Indian equity markets, intraday/scalping systems, robust order management, and production-grade automation.

Build a complete, locally runnable **EMA + VWAP Scalping Algo for Dhan**.

The implementation must be simple enough to understand, modify, debug, and extend, while being robust enough to run continuously on a Linux AWS VM with only **1 GB RAM**.

## 1. IMPORTANT PROJECT CONSTRAINTS

The final project must contain exactly these application files:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

There must be no requirement for any other Python/application source files.

The project may temporarily use these files as references:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

Read and understand those files if they exist, especially their Dhan API implementation patterns, authentication, instrument handling, WebSocket/REST usage, order placement, order status handling, and error handling.

However, the final application **must not depend on those files**.

After development, the user should be able to delete the entire `docs/` directory and the algo must continue working.

Do not copy unnecessary code blindly from the reference files. Adapt only useful and reliable patterns.

---

# 2. FILE RESPONSIBILITIES

## main.py

This must contain the complete trading application.

It should contain:

* Configuration loading
* Environment variable loading
* Logging
* Dhan API initialization
* Instrument resolution
* Market-data retrieval
* EMA calculation
* VWAP calculation
* Signal generation
* Position detection
* Entry order placement
* Exit order placement
* TP management
* SL management
* Position P&L monitoring
* Order-status monitoring
* Risk controls
* Trading-session controls
* Daily-loss controls
* Duplicate-entry prevention
* Graceful shutdown
* Bot status
* CLI/dashboard
* Main polling loop
* Exception handling
* Retry handling
* API-rate-limit protection
* Shutdown/stop-file handling

Keep the functions modular and logically separated even though everything must remain in `main.py`.

Every important function must have:

1. A clear function name.
2. A short docstring explaining what it does.
3. Explanation of important parameters.
4. Explanation of what it returns.
5. Comments explaining important trading logic.
6. Comments explaining why important safeguards exist.

The code should be educational and readable rather than unnecessarily clever.

---

# 3. config.yaml

Everything that a trader may reasonably want to change must be configurable through `config.yaml`.

Do not hard-code strategy parameters, quantities, trading times, TP/SL, polling intervals, symbols, exchange segments, product types, or risk settings in `main.py`.

Include sensible defaults.

Use a structure similar to:

```yaml
bot:
  name: "EMA_VWAP_SCALPER"
  mode: "LIVE"
  polling_seconds: 5
  dry_run: true
  log_level: "INFO"

instrument:
  exchange_segment: "NSE_EQ"
  symbol: "RELIANCE"
  security_id: ""
  quantity: 1
  product_type: "INTRADAY"

strategy:
  timeframe: "5m"

  ema:
    fast_period: 9
    slow_period: 21

  vwap:
    enabled: true

  entry:
    require_ema_alignment: true
    require_vwap_confirmation: true
    candle_confirmation: true
    minimum_volume_multiplier: 1.0

  exit:
    opposite_signal: true

risk:
  take_profit:
    enabled: true
    type: "percentage"
    value: 0.50

  stop_loss:
    enabled: true
    type: "percentage"
    value: 0.30

  max_daily_loss: 1000
  max_trades_per_day: 10
  max_open_positions: 1

trading_session:
  enabled: true
  start_time: "09:20"
  stop_new_entries_time: "15:00"
  close_all_positions_time: "15:15"

execution:
  order_type: "MARKET"
  entry_side: "BOTH"
  wait_for_order_confirmation: true
  order_status_poll_seconds: 1
  order_timeout_seconds: 15

position_management:
  monitor_pnl: true
  exit_on_tp: true
  exit_on_sl: true
  exit_on_opposite_signal: true

safety:
  prevent_duplicate_orders: true
  cancel_pending_orders_on_shutdown: true
  close_positions_on_shutdown: false
  max_api_retries: 3
  retry_delay_seconds: 2

cli:
  refresh_seconds: 5
  show_recent_logs: true
  show_signal_status: true
  show_position_pnl: true
```

You may improve the structure if necessary.

The important requirement is:

**Every meaningful operational parameter must be configurable.**

---

# 4. .env

Use environment variables for secrets.

Expected values should include whatever the Dhan API implementation requires, for example:

```env
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Do not put secrets inside `config.yaml`.

Never print the access token.

Never log credentials.

Provide `.env.example` only if absolutely necessary, but remember that the requested final application structure should remain minimal.

If `.env` is created, make sure the Python application loads it safely.

---

# 5. requirements.txt

Include only dependencies actually required.

Likely dependencies may include:

```text
dhanhq
pandas
numpy
PyYAML
python-dotenv
requests
```

Use versions compatible with the current Dhan Python SDK/API where appropriate.

Do not add large unnecessary libraries.

The application must be suitable for an AWS Linux VM with approximately 1 GB RAM.

Avoid heavyweight frameworks.

---

# 6. stop.py

Create a simple but reliable emergency-stop utility.

Usage:

```bash
python stop.py
```

It should signal the running bot to stop safely.

Use a lightweight mechanism such as a stop file:

```text
BOT_STOP
```

Do not require Redis, databases, Docker, Celery, or another service.

`main.py` must check the stop signal during its polling loop.

When the stop signal is detected:

1. Stop opening new trades.
2. Handle pending orders according to configuration.
3. Close positions only if configured.
4. Otherwise leave existing positions untouched.
5. Shut down gracefully.
6. Display a clear CLI message.

Also provide a way to remove/reset the stop state safely when starting the bot again.

---

# 7. STRATEGY — EMA + VWAP SCALPING

Implement a clear EMA + VWAP intraday/scalping strategy.

The strategy should use:

* Fast EMA
* Slow EMA
* VWAP
* Price action/candle confirmation
* Optional volume confirmation
* Configurable timeframe

Default:

```text
Fast EMA = 9
Slow EMA = 21
Timeframe = 5 minutes
```

## LONG ENTRY

A long signal should generally require:

1. Fast EMA is above Slow EMA.
2. Price is above VWAP.
3. Optional candle confirmation is bullish.
4. Optional volume condition passes.
5. There is no existing position.
6. Trading session allows a new entry.
7. Daily risk limits have not been reached.
8. No duplicate/pending entry order exists.

## SHORT ENTRY

A short signal should generally require:

1. Fast EMA is below Slow EMA.
2. Price is below VWAP.
3. Optional candle confirmation is bearish.
4. Optional volume condition passes.
5. There is no existing position.
6. Trading session allows a new entry.
7. Daily risk limits have not been reached.
8. No duplicate/pending entry order exists.

Do not assume short selling is always permitted for every instrument/product configuration.

Respect Dhan's product/order constraints.

Validate whether the requested instrument and configured product type support the requested side.

---

# 8. SIGNAL QUALITY

Do not generate an entry simply because EMA crossed.

Separate:

```text
DATA
↓
INDICATORS
↓
SIGNAL
↓
RISK CHECK
↓
ORDER
```

Create a dedicated signal-generation function.

For example:

```python
generate_signal(...)
```

It should return a structured result such as:

```text
LONG
SHORT
NONE
```

along with useful diagnostic information.

The CLI should be able to show why a trade was or was not triggered.

For example:

```text
EMA 9:       2481.25
EMA 21:      2478.90
VWAP:        2479.80
LTP:         2482.10

Trend:       BULLISH
VWAP:        ABOVE
Signal:      LONG
Risk Check:  PASSED
Action:      ENTRY ELIGIBLE
```

Or:

```text
Signal:      NONE
Reason:      Price below VWAP
```

This diagnostic behavior is important.

---

# 9. MARKET DATA

Implement robust market-data retrieval using the Dhan API.

Prefer an efficient mechanism appropriate for the strategy.

If historical candles are needed for indicators:

* Fetch enough historical candles to calculate EMA reliably.
* Avoid downloading unnecessarily large datasets on every polling cycle.
* Refresh data efficiently.
* Do not repeatedly request the same historical data unnecessarily.
* Respect API limits.

The polling interval must be configurable.

Default:

```yaml
polling_seconds: 5
```

The application should fetch/update market data approximately every configured polling interval.

Do not busy-loop.

Use:

```python
time.sleep(...)
```

or an equivalent lightweight mechanism.

---

# 10. INDICATOR CALCULATION

Use pandas/numpy where appropriate.

Implement clear functions such as:

```python
calculate_ema(...)
calculate_vwap(...)
calculate_indicators(...)
```

EMA should be calculated using the configured fast and slow periods.

VWAP should be calculated correctly for the trading session.

Be careful about session boundaries.

Do not accidentally calculate a multi-day cumulative VWAP when the strategy requires intraday/session VWAP.

Handle missing, malformed, or insufficient candle data gracefully.

Never trade when indicator data is invalid.

---

# 11. ORDER EXECUTION

Implement Dhan order execution carefully.

Entry orders should be configurable.

At minimum support:

```text
MARKET
LIMIT
```

if supported by the Dhan API implementation.

Default:

```yaml
order_type: "MARKET"
```

The application must:

1. Validate the signal.
2. Validate risk conditions.
3. Verify that a position does not already exist.
4. Verify there is no duplicate pending order.
5. Submit the order.
6. Capture the order ID.
7. Monitor order status.
8. Confirm execution.
9. Record the actual execution price.
10. Start TP/SL management only after the entry is confirmed.

Never assume that the requested order price equals the actual fill price.

Use the actual executed/fill price whenever available.

---

# 12. TP/SL

TP and SL must be configurable.

Support at least:

```text
percentage
points
```

if practical.

For example:

LONG:

```text
Entry = 100
TP = 100.50
SL = 99.70
```

SHORT:

```text
Entry = 100
TP = 99.50
SL = 100.30
```

The calculation must correctly account for long versus short positions.

The actual execution price must be used as the reference.

When TP is reached:

```text
EXIT POSITION
STOP BOT
```

When SL is reached:

```text
EXIT POSITION
STOP BOT
```

This requirement is mandatory.

After a TP or SL exit is confirmed, the bot must stop trading for that run/day rather than immediately opening another position.

Display:

```text
TP HIT → EXIT EXECUTED → BOT STOPPED
```

or:

```text
SL HIT → EXIT EXECUTED → BOT STOPPED
```

Do not merely stop monitoring while leaving a position open.

Confirm that the exit order has actually been executed where possible.

---

# 13. P&L MONITORING

The CLI must continuously show the current position.

Example:

```text
╔══════════════════════════════════════════════════════╗
║              EMA + VWAP SCALPER                      ║
╠══════════════════════════════════════════════════════╣
║ Status        : RUNNING                              ║
║ Symbol        : RELIANCE                             ║
║ Position      : LONG                                 ║
║ Quantity      : 1                                    ║
║ Entry         : ₹2480.20                             ║
║ LTP           : ₹2483.10                             ║
║ Unrealized P&L: ₹2.90                                ║
║ TP            : ₹2492.60                             ║
║ SL            : ₹2472.76                             ║
║ EMA 9         : ₹2482.20                             ║
║ EMA 21        : ₹2479.70                             ║
║ VWAP          : ₹2480.90                             ║
║ Signal        : LONG                                 ║
║ Next Poll     : 5 sec                                ║
╚══════════════════════════════════════════════════════╝
```

Update the display without consuming excessive CPU.

Avoid printing a huge new log block every five seconds.

Prefer a clean dashboard-style CLI.

---

# 14. SCI-FI CLI

Make the terminal experience polished and futuristic while keeping dependencies lightweight.

Use ASCII/Unicode characters where safe.

Example:

```text
╔══════════════════════════════════════════════════════════╗
║        ◈ EMA × VWAP QUANT ENGINE :: DHAN ◈              ║
╠══════════════════════════════════════════════════════════╣
║ SYSTEM       : ONLINE                                    ║
║ ENGINE       : SCALPER                                   ║
║ MARKET       : NSE                                       ║
║ SYMBOL       : RELIANCE                                  ║
║ MODE         : LIVE / PAPER                              ║
╠══════════════════════════════════════════════════════════╣
║ POSITION     : LONG                                      ║
║ ENTRY        : ₹2480.20                                  ║
║ LTP          : ₹2483.10                                  ║
║ P&L          : ₹+2.90                                    ║
║ TP           : ₹2492.60                                  ║
║ SL           : ₹2472.76                                  ║
╠══════════════════════════════════════════════════════════╣
║ EMA 9        : 2482.20                                   ║
║ EMA 21       : 2479.70                                   ║
║ VWAP         : 2480.90                                   ║
║ SIGNAL       : ▲ LONG                                    ║
╠══════════════════════════════════════════════════════════╣
║ ENGINE       : SCANNING                                  ║
║ NEXT POLL    : 05 SEC                                    ║
╚══════════════════════════════════════════════════════════╝
```

Include clear status messages such as:

```text
[DATA]
[ANALYSIS]
[SIGNAL]
[RISK]
[ORDER]
[POSITION]
[EXIT]
[SYSTEM]
[ERROR]
```

Do not make the CLI dependent on a heavyweight UI framework.

---

# 15. TRADING SESSION

The bot must support configurable trading-session controls.

Example:

```yaml
trading_session:
  enabled: true
  start_time: "09:20"
  stop_new_entries_time: "15:00"
  close_all_positions_time: "15:15"
```

When:

```yaml
enabled: true
```

the system operates as day trading with the configured session.

At `start_time`:

```text
Trading allowed
```

Before `start_time`:

```text
No new entries
```

After `stop_new_entries_time`:

```text
No new entries
Existing position may continue according to exit configuration
```

At `close_all_positions_time`:

1. Stop new entries.
2. Close all positions if any are open.
3. Verify exit where possible.
4. Stop the bot.

Display:

```text
DAY SESSION CLOSE
→ NEW ENTRIES DISABLED
→ CLOSING OPEN POSITIONS
→ POSITIONS FLAT
→ BOT STOPPED
```

Use Indian market time / Asia-Kolkata timezone correctly.

Do not depend on the Linux machine being configured to IST.

---

# 16. DISABLE TIME-BASED TRADING

The entire time-based trading restriction must be disable-able.

Example:

```yaml
trading_session:
  enabled: false
```

When disabled:

* Do not require a start time.
* Do not reject trades because of session start/end.
* Do not automatically close positions because of `close_all_positions_time`.
* Continue according to strategy, risk, TP/SL, and other configuration.

However, exchange/API rules must still be respected.

---

# 17. CLOSE ALL POSITIONS

Implement a reusable function:

```python
close_all_positions(...)
```

It should:

1. Fetch current positions.
2. Identify open positions.
3. Determine the required opposite order.
4. Submit exit order.
5. Verify execution where possible.
6. Report the result.

Never blindly submit repeated close orders.

Protect against duplicate exit orders.

---

# 18. RISK MANAGEMENT

Implement configurable safeguards.

At minimum:

### Maximum daily loss

```yaml
max_daily_loss: 1000
```

If realized/unrealized loss reaches the configured limit:

```text
NEW ENTRIES DISABLED
```

Optionally close existing positions according to configuration.

### Maximum trades per day

```yaml
max_trades_per_day: 10
```

Do not exceed the limit.

### Maximum open positions

```yaml
max_open_positions: 1
```

Do not open another position when the limit is reached.

### Duplicate-order protection

Do not submit repeated orders because the five-second polling cycle sees the same signal repeatedly.

This is extremely important.

Use order/position state to ensure:

```text
signal detected
→ order submitted
→ order pending/executed
→ do not submit again
```

---

# 19. DRY RUN / PAPER MODE

Implement:

```yaml
dry_run: true
```

When enabled:

* Do not submit real orders.
* Continue fetching data.
* Continue calculating indicators.
* Continue generating signals.
* Show what order would have been submitted.
* Simulate enough state to allow testing of the strategy flow.

Example:

```text
[PAPER ORDER]
LONG 1 RELIANCE
Entry: ₹2480.20
TP: ₹2492.60
SL: ₹2472.76
```

Make LIVE mode explicit.

Before sending a real order, clearly show:

```text
LIVE TRADING ENABLED
```

Never accidentally submit real orders because of a missing configuration value.

Prefer safe defaults.

---

# 20. ERROR HANDLING

The bot must not crash because of a temporary API/network error.

Implement:

* retries
* timeout handling
* malformed response handling
* missing candle handling
* missing position handling
* order rejection handling
* API exception handling
* network exception handling
* graceful shutdown

Do not retry indefinitely.

Use:

```yaml
safety:
  max_api_retries: 3
  retry_delay_seconds: 2
```

After repeated failures, put the strategy into a safe state.

Never keep blindly submitting orders after an uncertain API response.

If order status is unknown:

```text
UNKNOWN ORDER STATE
→ DO NOT SUBMIT DUPLICATE ORDER
→ RECHECK ORDER STATUS
```

---

# 21. LOGGING

Implement useful logging.

Logs should contain:

* startup
* configuration summary
* authentication status without secrets
* instrument resolution
* market-data errors
* indicator status
* signals
* risk checks
* order submission
* order ID
* order status
* fills
* TP
* SL
* exits
* P&L
* shutdown
* errors

Never log:

* access tokens
* secrets
* sensitive credentials

Use timestamps.

---

# 22. GRACEFUL SHUTDOWN

Handle:

```text
CTRL+C
SIGTERM
stop.py signal
```

On shutdown:

1. Stop new entries.
2. Cancel pending orders if configured.
3. Close positions only if explicitly configured.
4. Print final status.
5. Exit cleanly.

Do not automatically close positions merely because the process received SIGTERM unless configured.

---

# 23. STATE MANAGEMENT

Avoid requiring a database.

For this lightweight strategy, maintain runtime state in memory.

Track at least:

```text
current_position
entry_price
quantity
side
tp_price
sl_price
entry_order_id
exit_order_id
trades_today
realized_pnl
last_signal
last_signal_time
bot_status
```

If necessary, recover important state from Dhan positions/orders after restart rather than relying solely on local memory.

The bot should inspect broker state during startup.

This prevents accidental duplicate entries after a restart.

---

# 24. STARTUP SAFETY CHECK

When `main.py` starts:

1. Load configuration.
2. Validate configuration.
3. Load environment variables.
4. Authenticate with Dhan.
5. Resolve/validate instrument.
6. Fetch current positions.
7. Fetch pending orders.
8. Detect existing positions.
9. Detect pending orders.
10. Determine safe initial state.
11. Only then begin strategy polling.

If an existing position is detected:

```text
RECOVERING EXISTING POSITION
```

Do not automatically open another trade.

If an existing position has TP/SL requirements, calculate/restore them from configuration and actual entry price where possible.

---

# 25. TIME AND PRICE PRECISION

Respect exchange/instrument rules.

Do not assume all instruments use the same tick size.

Use appropriate price precision.

Quantity must be configurable and validated.

Do not allow zero or negative quantity.

Validate configuration before the strategy starts.

---

# 26. FUNCTION ORGANIZATION IN main.py

Use a logical function structure similar to:

```python
load_config()
load_environment()
validate_config()
setup_logging()

create_dhan_client()

resolve_instrument()
fetch_market_data()
fetch_candles()

calculate_ema()
calculate_vwap()
calculate_indicators()

generate_signal()

get_positions()
get_open_position()
get_pending_orders()

calculate_tp_price()
calculate_sl_price()

check_trading_session()
check_risk_limits()
check_duplicate_order()

place_entry_order()
wait_for_order_completion()

place_exit_order()
close_all_positions()

calculate_position_pnl()

display_dashboard()
display_signal_reason()

check_stop_signal()

handle_shutdown()

run_strategy_cycle()
main()
```

You may add helper functions where required.

Keep related functionality together.

Do not create unnecessary classes unless they genuinely improve clarity.

A straightforward functional architecture is preferred for this project.

---

# 27. MAIN LOOP

The main loop should conceptually operate as:

```text
START
 ↓
LOAD CONFIG
 ↓
CONNECT TO DHAN
 ↓
VALIDATE INSTRUMENT
 ↓
RECOVER EXISTING STATE
 ↓
INITIALIZE MARKET DATA
 ↓
┌───────────────────────────────┐
│       STRATEGY LOOP           │
│                               │
│ Fetch/update market data      │
│            ↓                  │
│ Calculate EMA                 │
│            ↓                  │
│ Calculate VWAP                │
│            ↓                  │
│ Generate signal               │
│            ↓                  │
│ Check session                 │
│            ↓                  │
│ Check risk                    │
│            ↓                  │
│ Check existing position       │
│            ↓                  │
│ Place order if eligible       │
│            ↓                  │
│ Monitor position              │
│            ↓                  │
│ Check TP/SL                   │
│            ↓                  │
│ Update P&L dashboard          │
│            ↓                  │
│ Check stop signal             │
│            ↓                  │
│ Sleep polling_seconds         │
└───────────────────────────────┘
```

Polling frequency must come from YAML.

Default:

```text
5 seconds
```

---

# 28. IMPORTANT TP/SL EXECUTION BEHAVIOR

TP/SL must not depend only on the strategy generating another signal.

Once a position exists:

```text
POSITION MANAGEMENT
```

becomes the priority.

For example:

```text
LONG
Entry = 100
TP = 100.50
SL = 99.70
```

If price reaches TP:

```text
EXIT
```

even if EMA/VWAP still says LONG.

If price reaches SL:

```text
EXIT
```

even if EMA/VWAP still says LONG.

After confirmed TP/SL exit:

```text
BOT STOPPED
```

No new trade should be opened.

---

# 29. DO NOT MAKE UNREALISTIC PROFIT GUARANTEES

The implementation and documentation must never claim that the strategy will definitely make money.

Trading involves:

* slippage
* brokerage
* taxes
* exchange charges
* spread
* latency
* gaps
* false signals
* API failures
* execution risk
* changing market regimes

The documentation should instead explain how a trader can **systematically tune and evaluate** the strategy.

Do not encourage reckless parameter optimization.

---

# 30. PARAMETER TUNING

The strategy should expose parameters that can be tuned, including:

```text
Fast EMA
Slow EMA
Timeframe
VWAP confirmation
Candle confirmation
Volume multiplier
TP %
SL %
Trading start time
Stop-entry time
Maximum trades
Maximum daily loss
Polling interval
```

Explain how changing each parameter affects:

* trade frequency
* signal quality
* false signals
* average holding time
* risk/reward
* drawdown
* responsiveness
* transaction costs

Explain that optimization should be done using:

```text
Backtesting
→ Out-of-sample testing
→ Paper trading
→ Small live deployment
→ Monitoring
```

Avoid overfitting.

---

# 31. architecture.md

Create a comprehensive `architecture.md`.

This document should read like a high-quality technical chapter explaining the complete strategy and implementation.

Include:

## 31.1 Strategy Overview

Explain:

* What EMA is.
* What VWAP is.
* Why EMA + VWAP can be combined.
* What market condition the strategy attempts to capture.
* Why this is appropriate for a scalping/intraday framework.
* Limitations.

## 31.2 Strategy Rules

Clearly explain LONG and SHORT conditions.

Use tables where helpful.

Example:

| Condition            | Long                  | Short                 |
| -------------------- | --------------------- | --------------------- |
| Fast EMA vs Slow EMA | Fast > Slow           | Fast < Slow           |
| Price vs VWAP        | Above                 | Below                 |
| Candle               | Bullish               | Bearish               |
| Volume               | Optional confirmation | Optional confirmation |

## 31.3 Complete Architecture

Explain:

```text
Dhan API
   ↓
Market Data
   ↓
Indicator Engine
   ↓
Signal Engine
   ↓
Risk Engine
   ↓
Execution Engine
   ↓
Position Manager
   ↓
TP/SL
   ↓
P&L Monitor
   ↓
CLI
```

Explain every component.

## 31.4 Function-by-Function Explanation

Explain every major function in `main.py`.

For each function explain:

* Purpose
* Inputs
* Outputs
* How it works
* Why it exists
* When it is called
* What can go wrong

## 31.5 Complete Trade Example

Provide a realistic hypothetical example.

For example:

```text
Symbol: RELIANCE
Quantity: 10
Fast EMA: 9
Slow EMA: 21

EMA 9 > EMA 21
Price > VWAP
Bullish candle
Volume confirmation passed
```

Then show:

```text
LONG ENTRY
Entry price = ₹2500
Quantity = 10

TP = 0.50%
SL = 0.30%
```

Calculate:

```text
TP = ₹2512.50
SL = ₹2492.50
```

Then show a hypothetical execution:

```text
Entry:
₹2500 × 10 = ₹25,000

Exit at TP:
₹2512.50 × 10 = ₹25,125

Gross P&L:
₹125
```

Then explain that actual net P&L will differ after brokerage, taxes, exchange charges and slippage.

Also provide an SL example:

```text
Entry = ₹2500
Exit = ₹2492.50
Quantity = 10

Gross loss = ₹75
```

Clearly label these as hypothetical examples.

## 31.6 Trade Lifecycle

Explain:

```text
Signal
→ Risk validation
→ Order
→ Order confirmation
→ Fill
→ Position
→ TP/SL monitoring
→ Exit
→ P&L
→ Bot shutdown
```

## 31.7 TP/SL Lifecycle

Explain exactly what happens when:

* TP is reached.
* SL is reached.
* API temporarily fails.
* Order is rejected.
* Position disappears unexpectedly.
* Bot restarts.
* stop.py is executed.

## 31.8 Day Trading Mode

Explain:

```yaml
trading_session.enabled: true
```

and what happens with:

* start time
* stop-entry time
* close-all time

## 31.9 Non-Time-Restricted Mode

Explain:

```yaml
trading_session.enabled: false
```

and how the behavior changes.

## 31.10 CLI

Explain every important section of the dashboard.

## 31.11 Risk Management

Explain:

* max daily loss
* max trades
* max positions
* duplicate-order protection
* broker-state recovery
* API failure handling

## 31.12 Parameter Tuning Guide

Provide practical explanations for tuning.

For example:

### EMA tuning

Explain:

```text
9/21
```

versus:

```text
5/13
```

versus:

```text
20/50
```

and how they change strategy behavior.

### TP/SL tuning

Explain why:

```text
small TP + large SL
```

can be dangerous.

Explain risk/reward.

### VWAP filter

Explain how enabling/disabling VWAP confirmation changes trade frequency.

### Timeframe

Compare:

```text
1m
3m
5m
15m
```

in terms of noise and responsiveness.

### Volume filter

Explain how volume confirmation can reduce weak breakouts but also reduce trade count.

Do not say that a particular parameter is guaranteed to be profitable.

---

# 32. STRATEGY IMPROVEMENT SECTION

Include a section explaining systematic ways to improve the strategy.

Discuss possible future enhancements such as:

* ATR-based TP/SL
* trailing stop
* break-even stop
* volatility filter
* market regime filter
* higher-timeframe trend filter
* opening-range filter
* volume profile
* dynamic position sizing
* maximum consecutive-loss protection
* cooldown period after a trade
* spread/slippage filter
* index trend confirmation
* sector trend confirmation
* news/event filters
* options-specific adaptations

Explain that each enhancement should be tested independently rather than adding everything at once.

---

# 33. PROFITABILITY DISCUSSION

Include a section titled:

```text
How to Improve the Probability of a Positive Trading Outcome
```

Do not promise profits.

Explain that the objective should be to improve:

```text
Expectancy
Risk-adjusted returns
Drawdown control
Execution quality
Consistency
```

Explain the basic expectancy concept:

```text
Expectancy =
(Win Rate × Average Win)
-
(Loss Rate × Average Loss)
```

Give a hypothetical example.

For example:

```text
Win rate = 55%
Average win = ₹100
Loss rate = 45%
Average loss = ₹80

Expectancy =
0.55 × 100 - 0.45 × 80
= ₹19 per trade
```

Explain that this is before real-world costs unless explicitly included.

---

# 34. TESTING GUIDE

Explain how to test the system.

Include:

## Dry run

```yaml
dry_run: true
```

## Paper trading

Explain how to observe signals without risking capital.

## Small live deployment

Explain why live deployment should begin with conservative quantity.

## Failure testing

Test:

* API unavailable
* network interruption
* order rejected
* order pending
* duplicate signal
* bot restart
* stop.py
* TP
* SL
* session close
* daily loss limit

---

# 35. AWS 1 GB RAM DEPLOYMENT

Include instructions for running on a lightweight Linux AWS VM.

Example:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Explain how to configure:

```text
.env
config.yaml
```

Explain how to stop:

```bash
python stop.py
```

Keep resource usage low.

Do not require Docker.

Do not require a database.

Do not require Redis.

Do not require PostgreSQL.

Do not require a web server.

---

# 36. SECURITY

Explain:

* Never commit `.env`.
* Never expose Dhan access tokens.
* Never print tokens.
* Use appropriate AWS security practices.
* Restrict SSH access.
* Use least-privilege infrastructure practices.
* Keep Python dependencies updated.

If useful, mention adding:

```text
.env
BOT_STOP
```

to `.gitignore`, but do not create additional application files unless required.

---

# 37. README-LIKE USAGE SECTION IN architecture.md

Include exact commands:

```bash
pip install -r requirements.txt
python main.py
```

and:

```bash
python stop.py
```

Explain how to change:

```text
symbol
quantity
EMA periods
VWAP
TP
SL
polling interval
trading times
risk limits
dry_run
```

through `config.yaml`.

---

# 38. CODE QUALITY REQUIREMENTS

The generated implementation must:

* Be valid Python.
* Be syntactically correct.
* Avoid undefined variables.
* Avoid placeholder functions.
* Avoid TODO-only implementations.
* Avoid fake Dhan API calls.
* Use the actual Dhan SDK/API patterns available in the supplied reference files.
* Handle current Dhan API behavior according to the available SDK/reference implementation.
* Validate API responses.
* Handle order IDs safely.
* Handle positions safely.
* Handle partial/failed execution safely where the API exposes that information.
* Avoid duplicate orders.
* Avoid infinite retry loops.
* Avoid excessive API calls.
* Avoid excessive memory usage.
* Be compatible with Linux.
* Be suitable for Python 3.10+ unless the Dhan SDK requires another supported version.
* Keep dependencies minimal.

---

# 39. IMPORTANT Dhan API REQUIREMENT

Before writing code, inspect:

```text
docs/Dhan_SRP.py
docs/project_requirements.md
```

if they exist.

Determine:

* Authentication pattern
* Dhan client initialization
* Candle API
* Quote API
* Order placement API
* Order status API
* Position API
* Holdings/positions structure
* Instrument/security ID handling
* Exchange segment constants
* Product type constants
* Order type constants

Use the correct implementation based on the supplied references and the installed Dhan SDK.

Do not invent API methods.

If the reference implementation uses a particular method for a required capability, follow that pattern unless it is clearly obsolete or unsafe.

---

# 40. CONFIG VALIDATION

At startup, validate:

* required environment variables
* symbol/security ID
* quantity > 0
* EMA periods > 0
* fast EMA < slow EMA
* TP > 0 when enabled
* SL > 0 when enabled
* polling interval >= 1
* max daily loss >= 0
* max trades >= 1
* valid trading times
* valid order type
* valid product type

Fail safely with a clear error.

Example:

```text
CONFIGURATION ERROR
fast_period must be less than slow_period
```

Do not start trading if configuration is invalid.

---

# 41. IMPORTANT SAFETY DEFAULTS

Use safe defaults.

Prefer:

```yaml
dry_run: true
```

unless the user explicitly changes it.

Never default to aggressive risk.

Never automatically increase quantity after losses.

Never implement martingale.

Never implement revenge trading.

Never remove SL because a trade is losing.

Never continuously re-enter after TP/SL.

Once TP/SL is reached and the position is closed:

```text
BOT STOPPED
```

as required.

---

# 42. OUTPUT EXPECTATION

When you finish generating the project:

1. Create all requested files.
2. Ensure imports are correct.
3. Ensure YAML is valid.
4. Ensure Python syntax is valid.
5. Ensure requirements are valid.
6. Ensure architecture.md matches the actual implementation.
7. Ensure function names in architecture.md match the actual functions.
8. Ensure no dependency remains on `docs/project_requirements.md` or `docs/Dhan_SRP.py`.
9. Perform a local syntax/import/config validation where possible.
10. Fix any errors before finishing.

The final project should be directly runnable after:

```bash
pip install -r requirements.txt
```

with valid Dhan credentials and configuration.

---

# 43. EDUCATIONAL CODE STYLE

Write `main.py` so that every important function can be understood independently.

Use comments such as:

```python
# Fetch enough candles to calculate the configured EMA values.
# We avoid requesting excessive history because this bot runs
# on a lightweight VM and polls repeatedly.
```

and:

```python
# We use the actual broker fill price rather than the requested
# order price because slippage can cause the execution price to differ.
```

and:

```python
# Duplicate-order protection is critical because the strategy is
# evaluated every few seconds. The same signal may remain valid
# across multiple polling cycles.
```

Comments should explain **why**, not merely repeat what the code says.

Avoid excessive comments on obvious Python syntax.

The code should be clean enough that each function and its use case can be understood step by step and incorporated, together with its explanations, into high-quality technical educational material.

---

# 44. FINAL IMPLEMENTATION PRINCIPLE

Build this as a real, robust **EMA + VWAP Scalping Algo for Dhan**, not as pseudocode.

The system should have this philosophy:

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
BOT STOP
```

Prioritize:

**correctness → safety → reliability → readability → performance**

Do not sacrifice order safety for simplicity.

Do not sacrifice readability for unnecessary abstraction.

Do not claim the strategy is guaranteed to be profitable.

The implementation and `architecture.md` should be sufficiently clear, structured, and explanatory that the code plus its explanations can serve as high-quality technical educational material.
