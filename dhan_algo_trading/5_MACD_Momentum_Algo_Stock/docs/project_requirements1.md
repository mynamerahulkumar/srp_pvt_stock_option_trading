Create a production-ready **MACD Momentum Algorithmic Trading Bot for the Dhan trading API**, designed to run reliably both:

1. Locally on a developer machine
2. On an AWS Linux VM with approximately **1 GB RAM**

The implementation must be clean, modular, robust, configurable, easy to understand, and suitable for future extension.

## 1. PROJECT FILE STRUCTURE

The project must contain exactly these files:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

Do not create additional Python modules, packages, directories, databases, JSON files, log files, or configuration files unless absolutely required by Dhan's SDK/runtime.

All application logic must remain inside `main.py`.

The reference files below may be inspected while developing the implementation:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

These are reference-only files and may later be deleted. Therefore:

* Do not depend on them at runtime.
* Do not import them.
* Do not require them for installation.
* Extract only useful Dhan API implementation patterns from them.
* The final application must work independently with only the six project files listed above.

---

# 2. CORE STRATEGY

Implement a **MACD Momentum Strategy** for Dhan.

The strategy should primarily use:

* MACD
* MACD Signal Line
* MACD Histogram
* Price
* Optional trend filter
* Optional volume filter
* Optional RSI confirmation
* Configurable stop-loss
* Configurable take-profit
* Optional trailing stop
* Configurable position sizing

The core MACD signal should be simple and transparent.

### Primary Long Signal

Generate a BUY signal when:

```text
MACD crosses above Signal Line
```

Optionally require:

```text
MACD Histogram > 0
```

and/or:

```text
Price > Trend Moving Average
```

and/or:

```text
RSI >= configured minimum
```

and/or:

```text
Volume >= configured volume threshold
```

All optional filters must be configurable through `config.yaml`.

### Primary Short Signal

Generate a SELL/short signal when:

```text
MACD crosses below Signal Line
```

Optionally require:

```text
MACD Histogram < 0
```

and/or:

```text
Price < Trend Moving Average
```

and/or:

```text
RSI <= configured maximum
```

and/or:

```text
Volume >= configured volume threshold
```

Do not hard-code these values.

---

# 3. MARKET/INSTRUMENT CONFIGURATION

The bot must support configuration for instruments through YAML.

At minimum support configuration for:

```yaml
instrument:
  exchange_segment:
  security_id:
  symbol:
  instrument_type:
  product_type:
  quantity:
```

Support common Dhan product types where applicable, such as:

```text
INTRADAY
CNC
MARGIN
```

The implementation should validate configuration before starting.

If the selected instrument/product is incompatible with the requested order operation, fail safely with a clear CLI message.

Do not make assumptions about Security IDs.

---

# 4. Dhan API INTEGRATION

Use the Dhan API/SDK correctly based on the available reference implementation and current compatible package.

The `.env` file should contain secrets such as:

```text
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Never put API credentials inside `config.yaml`.

Never print the access token.

Never expose credentials in error messages.

Use environment variables securely.

The bot must support:

* Market data retrieval
* Historical/candle data required for indicator calculation
* Order placement
* Order status checking
* Position retrieval
* Position P&L retrieval
* Position exit
* Close-all-position functionality

Use Dhan's appropriate API methods rather than inventing endpoints.

If the reference implementation contains working Dhan API patterns, reuse/adapt them.

---

# 5. CONFIG.YAML

Everything that a trader may reasonably want to tune must be configurable in `config.yaml`.

Create a complete, clearly organized configuration.

Include sections similar to:

```yaml
bot:
  name: "MACD Momentum Algo"
  enabled: true
  polling_seconds: 5
  dry_run: true

instrument:
  exchange_segment:
  security_id:
  symbol:
  instrument_type:
  product_type:
  quantity:

strategy:
  timeframe:
  macd:
    fast_period:
    slow_period:
    signal_period:

  filters:
    histogram_confirmation:
    trend_filter_enabled:
    trend_ma_period:
    rsi_filter_enabled:
    rsi_period:
    rsi_min:
    rsi_max:
    volume_filter_enabled:
    minimum_volume:

risk:
  stop_loss:
  take_profit:
  stop_loss_type:
  take_profit_type:
  trailing_stop_enabled:
  trailing_stop:
  max_trades_per_day:
  max_daily_loss:
  max_daily_profit:

execution:
  order_type:
  transaction_type:
  product_type:
  validity:
  allow_short:
  prevent_duplicate_orders:
  cooldown_seconds:

trading_hours:
  enabled:
  start_time:
  stop_entry_time:
  close_positions_time:
  timezone:

startup:
  behavior:
  reconcile_existing_positions:

logging:
  level:

cli:
  refresh_seconds:
  show_indicators:
  show_signal:
  show_orders:
```

Use sensible example defaults.

Clearly distinguish:

* strategy settings
* execution settings
* risk settings
* trading-time settings
* operational settings

---

# 6. DAY-TRADING MODE

Implement configurable trading hours.

Example:

```yaml
trading_hours:
  enabled: true
  start_time: "09:20"
  stop_entry_time: "15:00"
  close_positions_time: "15:15"
  timezone: "Asia/Kolkata"
```

When:

```yaml
trading_hours:
  enabled: true
```

the bot behaves as a day-trading strategy.

It should:

1. Start accepting strategy signals only after `start_time`.
2. Stop opening new trades after `stop_entry_time`.
3. At `close_positions_time`, close all open positions.
4. Stop the bot after positions are closed.
5. Never open a new position after the configured entry cutoff.
6. Handle weekends/non-trading days safely.

When:

```yaml
trading_hours:
  enabled: false
```

the bot must not impose these time restrictions.

It should continue operating until:

* TP/SL is reached
* user stops the bot
* risk limits stop trading
* another configured exit condition occurs
* application is terminated

---

# 7. STARTUP BEHAVIOR

Create configurable startup behavior.

Example:

```yaml
startup:
  behavior: "WAIT_FOR_SIGNAL"
  reconcile_existing_positions: true
```

Possible behavior:

```text
WAIT_FOR_SIGNAL
```

Before trading:

* connect to Dhan
* validate credentials
* validate configuration
* fetch current positions
* reconcile existing positions
* initialize historical market data
* calculate indicators
* wait for a valid MACD signal

Never blindly place a trade immediately after startup unless explicitly configured.

If an existing position is found, the bot must understand that position before opening another position.

Prevent accidental duplicate positions.

---

# 8. MACD CALCULATION

Implement MACD calculation clearly inside `main.py`.

Use a reliable technical-analysis implementation or implement the calculations directly using pandas/numpy if appropriate.

MACD:

```text
MACD = EMA(fast_period) - EMA(slow_period)
Signal = EMA(MACD, signal_period)
Histogram = MACD - Signal
```

Detect an actual crossover using previous candle and current candle values.

For bullish crossover:

```text
previous MACD <= previous Signal
AND
current MACD > current Signal
```

For bearish crossover:

```text
previous MACD >= previous Signal
AND
current MACD < current Signal
```

Avoid repeatedly generating the same signal on every polling cycle.

A crossover should represent a new event, not simply:

```text
MACD > Signal
```

on every polling cycle.

---

# 9. CANDLE/TIMEFRAME HANDLING

The strategy must operate using a configurable timeframe.

Example:

```yaml
strategy:
  timeframe: "5m"
```

Polling frequency is separate:

```yaml
bot:
  polling_seconds: 5
