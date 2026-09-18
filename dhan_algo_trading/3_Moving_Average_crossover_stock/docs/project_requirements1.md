Create a complete, production-ready Python algorithmic trading bot for the **Dhan trading API** based on a **Moving Average Crossover strategy**.

## 1. Project Structure

The final project must contain **ONLY these five files**:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
```

There may initially be two reference files:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

You may read and use these files as references for Dhan API usage, authentication, order placement, instrument handling, WebSocket/market-data handling, error handling, and project conventions.

**Important:** These reference files are temporary. The final implementation must NOT depend on them. The bot must continue working after both files are deleted.

Do not create additional Python modules, helper files, databases, JSON files, log files, cache files, or other runtime dependencies unless absolutely required by the Dhan API/library. Keep the implementation self-contained.

---

# 2. Main Strategy

Implement a **Moving Average Crossover Algo**.

The strategy should support configurable fast and slow moving averages.

Example:

```text
Fast MA = 9
Slow MA = 21
```

Basic logic:

### Bullish crossover

Generate a BUY signal when:

```text
Previous Fast MA <= Previous Slow MA
AND
Current Fast MA > Current Slow MA
```

### Bearish crossover

Generate a SELL/exit signal when:

```text
Previous Fast MA >= Previous Slow MA
AND
Current Fast MA < Current Slow MA
```

Do not repeatedly place orders on every polling cycle after a signal has already been acted upon.

The strategy must operate using completed candles by default so that signals are not generated from unstable/incomplete candle values.

Make candle timeframe configurable.

Example:

```yaml
strategy:
  timeframe: "5"
  fast_ma_period: 9
  slow_ma_period: 21
  ma_type: "SMA"
```

Support at least:

```text
SMA
EMA
```

Design the code so additional moving-average types can easily be added later.

---

# 3. Trading Modes

The configuration must support at least:

```text
LONG_ONLY
SHORT_ONLY
LONG_SHORT
```

For example:

### LONG_ONLY

* Bullish crossover → enter BUY
* Bearish crossover → exit BUY
* Never open short positions

### SHORT_ONLY

* Bearish crossover → enter SELL/short
* Bullish crossover → exit short
* Never open long positions

### LONG_SHORT

* Bullish crossover → enter long
* Bearish crossover → enter short
* Reverse position safely when required

Make this completely configurable.

---

# 4. Instrument Configuration

Everything related to the traded instrument must be configurable through `config.yaml`.

Support fields such as:

```yaml
instrument:
  exchange_segment: "NSE_EQ"
  security_id: ""
  trading_symbol: ""
  quantity: 1
  product_type: "INTRADAY"
```

Do not hardcode:

* Security ID
* Trading symbol
* Quantity
* Exchange segment
* Product type
* Order type
* Transaction type

The code should validate the configuration before starting the trading loop.

---

# 5. Order Types

Support configurable order type.

At minimum support:

```text
MARKET
LIMIT
```

Example:

```yaml
order:
  entry_order_type: "MARKET"
  exit_order_type: "MARKET"
```

For LIMIT orders, make the required price configurable or calculate it according to a clearly documented configuration option.

Do not silently convert LIMIT orders into MARKET orders.

Validate all required parameters before submitting an order.

---

# 6. Take Profit and Stop Loss

The bot must support configurable TP/SL.

Example:

```yaml
risk:
  take_profit_enabled: true
  take_profit_percent: 1.0

  stop_loss_enabled: true
  stop_loss_percent: 0.5
```

Support both:

```text
percentage based TP/SL
absolute price based TP/SL
```

if practical.

The configuration should determine which method is active.

For a LONG position:

```text
Entry Price = P

Take Profit = P + configured TP
Stop Loss   = P - configured SL
```

For a SHORT position:

```text
Entry Price = P

