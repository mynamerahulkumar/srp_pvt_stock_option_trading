You are an expert Python algorithmic-trading engineer specializing in the Dhan trading API, intraday/scalping systems, market-data polling, order management, risk controls, and production-grade trading bots.

Build a complete, locally runnable **Volume Breakout Scalping Algo for Dhan**.

The project must be simple enough to run on a local machine and on a lightweight **AWS Linux VM with approximately 1 GB RAM**, while being structured, readable, reliable, and easy to understand.

## 1. IMPORTANT PROJECT RULES

The final project must contain ONLY these files:

1. `main.py`
2. `config.yaml`
3. `.env`
4. `stop.py`
5. `requirements.txt`
6. `architecture.md`

Do not create additional source files, packages, folders, databases, Docker files, notebooks, dashboards, or unnecessary configuration files.

All application logic must be contained in `main.py`.

`config.yaml` must contain all strategy, risk-management, trading, polling, logging, CLI, and scheduling settings that a user may reasonably want to change.

`.env` must contain secrets such as:

* Dhan Client ID
* Dhan Access Token
* Any other credentials required by the implementation

Never hard-code credentials or access tokens in Python or YAML.

`stop.py` must provide a safe way to stop the running bot.

`architecture.md` must comprehensively explain the complete strategy, architecture, functions, execution flow, risk management, examples, tuning, and operational behavior.

---

# 2. REFERENCE FILES

Before implementing the project, inspect these files if they are available:

* `docs/project_requirements.md`
* `docs/Dhan_SRP.py`

These files are reference material only.

The user may delete them after development.

Therefore:

* Do NOT make the final application dependent on these files.
* Do NOT import them.
* Do NOT require them at runtime.
* Copy/adapt only the useful implementation patterns from them.
* The final six-file project must run independently.

For Dhan API implementation, use the correct/current API conventions available from the provided reference material and verify API usage carefully.

Do not invent Dhan API parameters, endpoints, response fields, order types, security IDs, or authentication behavior.

If the reference implementation contains obsolete or unsafe behavior, improve it rather than blindly copying it.

---

# 3. PRIMARY STRATEGY

Implement a **Volume Breakout Scalping Algorithm**.

The strategy should identify unusually high trading volume combined with a price breakout and enter a trade in the breakout direction.

The core concept should be:

1. Fetch market data.
2. Build/obtain candles at the configured timeframe.
3. Calculate:

   * Current/previous price
   * Previous high/low
   * Volume
   * Average volume
   * Volume ratio
   * Breakout level
4. Detect whether volume is significantly above normal.
5. Detect a valid bullish or bearish breakout.
6. Apply configurable filters.
7. Generate an entry signal.
8. Place the configured Dhan order.
9. Monitor the open position.
10. Exit using configured TP/SL and other configured exit conditions.
11. Once TP or SL is reached, stop the bot if configured.
12. If configured for day trading, close all open positions at the configured end time.

The implementation must avoid repeated entries for the same breakout.

---

# 4. STRATEGY CONFIGURATION

Every important strategy parameter must be configurable through `config.yaml`.

At minimum include configurable parameters for:

### Instrument

* Exchange segment
* Trading symbol
* Security ID
* Product type
* Quantity
* Order type
* Buy/sell enablement
* Long enablement
* Short enablement

### Candle configuration

* Candle timeframe
* Lookback candles
* Breakout lookback period
* Polling interval in seconds

### Volume breakout

* Volume moving-average period
* Minimum volume multiplier
* Minimum volume ratio
* Minimum breakout percentage
* Maximum breakout percentage if desired
* Require candle close confirmation
* Require volume confirmation
* Use previous candle high/low
* Use rolling high/low
* Minimum candle body percentage
* Maximum candle range percentage

### Trend filters

Allow configurable optional filters such as:

* EMA fast period
* EMA slow period
* Enable/disable EMA trend filter
* Long trades only above EMA
* Short trades only below EMA

The strategy should remain a volume-breakout strategy, not become unnecessarily complicated.

### Trade management

Provide configuration for:

* Take-profit
* Stop-loss
* TP mode:

  * percentage
  * points
  * absolute price
* SL mode:

  * percentage
  * points
  * absolute price
