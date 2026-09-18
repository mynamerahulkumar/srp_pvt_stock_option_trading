Create a production-ready **VWAP Intraday Momentum Algo for the Dhan trading API**, designed to run reliably both:

1. Locally on a developer machine
2. On a lightweight **AWS Linux VM with 1 GB RAM**

The implementation must be simple, modular, readable, robust, and easy to configure.

## 1. REQUIRED PROJECT FILES

The final project must contain **exactly these 6 files**:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

Do not create additional source-code files, packages, folders, databases, Docker files, notebooks, or unnecessary artifacts.

The project may temporarily read these existing reference files during development:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

Use them only as references for understanding the Dhan API implementation, authentication, order placement, market-data handling, logging conventions, or project requirements.

The final implementation must **not depend on those files**. After development, I should be able to delete the entire `docs/` directory and the algo must continue to work.

---

# 2. FILE RESPONSIBILITIES

## main.py

Put **all trading logic, strategy logic, Dhan API interaction, market-data handling, risk management, position management, CLI, logging, scheduling, and bot lifecycle management in this single file**.

Do not split Python functionality into additional files.

Organize `main.py` into clearly separated sections such as:

```text
Imports
Constants
Configuration
Logging
Dhan API Client
Market Data
Indicators
VWAP Strategy
Signal Generation
Risk Management
Order Management
Position Management
Day-Trading Scheduler
Bot State
CLI / Dashboard
Main Event Loop
Program Entry Point
```

Every important function must have:

* A clear function name
* A docstring
* Comments explaining what it does
* Explanation of important parameters
* Explanation of the returned value
* Explanation of why the function is required
* Error handling where appropriate

Keep the code readable enough that a developer can understand the complete trading flow by reading `main.py` from top to bottom.

---

# 3. config.yaml

Make **all practical strategy, trading, risk, scheduling, polling, logging, and CLI parameters configurable**.

Do not hard-code values in `main.py` when they could reasonably belong in configuration.

Create a well-structured YAML configuration.

Example structure:

```yaml
strategy:
  name: "VWAP Intraday Momentum"
  enabled: true

  timeframe: "5m"

  vwap:
    enabled: true

  momentum:
    lookback_bars: 3
    minimum_price_change_percent: 0.20

  volume:
    enabled: true
    volume_lookback: 20
    minimum_volume_multiplier: 1.20

  breakout:
    enabled: true
    breakout_buffer_percent: 0.05

  trend:
    enabled: true
    ema_period: 20

  confirmation:
    minimum_conditions: 3

trading:
  exchange_segment: "NSE_EQ"

  security_id: ""

  symbol: ""

  transaction_type: "BUY"

  quantity: 1

  product_type: "INTRADAY"

  order_type: "MARKET"

  validity: "DAY"

  max_positions: 1

risk:
  take_profit_percent: 1.0
  stop_loss_percent: 0.50

  max_daily_loss: 2000
  max_daily_trades: 5

  risk_per_trade: 0.5

  trailing_stop:
    enabled: false
    activation_percent: 0.50
    trail_percent: 0.25

day_trading:
  enabled: true

  start_time: "09:20"
  stop_entry_time: "15:00"
  square_off_time: "15:15"

  close_all_positions_at_end: true

  timezone: "Asia/Kolkata"

polling:
  seconds: 5

market_data:
  lookback_bars: 100

execution:
  entry_order_timeout_seconds: 30
  position_check_interval_seconds: 5

safety:
  paper_trading: true
  allow_live_orders: false

  require_confirmation_for_live_trading: true

  prevent_duplicate_orders: true

  recover_existing_position: true

logging:
  level: "INFO"
  console: true
  file: true

cli:
  refresh_seconds: 5
  show_market_data: true
  show_signal: true
  show_position: true
  show_pnl: true
```

Improve this structure if required.

The important requirement is that **nothing important should require editing Python source code**.

---

# 4. .env

Use environment variables for secrets.

The `.env` file should contain placeholders such as:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Never put credentials directly in `config.yaml` or `main.py`.

Never print access tokens or other secrets to the terminal or logs.

Load credentials securely using `python-dotenv`.

If required by the current Dhan API implementation, support the exact authentication fields used by the reference implementation.