Take Profit = P - configured TP
Stop Loss   = P + configured SL
```

The implementation must correctly account for tick size and price precision where applicable.

---

# 7. TP/SL Bot Shutdown Requirement

When TP or SL is reached:

1. Exit the open position.
2. Confirm/verify the position is closed.
3. Stop the trading bot for that trading session.
4. Do not enter another trade after TP/SL shutdown.
5. Log the reason for shutdown clearly.

Example:

```text
STOP_REASON = TAKE_PROFIT
STOP_REASON = STOP_LOSS
```

The bot must not continue trading after a TP/SL exit unless there is an explicit configuration option allowing this behavior.

Provide:

```yaml
risk:
  stop_bot_on_tp: true
  stop_bot_on_sl: true
```

Default these to `true`.

If disabled, the bot may continue according to the strategy.

---

# 8. Trading Session / Day Trading Configuration

Implement configurable trading start and stop times.

Example:

```yaml
trading_session:
  enabled: true
  start_time: "09:20"
  stop_time: "15:15"
  timezone: "Asia/Kolkata"
  close_all_positions_at_stop: true
```

When:

```text
trading_session.enabled = true
```

the bot should:

* Wait until the configured start time.
* Allow strategy execution only during the configured trading window.
* Stop initiating new trades after the configured stop time.
* Optionally close all open positions at the configured stop time.
* Confirm positions are closed.
* Shut down cleanly.

This mode should effectively support day trading.

When:

```text
trading_session.enabled = false
```

do not impose trading-session start/stop restrictions.

The strategy should continue running without mandatory time-based shutdown.

Do not assume that disabled session timing means positions should automatically be closed.

---

# 9. Close-All-Positions Functionality

Implement a robust function in `main.py`:

```python
close_all_positions()
```

This function must:

1. Fetch current positions from Dhan.
2. Identify open positions.
3. Determine the correct opposite transaction type.
4. Place exit orders.
5. Verify that positions are closed.
6. Retry safely if necessary.
7. Log every action.
8. Avoid duplicate exit orders.

Use it for:

* End-of-day shutdown
* Manual stop
* Emergency shutdown
* TP/SL shutdown where applicable

The function must handle multiple open positions safely.

---

# 10. stop.py

Create a minimal but reliable `stop.py`.

Its purpose is to stop the running bot safely.

It should provide a mechanism that allows the user to stop the bot and trigger the bot's shutdown process.

Do NOT simply kill the process without cleanup.

The shutdown process should attempt to:

1. Signal the running bot.
2. Allow `main.py` to perform graceful shutdown.
3. Close positions if configured.
4. Prevent new orders.
5. Exit cleanly.

Design this to work on a small Linux AWS VM.

Avoid heavyweight infrastructure.

If a lightweight PID/signal mechanism is appropriate, use it.

Document clearly in comments how `stop.py` communicates with `main.py`.

---

# 11. Graceful Shutdown

`main.py` must handle:

```text
SIGINT
SIGTERM
```

and any other practical shutdown signal.

On shutdown:

1. Stop generating new signals.
2. Stop placing new entry orders.
3. Determine whether positions should be closed.
4. Respect the configured shutdown behavior.
5. Close positions when configured.
6. Verify final position state.
7. Log shutdown reason.
8. Exit cleanly.

Do not leave the bot in an undefined state.

---

# 12. Dhan API Integration

Use the Dhan API/library according to the latest compatible implementation available in the reference files.

Before writing the implementation:

1. Carefully inspect `docs/project_requirements.md`.
2. Carefully inspect `docs/Dhan_SRP.py`.
3. Identify the correct Dhan authentication process.
4. Identify order placement APIs.
5. Identify order status APIs.
6. Identify position APIs.
7. Identify market-data/candle APIs.
8. Identify instrument/security-ID requirements.
9. Follow the existing reference implementation where appropriate.

Do not blindly copy obsolete or incorrect code.

If the reference implementation uses an older API pattern, adapt it to the currently available Dhan SDK/API used by the project.

Authentication credentials must NEVER be hardcoded.

---

# 13. .env

Use `.env` for secrets only.

Example:

```text
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Never place API credentials directly inside:

```text
main.py
config.yaml
stop.py
```

Do not print secrets in logs.

Use environment variables through a suitable Python package.

---

