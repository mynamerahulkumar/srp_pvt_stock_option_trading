You are an expert Python algorithmic-trading engineer specializing in the Dhan trading API, Indian NSE markets, robust automated execution, and production-quality trading systems.

Build a complete **Price Action Momentum Scalper Algo for Dhan**.

The project must be lightweight, reliable, easy to understand, and capable of running locally or on an AWS Linux VM with only **1 GB RAM**.

## 1. Project Objective

Create a live algorithmic trading bot based on **price-action momentum scalping**.

The strategy should identify short-term momentum using price action and configurable confirmation rules rather than relying on a large number of technical indicators.

The bot should:

* Connect to Dhan using credentials from `.env`.
* Fetch market data at a configurable polling interval.
* Default polling interval: **5 seconds**.
* Detect price-action momentum setups.
* Place trades automatically when all configured entry conditions are satisfied.
* Support configurable instruments.
* Support configurable quantity.
* Support long and short trades where permitted by the selected instrument/product.
* Set TP and SL according to configuration.
* Monitor the live position.
* Display current position and live/unrealized P&L in the CLI.
* Stop trading when TP or SL is reached.
* Optionally enforce a trading-day start and end time.
* At the configured end time, close all positions when enabled.
* Provide a clean emergency stop mechanism.
* Prevent duplicate orders.
* Recover safely after temporary API/network failures.
* Maintain state sufficiently to avoid accidental duplicate trades after a restart.
* Produce useful logs.
* Be understandable enough that every major function can be explained independently.

Do not over-engineer the project. Keep the implementation practical for a 1 GB RAM Linux VM.

---

# 2. REQUIRED PROJECT FILES

Create exactly these application files:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

The bot may create runtime files/directories automatically if required, such as:

```text
logs/
state/
```

Do NOT create additional Python modules.

All application logic must remain in:

```text
main.py
```

`stop.py` is only for stopping the running bot safely.

`config.yaml` contains all user-adjustable strategy, risk, execution, scheduling, polling, logging, and CLI parameters.

`.env` contains secrets.

`requirements.txt` contains dependencies.

`architecture.md` contains the complete strategy and architecture documentation.

---

# 3. REFERENCE FILES

Two reference files may exist initially:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

Read and understand these files before implementing the project if they exist.

Use them only as implementation references for:

* Dhan API usage
* authentication
* API initialization
* instrument/security identifiers
* market-data retrieval
* order placement
* order modification/cancellation
* position retrieval
* order status
* relevant Dhan SDK/API conventions

IMPORTANT:

The final implementation must NOT depend on these files.

After development, the following must be true:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

can be deleted and the bot must still work.

Do not import these files.

Use the currently supported Dhan API/SDK patterns found in the available reference material. If an API behavior is uncertain, isolate it behind small functions in `main.py` so it can easily be corrected later.

---

# 4. PRICE ACTION MOMENTUM STRATEGY

Implement a clear, deterministic **Price Action Momentum Scalping Strategy**.

The strategy should be based primarily on:

1. Recent candle structure
2. Breakout of a configurable lookback high/low
3. Candle body strength
4. Directional momentum
5. Volume confirmation, when enabled
6. Optional spread/slippage protection
7. Optional trend confirmation
8. Configurable minimum momentum threshold
9. Configurable cooldown between trades

Avoid unnecessary indicators.

The strategy should be easy to understand.

## Long setup

A long trade should be considered when conditions such as the following are satisfied:

### Breakout

Current/confirmed candle breaks above the recent configurable lookback high.

Example:

```text
breakout_high = highest high of previous N completed candles
```

Long breakout condition:

```text
current_price > breakout_high
```

### Momentum confirmation

The breakout candle should demonstrate sufficient bullish strength.

For example:

```text
body_size = abs(close - open)
candle_range = high - low
body_ratio = body_size / candle_range
```

Require:

```text
body_ratio >= minimum_body_ratio
```

and:

```text
close > open
```

### Optional volume confirmation

When enabled:

```text
current_volume >= average_volume * volume_multiplier
```

### Optional trend confirmation

When enabled, require a configurable fast/slow trend relationship.

Keep this optional because the primary strategy is price action.

---

# 5. SHORT SETUP

Implement the symmetrical short strategy.

A short trade can be considered when:

```text
current_price < recent_lookback_low
```

and:

```text
close < open
```

and:

```text
body_ratio >= minimum_body_ratio
```