* Optional trailing stop
* Trailing-stop activation
* Trailing-stop distance
* Maximum holding time
* Maximum trades per day
* Maximum consecutive losses
* Cooldown between trades
* One-position-at-a-time mode

### Trading hours

Provide:

* `time_window_enabled`
* `start_time`
* `stop_entry_time`
* `force_exit_time`
* `close_all_positions_at_end`
* Timezone

If the time-window feature is enabled, treat the strategy as a day-trading strategy.

If disabled, the bot must not require the user to configure trading hours and should be allowed to operate without mandatory time-based entry restrictions.

However, the configured exit/risk controls must still operate.

Use the appropriate India timezone handling for Indian-market trading.

---

# 5. DAY-TRADING MODE

Implement a clear configuration such as:

```yaml
trading:
  day_trading:
    enabled: true
    start_time: "09:20"
    stop_entry_time: "15:15"
    force_exit_time: "15:20"
    close_all_positions_at_end: true
```

Behavior:

### When enabled

* Do not enter before `start_time`.
* Do not initiate new trades after `stop_entry_time`.
* At `force_exit_time`, close positions if configured.
* If `close_all_positions_at_end` is true, safely close all relevant open positions.
* Then stop the bot.

### When disabled

* Do not impose the day-trading time window.
* Continue operating according to the configured strategy and risk controls.
* Do not force the user to provide trading-hour settings.

The code must handle these two modes cleanly.

---

# 6. ENTRY LOGIC

Implement the volume breakout logic clearly.

A typical long setup should require configurable conditions such as:

```text
Current/confirmed candle price breaks above the previous N-candle high
AND
Current volume > average volume × volume_multiplier
AND
optional trend filter passes
AND
optional candle confirmation passes
AND
risk limits permit a new trade
AND
no existing position is active
```

A typical short setup should require:

```text
Current/confirmed candle price breaks below the previous N-candle low
AND
Current volume > average volume × volume_multiplier
AND
optional trend filter passes
AND
optional candle confirmation passes
AND
risk limits permit a new trade
AND
no existing position is active
```

Avoid look-ahead bias.

Do not use future candle information.

Clearly distinguish:

* completed candles
* currently forming candle
* previous breakout range
* confirmed breakout

The implementation should preferably make entry decisions using completed/confirmed candles unless configuration explicitly enables another behavior.

Prevent the same candle from generating multiple entries.

---

# 7. SIGNAL QUALITY

Implement safeguards against poor-quality breakouts.

Allow configuration for:

* Minimum volume ratio
* Minimum breakout percentage
* Maximum breakout percentage
* Minimum candle-body percentage
* Maximum candle-range percentage
* EMA trend filter
* Cooldown
* Maximum trades per day

Do not add dozens of indicators unnecessarily.

The primary signal must remain:

**Price Breakout + Abnormal Volume**

---

# 8. ORDER EXECUTION

Implement Dhan order execution carefully.

The bot must:

1. Validate configuration.
2. Validate instrument information.
3. Check current positions before entering.
4. Confirm that risk limits permit the trade.
5. Generate the order.
6. Submit the order through Dhan.
7. Capture the order ID.
8. Monitor order status.
9. Determine whether the order was:

   * accepted
   * pending
   * partially filled
   * completely filled
   * rejected
   * cancelled
10. Handle failures safely.
11. Never assume an order was filled merely because an API call returned successfully.

After entry, obtain the actual executed/average price where available.

Use the actual execution price for TP/SL calculations rather than blindly using the intended entry price.

---

# 9. TP/SL

The bot MUST support both Take Profit and Stop Loss.

Example configuration:

```yaml
risk:
  take_profit:
    enabled: true
    mode: "percentage"
    value: 0.40

  stop_loss:
    enabled: true
    mode: "percentage"
    value: 0.20
```

Support reasonable modes such as:

* percentage
* points

Calculate long and short exits correctly.

For a long:

```text
TP = entry + TP distance
SL = entry - SL distance
```

For a short:

```text
TP = entry - TP distance
SL = entry + SL distance
```

Make all calculations explicit and easy to understand.

---

# 10. TP/SL EXIT BEHAVIOR

Continuously monitor the active position.

When TP is reached:

1. Exit the position.
2. Confirm the exit order.
3. Calculate/report realized P&L when available.
4. Record the trade.
5. If configured, STOP THE BOT.