# 14. config.yaml

All non-secret configuration must be controlled through `config.yaml`.

Do not scatter hardcoded strategy settings throughout `main.py`.

At minimum include configuration sections for:

```yaml
bot:
strategy:
instrument:
order:
risk:
trading_session:
polling:
logging:
shutdown:
```

Example structure:

```yaml
bot:
  name: "Dhan Moving Average Crossover"
  mode: "LIVE"
  dry_run: true

strategy:
  timeframe: "5"
  fast_ma_period: 9
  slow_ma_period: 21
  ma_type: "SMA"
  trading_mode: "LONG_ONLY"

instrument:
  exchange_segment: "NSE_EQ"
  security_id: ""
  trading_symbol: ""
  quantity: 1
  product_type: "INTRADAY"

order:
  entry_order_type: "MARKET"
  exit_order_type: "MARKET"

risk:
  take_profit_enabled: true
  take_profit_percent: 1.0
  stop_loss_enabled: true
  stop_loss_percent: 0.5
  stop_bot_on_tp: true
  stop_bot_on_sl: true

trading_session:
  enabled: true
  start_time: "09:20"
  stop_time: "15:15"
  timezone: "Asia/Kolkata"
  close_all_positions_at_stop: true

polling:
  interval_seconds: 10
  candle_lookback: 100

shutdown:
  close_positions_on_manual_stop: true
  close_positions_on_error: false

logging:
  level: "INFO"
```

You may improve this structure if necessary.

---

# 15. LIVE and DRY-RUN Mode

Implement:

```yaml
bot:
  mode: "LIVE"
  dry_run: true
```

or an equivalent clear mechanism.

DRY-RUN mode must:

* Fetch real market data.
* Calculate signals.
* Show what orders WOULD be placed.
* NOT send real orders.

LIVE mode must send actual Dhan orders.

Make the behavior extremely clear in logs.

At startup, print something similar to:

```text
==================================================
Dhan Moving Average Crossover Algo
Mode: DRY RUN
Trading Symbol: ...
Timeframe: ...
Fast MA: ...
Slow MA: ...
==================================================
```

Never accidentally send live orders when dry-run mode is enabled.

---

# 16. Market Data and Candles

Implement a reliable market-data function such as:

```python
fetch_candles()
```

It should obtain sufficient historical candle data to calculate the moving averages.

The number of candles must be configurable.

Example:

```yaml
polling:
  candle_lookback: 100
```

The strategy must have enough candles before generating a signal.

If there is insufficient data:

* Do not trade.
* Log the reason.
* Continue safely.

Use completed candles by default.

If the Dhan API provides timestamps, correctly handle timezone conversion.

---

# 17. Moving Average Calculation

Implement functions such as:

```python
calculate_sma()
calculate_ema()
calculate_moving_average()
```

or an equivalent clean design.

The code should clearly explain:

* What the function does.
* What inputs it expects.
* What it returns.
* Why it is required.
* Where it is used in the strategy.

Avoid unnecessarily complicated technical-analysis frameworks if simple pandas calculations are sufficient.

Keep dependencies lightweight.

---

# 18. Signal Generation

Create a dedicated strategy function, for example:

```python
generate_signal()
```

It should return a clearly defined result such as:

```text
BUY
SELL
HOLD
```

or a structured equivalent.

The function must use crossover logic rather than simply checking whether:

```text
Fast MA > Slow MA
```

because the strategy specifically requires an actual crossover event.

Document this distinction clearly in comments.

---

# 19. Position Management

Implement functions for:

```python
get_positions()
get_open_position()
has_open_position()
get_position_side()
get_position_quantity()
```

or equivalent clean functions.

Before entering any trade:

* Check the current position.
* Prevent duplicate positions.
* Prevent accidental duplicate orders.
* Handle existing opposite positions correctly.
* Verify order state where required.

Never assume an order was filled simply because the order API returned successfully.

---

# 20. Order Execution

Create clean functions such as:

```python
place_entry_order()
place_exit_order()
wait_for_order_completion()
```