plus optional:

* volume confirmation
* trend confirmation
* momentum threshold

Do not duplicate unnecessary code.

Create reusable functions for long and short setup validation.

---

# 6. USE COMPLETED CANDLES

Avoid using incomplete candles for signal confirmation wherever possible.

Make candle timeframe configurable.

Example:

```yaml
strategy:
  timeframe: "1"
```

The implementation should clearly distinguish:

```text
completed candle
```

from:

```text
currently forming candle
```

Do not repeatedly enter on the same candle.

Maintain a last-processed candle timestamp/state.

---

# 7. STRATEGY PARAMETERS

Everything should be configurable through `config.yaml`.

At minimum provide:

```yaml
strategy:
  enabled: true
  timeframe: "1"
  lookback_candles: 5

  minimum_body_ratio: 0.60

  volume_confirmation:
    enabled: true
    average_period: 20
    volume_multiplier: 1.20

  trend_confirmation:
    enabled: false
    fast_period: 9
    slow_period: 21

  minimum_price_move_percent: 0.0

  allow_long: true
  allow_short: true

  cooldown_seconds: 60

  max_trades_per_day: 5
```

Choose sensible defaults.

The implementation may add additional parameters where useful.

---

# 8. INSTRUMENT CONFIGURATION

Make instrument configuration completely configurable.

Example:

```yaml
instrument:
  exchange_segment: "NSE_EQ"
  security_id: ""
  trading_symbol: ""
  product_type: "INTRADAY"
  quantity: 1
```

Also support configurable order properties such as:

```yaml
order:
  order_type: "MARKET"
  validity: "DAY"
  disclosed_quantity: 0
  amo: false
```

Do not hard-code a particular stock.

The same code should be reusable for different NSE instruments by changing configuration.

---

# 9. TP / SL

Implement configurable take-profit and stop-loss.

Example:

```yaml
risk:
  take_profit:
    enabled: true
    type: "PERCENT"
    value: 0.30

  stop_loss:
    enabled: true
    type: "PERCENT"
    value: 0.20
```

Support at least:

```text
PERCENT
POINTS
```

The calculation must correctly account for:

### Long

```text
TP = entry_price + target
SL = entry_price - stop
```

### Short

```text
TP = entry_price - target
SL = entry_price + stop
```

Make sure the bot does not assume that the order fills exactly at the requested price.

Use the actual average fill/entry price wherever Dhan provides it.

---

# 10. TP/SL EXECUTION

After an entry is successfully filled:

1. Determine actual entry price.
2. Calculate TP.
3. Calculate SL.
4. Monitor the position.
5. Exit when either condition is reached.
6. Record the result.
7. Stop the bot after TP/SL is reached.

IMPORTANT:

When TP or SL is reached:

```text
close the position
stop the bot
```

Do not continue searching for new trades.

Make this behavior configurable, but the default must be:

```yaml
risk:
  stop_bot_after_exit: true
```

If the configured exit mechanism uses exchange-side protective orders, still verify position/order state and ensure the bot does not accidentally enter another trade.

---

# 11. POSITION MONITORING

Every polling cycle, when a position exists, display:

```text
Symbol
Direction
Quantity
Entry Price
Current Price
Stop Loss
Take Profit
Unrealized P&L
P&L %
Position Status
```

The CLI should make it immediately obvious whether the bot is:

```text
WAITING
SIGNAL DETECTED
ORDER SUBMITTED
ORDER FILLED
POSITION OPEN
TP HIT
SL HIT
EXITING
STOPPED
ERROR
```

---

# 12. DAILY TRADING MODE

Add:

```yaml
schedule:
  enabled: true
  start_time: "09:20"
  stop_time: "15:15"
  close_all_positions_at_stop_time: true
```

When:

```yaml
schedule:
  enabled: true
```

the bot should:

* Wait until `start_time`.
* Not initiate trades before start time.
* Trade only inside the configured window.
* Stop opening new trades after `stop_time`.
* Close open positions at `stop_time` if:

  ```yaml
  close_all_positions_at_stop_time: true
  ```
* Stop the bot after positions are closed.

If:

```yaml
schedule:
  enabled: false
```

the bot must not enforce a trading-time window.

It should be possible to run the bot without daily time restrictions.

Use Indian market time appropriately.

Do not hard-code the timezone. Make it configurable:

```yaml
schedule:
  timezone: "Asia/Kolkata"
```

---