```

The bot should poll every configured number of seconds, but should not incorrectly treat every polling update as a new candle.

Implement logic to:

* identify the latest completed candle
* avoid duplicate processing of the same candle
* calculate indicators from sufficient historical candles
* only generate a new crossover signal when appropriate

Explain this carefully in comments and `architecture.md`.

---

# 10. ORDER EXECUTION

Implement safe order execution.

Before placing an order:

1. Confirm bot is enabled.
2. Confirm trading window.
3. Confirm market is expected to be open.
4. Check current position.
5. Check duplicate-order protection.
6. Check daily trade limit.
7. Check daily loss/profit limits.
8. Confirm valid strategy signal.
9. Calculate quantity.
10. Submit order.
11. Record order details in runtime state.
12. Verify order status.
13. Track the resulting position.

Use configurable order type, preferably supporting:

```text
MARKET
LIMIT
```

If LIMIT orders are supported, use a configurable price source/limit offset.

Never use a hard-coded order price.

---

# 11. POSITION MANAGEMENT

The bot must continuously track:

* Current position
* Direction
* Quantity
* Entry price
* Current price
* Unrealized P&L
* Realized P&L where available
* Stop-loss
* Take-profit
* Highest price since entry for trailing stop
* Lowest price since entry for trailing stop

The CLI must show the current position clearly.

Example:

```text
POSITION
────────────────────────────────────
Symbol       : RELIANCE
Direction    : LONG
Quantity     : 10
Entry Price  : ₹2,450.00
LTP          : ₹2,468.50
Unrealized   : +₹185.00
Stop Loss    : ₹2,425.00
Take Profit  : ₹2,500.00
Status       : RUNNING
────────────────────────────────────
```

---

# 12. TAKE-PROFIT / STOP-LOSS

TP/SL must be configurable.

Support at least:

```yaml
risk:
  stop_loss:
  take_profit:
```

Support percentage-based risk parameters.

Example:

```yaml
stop_loss_type: "PERCENT"
take_profit_type: "PERCENT"
stop_loss: 1.0
take_profit: 2.0
```

For a LONG:

```text
SL = Entry × (1 - SL%)
TP = Entry × (1 + TP%)
```

For a SHORT:

```text
SL = Entry × (1 + SL%)
TP = Entry × (1 - TP%)
```

The implementation should make the calculation function reusable.

---

# 13. IMPORTANT TP/SL BOT STOP REQUIREMENT

When the active position reaches:

```text
Take Profit
```

or:

```text
Stop Loss
```

the bot must:

1. Detect the condition.
2. Exit the position.
3. Verify the exit order/status as far as practical.
4. Display the exit reason.
5. Display entry price.
6. Display exit price.
7. Display quantity.
8. Display P&L.
9. Stop further trading.
10. Stop the bot cleanly.

Example:

```text
╔══════════════════════════════════════╗
║       TAKE PROFIT ACTIVATED          ║
╠══════════════════════════════════════╣
║ Entry : ₹100.00                      ║
║ Exit  : ₹102.00                      ║
║ Qty   : 10                            ║
║ P&L   : +₹20.00                       ║
║ Reason: TAKE_PROFIT                   ║
║ BOT   : STOPPED                       ║
╚══════════════════════════════════════╝
```

The same behavior must occur for stop-loss.

Do not allow the strategy to immediately re-enter after TP/SL.

---

# 14. TRAILING STOP-LOSS

Implement optional trailing stop.

Example:

```yaml
trailing_stop_enabled: true
trailing_stop: 0.75
```

For LONG:

```text
Trailing SL = highest_price_since_entry × (1 - trailing%)
```

For SHORT:

```text
Trailing SL = lowest_price_since_entry × (1 + trailing%)
```

Only activate this logic when enabled.

Clearly explain the difference between:

* fixed SL
* trailing SL
* TP

in `architecture.md`.

---

# 15. RISK MANAGEMENT

Implement configurable safeguards.

At minimum:

```text
Maximum trades per day
Maximum daily loss
Maximum daily profit
Duplicate order prevention
Position limit
Cooldown between trades
```

Example:

```yaml
risk:
  max_trades_per_day: 3
  max_daily_loss: 2000
  max_daily_profit: 5000