When SL is reached:

1. Exit the position.
2. Confirm the exit order.
3. Calculate/report realized P&L when available.
4. Record the trade.
5. If configured, STOP THE BOT.

Create configuration:

```yaml
risk:
  stop_bot_after_tp: true
  stop_bot_after_sl: true
```

The default behavior should be configurable.

If the user specifically wants the bot to stop after TP/SL, this configuration must make that behavior possible.

---

# 11. POSITION SAFETY

The bot must always know whether it currently has an open position.

Before entering a new trade:

* Fetch/verify positions.
* Do not open another position when `one_position_at_a_time` is enabled.
* Prevent accidental duplicate orders.

On restart:

* Do NOT blindly enter a new trade.
* First inspect existing Dhan positions.
* If a position already exists, recover its state and monitor it.
* Reconstruct TP/SL monitoring when possible.
* If safe recovery is impossible, fail safely and explain the issue in the CLI.

Never create an opposite position accidentally while trying to close an existing position.

---

# 12. CLOSE-ALL-POSITIONS FUNCTIONALITY

Implement a safe function to close all positions belonging to the configured strategy/account context when day-trading shutdown is enabled.

The function must:

1. Fetch current positions.
2. Identify non-zero positions.
3. Determine the correct opposite transaction type.
4. Submit exit orders.
5. Verify order status.
6. Re-check positions.
7. Confirm positions are closed.
8. Retry only when safe and configurable.
9. Never blindly submit repeated market orders.

Provide a configuration option:

```yaml
trading:
  close_all_positions_at_end: true
```

The CLI should clearly display when this process starts and finishes.

---

# 13. STOP.PY

Create `stop.py` as a simple emergency/control utility.

It should allow the user to request a graceful bot shutdown.

Do NOT make `stop.py` directly terminate the Python process in a way that could leave an open position unmanaged.

Use a lightweight local stop mechanism suitable for a 1 GB RAM AWS VM.

For example, use a small stop signal/file mechanism.

The main bot should check the stop signal regularly.

When a stop request is detected:

1. Stop generating new entries.
2. Handle existing position according to configuration.
3. Optionally close open positions if configured.
4. Confirm the position state.
5. Exit gracefully.

Make the behavior configurable.

Clearly document how to run:

```bash
python stop.py
```

and how the main process responds.

---

# 14. POLLING

The bot must poll market data approximately every configurable number of seconds.

Example:

```yaml
system:
  polling_seconds: 5
```

Every polling cycle should:

1. Check stop signal.
2. Check time-window rules.
3. Fetch required market/candle data.
4. Update position state.
5. Evaluate TP/SL if a position exists.
6. Evaluate new entry signals if no position exists.
7. Execute trades when conditions are satisfied.
8. Update CLI.
9. Sleep for the configured interval.

Do not hard-code five seconds.

The YAML value must control polling frequency.

Avoid unnecessary API calls.

Design the loop to be lightweight enough for a 1 GB RAM VM.

---

# 15. MARKET DATA

Use Dhan-supported market-data functionality.

Handle:

* API errors
* network timeouts
* malformed responses
* missing candles
* stale data
* empty data
* rate limiting
* temporary connection problems

Do not crash the entire bot because one polling request fails.

Use controlled retry/backoff behavior.

Do not create an uncontrolled infinite retry loop.

Log useful errors.

---

# 16. CONFIGURATION VALIDATION

At startup validate:

* Required environment variables
* Security ID
* exchange segment
* symbol
* quantity
* TP
* SL
* polling interval
* volume multiplier
* candle interval
* trading times when day trading is enabled
* maximum trades
* risk limits

Reject obviously unsafe values.

Examples:

* quantity <= 0
* negative stop loss
* negative take profit
* polling interval <= 0
* invalid time format
* missing credentials

Fail early with a clear CLI error.

---

# 17. SCI-FI CLI

Create a professional but lightweight **sci-fi trading terminal CLI**.

It should look modern when running locally or on an AWS terminal.

Do not use a heavy dashboard or web server.

The terminal should clearly show:

* Bot name
* Status
* Strategy
* Trading symbol
* Security ID
* Current market price
* Current signal
* Volume
* Average volume
* Volume ratio
* Breakout level
* Current position
* Position quantity
* Entry price
* Current price
* TP
* SL
* Unrealized P&L
* Realized P&L if available
* Trade count
* Winning trades
* Losing trades
* Last trade
* Next polling cycle
* Polling interval
* Trading mode
* Day-trading status
* Current time
* Stop status