---

# 5. requirements.txt

Include only dependencies actually required by the implementation.

Likely dependencies may include:

```text
dhanhq
pandas
numpy
PyYAML
python-dotenv
requests
```

Do not unnecessarily install large frameworks.

The application must remain lightweight enough for an AWS VM with only 1 GB RAM.

Pin versions only when necessary for compatibility.

---

# 6. stop.py

Create a lightweight emergency/control script.

Running:

```bash
python stop.py
```

must request the running bot to stop safely.

Do not terminate the process using a dangerous hard kill unless absolutely necessary.

Use a simple local mechanism such as a stop/control file or another lightweight IPC mechanism.

The main bot must check the stop signal regularly.

When a stop request is detected:

1. Stop creating new trades
2. Cancel/manage pending orders if required
3. Optionally close all open positions according to configuration
4. Log the reason
5. Exit cleanly

The behavior must be configurable.

Example:

```yaml
shutdown:
  close_positions_on_manual_stop: true
```

---

# 7. VWAP INTRADAY MOMENTUM STRATEGY

Implement a genuine **VWAP-based intraday momentum strategy**.

The strategy should be designed around the concept:

> Trade long when price demonstrates bullish momentum above VWAP with sufficient confirmation from momentum, volume, and trend.

The primary strategy must use:

### VWAP

Calculate session VWAP from intraday data.

Use:

```text
VWAP = cumulative(price × volume) / cumulative(volume)
```

Prefer a standard representative price such as:

```text
Typical Price = (High + Low + Close) / 3
```

Explain the calculation in comments.

Reset VWAP appropriately for a new trading session.

Do not accidentally calculate a multi-day VWAP when the strategy is intended to be intraday.

---

# 8. LONG ENTRY CONDITIONS

Implement configurable conditions.

A BUY signal can be generated when the configured minimum number of conditions are satisfied.

Potential conditions:

### Condition 1 — Price Above VWAP

Current/confirmed candle close must be above VWAP.

### Condition 2 — VWAP Momentum

VWAP should be flat-to-rising or configurable.

### Condition 3 — Price Momentum

Price should demonstrate positive momentum over the configured lookback.

For example:

```text
current_close > close N candles ago
```

with the percentage movement exceeding:

```yaml
minimum_price_change_percent
```

### Condition 4 — Volume Confirmation

Current volume should exceed average volume multiplied by:

```yaml
minimum_volume_multiplier
```

Example:

```text
current_volume > average_volume × 1.20
```

### Condition 5 — EMA Trend Confirmation

If enabled:

```text
close > EMA
```

and optionally:

```text
EMA slope > 0
```

### Condition 6 — VWAP Breakout

Price should break above VWAP by the configured buffer.

Example:

```text
close > VWAP × (1 + breakout_buffer_percent / 100)
```

Make the exact interpretation clear and configurable.

---

# 9. SIGNAL QUALITY

Do not enter trades merely because one condition is true unless configuration explicitly permits it.

Implement:

```yaml
confirmation:
  minimum_conditions: 3
```

For every evaluation, calculate and display something like:

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

This makes the strategy easy to understand and debug.

---

# 10. AVOID LOOK-AHEAD BIAS

Do not use future candles.

Signals must be generated only from information available at the time.

Prefer confirmed candle data for strategy decisions.

Clearly distinguish:

```text
Current forming candle
Last completed candle
Historical candles
```

If Dhan's market-data API provides only current quotes, use the appropriate historical/intraday API to construct candles where necessary.

Do not assume an API endpoint exists.

Verify the actual Dhan API interface from the provided reference files and current SDK documentation if required.

---

# 11. ORDER EXECUTION

Implement Dhan order placement using the correct current Dhan API interface.

Support the configured:

* Exchange segment
* Security ID
* Symbol
* Transaction type
* Quantity
* Product type
* Order type
* Validity

Default strategy should be:

```text
BUY → monitor position → TP/SL → exit
```

Do not create duplicate positions.

Before placing an entry order:

1. Check whether a position already exists
2. Check whether an entry order is already pending
3. Check daily trade limit
4. Check daily loss limit
5. Check trading time
6. Check bot stop signal
7. Check live/paper trading mode
8. Validate required configuration

---