```

When a risk limit is reached:

* do not open another position
* explain the reason in CLI
* optionally close existing position if explicitly configured
* stop the bot when appropriate

Never silently stop trading.

---

# 16. EXIT LOGIC

Support configurable exits.

At minimum:

```text
STOP_LOSS
TAKE_PROFIT
TRAILING_STOP
TRADING_DAY_END
MANUAL_STOP
RISK_LIMIT
```

The exit function should receive a clear reason.

Example:

```python
exit_position(reason="TAKE_PROFIT")
```

The reason must appear in the CLI.

---

# 17. STOP.PY

Create `stop.py` as a lightweight emergency stop utility.

Its purpose is to allow the user to stop the running bot safely.

The implementation should communicate with the running `main.py` process using a simple local mechanism that works on Linux without requiring Redis, databases, or external services.

A lightweight stop-file/signal mechanism is acceptable.

The stop utility should:

1. Signal the bot to stop.
2. Allow the main process to detect the stop request.
3. Cause the bot to close positions according to configuration.
4. Stop cleanly.

Do not require a second API service.

The stop command should be simple:

```bash
python stop.py
```

The CLI should clearly report:

```text
MANUAL STOP REQUEST RECEIVED
```

---

# 18. GRACEFUL SHUTDOWN

Handle:

```text
Ctrl+C
SIGTERM
manual stop request
```

The bot should:

1. Stop generating new orders.
2. Check whether an open position exists.
3. Follow the configured shutdown behavior.
4. Close the position if configured.
5. Verify exit as far as practical.
6. Print final P&L.
7. Exit cleanly.

Do not leave the bot in an inconsistent state.

---

# 19. SCI-FI CLI

Create an attractive but lightweight terminal interface.

Do not use an overly heavy UI framework that would consume unnecessary RAM.

The CLI should look like a professional futuristic trading terminal.

Example:

```text
╔════════════════════════════════════════════════════════════╗
║              ◈ MACD MOMENTUM // DHAN CORE ◈              ║
╠════════════════════════════════════════════════════════════╣
║ SYSTEM : ONLINE          MODE : DAY TRADE                ║
║ MARKET : OPEN            ENGINE : RUNNING                ║
║ POLL   : 5s              TIMEFRAME : 5m                  ║
╠════════════════════════════════════════════════════════════╣
║ MARKET DATA                                                ║
║ SYMBOL : RELIANCE       LTP : ₹2,468.50                  ║
║ MACD   : 4.82            SIGNAL : 3.91                   ║
║ HIST   : +0.91           TREND : BULLISH                 ║
╠════════════════════════════════════════════════════════════╣
║ POSITION                                                   ║
║ STATUS : LONG                                             ║
║ ENTRY  : ₹2,450.00                                        ║
║ QTY    : 10                                               ║
║ P&L    : +₹185.00                                         ║
║ SL     : ₹2,425.50                                        ║
║ TP     : ₹2,499.00                                        ║
╠════════════════════════════════════════════════════════════╣
║ SIGNAL                                                     ║
║ MACD BULLISH CROSSOVER                                     ║
║ NEXT ACTION : HOLD / MONITOR                               ║
╠════════════════════════════════════════════════════════════╣
║ LAST CHECK : 21:10:05                                      ║
║ NEXT POLL  : 21:10:10                                      ║
╚════════════════════════════════════════════════════════════╝
```

Refresh the CLI every configurable number of seconds.

The polling interval must remain configurable in YAML.

The interface should show:

* Bot status
* Market status where available
* Current symbol
* LTP
* MACD
* Signal
* Histogram
* Trend filter status
* RSI if enabled
* Current position
* Entry price
* Current price
* Current P&L
* SL
* TP
* Trailing SL
* Number of trades today
* Daily P&L
* Last signal
* Last order
* Last error
* Next polling time

Avoid printing hundreds of repeated lines.

Prefer refreshing/updating the same terminal screen.

---

# 20. LOGGING

Use Python's standard `logging` module.

Support:

```yaml
logging:
  level: "INFO"