Example visual concept:

```text
╔══════════════════════════════════════════════════════════════╗
║              ◈ VOLUME BREAKOUT SCALPER ◈                   ║
║                    DHAN TRADING CORE                       ║
╠══════════════════════════════════════════════════════════════╣
║ STATUS       : ● ONLINE                                     ║
║ MODE         : INTRADAY                                     ║
║ SYMBOL       : NIFTY / CONFIGURED SYMBOL                    ║
║ PRICE        : 24,xxx.xx                                    ║
║ VOLUME RATIO : 2.41x                                        ║
║ BREAKOUT     : CONFIRMED                                    ║
╠══════════════════════════════════════════════════════════════╣
║ POSITION     : LONG                                         ║
║ QTY          : 50                                           ║
║ ENTRY        : 24,100.00                                    ║
║ CURRENT      : 24,145.00                                    ║
║ TP           : 24,196.40                                    ║
║ SL           : 24,051.80                                    ║
║ P&L          : +₹2,250.00                                   ║
╠══════════════════════════════════════════════════════════════╣
║ SIGNAL       : VOLUME BREAKOUT                              ║
║ NEXT POLL    : 5 SEC                                        ║
║ TRADES       : 2 / 5                                        ║
╚══════════════════════════════════════════════════════════════╝
```

The exact design is up to you, but keep it lightweight and reliable.

Do not make the CLI consume excessive CPU or memory.

Refresh/update the terminal approximately every polling cycle.

If a rich CLI library is useful, it may be used, but keep dependencies lightweight and suitable for a 1 GB VM.

---

# 18. CLI TRADE EVENTS

The CLI should clearly announce important events such as:

```text
[22:14:05] MARKET DATA UPDATED
[22:14:05] VOLUME RATIO: 2.37x
[22:14:05] BREAKOUT LEVEL: 24,120
[22:14:05] SIGNAL: LONG BREAKOUT
[22:14:06] RISK CHECK: PASSED
[22:14:06] ORDER SUBMITTED
[22:14:07] ORDER FILLED
[22:14:07] ENTRY: 24,125
[22:14:07] TP: 24,173.50
[22:14:07] SL: 24,100.75
```

When there is no trade:

```text
[22:14:10] SIGNAL: NONE
[22:14:10] REASON: Volume below threshold
```

or:

```text
[22:14:10] SIGNAL: NONE
[22:14:10] REASON: Breakout not confirmed
```

Make the reason for non-entry understandable.

---

# 19. P&L DISPLAY

The CLI must display the current position P&L whenever a position is active.

For a long:

```text
P&L = (current_price - entry_price) × quantity
```

For a short:

```text
P&L = (entry_price - current_price) × quantity
```

If Dhan provides an authoritative position P&L, use it where appropriate.

Clearly distinguish:

* estimated/unrealized P&L
* realized P&L

Do not falsely claim that an estimated P&L is realized.

---

# 20. TRADE JOURNAL

Do not create a database or additional file.

Maintain the current session's trade statistics in memory.

Track:

* Number of trades
* Long trades
* Short trades
* Winning trades
* Losing trades
* Gross profit
* Gross loss
* Net P&L
* Last trade
* Current trade
* Maximum consecutive losses

If the bot restarts, it may reset session statistics unless information can safely be recovered from Dhan.

Do not create extra persistence files unless explicitly requested.

---

# 21. RISK MANAGEMENT

Implement robust risk controls.

At minimum:

* Maximum trades per day
* Maximum consecutive losses
* One position at a time
* Cooldown after trade
* Quantity validation
* TP
* SL
* Optional trailing stop
* Optional maximum holding time
* Optional daily loss limit
* Optional daily profit target
* Stop after TP
* Stop after SL

Example:

```yaml
risk:
  max_trades_per_day: 5
  max_consecutive_losses: 3
  max_daily_loss: 2000
  daily_profit_target: 3000
  one_position_at_a_time: true
  cooldown_seconds: 60
```

If a daily loss limit is reached:

* Do not open additional trades.
* Optionally close the active position according to configuration.
* Stop the bot if configured.