# 12. TAKE PROFIT AND STOP LOSS

TP/SL must be configurable.

For a long position:

```text
Entry Price = E

Take Profit = E × (1 + TP% / 100)

Stop Loss = E × (1 - SL% / 100)
```

Do not assume the order was filled at the requested price.

After an order is executed, obtain the **actual average execution price** and calculate TP/SL from the actual fill price.

Example:

```text
Entry = ₹500
TP = 1%
SL = 0.5%

Target = ₹505
Stop = ₹497.50
```

Monitor the position continuously.

When TP or SL is reached:

1. Place the appropriate exit order
2. Confirm the position has closed
3. Calculate realized P&L
4. Log the trade
5. Stop the bot if configured to stop after TP/SL

Configuration example:

```yaml
risk:
  stop_bot_after_exit: true
```

If this is enabled, the bot must stop after the first completed TP/SL exit.

---

# 13. EXIT LOGIC

Support configurable exit methods:

### Take Profit

Exit when target is reached.

### Stop Loss

Exit when stop is reached.

### End-of-Day Exit

If:

```yaml
day_trading:
  enabled: true
  close_all_positions_at_end: true
```

close open positions at the configured square-off time.

### Manual Stop

If `stop.py` is executed, perform configured shutdown behavior.

### Optional Momentum Exit

Allow a configurable strategy exit if momentum disappears or price closes below VWAP.

Example:

```yaml
exit:
  vwap_failure_exit:
    enabled: false
  momentum_failure_exit:
    enabled: false
```

Do not enable complex exits by default unless justified.

---

# 14. DAY-TRADING MODE

If:

```yaml
day_trading:
  enabled: true
```

then:

* Do not enter before `start_time`
* Do not enter after `stop_entry_time`
* Close positions at `square_off_time`
* Use `Asia/Kolkata`
* Prevent overnight positions
* Handle weekends/non-trading days gracefully

If day trading is disabled:

```yaml
day_trading:
  enabled: false
```

the strategy must not impose intraday start/stop restrictions.

It should still follow TP/SL and other configured risk controls.

Do not hard-code Indian market times into strategy logic.

---

# 15. POLLING

The bot must poll market/position information approximately every:

```yaml
polling:
  seconds: 5
```

The value must be configurable.

For example:

```text
Every 5 seconds:
    Check stop signal
    Check trading session
    Fetch current market data
    Update indicators if required
    Check open position
    Check TP/SL
    Evaluate strategy
    Check pending orders
    Update CLI
    Sleep
```

Do not create unnecessary API requests.

Use efficient polling suitable for a 1 GB RAM VM.

Prevent multiple simultaneous order submissions.

---

# 16. POSITION P&L

The CLI must clearly show the current position.

Example:

```text
╔══════════════════════════════════════════════════════╗
║              VWAP MOMENTUM ENGINE                    ║
╠══════════════════════════════════════════════════════╣
║ Status       : RUNNING                               ║
║ Mode         : PAPER                                 ║
║ Symbol       : RELIANCE                              ║
║ Strategy     : VWAP Intraday Momentum                ║
║ Timeframe    : 5m                                    ║
║                                                    ║
║ Market Price : ₹2,850.50                             ║
║ VWAP         : ₹2,842.20                             ║
║ EMA          : ₹2,846.70                             ║
║                                                    ║
║ Signal       : BUY                                   ║
║ Score        : 4 / 5                                 ║
║                                                    ║
║ Position     : LONG                                  ║
║ Quantity     : 1                                     ║
║ Entry        : ₹2,847.00                             ║
║ Current      : ₹2,850.50                             ║
║ Target       : ₹2,875.47                             ║
║ Stop Loss    : ₹2,832.77                             ║
║ Unrealized   : ₹+3.50                                ║
║                                                    ║
║ Next Poll    : 5 sec                                 ║
╚══════════════════════════════════════════════════════╝
```

Make the CLI clean and **sci-fi trading terminal style**, but do not add heavy UI dependencies.

Use Unicode/ASCII safely so it works on Linux SSH terminals.

Do not rely on a graphical interface.

---

# 17. CLI INFORMATION

The CLI should show:

* Bot status
* Paper/live mode
* Symbol
* Security ID
* Strategy
* Timeframe
* Current price
* VWAP
* EMA if enabled
* Volume
* Average volume
* Momentum
* Signal
* Signal score
* Position
* Quantity
* Entry price
* Current price
* Target
* Stop loss
* Unrealized P&L
* Realized P&L
* Number of trades today
* Daily P&L
* Current trading session status
* Next allowed action
* Last API update
* Last strategy evaluation
* Polling interval
* Stop status
* Reason for most recent signal

Refresh approximately every configured polling interval.

Do not flood the terminal with unlimited lines.

Use a refreshed dashboard or compact terminal output.

---

# 18. PAPER TRADING SAFETY

The default configuration must be safe.

Use:

```yaml
safety:
  paper_trading: true
  allow_live_orders: false
```

The bot must not accidentally place real orders.

If live trading is enabled, require:

```yaml
allow_live_orders: true
```

and optionally:

```yaml
require_confirmation_for_live_trading: true
```

Make the live-trading behavior explicit in the CLI.

Example:

```text
⚠ LIVE TRADING ENABLED ⚠
```

Never silently switch from paper trading to live trading.

---

# 19. RISK CONTROLS

Implement:

* Maximum daily trades
* Maximum daily loss
* Maximum open positions
* Duplicate-order prevention
* TP
* SL
* Optional trailing stop
* Trading session restrictions
* Manual stop
* End-of-day square-off
* API failure protection
* Invalid-data protection

If daily loss exceeds:

```yaml
max_daily_loss
```

stop opening new trades.

If required by configuration, close open positions and terminate the bot.

---

# 20. API ERROR HANDLING

The Dhan API can fail because of:

* Network issues
* Temporary API errors
* Invalid parameters
* Authentication problems
* Rate limits
* Order rejection
* Missing market data
* Delayed responses

Implement safe exception handling.

The bot must:

* Log errors clearly
* Avoid crashing unnecessarily
* Retry transient errors where appropriate
* Use bounded retries
* Avoid rapid retry loops
* Never duplicate an order because of an uncertain API response
* Re-check actual order/position status after uncertain order submission

Never assume an order was filled merely because an API request returned successfully.

---

# 21. POSITION RECOVERY

If:

```yaml
safety:
  recover_existing_position: true
```

the bot should inspect existing Dhan positions when starting.

If an existing position belonging to the configured instrument is found:

* Detect it
* Display it
* Obtain actual average price
* Reconstruct TP/SL
* Resume monitoring

Do not blindly place another entry.

If the existing position cannot safely be identified, fail safely and require manual intervention rather than creating another position.

---

# 22. ORDER STATE MANAGEMENT

Implement clear states such as:

```text
STARTING
WAITING_FOR_SESSION
WAITING_FOR_SIGNAL
ENTRY_PENDING
POSITION_OPEN
EXIT_PENDING
TRADE_COMPLETED
DAILY_LIMIT_REACHED
STOP_REQUESTED
SHUTTING_DOWN
STOPPED
ERROR
```

Use a simple state machine or equivalent clear logic.

Avoid complicated frameworks.

---

# 23. TRADE RECORD

Maintain an in-memory representation of the current trade.

For each completed trade capture:

```text
timestamp
symbol
side
quantity
entry_price
exit_price
take_profit
stop_loss
exit_reason
gross_pnl
```

Do not introduce a database unless absolutely necessary.

Keep memory usage low.

At minimum, log complete trade information to the console and configured log output.

---

# 24. LOGGING

Provide useful structured logs such as:

```text
[INFO] Strategy evaluation started
[INFO] VWAP = 2842.20
[INFO] Price = 2850.50
[INFO] Momentum = +0.31%
[INFO] Volume ratio = 1.42
[INFO] EMA trend = bullish
[INFO] Signal score = 4/5
[INFO] BUY signal generated
[INFO] Entry order submitted
[INFO] Entry filled at ₹2847.00
[INFO] TP = ₹2875.47
[INFO] SL = ₹2832.77
```

Never expose API credentials.

---

# 25. DATA VALIDATION

Before generating a signal, validate:

* Required columns exist
* Enough candles are available
* No unexpected null values
* Price > 0
* Volume is valid
* VWAP is valid
* Indicator values are not NaN
* Timestamp is valid
* Market data is sufficiently recent