```

Useful levels:

```text
DEBUG
INFO
WARNING
ERROR
```

Do not create a separate logging configuration file.

Keep logs useful for debugging without flooding the terminal.

Never log:

* access tokens
* secrets
* sensitive credentials

---

# 21. ERROR HANDLING

The bot must be resilient.

Handle:

* API timeout
* API connection failure
* malformed API response
* missing candle data
* insufficient historical candles
* invalid configuration
* invalid quantity
* order rejection
* order timeout
* network failure
* rate limiting
* position mismatch
* missing LTP
* market closed
* unexpected exceptions

Transient errors should use controlled retry/backoff where appropriate.

Do not create an infinite tight retry loop.

The bot must not accidentally place duplicate orders because of an API timeout.

---

# 22. DATA VALIDATION

Validate market data before calculating indicators.

Check:

* required columns exist
* timestamps are valid
* prices are numeric
* OHLC values are valid
* enough candles exist
* no obvious corrupted data

Handle empty data gracefully.

Do not trade if the indicator data is unreliable.

---

# 23. POSITION RECONCILIATION

On startup and periodically when appropriate:

* retrieve Dhan positions
* identify the configured instrument
* compare broker state with internal state
* update internal state

Never assume that an order was filled simply because an order request was submitted.

Broker state should be treated as authoritative.

---

# 24. DUPLICATE ORDER PROTECTION

Before every entry order:

```text
Check current broker position
Check pending orders if available
Check internal state
Check cooldown
Check whether this candle has already generated a trade
```

The bot must not send multiple BUY orders simply because the same MACD crossover is visible across several 5-second polling cycles.

---

# 25. DRY-RUN MODE

Implement:

```yaml
bot:
  dry_run: true
```

When enabled:

* do not place real orders
* calculate signals
* calculate theoretical entries/exits
* display what would have happened
* display simulated P&L
* clearly mark the terminal as:

```text
DRY RUN
```

When:

```yaml
dry_run: false
```

real Dhan orders may be placed.

Default the sample configuration to safe mode where appropriate.

---

# 26. CONFIGURATION VALIDATION

Before starting the trading loop, validate:

* required environment variables
* security ID
* symbol
* exchange segment
* quantity
* MACD parameters
* timeframe
* polling interval
* TP/SL values
* trading times
* product type
* order type

Examples of invalid configurations:

```text
fast_period >= slow_period
signal_period <= 0
quantity <= 0
polling_seconds <= 0
take_profit <= 0
stop_loss <= 0
```

Fail early with a clear explanation.

---

# 27. CODE ORGANIZATION INSIDE MAIN.PY

Even though all code must remain in `main.py`, organize it into clear functions/classes.

Use logical sections such as:

```text
Imports
Constants
Configuration
Environment/API initialization
Data models/state
Validation
Dhan API helpers
Market data
Indicator calculations
Signal generation
Risk management
Order execution
Position management
TP/SL management
Trading schedule
CLI
Shutdown
Main loop
main()
```

Use type hints where practical.

Use descriptive names.

Avoid giant functions.

---

# 28. FUNCTION COMMENTS AND EXPLANATIONS

Every important function in `main.py` must contain a useful docstring.

Each docstring should explain:

1. What the function does.
2. Why the function exists.
3. Important inputs.
4. Important outputs.
5. Important trading considerations.
6. Failure/edge cases where useful.

Example style:

```python
def calculate_macd(data, fast_period, slow_period, signal_period):
    """
    Calculate MACD, Signal Line, and Histogram.

    Why this function exists:
        MACD is the core momentum indicator used by the strategy.

    Inputs:
        data: OHLCV candle DataFrame.
        fast_period: Fast EMA period.
        slow_period: Slow EMA period.
        signal_period: Signal EMA period.

    Returns:
        DataFrame containing MACD-related columns.

    Trading note:
        The strategy should use completed candles when detecting
        crossovers to avoid unstable intrabar signals.
    """
```

Use this level of explanatory quality throughout the code.

Do not put meaningless comments such as:

```python
# calculate macd
```

Comments should explain the reasoning where useful.

---

# 29. MAIN TRADING LOOP

Implement a clear trading loop.

Conceptually:

```text
START
  ↓
Load configuration
  ↓
Validate environment/config
  ↓
Connect to Dhan
  ↓
Reconcile existing position
  ↓
Fetch historical candles
  ↓
Calculate indicators
  ↓
Wait for completed candle
  ↓
Check schedule
  ↓
Check risk limits
  ↓
Check existing position
  ↓
Monitor TP/SL
  ↓
Generate MACD signal
  ↓
Validate signal
  ↓
Place order if appropriate
  ↓
Monitor order/position
  ↓
Update CLI
  ↓
Wait configured polling interval
  ↓