Never imply that these controls guarantee profitability.

---

# 22. PROFITABILITY

Do NOT make claims that the strategy will always make profit.

The implementation should be designed to maximize disciplined execution and provide configurable parameters for optimization.

The documentation should explain that profitability depends on:

* market regime
* slippage
* brokerage
* taxes
* liquidity
* execution latency
* volatility
* parameter selection
* overfitting
* transaction costs

Do not use language such as:

* guaranteed profit
* sure-shot strategy
* risk-free
* guaranteed win rate

Instead, explain how a trader can systematically improve the strategy through testing and tuning.

---

# 23. PARAMETER TUNING

The system must make parameter tuning easy.

Clearly expose parameters such as:

* Volume moving-average period
* Volume multiplier
* Breakout lookback
* Candle timeframe
* EMA periods
* Minimum breakout percentage
* Minimum candle body
* Maximum candle range
* TP
* SL
* Trailing stop
* Cooldown
* Maximum trades
* Trading window
* Polling interval

The architecture documentation must explain the trade-offs.

For example:

### Increasing volume multiplier

Potential effect:

* fewer trades
* stronger volume confirmation
* potentially fewer false breakouts
* possibility of missing early breakouts

### Increasing breakout lookback

Potential effect:

* stronger breakout levels
* fewer signals
* potentially higher-quality setups
* slower signal generation

### Increasing stop loss

Potential effect:

* more room for normal price movement
* larger loss per trade
* potentially lower premature exits

### Increasing take profit

Potential effect:

* larger reward per winning trade
* potentially lower win rate
* more trades may reverse before reaching TP

Do not present any parameter as universally optimal.

---

# 24. NO LOOK-AHEAD BIAS

This is critical.

The strategy must never use future information.

When calculating:

* moving averages
* volume average
* breakout levels
* trend filters

make sure the current decision does not accidentally use future candle data.

Clearly define which candle is being evaluated.

Use only information available at the time of the decision.

---

# 25. DUPLICATE ORDER PROTECTION

Implement multiple layers of protection against duplicate orders.

For example:

1. Check internal position state.
2. Fetch Dhan position state.
3. Check whether an order is already pending.
4. Check last signal candle.
5. Apply cooldown.
6. Apply maximum-trades limit.

Never send multiple entry orders merely because the same breakout condition remains true across polling cycles.

---

# 26. ERROR HANDLING

Handle exceptions gracefully.

At minimum handle:

* authentication errors
* network errors
* timeout
* API errors
* invalid response
* order rejection
* order cancellation
* partial fills
* missing market data
* invalid configuration
* keyboard interrupt
* stop signal
* unexpected runtime exceptions

The bot must not silently fail.

For unexpected exceptions:

* log the error
* show it in the CLI/log
* protect the current position
* avoid opening new trades until the state is known
* attempt safe recovery where possible

---

# 27. LOGGING

Use Python's standard logging framework unless a lightweight alternative is genuinely necessary.

Support configuration such as:

```yaml
logging:
  level: "INFO"
```

Log:

* startup
* configuration validation
* API connection
* market-data fetch
* signal generation
* risk checks
* order submission
* order response
* order fill
* position updates
* TP
* SL
* exit
* daily shutdown
* stop request
* errors

Do not log secrets.

Never print:

* access tokens
* passwords
* API secrets

---

# 28. MAIN.PY FUNCTION STRUCTURE

Keep functions logically separated even though everything must be inside `main.py`.

Use clear functions/classes as appropriate.

At minimum, create well-documented functions for concepts such as:

```text
load_config()
load_environment()
validate_config()
initialize_dhan_client()
load_market_data()
build_candles()
calculate_volume_metrics()
calculate_breakout_levels()
calculate_trend_filter()
generate_signal()
check_risk_limits()
get_current_position()
calculate_trade_levels()
place_entry_order()
monitor_order()
place_exit_order()
check_take_profit()
check_stop_loss()
check_trailing_stop()
close_all_positions()
process_stop_signal()
update_trade_statistics()
render_cli()
run_strategy_cycle()
run_bot()
main()
```

You may change the exact function names if necessary, but maintain a similarly clean separation of responsibilities.

---

# 29. COMMENTS AND FUNCTION DOCUMENTATION