If validation fails:

```text
NO TRADE
```

rather than guessing.

---

# 26. MARKET DATA

Use the correct Dhan market-data API based on the available SDK/reference implementation.

Do not fabricate Dhan API methods.

Inspect:

```text
docs/Dhan_SRP.py
docs/project_requirements.md
```

to understand the expected Dhan API patterns.

If the SDK version differs, implement using the correct interface for the dependency version selected in `requirements.txt`.

Keep market-data processing efficient.

Use pandas/numpy only where useful.

Do not continuously accumulate unlimited historical data in memory.

---

# 27. STRATEGY FUNCTION DESIGN

Use functions similar to:

```python
load_config()
load_environment()
setup_logging()
validate_config()
initialize_dhan_client()

fetch_historical_data()
fetch_latest_market_data()
build_candles()

calculate_vwap()
calculate_ema()
calculate_momentum()
calculate_volume_ratio()

evaluate_vwap_condition()
evaluate_momentum_condition()
evaluate_volume_condition()
evaluate_trend_condition()
evaluate_breakout_condition()

generate_signal()

check_trading_session()
check_risk_limits()
check_existing_position()

calculate_take_profit()
calculate_stop_loss()

place_entry_order()
get_order_status()
get_position()
place_exit_order()

monitor_position()
check_take_profit()
check_stop_loss()

handle_manual_stop()
square_off_positions()

display_dashboard()

run_bot()
main()
```

You may rename or consolidate functions when appropriate, but preserve this level of separation.

Each function must have a clear docstring and explanatory comments.

---

# 28. STRATEGY DECISION PIPELINE

The main strategy flow should be conceptually:

```text
Market Data
     ↓
Data Validation
     ↓
Candle Construction
     ↓
VWAP Calculation
     ↓
Momentum Calculation
     ↓
Volume Analysis
     ↓
EMA/Trend Analysis
     ↓
Breakout Analysis
     ↓
Signal Scoring
     ↓
Risk Checks
     ↓
Trading-Time Check
     ↓
Position Check
     ↓
BUY Order
     ↓
Fill Confirmation
     ↓
TP/SL Calculation
     ↓
Position Monitoring
     ↓
TP / SL / Strategy Exit / EOD
     ↓
Exit Confirmation
     ↓
P&L Calculation
     ↓
Stop or Continue
```

Make this flow obvious in both the code and `architecture.md`.

---

# 29. ARCHITECTURE.MD

Create a comprehensive `architecture.md`.

Write it as a polished technical chapter explaining the complete VWAP Intraday Momentum Algo.

It should contain:

## 29.1 Introduction

Explain:

* What VWAP is
* Why traders use VWAP
* What momentum means
* Why combining VWAP + momentum can be useful
* Difference between trend-following and mean-reversion
* Why this implementation is momentum-oriented

## 29.2 Strategy Rules

Explain every entry condition.

For example:

```text
Price > VWAP
+
Momentum positive
+
Volume confirmation
+
Trend confirmation
+
Breakout confirmation
=
BUY
```

Explain the configurable confirmation score.

## 29.3 Mathematical Formulas

Include formulas for:

VWAP

EMA

Momentum %

Volume ratio

Take profit

Stop loss

P&L

Use readable mathematical notation.

## 29.4 Complete Architecture

Explain:

```text
Configuration
    ↓
Environment
    ↓
Dhan Client
    ↓
Market Data
    ↓
Indicators
    ↓
Signal Engine
    ↓
Risk Engine
    ↓
Order Engine
    ↓
Position Monitor
    ↓
CLI
```

## 29.5 Function-by-Function Explanation

Document every major function in `main.py`.

For each function explain:

```text
Function:
Purpose:
Inputs:
Outputs:
How it works:
Why it exists:
Important safety considerations:
```

## 29.6 Complete Trade Example

Provide a realistic hypothetical example.

For example:

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
Breakout               ✓

Signal: BUY
```

Then demonstrate:

```text
Entry = ₹500
Quantity = 10

TP = 1%
SL = 0.5%

Target = ₹505
Stop = ₹497.50
```

Show multiple outcomes:

### Scenario A — Take Profit

```text
Entry = ₹500
Exit = ₹505
Quantity = 10