Repeat
```

Keep the main loop easy to read.

---

# 30. ORDER/POSITION STATE

Use a clean internal state representation.

Track at minimum:

```text
bot_running
position_direction
position_quantity
entry_price
current_price
stop_loss
take_profit
trailing_stop
highest_price
lowest_price
current_pnl
daily_pnl
trades_today
last_processed_candle
last_signal
last_order_id
last_order_status
exit_reason
```

Do not rely solely on in-memory state when broker information can be queried.

---

# 31. P&L CALCULATION

Provide a reusable P&L calculation function.

For LONG:

```text
P&L = (Exit/Current Price - Entry Price) × Quantity
```

For SHORT:

```text
P&L = (Entry Price - Exit/Current Price) × Quantity
```

Where possible, display broker-reported P&L as the authoritative value after execution.

Clearly distinguish:

```text
Gross P&L
```

from actual net P&L if charges are not available.

Do not claim that displayed P&L is net profit unless brokerage, taxes, exchange charges, slippage, etc. are actually included.

---

# 32. TRADING COSTS

Make it possible to configure estimated costs if useful:

```yaml
risk:
  estimated_cost_per_trade: 0
```

If implemented, clearly label the result as an estimate.

Do not invent brokerage/tax values.

---

# 33. STRATEGY TUNING

Make the strategy easy to tune.

The YAML should expose parameters such as:

```text
MACD fast period
MACD slow period
MACD signal period
Timeframe
Histogram confirmation
Trend MA
RSI filter
RSI thresholds
Volume filter
Stop-loss
Take-profit
Trailing stop
Cooldown
Maximum trades
```

Avoid hard-coded thresholds.

---

# 34. ARCHITECTURE.MD

Create a detailed `architecture.md`.

This file should explain the complete strategy and implementation in a structured, educational chapter-like format.

Use Markdown.

Include:

# MACD Momentum Algo

## 1. Strategy Overview

Explain:

* What MACD is
* Why MACD can be used for momentum trading
* What a crossover means
* Difference between MACD line and signal line
* Histogram interpretation

## 2. Strategy Rules

Clearly document:

### Long Entry

Example:

```text
MACD crosses above Signal
+ optional confirmation filters
= LONG entry
```

### Short Entry

```text
MACD crosses below Signal
+ optional confirmation filters
= SHORT entry
```

## 3. Example Trade Walkthrough

Provide a realistic hypothetical example.

For example:

```text
Instrument: Example stock
Timeframe: 5 minutes
Quantity: 100

Entry: ₹500
Stop Loss: 1%
Take Profit: 2%
```

Then explain:

```text
Entry = ₹500
SL = ₹495
TP = ₹510
```

If TP is reached:

```text
Profit = (510 - 500) × 100
       = ₹1,000
```

For a hypothetical short example, explain the reverse calculation.

Clearly state that examples are illustrative and actual results depend on market conditions, execution, slippage, charges, liquidity, and other factors.

## 4. Complete Architecture

Explain:

```text
Configuration
     ↓
Dhan API
     ↓
Market Data
     ↓
Candle Engine
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
Exit Engine
     ↓
CLI
```

Explain each component.

## 5. Function-by-Function Explanation

Document every important function in `main.py`.

For each function explain:

* Purpose
* Inputs
* Outputs
* How it works
* Why it matters
* Important edge cases

The explanation should correspond to the actual code.

Do not document functions that do not exist.

## 6. Main Loop Walkthrough

Explain exactly what happens during every polling cycle.

Example:

```text
1. Wake up
2. Check stop request
3. Fetch position
4. Fetch market data
5. Check latest completed candle
6. Calculate MACD
7. Check risk
8. Check TP/SL
9. Check trading hours
10. Evaluate signal
11. Execute order if permitted
12. Update P&L
13. Refresh CLI
14. Sleep
```

Adjust this documentation to match the actual implementation.

## 7. TP/SL Lifecycle

Explain:

```text
Entry
 ↓
Position monitoring
 ↓
Price moves
 ↓
TP/SL evaluation
 ↓
Exit
 ↓
P&L calculation
 ↓