# 13. CLOSE ALL POSITIONS

Implement a safe function:

```text
close_all_positions()
```

This function should:

1. Retrieve open positions.
2. Identify positions belonging to this strategy/instrument where possible.
3. Send appropriate exit orders.
4. Verify that positions are closed.
5. Log the result.
6. Stop the bot if configured.

Never blindly send repeated close orders.

Use idempotent logic where practical.

---

# 14. EMERGENCY STOP

Create:

```text
stop.py
```

The purpose of `stop.py` is to safely request the running bot to stop.

Use a lightweight mechanism suitable for Linux, such as:

```text
stop flag file
```

Example:

```text
state/STOP
```

`main.py` must check this stop signal every polling cycle.

When detected:

1. Stop opening new trades.
2. Depending on configuration, optionally close the current strategy position.
3. Log the action.
4. Shut down cleanly.

Configuration:

```yaml
emergency_stop:
  close_position: true
```

`stop.py` should be extremely simple and reliable.

It should work like:

```bash
python stop.py
```

Do not require another server.

---

# 15. POLLING

The default polling interval must be:

```yaml
runtime:
  polling_seconds: 5
```

Every polling cycle:

1. Check stop signal.
2. Check schedule.
3. Check current position.
4. Fetch current market data.
5. Update P&L.
6. Evaluate strategy if appropriate.
7. Place order if signal is valid.
8. Monitor TP/SL.
9. Update CLI.
10. Sleep for configured seconds.

Do not use unnecessary high-frequency polling.

The polling interval must be configurable.

---

# 16. DUPLICATE TRADE PROTECTION

Implement multiple protections:

* One active position at a time by default.
* Do not submit another order while an entry order is pending.
* Do not process the same candle repeatedly.
* Respect cooldown.
* Respect maximum daily trades.
* Verify actual Dhan order/position state before entering.
* Handle uncertain order status safely.

Configuration:

```yaml
execution:
  one_position_at_a_time: true
  verify_order_status: true
  verify_position_before_entry: true
```

---

# 17. DAILY TRADE LIMIT

Implement:

```yaml
risk:
  max_trades_per_day: 5
```

The bot must count completed/initiated trades according to a clearly documented definition.

Prevent new entries once the limit is reached.

Persist enough state to survive an application restart during the same trading day.

---

# 18. CAPITAL / RISK CONTROLS

Add configurable risk controls such as:

```yaml
risk:
  max_daily_loss: 1000
  max_daily_profit: 3000
  max_trades_per_day: 5
  stop_bot_after_exit: true
```

If the daily loss limit is reached:

* Do not open new positions.
* Close the current strategy position if configured.
* Stop the bot.

If daily profit target is reached:

* Do not open new positions.
* Optionally close the current position.
* Stop the bot.

Use:

```yaml
daily_limits:
  enabled: true
  max_loss: 1000
  max_profit: 3000
  close_position_on_limit: true
```

Keep these controls clearly separated from TP/SL.

---

# 19. SLIPPAGE PROTECTION

Add optional protection:

```yaml
execution:
  max_entry_slippage_percent: 0.10
  max_exit_slippage_percent: 0.20
```

If the actual entry price differs materially from expected trigger/reference price, log the slippage.

Do not create complicated execution algorithms.

The goal is robust and understandable execution.

---

# 20. Dhan API LAYER

Keep all Dhan API interaction inside clearly named functions in `main.py`.

For example:

```text
initialize_dhan()
get_market_data()
get_ltp()
get_historical_data()
place_entry_order()
place_exit_order()
get_order_status()
get_positions()
get_open_position()
close_all_positions()
```

Use the exact API methods supported by the Dhan reference implementation/SDK.

Do not spread API calls randomly throughout the strategy logic.

The strategy should call clean wrapper functions.

This separation is important.

---

# 21. STRATEGY LAYER

Keep strategy calculations independent from Dhan API code.

Create functions such as:

```text
calculate_candle_metrics()
calculate_breakout_levels()
calculate_volume_confirmation()
calculate_trend_confirmation()
check_long_signal()
check_short_signal()
generate_signal()
```

A strategy function should ideally receive market data and configuration and return something simple such as:

```text
LONG
SHORT
NONE
```

or a structured signal object/dictionary.

Do not place order execution directly inside strategy calculations.

---

# 22. EXECUTION LAYER

Create separate functions for:

```text
execute_signal()
wait_for_order_fill()
calculate_exit_levels()
monitor_position()
exit_position()
```

Execution should consume a strategy signal.

Do not mix:

```text
indicator calculation
```

with:

```text
Dhan order submission
```

---

# 23. STATE MANAGEMENT

Use a lightweight state file, preferably JSON.

Example:

```text
state/bot_state.json
```

Persist useful information such as:

```text
bot status
current trading day
trade count
last processed candle
last signal
entry order ID
exit order ID
entry price
TP
SL
position direction
```

Do not persist secrets.

Handle corrupted state files gracefully.

If the state cannot safely be trusted, fail safely rather than placing an unexpected trade.

---

# 24. LOGGING

Implement Python logging.

Logs should include:

```text
timestamp
log level
event
symbol
strategy
order ID where applicable
position information
```

Log important events:

* startup
* configuration loaded
* Dhan connection initialized
* market data errors
* signal generated
* signal rejected
* order submitted
* order filled
* order rejected
* TP reached
* SL reached
* position closed
* daily limit reached
* schedule stopped
* emergency stop
* shutdown
* unexpected exception

Use rotating log files so the AWS VM does not eventually run out of disk space.

Configuration:

```yaml
logging:
  level: "INFO"
  file: "logs/price_action_momentum.log"
  max_bytes: 5242880
  backup_count: 3
```

---

# 25. SCI-FI CLI

Create a clean, compact, sci-fi-style terminal interface.

Do not make it excessively decorative.

The CLI should feel like a professional trading console.

Example concept:

```text
╔══════════════════════════════════════════════════════╗
║        ◈ DHAN // PRICE ACTION MOMENTUM CORE ◈       ║
╠══════════════════════════════════════════════════════╣
║ SYSTEM       : ONLINE                                ║
║ MARKET       : NSE                                   ║
║ MODE         : INTRADAY                              ║
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
║ NEXT SCAN   : 5 SEC                                  ║
╚══════════════════════════════════════════════════════╝
```

The actual implementation can use ASCII/Unicode safely.

Provide a configuration option:

```yaml
cli:
  enabled: true
  refresh_seconds: 1
  show_signal_details: true
  show_position_pnl: true
```

Do not require a heavy UI framework.

Prefer standard library output or a lightweight dependency.

---

# 26. LIVE P&L

The CLI must show current P&L.

For long:

```text
P&L = (LTP - Entry Price) × Quantity
```

For short:

```text
P&L = (Entry Price - LTP) × Quantity
```

If Dhan provides authoritative realized/unrealized P&L, prefer the broker-provided value for live account state.

Clearly distinguish:

```text
Unrealized P&L
Realized P&L
```

where possible.

---

# 27. ERROR HANDLING

The bot must NOT crash because of a temporary:

* API timeout
* network failure
* malformed response
* rate-limit response
* temporary market-data failure

Implement:

* exception handling
* retry with bounded backoff
* logging
* safe state handling

Do not retry order submission blindly.

This is extremely important.

For order submission, an ambiguous API response must be treated as:

```text
UNKNOWN ORDER STATE
```

and the bot should query the order status before deciding whether another order should be submitted.

---

# 28. MARKET DATA VALIDATION

Validate:

* timestamps
* OHLC values
* volume
* NaN/null values
* candle ordering
* duplicate candles
* missing candles

Do not generate a signal from invalid data.

Log why a signal was rejected.

---

# 29. TIME HANDLING

Use timezone-aware datetime objects.

Use:

```text
Asia/Kolkata
```

through configuration.

Avoid naive datetime comparisons between local time and UTC.

Clearly document all time assumptions.

---

# 30. CONFIGURATION VALIDATION

At startup validate `config.yaml`.

Reject unsafe configurations such as:

* quantity <= 0
* negative TP
* negative SL
* invalid timeframe
* invalid polling interval
* start time after stop time
* invalid security ID
* both long and short disabled
* impossible risk limits

Print clear configuration errors and stop.

Never silently replace dangerous values with defaults.

---

# 31. ENVIRONMENT VARIABLES

`.env` should contain only secrets and environment-specific values.

Example:

```text
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

If the Dhan API requires additional credentials, include them only if actually required.

Never place secrets in `config.yaml`.

Never print secrets to logs or CLI.

---

# 32. REQUIREMENTS

Keep dependencies minimal.

`requirements.txt` should include only packages actually required.

Potential dependencies may include:

```text
dhanhq
pandas
PyYAML
python-dotenv
```

Add other packages only if genuinely necessary.

Avoid large frameworks.

The bot must be suitable for:

```text
AWS Linux
1 GB RAM
```

---

# 33. MAIN.PY FUNCTION DOCUMENTATION

Every important function in `main.py` must have a useful docstring.

For example:

```python
def calculate_breakout_levels(candles, lookback):
    """
    Calculate the breakout levels using completed candles.

    Use case:
    The strategy uses these levels to determine whether price
    has broken out of its recent trading range.
    """
```

Every major function should explain:

1. What the function does.
2. Why it exists.
3. What inputs it receives.
4. What it returns.
5. Important safety considerations.
6. Its use case in the trading system.

Add concise inline comments around non-obvious trading logic.

Do not comment every obvious line.

Comments should explain trading logic, execution decisions, and safety considerations.

---

# 34. MAIN PROGRAM FLOW

Structure `main.py` logically in sections:

```text
Imports
Constants
Configuration loading
Logging
Environment loading
State management
Dhan API wrapper
Market-data functions
Strategy calculations
Signal generation
Risk management
Order execution
Position monitoring
TP/SL management
Scheduling
CLI
Emergency stop
Main loop
Main entry point
```

Use functions/classes only where they improve clarity.

A single-file architecture is intentional.

---

# 35. MAIN LOOP

The main loop should approximately follow:

```text
START
 ↓
Load .env
 ↓
Load config.yaml
 ↓
Validate configuration
 ↓
Initialize logging
 ↓
Initialize state
 ↓
Initialize Dhan
 ↓
Check current broker positions
 ↓
Synchronize local state
 ↓
Display SYSTEM ONLINE
 ↓
MAIN LOOP
     ↓
     Check emergency stop
     ↓
     Check trading schedule
     ↓
     Check daily limits
     ↓
     Get current position
     ↓
     If position exists:
         update LTP
         calculate P&L
         check TP
         check SL
         update CLI
     ↓
     If no position:
         fetch candles
         validate candles
         generate signal
         check cooldown
         check trade limit
         check risk
         execute signal
     ↓
     Sleep polling_seconds
 ↓
SAFE SHUTDOWN
```

---

# 36. RESTART RECOVERY

If the bot restarts while a position already exists:

* Query Dhan positions.
* Identify the relevant position.
* Recover the position state.
* Calculate/restore TP and SL where possible.
* Resume monitoring.
* Do NOT create another entry.

If an order is pending:

* Query its status.
* Do not submit another order until the status is understood.

Document this behavior clearly.

---

# 37. ORDER TAGGING

If supported by Dhan, use a configurable order tag/client correlation identifier.

Example:

```yaml
execution:
  order_tag: "PAM_SCALPER"
```

Use it to make order tracking easier.

Do not assume unsupported Dhan functionality. Follow the actual API.

---

# 38. SECURITY

Never:

* hard-code API credentials
* print access tokens
* save tokens in state files
* commit `.env`
* expose secrets in exceptions/logs

Add `.env` loading and make the configuration safe for deployment.

---

# 39. DRY RUN / PAPER MODE

Implement:

```yaml
runtime:
  dry_run: true
```

When enabled:

* Do not send real orders.
* Generate signals normally.
* Show hypothetical execution.
* Show calculated TP/SL.
* Log what order would have been submitted.

When:

```yaml
runtime:
  dry_run: false
```

the bot can submit live orders.

Make dry-run behavior obvious in the CLI:

```text
MODE: DRY RUN
```

This should be the safe default.

---

# 40. CONFIG.YAML

Create a complete example configuration.

Include sections similar to:

```yaml
app:
  name: "Dhan Price Action Momentum Scalper"
  version: "1.0.0"

runtime:
  dry_run: true
  polling_seconds: 5
  state_file: "state/bot_state.json"

instrument:
  exchange_segment: "NSE_EQ"
  security_id: ""
  trading_symbol: ""
  product_type: "INTRADAY"
  quantity: 1

strategy:
  enabled: true
  timeframe: "1"
  lookback_candles: 5
  minimum_body_ratio: 0.60

  volume_confirmation:
    enabled: true
    average_period: 20
    volume_multiplier: 1.20

  trend_confirmation:
    enabled: false
    fast_period: 9
    slow_period: 21

  minimum_price_move_percent: 0.0
  allow_long: true
  allow_short: true
  cooldown_seconds: 60
  max_trades_per_day: 5