Gross P&L = ₹50
```

### Scenario B — Stop Loss

```text
Entry = ₹500
Exit = ₹497.50
Quantity = 10

Gross P&L = -₹25
```

Clearly state that these are hypothetical examples and do not guarantee profitability.

## 29.7 How to Tune the Strategy

Explain how each parameter affects behavior.

Create a table containing:

```text
Parameter
Purpose
Increasing it does what?
Decreasing it does what?
Typical trade-off
```

Include:

* VWAP timeframe
* Momentum lookback
* Minimum momentum %
* Volume lookback
* Volume multiplier
* EMA period
* Breakout buffer
* Minimum confirmation score
* TP %
* SL %
* Trailing stop
* Polling interval
* Maximum trades
* Daily loss limit

Explain the trade-off between:

```text
More trades
vs
Higher selectivity
```

and:

```text
Higher win rate
vs
Potentially lower trade frequency
```

Do not claim that parameter tuning guarantees profit.

## 29.8 Improving the Strategy

Explain possible research improvements such as:

* Better symbol selection
* Volatility filters
* ATR-based stops
* Market trend filter
* Index confirmation
* Opening-range breakout confirmation
* Relative volume
* Avoiding low-volume periods
* Avoiding extreme spreads
* Slippage modeling
* Transaction-cost modeling
* Walk-forward testing
* Out-of-sample validation
* Paper trading
* Position sizing
* Maximum drawdown controls

Clearly distinguish **strategy improvements** from **guaranteed profitability**.

Never state that any configuration will definitely make the trader profitable.

## 29.9 Risk Management

Explain:

* TP
* SL
* Daily loss limit
* Daily trade limit
* Position limits
* Square-off
* Duplicate-order prevention
* API failure protection
* Manual stop

## 29.10 Execution Lifecycle

Explain what happens from:

```text
python main.py
```

until:

```text
Bot stopped
```

Step by step.

## 29.11 AWS Deployment

Explain how to run it on a 1 GB RAM Linux VM.

Include:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Explain how to run safely in a terminal session.

Do not introduce Docker.

## 29.12 Operational Checklist

Include a pre-live checklist:

```text
☐ API credentials configured
☐ Security ID verified
☐ Symbol verified
☐ Quantity verified
☐ Paper trading tested
☐ TP verified
☐ SL verified
☐ Day-trading times verified
☐ Daily loss limit configured
☐ Daily trade limit configured
☐ Existing positions checked
☐ Stop mechanism tested
☐ AWS process tested
☐ Logs verified
```

## 29.13 Troubleshooting

Explain common failures:

* Authentication failure
* No market data
* Invalid security ID
* Order rejected
* Existing position detected
* Stop signal received
* API timeout
* Insufficient candles
* Invalid configuration

---

# 30. CODE QUALITY

Write production-quality Python.

Use:

* Type hints where useful
* Clear names
* Small functions
* Defensive programming
* Exception handling
* Logging
* Configuration validation
* No unnecessary abstractions

Avoid:

* Huge deeply nested functions
* Global mutable state where unnecessary
* Hard-coded trading parameters
* Hidden side effects
* Magic numbers
* Infinite uncontrolled retries
* Unnecessary dependencies

Because everything must remain in `main.py`, use clear section headers to keep the file navigable.

---

# 31. IMPORTANT LIVE-TRADING SAFETY

Never assume:

```text
HTTP/API success = order filled
```

Always verify actual order status.

Never assume:

```text
requested price = execution price
```

Use the actual average fill price.

Never place another entry while an existing position/order is unresolved.

When uncertain about an order's status, prioritize preventing duplicate orders over continuing automatically.

---

# 32. STARTUP BEHAVIOR

When starting:

```bash
python main.py
```

perform:

1. Load `.env`
2. Load `config.yaml`
3. Validate configuration
4. Initialize logging
5. Initialize Dhan client
6. Validate required credentials
7. Validate trading configuration
8. Check existing positions
9. Display safety mode
10. Display strategy configuration
11. Display trading session
12. Start polling loop

Example:

```text
╔══════════════════════════════════════════════╗
║       VWAP MOMENTUM ENGINE v1.0             ║
║              DHAN EXECUTION CORE             ║
╠══════════════════════════════════════════════╣
║ MODE       : PAPER                           ║
║ STRATEGY   : VWAP MOMENTUM                   ║
║ SYMBOL     : RELIANCE                        ║
║ TIMEFRAME  : 5m                              ║
║ POLLING    : 5 seconds                       ║
║ STATUS     : INITIALIZING                    ║
╚══════════════════════════════════════════════╝
```

---

# 33. CLEAN SHUTDOWN

Handle:

```text
CTRL+C
```

gracefully.

On shutdown:

1. Set bot state to shutting down
2. Stop new entries
3. Check open position
4. Follow configured shutdown behavior
5. Close positions if configured
6. Log final status
7. Exit cleanly

---

# 34. NO TRADE CONDITIONS

The strategy should explicitly return `NO_TRADE` when:

* Price is below VWAP
* Momentum insufficient
* Volume insufficient
* Trend confirmation fails
* Breakout confirmation fails
* Not enough candles
* Daily limit reached
* Outside trading hours
* Existing position exists
* Pending order exists
* Market data invalid
* Stop requested
* Live trading safety condition fails

Make the reason visible in the CLI.

Example:

```text
SIGNAL: NO TRADE
Reason: Volume confirmation failed
Score: 2/5
Required: 3/5
```

---

# 35. TESTABILITY

Although this is a single-file application, structure functions so indicator calculations and signal logic can be tested independently.

For example:

```python
calculate_vwap(...)
calculate_momentum(...)
calculate_volume_ratio(...)
generate_signal(...)
calculate_take_profit(...)
calculate_stop_loss(...)
```

must not unnecessarily depend on live Dhan API calls.

This allows later testing with historical data.

Do not create a separate test file because the required project structure is intentionally limited.

---

# 36. IMPORTANT IMPLEMENTATION PRINCIPLE

Do not make the algorithm artificially complex.

The objective is:

```text
Simple
→ Understandable
→ Configurable
→ Safe
→ Testable
→ Extensible
→ Production-oriented
```

The strategy should be sophisticated enough to be useful but simple enough that every decision can be explained.

---

# 37. DOCUMENTATION QUALITY

Comments inside `main.py` should explain the **reasoning behind the code**, not merely repeat what the code says.

Bad:

```python
# Calculate VWAP
vwap = ...
```

Better:

```python
# VWAP measures the average traded price weighted by volume during
# the current trading session. For a momentum strategy, we use VWAP
# as the primary reference point: sustained price action above VWAP
# suggests buyers are accepting higher prices.
vwap = ...
```

Use this level of explanation for important strategy and risk-management functions.

---

# 38. FINAL VALIDATION

Before finishing, verify:

```text
[ ] Exactly six final files exist
[ ] main.py contains the complete application
[ ] config.yaml contains configurable parameters
[ ] .env contains credential placeholders
[ ] stop.py works
[ ] requirements.txt is sufficient
[ ] architecture.md is complete
[ ] No dependency on docs/ files
[ ] Paper trading is safe by default
[ ] Live trading requires explicit configuration
[ ] VWAP is session-based
[ ] No look-ahead bias
[ ] TP/SL use actual fill price
[ ] TP/SL monitoring works
[ ] Bot can stop after TP/SL
[ ] Day-trading mode is configurable
[ ] EOD square-off works
[ ] Manual stop works
[ ] Existing positions are handled
[ ] Duplicate orders are prevented
[ ] Daily loss limit works
[ ] Daily trade limit works
[ ] CLI displays current P&L
[ ] CLI refreshes according to polling configuration
[ ] Polling interval is configurable
[ ] API failures are handled
[ ] Ctrl+C performs clean shutdown
[ ] Code runs on lightweight Linux
[ ] No unnecessary heavy dependencies
```

Do not claim that the strategy is profitable merely because the code works.

The documentation may discuss ways traders can research and tune the strategy to potentially improve performance, but clearly distinguish historical/backtest results from future performance.

Finally, write the implementation and `architecture.md` with **clear explanations, examples, formulas, function documentation, and step-by-step technical reasoning**, so that the code and explanations are suitable for reuse as high-quality educational material in technical trading documentation and books.