Bot stops
```

Explain both long and short trades.

## 8. Day Trading Mode

Explain:

* start time
* entry cutoff
* position close time
* behavior after market close
* what happens when day trading mode is disabled

## 9. Risk Management

Explain:

* maximum trades
* maximum loss
* maximum profit
* cooldown
* duplicate-order prevention
* position reconciliation

## 10. Parameter Tuning

Explain how traders can experiment with:

### MACD parameters

Explain the trade-off between:

* faster MACD
* slower MACD

Explain that faster settings may produce more signals/noise while slower settings may produce fewer but later signals.

### Timeframe

Compare:

```text
1-minute
5-minute
15-minute
30-minute
```

Explain the general trade-off between responsiveness and noise.

### Histogram confirmation

Explain when it may reduce false signals and when it may cause late entries.

### Trend filter

Explain how a moving-average filter can reduce counter-trend trades.

### RSI filter

Explain how RSI can be used as confirmation rather than as a standalone signal.

### Stop-loss

Explain the trade-off between:

* tight SL
* wide SL

### Take-profit

Explain:

* risk/reward
* win rate versus average win
* why maximizing win rate alone is not necessarily optimal

### Trailing stop

Explain when it may help and when it can exit too early.

## 11. Strategy Improvement Process

Provide a disciplined workflow:

```text
Baseline
 ↓
Backtest
 ↓
Measure
 ↓
Change ONE parameter
 ↓
Backtest again
 ↓
Out-of-sample test
 ↓
Paper trade
 ↓
Small live deployment
 ↓
Monitor
```

Discuss metrics such as:

* total return
* net P&L
* maximum drawdown
* win rate
* average win
* average loss
* profit factor
* expectancy
* number of trades
* Sharpe ratio where appropriate

Do not promise profits.

Explain that parameter optimization can overfit historical data.

## 12. Example Parameter Profiles

Provide illustrative profiles such as:

```text
Conservative
Balanced
Aggressive
Scalping-oriented
Trend-following
```

These are examples only and must not be presented as guaranteed profitable configurations.

## 13. Failure Scenarios

Explain what happens when:

* Dhan API fails
* order is rejected
* internet disconnects
* bot restarts
* an existing position is found
* stop.py is executed
* TP is reached
* SL is reached
* market closes
* insufficient candle data exists

## 14. Deployment

Explain how to run locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Explain AWS Linux deployment using a lightweight process manager approach where appropriate.

Do not require Docker unless necessary.

## 15. Safety Checklist

Before enabling live trading:

```text
[ ] API credentials verified
[ ] Security ID verified
[ ] Quantity verified
[ ] Product type verified
[ ] Dry-run tested
[ ] Strategy tested
[ ] TP tested
[ ] SL tested
[ ] Stop mechanism tested
[ ] Trading hours tested
[ ] Position reconciliation tested
[ ] Risk limits configured
[ ] Duplicate-order protection tested
```

## 16. Practical Lessons

Explain the difference between:

```text
A strategy that works logically
```

and:

```text
A strategy that performs well after costs, slippage and real execution
```

Explain why live trading requires testing and monitoring.

---

# 35. EDUCATIONAL CODE QUALITY

The implementation must be written so that someone reading `main.py` can understand the trading system from beginning to end.

Prefer clarity over cleverness.

Avoid unnecessarily compressed one-line expressions.

Use descriptive variables.

Separate strategy decisions from broker execution.

For example:

```text
Signal generation
```

should not directly contain complex Dhan API order code.

Instead use functions such as:

```text
calculate_indicators()
generate_signal()
check_risk_limits()
calculate_exit_levels()
place_entry_order()
monitor_position()
exit_position()
```

Adapt names as appropriate to the final implementation.

---

# 36. REQUIREMENTS.TXT

Create a minimal `requirements.txt`.

Only include dependencies actually used by the implementation.

Likely dependencies may include:

```text
dhanhq
pandas
numpy
PyYAML
python-dotenv
```

Add a technical-analysis package only if actually needed.

Avoid unnecessary dependencies because the target AWS VM has only approximately 1 GB RAM.

Pin compatible versions where appropriate.

Do not include packages that are not imported.

---

# 37. ENV FILE

Create a safe `.env` template:

```text
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Do not put real credentials into the file.

Do not commit real credentials.

The program must validate that required credentials exist before live API operation.

---