Every important function in `main.py` must contain useful comments and/or docstrings explaining:

1. What the function does.
2. Why it exists.
3. What inputs it expects.
4. What it returns.
5. Important trading considerations.
6. Any Dhan API considerations.
7. Important failure/safety behavior.

Example style:

```python
def calculate_volume_ratio(current_volume, average_volume):
    """
    Calculate how unusual the current trading volume is.

    Use case:
    The strategy uses this value to determine whether a breakout
    is supported by unusually high market participation.

    A value of 2.0 means current volume is approximately twice
    the configured average volume.
    """
```

Comments should explain the trading concept as well as the programming concept.

Avoid meaningless comments such as:

```python
# add two numbers
```

Prefer educational comments such as:

```python
# We compare the current confirmed candle's volume against the
# rolling average of previous candles. This helps identify
# breakouts occurring with abnormal market participation.
```

---

# 30. CODE QUALITY

Use:

* Python 3.10+ compatible syntax where practical
* type hints where useful
* small functions
* clear names
* constants/configuration rather than magic numbers
* defensive error handling
* clean separation of strategy and execution logic
* minimal memory usage

Avoid:

* unnecessary abstractions
* over-engineering
* microservices
* databases
* background servers
* complex multiprocessing
* unnecessary threads
* large frameworks

The bot should remain understandable.

---

# 31. CONFIG.YAML

Create a complete example configuration.

It should include sections similar to:

```yaml
strategy:
  name: "Volume Breakout Scalper"
  enabled: true

instrument:
  exchange_segment: ""
  trading_symbol: ""
  security_id: ""
  product_type: ""
  quantity: 1

candles:
  interval: ""
  lookback: 50

volume_breakout:
  volume_ma_period: 20
  volume_multiplier: 2.0
  breakout_lookback: 20
  min_breakout_percent: 0.05
  max_breakout_percent: 1.0
  require_volume_confirmation: true
  require_candle_confirmation: true

trend_filter:
  enabled: true
  ema_fast: 9
  ema_slow: 21

risk:
  take_profit:
    enabled: true
    mode: "percentage"
    value: 0.40

  stop_loss:
    enabled: true
    mode: "percentage"
    value: 0.20

  trailing_stop:
    enabled: false
    activation_percent: 0.20
    distance_percent: 0.10

  max_trades_per_day: 5
  max_consecutive_losses: 3
  max_daily_loss: 2000
  daily_profit_target: 3000
  one_position_at_a_time: true
  cooldown_seconds: 60

trading:
  long_enabled: true
  short_enabled: true
  order_type: "MARKET"

  day_trading:
    enabled: true
    start_time: "09:20"
    stop_entry_time: "15:15"
    force_exit_time: "15:20"
    close_all_positions_at_end: true

  stop_bot_after_tp: true
  stop_bot_after_sl: true

system:
  polling_seconds: 5
  timezone: "Asia/Kolkata"
  dry_run: true

logging:
  level: "INFO"
```

Adapt field names to the actual implementation.

The example must be internally consistent and runnable after the user fills in their Dhan credentials/instrument configuration.

---

# 32. DRY-RUN MODE

Implement:

```yaml
system:
  dry_run: true
```

When enabled:

* Do not send real orders.
* Generate signals.
* Show intended orders.
* Calculate intended TP/SL.
* Display what would happen.
* Clearly label the CLI as `DRY RUN`.

When disabled:

* Submit actual Dhan orders.

Default `dry_run` should preferably be `true` to reduce accidental live trading.

---

# 33. LIVE-TRADING SAFETY

When `dry_run: false`, display a clear warning during startup:

```text
⚠ LIVE TRADING ENABLED
Real orders may be submitted to Dhan.
```

Require configuration validation before proceeding.

Do not add an artificial confirmation prompt that makes AWS unattended operation impossible unless it is configurable.

Provide:

```yaml
trading:
  live_trading_confirmation: false
```

If implemented, make it configurable.

---

# 34. AWS 1 GB RAM REQUIREMENTS

The application must run efficiently on a small Linux VM.

Avoid:

* large dataframes retained indefinitely
* unnecessary historical-data caching
* memory leaks
* high-frequency busy loops
* web dashboards
* large logging buffers

Use bounded data structures where possible.

The bot should sleep between polling cycles.

It should recover from temporary network failures.