The exact function names can differ if there is a better architecture.

The order workflow should be:

```text
Signal
   ↓
Check trading session
   ↓
Check bot state
   ↓
Check existing position
   ↓
Check risk conditions
   ↓
Place order
   ↓
Check order status
   ↓
Confirm position
   ↓
Register entry price
   ↓
Monitor TP/SL
```

Handle:

* API failures
* rejected orders
* partial fills
* timeouts
* network errors
* invalid configuration
* duplicate execution

Do not blindly retry an order in a way that could create duplicate positions.

---

# 21. TP/SL Monitoring

Create a dedicated monitoring mechanism for TP/SL.

For every open position:

1. Obtain the current market price.
2. Calculate TP and SL levels.
3. Compare the current price against those levels.
4. If TP is reached, exit.
5. If SL is reached, exit.
6. Confirm the position is closed.
7. Stop the bot if configured.

Make sure LONG and SHORT calculations are correct.

Avoid relying only on candle close for TP/SL if the configuration intends real-time monitoring.

If Dhan market data supports a suitable live price feed, use it where practical. Otherwise use a lightweight polling approach.

The design must work reliably on a 1 GB RAM Linux VM.

---

# 22. State Management

Keep runtime state in memory where possible.

Track information such as:

```text
bot_running
entry_price
current_position
position_quantity
trade_direction
take_profit_price
stop_loss_price
last_processed_candle
last_signal
shutdown_reason
```

Do not introduce Redis, databases, Docker, Celery, Kafka, or other heavy infrastructure.

The application should remain lightweight.

---

# 23. Duplicate Signal Protection

The bot must not repeatedly execute the same crossover.

For example, if:

```text
BUY crossover
```

has already caused a long entry, subsequent polling cycles must not create additional BUY orders simply because the fast MA remains above the slow MA.

Track the last processed candle/signal appropriately.

Prefer using candle timestamp rather than relying solely on sleep timing.

---

# 24. Error Handling

Implement robust error handling.

Handle at minimum:

```text
Missing .env variables
Invalid config.yaml
Invalid security ID
Invalid quantity
Dhan authentication failure
Network failure
API timeout
API rejection
Order rejection
Partial fill
No candle data
Malformed candle response
No position data
Unexpected API response
KeyboardInterrupt
SIGTERM
```

The bot should fail safely.

When an error occurs:

* Log a useful human-readable message.
* Avoid exposing secrets.
* Do not accidentally place duplicate orders.
* Continue where safe.
* Stop when continuing could be dangerous.

---

# 25. Logging

Use Python's standard `logging` module.

Logs should be useful for debugging and live operation.

Include:

```text
timestamp
log level
message
```

Log important events such as:

```text
Bot startup
Configuration loaded
Authentication successful
Market data fetched
Candle processed
MA values
Signal generated
Existing position detected
Order submitted
Order status
Order rejected
Entry price
TP level
SL level
TP triggered
SL triggered
Position closed
Trading session started
Trading session ended
Shutdown requested
Bot stopped
```

Never log:

```text
DHAN_ACCESS_TOKEN
API secrets
```

Avoid excessive logging on every second if nothing meaningful happened.

---

# 26. Configuration Validation

Before trading starts, validate all configuration values.

Examples:

```text
fast_ma_period > 0
slow_ma_period > 0
fast_ma_period < slow_ma_period
quantity > 0
timeframe valid
trading_mode valid
order type valid
product type valid
TP percentage > 0 when enabled
SL percentage > 0 when enabled
start_time valid
stop_time valid
security_id present
trading_symbol present where required
```

Fail fast with a clear message if configuration is invalid.

---

# 27. Safety Features

Implement multiple safety checks.

The bot must have:

* DRY-RUN mode
* Duplicate-order protection
* Position verification
* Order-status verification
* Graceful shutdown
* TP/SL protection
* Session timing
* Optional close-all-positions
* API error handling
* Configuration validation
* Signal de-duplication

Do not assume that a successful API request always means a successful trade execution.

---

# 28. Startup Safety

At startup:

1. Load `.env`.
2. Load `config.yaml`.
3. Validate configuration.
4. Authenticate with Dhan.
5. Fetch current positions.
6. Display existing positions.
7. Determine whether the bot can safely start.
8. Only then begin strategy execution.

If there is already an open position, handle it according to configuration.

Provide an explicit configuration such as:

```yaml
shutdown:
  manage_existing_positions: true
```

or an equivalent setting.

Do not unexpectedly close an existing manually opened position unless the configuration explicitly allows it.

---

# 29. Trading Session Logic

The main loop should conceptually work like:

```text
START
  ↓
Load configuration
  ↓
Authenticate
  ↓
Validate account/position state
  ↓
Wait for trading start time if enabled
  ↓
Fetch candles
  ↓
Calculate indicators
  ↓
Generate signal
  ↓
Check existing position
  ↓
Execute trade if appropriate
  ↓
Monitor position
  ↓
Monitor TP/SL
  ↓
Check stop time
  ↓
Close positions if configured
  ↓
Stop
```

If session timing is disabled:

```text
START
  ↓
Load configuration
  ↓
Authenticate
  ↓
Fetch candles
  ↓
Calculate indicators
  ↓
Generate signals
  ↓
Manage positions
  ↓
Monitor TP/SL
  ↓
Continue
```

---

# 30. Main Loop Design

Keep the main loop easy to understand.

Avoid deeply nested code.

Prefer:

```python
def main():
    load_configuration()
    validate_configuration()
    initialize_dhan()
    register_signal_handlers()
    run_trading_loop()
    graceful_shutdown()
```

Use helper functions for individual responsibilities.

Every function should have a useful docstring.

---

# 31. Function Documentation

In `main.py`, write clear comments/docstrings for every important function.

For each function explain:

1. Purpose
2. Inputs
3. Outputs
4. Important assumptions
5. How it is used by the trading system
6. Important safety considerations

Example style:

```python
def generate_signal(candles, config):
    """
    Generate a trading signal from the moving-average crossover.

    The function compares the previous completed candle's fast and
    slow moving averages with the latest completed candle's values.

    Returns:
        BUY  - bullish crossover
        SELL - bearish crossover
        HOLD - no new crossover

    Important:
        This function detects a crossover event. It does not simply
        check whether the fast MA is currently above or below the
        slow MA.
    """
```

Use comments to explain important sections of code without making the code unnecessarily verbose.

---

# 32. Educational Code Quality

Write the implementation in a way that makes the logic easy to understand.

Use descriptive variable names.

Prefer:

```python
fast_ma
slow_ma
previous_fast_ma
previous_slow_ma
entry_price
take_profit_price
stop_loss_price
```

instead of unclear names such as:

```python
x
y
p1
p2
```

Keep strategy calculations separated from Dhan API operations as much as possible.

For example:

```text
Market Data
     ↓
Indicator Calculation
     ↓
Signal Generation
     ↓
Risk Checks
     ↓
Order Execution
     ↓
Position Management
```

This separation should be obvious from the code.

---

# 33. Lightweight AWS Deployment

The bot must be suitable for:

```text
AWS Linux VM
1 GB RAM
Python 3.x
```

Avoid:

* Large ML libraries
* Heavy frameworks
* Databases
* Docker requirements
* Redis
* Kafka
* Celery
* unnecessary background services

Use lightweight dependencies.

The bot should also run locally with:

```bash
python3 main.py
```

and the stop command should be straightforward, for example:

```bash
python3 stop.py
```

Document the exact commands in comments at the top of the relevant files.

---

# 34. requirements.txt

Create a minimal `requirements.txt`.

Only include packages actually required by the implementation.

Likely dependencies may include packages for:

```text
Dhan API/SDK
pandas
PyYAML
python-dotenv
```

but inspect the reference implementation and use the correct Dhan dependency/version required by the project.

Do not add unnecessary libraries.

---

# 35. Security

Never hardcode credentials.

Never print credentials.

Never commit secrets into `config.yaml`.