# 38. SECURITY

Never:

* hard-code credentials
* print access tokens
* store credentials in YAML
* write credentials to logs
* expose secrets in exceptions

Handle API credentials through environment variables.

---

# 39. TESTABILITY

Although only the required project files may exist, structure functions so they can be tested individually later.

For example:

```text
calculate_macd()
detect_crossover()
calculate_stop_loss()
calculate_take_profit()
calculate_pnl()
check_trading_window()
check_risk_limits()
```

Pure calculation functions should avoid unnecessary API calls.

This will make future testing and backtesting easier.

---

# 40. IMPORTANT LIVE-TRADING SAFETY

Implement a clear startup banner:

```text
╔══════════════════════════════════════════════╗
║        MACD MOMENTUM // DHAN CORE           ║
║                                              ║
║        ALGORITHMIC TRADING ENGINE            ║
╚══════════════════════════════════════════════╝
```

If `dry_run=true`:

```text
MODE: DRY RUN — NO REAL ORDERS
```

If `dry_run=false`:

```text
MODE: LIVE TRADING
```

Require an explicit configuration state for live trading.

Never silently switch from dry-run to live mode.

---

# 41. BOT START/STOP STATE MACHINE

Implement a clear state model where useful:

```text
STARTING
WAITING
READY
SIGNAL_DETECTED
ORDER_PENDING
POSITION_OPEN
EXIT_PENDING
STOPPING
STOPPED
ERROR
```

Do not over-engineer it, but maintain enough state to prevent invalid actions.

---

# 42. POLLING

The market/trading loop should poll every:

```yaml
bot:
  polling_seconds: 5
```

The value must be configurable.

Do not hard-code five seconds.

Do not use an unnecessarily aggressive polling frequency.

If the API returns an error, apply safe retry/backoff behavior.

---

# 43. TERMINAL COMMANDS

Support simple operational commands where practical.

At minimum:

```bash
python main.py
python stop.py
```

Document these commands in `architecture.md`.

If adding CLI arguments, keep them lightweight and intuitive.

Examples:

```bash
python main.py --config config.yaml
python stop.py
```

Do not create unnecessary CLI complexity.

---

# 44. CODE CONSISTENCY

Before completing the implementation:

* Remove dead code.
* Remove unused imports.
* Remove references to deleted files.
* Verify YAML keys match code.
* Verify environment variables match code.
* Verify function names in `architecture.md` match `main.py`.
* Verify all configuration parameters are actually used.
* Verify all important code paths have useful error handling.
* Verify the project can start without real trading credentials when `dry_run=true`, if the architecture permits it.
* Verify live mode refuses to start when credentials are missing.

---

# 45. FINAL SELF-REVIEW

Before finishing, review the complete implementation as if it were going to run unattended on an AWS Linux VM.

Pay particular attention to:

1. Duplicate orders.
2. API failures.
3. Restart behavior.
4. Existing positions.
5. TP/SL detection.
6. Day-end position closing.
7. Manual stop.
8. Daily loss limits.
9. Incorrect crossover detection.
10. Repeated processing of the same candle.
11. Missing market data.
12. Invalid configuration.
13. Network failures.
14. Unexpected exceptions.
15. Clean shutdown.
16. Memory usage.

The program must fail safely rather than aggressively trading when something is uncertain.

---

# 46. IMPORTANT DOCUMENTATION REQUIREMENT

`architecture.md` must be written as a polished, self-contained technical chapter.

It should not merely say what the code does.

It should explain:

```text
WHAT the strategy does
WHY each component exists
HOW the components interact
WHAT happens during a trade
HOW P&L is calculated
HOW TP/SL works
HOW day trading works
HOW to tune parameters
HOW to evaluate results
HOW to improve the strategy
WHAT risks and limitations exist
```

Use realistic hypothetical numerical examples throughout the explanations where useful.

The documentation should make the concepts understandable to a reader who understands basic trading but is learning algorithmic implementation.

The code comments and `architecture.md` explanations should complement each other without unnecessarily duplicating every line of code.

Write the implementation and explanations in a clear, professional, structured style that remains useful when the code and its explanations are later presented together as educational technical material.