It should shut down cleanly on:

* SIGINT
* SIGTERM
* stop signal

---

# 35. REQUIREMENTS.TXT

Only include dependencies that are actually needed.

Use a minimal dependency list.

Do not include unnecessary packages.

The project should support:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Also document the installation/run process in `architecture.md`.

---

# 36. ENV FILE

Create an example `.env` structure such as:

```env
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Do not put real credentials in the file.

Do not hard-code credentials anywhere.

If additional environment variables are actually required, add them only when necessary.

---

# 37. ARCHITECTURE.MD

Create a detailed `architecture.md`.

Write it as a polished technical chapter explaining the complete Volume Breakout Scalping Algo.

It should include:

## 37.1 Strategy Overview

Explain:

* What volume breakout means
* Why volume matters
* Why breakouts can occur
* How abnormal volume confirms market participation
* Long setup
* Short setup
* When no trade is taken

## 37.2 Strategy Formula

Explain formulas such as:

```text
Average Volume = mean(previous N completed candle volumes)

Volume Ratio = Current Volume / Average Volume

Long Breakout:
Price > Previous N-Candle High
AND
Volume Ratio >= Minimum Volume Multiplier

Short Breakout:
Price < Previous N-Candle Low
AND
Volume Ratio >= Minimum Volume Multiplier
```

Adapt formulas to the exact code.

## 37.3 Architecture

Explain:

```text
Configuration
     ↓
Environment
     ↓
Dhan Connection
     ↓
Market Data
     ↓
Candle Processing
     ↓
Volume Analysis
     ↓
Breakout Detection
     ↓
Trend Filter
     ↓
Risk Management
     ↓
Signal
     ↓
Order Execution
     ↓
Position Monitoring
     ↓
TP / SL / Exit
     ↓
Trade Statistics
     ↓
CLI
```

## 37.4 Function-by-Function Explanation

Explain every important function in `main.py`.

For each function explain:

* purpose
* input
* output
* trading use case
* how it interacts with other functions
* important edge cases

## 37.5 Complete Trade Example

Provide a realistic hypothetical example.

For example:

```text
Previous breakout high: ₹1,000
Current price: ₹1,003
Average volume: 100,000
Current volume: 250,000
Volume ratio: 2.5x
```

Explain how the signal is generated.

Then show:

```text
Entry = ₹1,003
Quantity = 100
TP = ₹1,007.01
SL = ₹1,000.99
```

Use formulas based on the actual configuration.

Then explain:

```text
Entry value
Exit value
Gross P&L
Approximate transaction-cost considerations
Net P&L concept
```

Make it clear that the numbers are hypothetical.

Include both:

* profitable trade example
* losing trade example

## 37.6 Trade Lifecycle

Explain:

```text
Signal
→ Risk Check
→ Order
→ Fill
→ Position
→ TP/SL Monitoring
→ Exit
→ P&L
→ Bot Stop / Continue
```

## 37.7 What Happens Every 5 Seconds

Explain the polling loop step-by-step.

For example:

```text
T+0 sec
Check stop signal

T+0 sec
Check current position

T+0 sec
Fetch market data

T+0 sec
Calculate volume ratio

T+0 sec
Check breakout

T+0 sec
Check risk limits

T+0 sec
Trade if valid