risk:
  take_profit:
    enabled: true
    type: "PERCENT"
    value: 0.30

  stop_loss:
    enabled: true
    type: "PERCENT"
    value: 0.20

  stop_bot_after_exit: true

daily_limits:
  enabled: true
  max_loss: 1000
  max_profit: 3000
  close_position_on_limit: true

execution:
  one_position_at_a_time: true
  verify_order_status: true
  verify_position_before_entry: true
  max_entry_slippage_percent: 0.10
  max_exit_slippage_percent: 0.20
  order_tag: "PAM_SCALPER"

schedule:
  enabled: true
  timezone: "Asia/Kolkata"
  start_time: "09:20"
  stop_time: "15:15"
  close_all_positions_at_stop_time: true

emergency_stop:
  close_position: true

cli:
  enabled: true
  refresh_seconds: 1
  show_signal_details: true
  show_position_pnl: true

logging:
  level: "INFO"
  file: "logs/price_action_momentum.log"
  max_bytes: 5242880
  backup_count: 3
```

Add comments explaining each configurable parameter.

---

# 41. ARCHITECTURE.MD

Create a comprehensive:

```text
architecture.md
```

This document must be written as a complete educational chapter explaining the actual implementation.

It should contain:

## 41.1 Strategy Overview

Explain:

* What price-action momentum means.
* Why breakout momentum can work.
* Why candle-body strength is used.
* Why volume confirmation can help.
* Why false breakouts occur.
* Why scalping requires strict risk management.

## 41.2 Strategy Rules

Explain long and short rules step by step.

Use simple numerical examples.

Example:

```text
Previous 5-candle high = ₹1,000

Price breaks to ₹1,003

Breakout candle:
Open = ₹1,000
High = ₹1,005
Low = ₹999
Close = ₹1,004

Body = ₹4
Range = ₹6