The `.env` file must be used for sensitive credentials.

If a required environment variable is missing, stop with a clear error.

---

# 36. API Rate Limits

Design polling so that it does not unnecessarily overload the Dhan API.

Use:

```yaml
polling:
  interval_seconds: 10
```

or an appropriate configurable value.

Do not fetch historical data more frequently than necessary.

Where practical:

* Reuse candle data.
* Process only new completed candles.
* Avoid duplicate API calls.
* Avoid unnecessary position queries.

---

# 37. Order Idempotency and Safety

Before submitting any entry order:

```text
Check position
Check whether an order for the same signal is already pending
Check whether the candle has already been processed
Check bot state
```

After submitting an order:

```text
Record order ID
Check order status
Confirm execution
Confirm position
```

Do not issue another entry order merely because the confirmation API temporarily failed.

When uncertain about order state, prioritize safety and reconciliation over placing another order.

---

# 38. Reconciliation

Implement a lightweight reconciliation mechanism.

Periodically compare:

```text
Expected bot state
vs
Actual Dhan account state
```

For example:

```text
Bot thinks: LONG
Dhan says: FLAT
```

or:

```text
Bot thinks: FLAT
Dhan says: LONG
```

Handle discrepancies safely and log them.

Do not automatically create a new trade simply because the local state differs from the broker state.

---

# 39. Final File Requirements

### `main.py`

Must contain:

* Configuration loading
* Environment loading
* Configuration validation
* Dhan authentication
* Market-data retrieval
* Candle processing
* SMA/EMA calculation
* Moving-average crossover strategy
* Signal generation
* Position management
* Order placement
* Order-status verification
* TP/SL calculation
* TP/SL monitoring
* Trading-session logic
* Close-all-positions
* Graceful shutdown
* Signal handling
* Logging
* Main trading loop

All implementation should remain in this single file.

### `config.yaml`

Must contain all non-secret configurable settings.

### `.env`

Must contain Dhan credentials/secrets.

### `stop.py`

Must safely request bot shutdown.

### `requirements.txt`

Must contain only required Python dependencies.

---

# 40. Final Testing Checklist

Before finishing the implementation, review the code against these scenarios:

### Startup

* Missing `.env`
* Invalid YAML
* Invalid strategy configuration
* Invalid instrument configuration
* Dhan authentication failure

### Strategy

* Insufficient candles
* No crossover
* Bullish crossover
* Bearish crossover
* Repeated polling after crossover

### Position

* No position
* Existing long
* Existing short
* Opposite crossover
* Multiple positions if applicable

### Orders

* Market order
* Limit order
* Order rejection
* API timeout
* Partial fill
* Unknown order status

### Risk

* TP reached
* SL reached
* TP disabled
* SL disabled
* TP/SL bot shutdown enabled
* TP/SL bot shutdown disabled

### Trading Session

* Before start time
* During session
* After stop time
* Close-all enabled
* Close-all disabled
* Session timing disabled

### Shutdown

* `Ctrl+C`
* SIGTERM
* `python3 stop.py`
* API failure
* Unexpected exception

Ensure every scenario fails safely.

---

# 41. Code Style

Use:

* Python type hints where useful
* PEP 8 style
* Clear function names
* Clear variable names
* Small focused functions
* Useful docstrings
* Defensive programming
* Standard logging
* Minimal dependencies

Do not over-engineer the application.

The code should be understandable by someone who is learning algorithmic trading and Python.

---

# 42. Final Implementation Instruction

Now inspect:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

carefully and use them as implementation references.

Then create/update:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
```

Make sure the final five-file implementation is **self-contained** and does not require either reference file after development.

Do not create additional files.

Do not leave TODO placeholders for core functionality.

Do not provide pseudo-code where actual implementation is required.

Implement the complete working Dhan Moving Average Crossover trading bot.

At the end, review the entire implementation for correctness, safety, readability, maintainability, and clarity. The code, comments, docstrings, and explanations should be written clearly enough that the implementation can later be used as a high-quality technical reference, including its code and explanations, in books and other educational material.