T+5 sec
Repeat
```

Explain that the actual polling interval is configurable.

## 37.8 TP/SL

Explain:

* percentage TP
* percentage SL
* points-based TP/SL
* long calculation
* short calculation
* why actual fill price matters
* slippage
* gap risk
* execution risk

## 37.9 Day-Trading Mode

Explain exactly what happens when enabled and disabled.

## 37.10 Stop Bot

Explain:

* `stop.py`
* graceful stop
* active-position handling
* close-all behavior
* shutdown safety

## 37.11 Risk Management

Explain every risk parameter.

## 37.12 Parameter Tuning

Create a useful table:

| Parameter | Lower Value | Higher Value | Typical Trade-off |
| --------- | ----------- | ------------ | ----------------- |

Include:

* volume multiplier
* breakout lookback
* candle timeframe
* EMA periods
* TP
* SL
* trailing stop
* cooldown
* maximum trades
* polling interval

Explain that optimization must be based on out-of-sample testing and should avoid overfitting.

## 37.13 Improving the Strategy

Give practical suggestions for systematic improvement, such as:

* test multiple liquid instruments
* compare different candle timeframes
* tune volume threshold
* filter low-liquidity periods
* add trend confirmation
* evaluate breakout distance
* evaluate TP/SL combinations
* test slippage
* include brokerage/taxes in analysis
* analyze performance by time of day
* analyze long vs short performance
* use walk-forward testing
* use out-of-sample validation

Do not promise profitability.

## 37.14 Common Failure Modes

Explain:

* false breakout
* low-volume breakout
* sudden reversal
* slippage
* API failure
* order rejection
* partial fill
* stale market data
* duplicate order
* restart with existing position
* network failure
* incorrect instrument configuration
* incorrect trading hours

Explain how the implementation handles each one.

## 37.15 Operational Guide

Explain exactly:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Explain how to stop:

```bash
python stop.py
```

Explain how to configure dry run and live mode.

## 37.16 AWS Deployment

Explain a lightweight AWS Linux deployment approach.

Keep it simple.

Explain:

* Python installation
* virtual environment
* environment variables
* config
* starting the bot
* stopping the bot
* keeping the process alive
* log inspection

Do not add Docker unless explicitly requested.

---

# 38. EDUCATIONAL CODE STYLE

Although the project must be production-oriented, write the code so that a technically capable reader can understand it sequentially.

The implementation should naturally follow:

```text
Configuration
→ Data
→ Indicators
→ Signal
→ Risk
→ Order
→ Position
→ Exit
→ Monitoring
```

Avoid putting the entire application into one giant function.

Avoid overly compressed one-liners.

Prefer explicit calculations.

For example, prefer:

```python
average_volume = calculate_average_volume(volumes)

volume_ratio = calculate_volume_ratio(
    current_volume=current_volume,
    average_volume=average_volume,
)
```

over hiding the entire strategy in a single expression.

---

# 39. SECURITY

Never expose:

* Dhan access token
* API credentials
* environment secrets

in:

* logs
* CLI
* exceptions
* architecture.md
* comments
* configuration examples

Use placeholders in `.env`.

---

# 40. FINAL VALIDATION

Before considering the implementation complete, verify:

### Files

Only these files exist:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

### Functional validation

Verify:

* YAML loads correctly.
* Environment variables load correctly.
* Configuration validation works.
* Dhan client initialization is correct.
* Market-data retrieval is handled correctly.
* Volume calculation works.
* Breakout calculation works.
* Long signal works.
* Short signal works.
* Risk checks work.
* Duplicate-entry protection works.
* TP calculation works.
* SL calculation works.
* TP exit works.
* SL exit works.
* Bot-stop-after-TP works.
* Bot-stop-after-SL works.
* Day-trading mode works.
* Day-trading-disabled mode works.
* Close-all-positions works safely.
* Stop signal works.
* Dry-run mode does not submit real orders.
* Live mode uses Dhan correctly.
* CLI updates every configured polling cycle.
* Current position P&L is displayed.
* Errors do not silently kill the bot.
* SIGINT/SIGTERM are handled gracefully.

---

# 41. IMPORTANT Dhan IMPLEMENTATION RULE

Do not invent Dhan API behavior.

Inspect the supplied Dhan reference implementation and use the appropriate Dhan SDK/API conventions.

Where the reference files conflict with current API behavior, use the correct implementation based on the available official/current Dhan API documentation or SDK conventions.

Make all Dhan-specific code easy to identify in `main.py`.

Do not scatter Dhan API calls throughout unrelated strategy functions when a clean helper function can be used.

The strategy logic should remain conceptually separate from broker execution logic even though everything lives inside `main.py`.

---

# 42. FINAL OUTPUT REQUIREMENT

Generate the complete contents of all six files:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

Do not generate any other files.

Do not leave TODO placeholders for core functionality.

Do not provide pseudo-code where real implementation is required.

Do not omit important error handling.

Do not create unnecessary complexity.

The final code must be directly usable after configuring the Dhan credentials and instrument details.

At the end, ensure the code and its accompanying explanations are written clearly enough that the implementation, function-by-function explanation, strategy logic, trade examples, risk-management explanation, and parameter-tuning guidance can be understood and reused as high-quality technical educational material, while still remaining a practical working trading system.