Body ratio = 4 / 6 = 66.7%
```

Then explain why this satisfies a 60% body-ratio threshold.

## 41.3 Complete Trade Example

Provide a realistic example showing:

```text
Entry
Quantity
Entry price
TP
SL
Price movement
Exit
Gross P&L
```

For example:

```text
Long entry = ₹1,000
Quantity = 100
TP = 0.30%
SL = 0.20%
```

Calculate the resulting prices and P&L correctly.

Also provide an example where SL is hit.

Clearly explain that these are examples, not guaranteed outcomes.

## 41.4 Execution Lifecycle

Explain:

```text
Signal
→ Order
→ Fill
→ Position
→ Monitoring
→ TP/SL
→ Exit
→ Shutdown
```

## 41.5 Every Main.py Function

Document each important function:

```text
Function name
Purpose
Inputs
Outputs
How it works
Why it is needed
Failure scenarios
```

The explanations must correspond to the actual implemented code.

Do NOT document functions that do not exist.

## 41.6 Configuration Tuning

Explain how a trader can tune:

* lookback candles
* body ratio
* volume multiplier
* volume period
* trend confirmation
* TP
* SL
* cooldown
* polling interval
* max trades
* daily loss
* daily profit

For every parameter explain:

```text
Increasing it may do X
Decreasing it may do Y
Potential benefit
Potential drawback
```

Avoid claiming that any parameter will guarantee higher profits.

## 41.7 Profitability Improvement Framework

Provide practical guidance on improving strategy quality through:

* historical backtesting
* out-of-sample testing
* walk-forward testing
* transaction-cost analysis
* slippage analysis
* parameter sensitivity analysis
* maximum drawdown
* win rate
* average win
* average loss
* profit factor
* expectancy
* risk/reward
* regime analysis

Explain that profitability cannot be guaranteed.

The objective should be to improve expected risk-adjusted performance rather than simply maximize the number of winning trades.

## 41.8 False Breakout Handling

Explain common false breakout situations and how configuration can reduce them.

## 41.9 Risk Management

Explain why:

```text
small stop + disciplined position sizing
```

can be more important than increasing signal frequency.

## 41.10 Live Trading Safety

Explain:

* dry run
* small quantity
* API failures
* duplicate orders
* restart recovery
* emergency stop
* broker position verification
* daily loss limits

## 41.11 Deployment

Explain how to run:

```bash
python main.py
```

and:

```bash
python stop.py
```

Include example Linux/AWS deployment commands where useful.

Explain how to keep it running with a lightweight process manager such as `systemd` or `nohup`, but do not require additional project files.

## 41.12 Example CLI

Show a representative CLI output.

## 41.13 End-to-End Example

Walk through one complete trade from:

```text
market data
→ candle formation
→ breakout
→ momentum confirmation
→ signal
→ risk validation
→ order
→ fill
→ TP/SL calculation
→ monitoring
→ exit
→ P&L
→ shutdown
```

Make the explanation clear enough for a reader to follow without seeing the source code first.

At the end, explicitly state that examples are educational and that live trading involves market, execution, liquidity, slippage, and loss risks.

Write `architecture.md` in a polished, educational technical style. The explanations should be directly useful as reusable educational material, including the code explanations and examples.

---

# 42. CODE QUALITY REQUIREMENTS

The generated code must:

* Be complete.
* Be executable.
* Avoid pseudocode.
* Avoid TODO placeholders.
* Avoid fake Dhan API methods.
* Use the actual Dhan API/SDK patterns available from the reference.
* Have clear error handling.
* Have type hints where practical.
* Have useful docstrings.
* Be PEP 8 reasonably compliant.
* Be lightweight.
* Avoid unnecessary classes/frameworks.
* Avoid unnecessary background threads.
* Avoid memory-heavy data structures.
* Avoid infinite tight loops.
* Handle Ctrl+C gracefully.
* Shut down cleanly.
* Never accidentally submit duplicate orders because of an exception.
* Never expose credentials.

---

# 43. IMPORTANT TRADING SAFETY RULE

Never assume an order was filled merely because order submission returned successfully.

Always distinguish:

```text
SUBMITTED
PENDING
FILLED
REJECTED
CANCELLED
UNKNOWN
```

Use broker order status/position information to confirm actual execution.

If the state is unknown:

```text
do not submit another entry order
```

until the existing order state has been resolved.

---

# 44. NO PROFIT GUARANTEE

Do not encode any assumption that the strategy will always be profitable.

The implementation should focus on:

```text
signal quality
risk control
execution reliability
capital preservation
measurable performance
```

The documentation can provide suggestions for parameter optimization, but clearly state that no parameter guarantees profit.

---

# 45. FINAL VALIDATION

After generating all files, inspect the entire implementation for consistency.

Verify:

1. Every config key used by `main.py` exists in `config.yaml`.
2. Every required function exists.
3. Dhan API calls follow the reference implementation.
4. No dependency on `docs/project_requirements.md`.
5. No dependency on `docs/Dhan_SRP.py`.
6. `.env` secrets are not logged.
7. `stop.py` works with the stop mechanism.
8. TP/SL calculations work for both long and short.
9. TP/SL exit stops the bot when configured.
10. Schedule works when enabled.
11. Schedule restrictions are disabled when `schedule.enabled=false`.
12. Close-all-positions works at configured stop time.
13. Emergency stop works.
14. Daily loss/profit limits work.
15. Maximum daily trades work.
16. Duplicate entries are prevented.
17. Restart recovery is safe.
18. Dry-run mode cannot submit live orders.
19. CLI displays current position and P&L.
20. Polling interval comes from YAML.
21. Invalid configuration is rejected safely.
22. Temporary API failures do not crash the bot.
23. Ambiguous order status does not cause duplicate orders.
24. The project runs within the constraints of a 1 GB RAM Linux VM.
25. `architecture.md` matches the actual code.

---

# 46. FINAL FILE STRUCTURE

The final project must look like:

```text
price-action-momentum/
│
├── main.py
├── config.yaml
├── .env
├── stop.py
├── requirements.txt
└── architecture.md
```

Runtime-generated files may appear as:

```text
logs/
└── price_action_momentum.log

state/
├── bot_state.json
└── STOP
```

Do not create any other source-code files.

---

# 47. FINAL IMPLEMENTATION STANDARD

Write the code as if another developer will need to understand every important trading decision by reading `main.py`.

The implementation must prioritize:

```text
READABILITY
RELIABILITY
SAFETY
CONFIGURABILITY
EXECUTION CORRECTNESS
LOW RESOURCE USAGE
```

Do not sacrifice execution safety merely to make the code shorter.

At the same time, avoid unnecessary enterprise-level complexity.

The resulting code and its explanations should be structured, clear, technically accurate, and reusable as high-quality educational material, with each important function, trading decision, execution step, configuration parameter, and end-to-end example explained clearly.
