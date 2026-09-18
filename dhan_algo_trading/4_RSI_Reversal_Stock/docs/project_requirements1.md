You are an expert Python algorithmic-trading engineer specializing in the Dhan API and production-grade algorithmic trading systems.

Build a complete, robust, lightweight, configuration-driven **RSI Reversal Algo for Dhan**.

The implementation must be designed to run reliably:

* Locally
* On an AWS Linux VM with approximately 1 GB RAM
* With Python 3.10+
* Without unnecessary databases, servers, containers, multiprocessing, or heavy infrastructure

The system must prioritize:

* Trading safety
* Correct Dhan API integration
* Duplicate-order prevention
* Reliable order-state reconciliation
* Position monitoring
* TP/SL management
* Graceful shutdown
* Restart recovery
* Configurability
* Clear CLI visibility
* Clean, readable code
* Detailed technical documentation

---

# 1. PROJECT FILES

Create exactly these files:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

`main.py` must contain all application and trading logic.

`config.yaml` must contain all user-configurable settings.

`.env` must contain secrets.

`stop.py` must provide a graceful stop mechanism.

`requirements.txt` must contain only required Python dependencies.

`architecture.md` must contain the complete strategy and architecture explanation.

The following files may temporarily exist and may be used as reference material:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

Read them if available.

Use them to understand existing:

* Dhan authentication
* Dhan client initialization
* Market-data retrieval
* Instrument handling
* Security IDs
* Order placement
* Order status
* Position retrieval
* Order cancellation
* Position exit
* Existing project conventions

However, these files will later be deleted.

**The final application must not depend on them at runtime.**

After they are deleted, the complete application must still work using only:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

---

# 2. RSI REVERSAL STRATEGY

Implement a clean and understandable **RSI Reversal Strategy**.

The strategy should identify potentially oversold and overbought conditions and trade the subsequent reversal after confirmation.

RSI should remain the primary indicator.

Do not add unnecessary indicators.

The core strategy flow:

```text
MARKET DATA
     ↓
COMPLETED CANDLE
     ↓
RSI CALCULATION
     ↓
OVERSOLD / OVERBOUGHT
     ↓
REVERSAL CONFIRMATION
     ↓
CANDLE CONFIRMATION
     ↓
LONG / SHORT SIGNAL
     ↓
RISK VALIDATION
     ↓
ORDER EXECUTION
     ↓
ORDER VERIFICATION
     ↓
POSITION MONITORING
     ↓
TP / SL / SESSION EXIT
     ↓
POSITION CLOSED
     ↓
BOT STOPS
```

---

# 3. RSI CALCULATION

Implement RSI using **Wilder's RSI methodology**.

Make all RSI parameters configurable.

Example:

```yaml
strategy:
  name: "RSI Reversal"

  timeframe: "5"

  rsi_period: 14

  oversold: 30
  overbought: 70

  use_reversal_confirmation: true
  use_candle_confirmation: true
```

Do not hard-code strategy parameters in `main.py`.

Explain in comments:

* What RSI measures
* RSI period
* RSI calculation
* Oversold condition
* Overbought condition
* Reversal confirmation
* Why confirmation is required
* Why an oversold/overbought reading alone does not guarantee a reversal

---

# 4. LONG ENTRY LOGIC

Default LONG logic:

```text
Previous RSI <= Oversold
        AND
Current RSI > Oversold
        AND
optional bullish candle confirmation
        ↓
LONG SIGNAL
```

Example:

```text
RSI previously = 28
RSI currently  = 32
Oversold       = 30

RSI crossed back above 30
        ↓
Reversal confirmed
        ↓
LONG
```

The implementation should make the confirmation configurable.

The signal-generation function must not place orders.

---

# 5. SHORT ENTRY LOGIC

Default SHORT logic:

```text
Previous RSI >= Overbought
        AND
Current RSI < Overbought
        AND
optional bearish candle confirmation
        ↓
SHORT SIGNAL
```

Example:

```text
RSI previously = 72
RSI currently  = 68
Overbought     = 70

RSI crossed back below 70
        ↓
Reversal confirmed
        ↓
SHORT
```

---

# 6. CLOSED CANDLE STRATEGY

The strategy must use completed candles by default.

Do not generate multiple signals from the same unfinished candle.

Every polling cycle should:

1. Fetch required market data.
2. Identify the latest completed candle.
3. Get its timestamp.
4. Check whether this candle has already been processed.
5. If already processed, do not generate another entry signal.
6. If new, calculate RSI.
7. Evaluate reversal conditions.
8. Evaluate candle confirmation.
9. Generate a signal.

Maintain:

```text
last_processed_candle
```

to prevent duplicate signals.

---

# 7. POLLING

The bot must continuously poll market data.

Default:

```yaml
runtime:
  polling_interval_seconds: 5
```

Every configured polling interval, the bot should:

```text
FETCH DATA
    ↓
SYNC POSITION
    ↓
UPDATE CURRENT P&L
    ↓
CHECK TP/SL
    ↓
CHECK STOP REQUEST
    ↓
CHECK SESSION
    ↓
IF POSITION OPEN
    → MONITOR ONLY

IF FLAT
    ↓
CHECK RISK
    ↓
CHECK NEW CLOSED CANDLE
    ↓
CALCULATE RSI
    ↓
GENERATE SIGNAL
    ↓
VALIDATE TRADE
    ↓
EXECUTE IF ALLOWED
```

The polling interval must be configurable.

Do not hard-code five seconds.

Do not call Dhan APIs unnecessarily.

---

# 8. SCI-FI CLI

Create a professional **sci-fi/futuristic trading terminal dashboard**.

Use a lightweight library such as `rich` if appropriate.

Do not continuously print unlimited lines.

Prefer refreshing the same dashboard.

The CLI should look like a futuristic algorithmic trading command center.

Example:

```text
╔══════════════════════════════════════════════════════════════════╗
║              ⚡ RSI REVERSAL // TRADING CORE ⚡                 ║
╠══════════════════════════════════════════════════════════════════╣
║ SYSTEM                                                         ║
║ STATUS       : ● ONLINE                                        ║
║ MODE         : PAPER                                           ║
║ ENGINE       : ARMED                                           ║
║ API          : CONNECTED                                       ║
║ RUNTIME      : 00:42:17                                        ║
║                                                                  ║
║ MARKET                                                          ║
║ SYMBOL       : RELIANCE                                        ║
║ TIMEFRAME    : 5 MIN                                           ║
║ LTP          : ₹1,262.80                                       ║
║ RSI          : 32.41                                           ║
║ PREV RSI     : 28.74                                           ║
║ OVERSOLD     : 30                                               ║
║ OVERBOUGHT   : 70                                               ║
║                                                                  ║
║ STRATEGY                                                        ║
║ SIGNAL       : LONG                                            ║
║ CONFIRMATION : ✓ CONFIRMED                                     ║
║ NEXT ACTION  : EXECUTE / WAITING                               ║
║                                                                  ║
║ POSITION                                                         ║
║ SIDE         : LONG                                            ║
║ QUANTITY     : 1                                               ║
║ ENTRY        : ₹1,250.50                                       ║
║ LTP          : ₹1,262.80                                       ║
║ TP           : ₹1,263.00                                       ║
║ SL           : ₹1,244.25                                       ║
║ P&L          : +₹12.30                                         ║
║ P&L %        : +0.98%                                          ║
║                                                                  ║
║ ENGINE                                                         ║
║ STATE        : MONITORING                                      ║
║ LAST TRADE   : 10:35:12                                        ║
║ NEXT POLL    : 5 SEC                                           ║
║                                                                  ║
║ EVENT STREAM                                                    ║
║ 10:35:12  POSITION  LONG 1 @ ₹1250.50                         ║
║ 10:35:07  SIGNAL    RSI REVERSAL LONG                         ║
║ 10:35:02  RSI       32.41                                      ║
╚══════════════════════════════════════════════════════════════════╝
```

Improve the design where appropriate.

---

# 9. CLI INFORMATION

The CLI must display:

## System

* Status
* PAPER/LIVE
* API status
* Strategy status
* Runtime
* Current state

## Market

* Symbol
* Security ID
* Timeframe
* LTP
* Current RSI
* Previous RSI
* Oversold
* Overbought
* Latest candle timestamp

## Strategy

* Current signal
* Confirmation status
* Current strategy condition
* Next action

## Position

* LONG/SHORT/FLAT
* Quantity
* Entry price
* Current price
* P&L
* P&L percentage
* TP
* SL
* Position age

## Trading

* Last trade time
* Last trade price
* Last order status
* Last exit reason
* Number of trades today
* Maximum allowed trades

## Runtime

* Polling interval
* Last market-data update
* Last position synchronization
* Next poll
* Stop-request status

---

# 10. "WHEN WILL IT TRADE?"

The CLI must clearly communicate what the strategy is waiting for.

Examples:

```text
NEXT ACTION: WAITING FOR RSI TO ENTER OVERSOLD
```

```text
NEXT ACTION: RSI OVERSOLD — WAITING FOR REVERSAL
```

```text
NEXT ACTION: RSI REVERSAL DETECTED — WAITING FOR CANDLE CONFIRMATION
```

```text
NEXT ACTION: LONG SIGNAL — RISK CHECK PENDING
```

```text
NEXT ACTION: POSITION OPEN — MONITORING TP/SL
```

```text
NEXT ACTION: SESSION NOT STARTED
```

```text
NEXT ACTION: MAX TRADES REACHED
```

```text
NEXT ACTION: POSITION FLAT — SCANNING
```

This is mandatory.

The user should be able to understand **why the algorithm is not trading** by looking at the dashboard.

---

# 11. "WHY NO TRADE?" REASON

Maintain a clear reason such as:

```text
WAITING_FOR_MARKET_DATA
WAITING_FOR_NEW_CLOSED_CANDLE
RSI_NOT_OVERSOLD
RSI_NOT_OVERBOUGHT
WAITING_FOR_RSI_REVERSAL
WAITING_FOR_CANDLE_CONFIRMATION
LONG_DISABLED
SHORT_DISABLED
POSITION_ALREADY_OPEN
MAX_TRADES_REACHED
SESSION_NOT_STARTED
SESSION_ENDED
RISK_LIMIT_REACHED
PENDING_ORDER_EXISTS
STOP_REQUESTED
API_UNAVAILABLE
CONFIGURATION_ERROR
```

Display a human-readable version in the CLI.

---

# 12. CURRENT POSITION P&L

Continuously show current position P&L.

For FLAT:

```text
POSITION: FLAT
P&L: ₹0.00
```

For LONG:

```text
POSITION: LONG
ENTRY: ₹1250.50
LTP: ₹1262.80
QTY: 1
P&L: +₹12.30
```

For SHORT:

```text
POSITION: SHORT
ENTRY: ₹1250.50
LTP: ₹1238.20
QTY: 1
P&L: +₹12.30
```

Use actual Dhan position information whenever possible.

Calculate direction-aware P&L correctly.

Do not display misleading P&L based only on stale local data.

---

# 13. CONFIGURATION

Everything reasonably configurable must be in `config.yaml`.

Create a comprehensive configuration:

```yaml
environment:
  mode: "PAPER"

api:
  dhan_client_id_env: "DHAN_CLIENT_ID"
  dhan_access_token_env: "DHAN_ACCESS_TOKEN"

strategy:
  name: "RSI Reversal"
  timeframe: "5"

  rsi_period: 14
  oversold: 30
  overbought: 70

  use_reversal_confirmation: true
  use_candle_confirmation: true

trading:
  exchange_segment: "NSE_EQ"
  security_id: ""
  trading_symbol: ""

  product_type: "INTRADAY"
  order_type: "MARKET"

  quantity: 1

  allow_long: true
  allow_short: true

  max_open_positions: 1
  one_trade_at_a_time: true

runtime:
  polling_interval_seconds: 5
  log_level: "INFO"

session:
  enabled: true

  start_time: "09:20"
  stop_time: "15:15"

  timezone: "Asia/Kolkata"

  close_all_positions_at_stop_time: true

risk_management:
  enabled: true

  take_profit:
    enabled: true
    type: "PERCENT"
    value: 1.0

  stop_loss:
    enabled: true
    type: "PERCENT"
    value: 0.5

  max_trades_per_day: 1
  max_daily_loss: 0
  max_daily_profit: 0

shutdown:
  close_positions_on_manual_stop: false
  close_positions_on_session_end: true
  close_positions_on_tp_sl: true
  cancel_pending_orders: true

recovery:
  enabled: true
  manage_existing_position: true
  prevent_duplicate_entry: true

safety:
  manage_only_configured_symbol: true
  require_flat_before_entry: true
  block_if_unexpected_position: true

cli:
  enabled: true
  refresh_seconds: 1
  event_history_size: 8
```

Add useful comments to every important setting.

---

# 14. DAY-TRADING MODE

The `session.enabled` setting determines whether mandatory trading hours are enforced.

If:

```yaml
session:
  enabled: true
```

then treat the strategy as day trading.

Flow:

```text
BEFORE START TIME
       ↓
WAIT

START TIME
       ↓
ALLOW NEW TRADES

STOP TIME
       ↓
STOP NEW ENTRIES
       ↓
CLOSE POSITIONS IF CONFIGURED
       ↓
VERIFY CLOSED
       ↓
STOP BOT
```

If:

```yaml
session:
  enabled: false
```

then there is no mandatory start or stop time.

The bot may continue operating without session restrictions.

TP, SL, risk limits, manual stop, and safety shutdowns remain active.

---

# 15. SESSION TIMEZONE

Default:

```text
Asia/Kolkata
```

Use timezone-aware datetime.

Do not depend on the AWS machine timezone.

Use the configured timezone consistently for:

* Session start
* Session stop
* Daily trade count
* Daily risk limits
* Trading date calculations

---

# 16. TAKE PROFIT AND STOP LOSS

Implement configurable TP and SL.

Support at least:

```text
PERCENT
POINTS
```

For LONG:

```text
TP = Entry + TP distance
SL = Entry - SL distance
```

For SHORT:

```text
TP = Entry - TP distance
SL = Entry + SL distance
```

Use actual executed/fill price wherever possible.

---

# 17. TP/SL TERMINAL EVENT

When TP or SL is reached:

```text
POSITION REACHES TP/SL
        ↓
EXIT POSITION
        ↓
VERIFY POSITION CLOSED
        ↓
CANCEL RELATED PENDING ORDERS
        ↓
LOG EXIT REASON
        ↓
STOP BOT
```

The bot must not look for another trade.

TP/SL is a terminal event for the current bot execution.

---

# 18. TP/SL MONITORING

Because polling is configurable, check TP/SL on every position-monitoring cycle.

At every poll:

```text
GET POSITION
GET CURRENT PRICE
CALCULATE P&L
CHECK TP
CHECK SL
```

If a level has been reached:

```text
EXIT
→ VERIFY
→ STOP
```

Clearly document that software-polled TP/SL can be affected by:

* Polling interval
* API latency
* Network latency
* Slippage
* Market gaps
* Fast price movement

Never claim that the exact configured TP/SL price is guaranteed.

---

# 19. POSITION MONITORING

Create a dedicated function:

```python
monitor_position(...)
```

It should determine:

* Side
* Quantity
* Entry price
* Current price
* P&L
* P&L percentage
* TP
* SL
* Position age
* TP/SL state

It must be documented thoroughly.

---

# 20. ORDER EXECUTION

Use a clear lifecycle:

```text
SIGNAL
 ↓
RISK CHECK
 ↓
POSITION CHECK
 ↓
PENDING ORDER CHECK
 ↓
ORDER SUBMISSION
 ↓
ORDER STATUS
 ↓
FILL VERIFICATION
 ↓
POSITION VERIFICATION
```

Never assume:

```text
API accepted request = order filled
```

Verify the actual Dhan order state.

---

# 21. ORDER STATES

Handle:

```text
NOT_SUBMITTED
SUBMITTED
PENDING
PARTIALLY_FILLED
FILLED
REJECTED
CANCELLED
UNKNOWN
```

Implement safe behavior for each state.

---

# 22. DUPLICATE ORDER PROTECTION

Prevent duplicate orders caused by:

* Polling
* Same candle
* API delays
* Network timeout
* Process restart
* Partial fills
* Unknown order state

If an entry request has an ambiguous result:

```text
DO NOT RESUBMIT
        ↓
QUERY ORDER STATUS
        ↓
QUERY POSITION
        ↓
RECONCILE
```

Only submit another order after confirming it is safe.

---

# 23. PARTIAL FILLS

Handle partial fills correctly.

If an order is partially filled:

* Query filled quantity.
* Query actual position.
* Do not blindly submit another order.
* Continue monitoring.
* Reconcile the actual position.
* Calculate TP/SL based on the actual position/fill where appropriate.

---

# 24. EXISTING POSITION RECOVERY

At startup:

```text
CONNECT TO DHAN
      ↓
QUERY POSITIONS
      ↓
QUERY ORDERS
      ↓
CHECK CONFIGURED INSTRUMENT
      ↓
DETECT EXISTING POSITION
```

If a position exists:

* Recover direction.
* Recover quantity.
* Recover entry price.
* Recover/recalculate TP/SL.
* Resume monitoring.
* Prevent duplicate entry.

Never place a new entry simply because the process restarted.

---

# 25. POSITION SAFETY

Before entering:

1. Query current position.
2. Check security ID.
3. Check symbol.
4. Check quantity.
5. Check pending orders.
6. Check max open positions.
7. Check trade count.
8. Check session.
9. Check risk limits.
10. Check strategy signal.
11. Check duplicate-entry protection.

If an unexpected position exists and:

```yaml
block_if_unexpected_position: true
```

do not open another position.

Move to a safe state and explain the reason in the CLI.

---

# 26. CLOSE ALL POSITIONS

Create:

```python
close_all_positions(...)
```

The function must:

* Retrieve actual positions.
* Identify positions that the bot is allowed to manage.
* Determine correct exit transaction.
* Submit exit orders.
* Verify order execution.
* Verify position quantity reaches zero.
* Cancel pending orders if configured.

Do not blindly close unrelated positions.

Respect:

```yaml
safety:
  manage_only_configured_symbol: true
```

---

# 27. RISK MANAGEMENT

Implement:

```yaml
risk_management:
  max_trades_per_day: 1
  max_daily_loss: 0
  max_daily_profit: 0
```

At minimum support:

* Maximum trades per day
* Maximum open position
* TP
* SL
* Duplicate-order prevention
* Session restrictions
* Manual stop
* Risk shutdown

If a risk limit is reached:

```text
STOP NEW ENTRIES
```

Handle any existing position according to configuration.

---

# 28. DAILY TRADE COUNT

Use the configured timezone.

Do not rely solely on an in-memory counter.

After restart, reconcile today's activity from Dhan where practical so the bot does not accidentally exceed:

```text
max_trades_per_day
```

---

# 29. MARKET DATA

Create:

```python
get_market_data(...)
```

It should:

* Fetch only required candle history.
* Include sufficient RSI warm-up.
* Identify completed candles.
* Validate data.
* Handle missing data.
* Handle API/network errors.
* Avoid large memory consumption.

---

# 30. RSI FUNCTION

Create:

```python
calculate_rsi(...)
```

It should:

* Accept candle data.
* Calculate Wilder RSI.
* Validate sufficient data.
* Handle invalid/missing values.
* Return usable RSI values.

Explain the mathematics in comments and in `architecture.md`.

---

# 31. REVERSAL FUNCTION

Create:

```python
confirm_reversal(...)
```

It should determine whether RSI has reversed from an extreme zone.

It must not place orders.

Document:

* Inputs
* Outputs
* Strategy reasoning
* Use case
* Safety considerations

---

# 32. CANDLE CONFIRMATION FUNCTION

Create:

```python
confirm_candle(...)
```

For LONG:

* Confirm bullish candle behavior.

For SHORT:

* Confirm bearish candle behavior.

Do not overcomplicate this function.

---

# 33. SIGNAL FUNCTION

Create:

```python
generate_signal(...)
```

It must:

* Evaluate RSI
* Evaluate reversal
* Evaluate candle confirmation
* Respect configuration
* Return LONG/SHORT/NONE
* Never place orders

Keep strategy logic independent from Dhan execution.

---

# 34. TRADE VALIDATION

Create:

```python
validate_trade(...)
```

It should verify:

* Session
* Trading mode
* Signal direction
* Position
* Pending orders
* Daily trade limit
* Risk limits
* Quantity
* Long/short permissions
* Safety settings

Return both:

```text
allowed
reason
```

The reason must be displayed in the CLI.

---

# 35. "NEXT ACTION" ENGINE

Create a dedicated mechanism to determine the bot's current next action.

Examples:

```text
WAITING FOR NEW CANDLE
WAITING FOR RSI OVERSOLD
WAITING FOR RSI OVERBOUGHT
WAITING FOR REVERSAL
WAITING FOR CANDLE CONFIRMATION
READY TO BUY
READY TO SELL
POSITION OPEN
MONITORING TP/SL
SESSION NOT STARTED
SESSION ENDED
MAX TRADES REACHED
RISK BLOCKED
STOPPING
```

Display it prominently.

---

# 36. STOP.PY

Create a lightweight `stop.py`.

Use a local stop-file mechanism suitable for AWS.

Example:

```text
stop.py
   ↓
creates STOP signal
   ↓
main.py detects STOP signal
   ↓
stop new entries
   ↓
handle existing position according to configuration
   ↓
gracefully exit
```

It must work when `main.py` and `stop.py` are run from separate terminals.

Do not require:

* Database
* Redis
* Web server
* External service

Document its usage in `architecture.md`.

---

# 37. GRACEFUL SHUTDOWN

Handle:

```text
Ctrl+C
SIGTERM
stop.py
```

On shutdown:

1. Stop generating new signals.
2. Check actual positions.
3. Cancel pending orders if configured.
4. Close positions if configured.
5. Verify closure.
6. Log reason.
7. Exit cleanly.

---

# 38. STATE MACHINE

Use a simple state model:

```text
STARTING
WAITING_FOR_SESSION
READY
SIGNAL_DETECTED
ENTRY_PENDING
POSITION_OPEN
MONITORING
EXIT_PENDING
POSITION_CLOSED
STOPPING
STOPPED
ERROR
```

Explain state transitions in `architecture.md`.

Do not create an unnecessarily complicated state-machine framework.

---

# 39. LOGGING

Use Python's standard `logging` module.

Display useful events such as:

```text
BOT STARTED
CONFIGURATION LOADED
CONFIGURATION VALIDATED
PAPER MODE
LIVE MODE
DHAN CONNECTED
SESSION ACTIVE
MARKET DATA UPDATED
RSI CALCULATED
SIGNAL DETECTED
RISK CHECK PASSED
ENTRY ORDER SUBMITTED
ENTRY ORDER FILLED
POSITION OPEN
TP ARMED
SL ARMED
POSITION MONITORING
TAKE PROFIT HIT
STOP LOSS HIT
EXIT ORDER SUBMITTED
POSITION CLOSED
SESSION END
MANUAL STOP
RISK LIMIT REACHED
RECOVERY MODE
ERROR
BOT STOPPED
```

Never log credentials.

---

# 40. ERROR HANDLING

Handle:

* Authentication failures
* Network errors
* API errors
* Timeout
* Invalid market data
* Missing candles
* Invalid configuration
* Order rejection
* Partial fills
* Unknown order state
* Position mismatch
* Unexpected exceptions

Do not hide important errors.

Do not expose credentials.

---

# 41. RETRIES

Safe retries may be used for:

* Market-data requests
* Position queries
* Order-status queries

Do not blindly retry order submission.

For an ambiguous order response:

```text
ORDER SUBMISSION UNCERTAIN
        ↓
QUERY ORDER STATUS
        ↓
QUERY POSITION
        ↓
RECONCILE
```

Only act after state is known.

---

# 42. PAPER MODE

Default:

```yaml
environment:
  mode: "PAPER"
```

Allowed:

```text
PAPER
LIVE
```

PAPER mode must never send live Dhan orders.

If Dhan does not provide the required paper execution mechanism, implement local simulation.

The paper engine should simulate:

* Entry
* Position
* Fill
* P&L
* TP
* SL
* Exit
* Bot shutdown

The same strategy and risk logic should be used in both PAPER and LIVE modes wherever practical.

---

# 43. LIVE MODE

When LIVE is selected, display:

```text
⚠ WARNING: LIVE TRADING ENABLED ⚠
REAL ORDERS MAY BE PLACED
REAL MONEY MAY BE AT RISK
```

Before every live order:

```text
CONFIGURATION
→ SESSION
→ POSITION
→ PENDING ORDERS
→ RISK
→ SIGNAL
→ SAFETY
→ ORDER
→ VERIFY
```

If any safety check fails:

```text
DO NOT PLACE ORDER
```

---

# 44. CONFIGURATION VALIDATION

Create:

```python
validate_config(...)
```

Validate:

* YAML
* Credentials
* Trading mode
* Security ID
* Trading symbol
* Quantity
* Exchange segment
* Product type
* RSI period
* Oversold
* Overbought
* TP
* SL
* Session
* Timezone
* Polling
* CLI

Reject invalid values such as:

```text
RSI period <= 0
oversold >= overbought
quantity <= 0
negative TP
negative SL
invalid mode
invalid time
missing credentials
missing security ID
```

Never start trading with invalid configuration.

---

# 45. MAIN.PY STRUCTURE

Organize `main.py` into these logical sections:

```text
1. Module documentation
2. Imports
3. Constants
4. State definitions
5. Configuration loading
6. Environment loading
7. Logging
8. CLI
9. Configuration validation
10. Dhan client
11. Market data
12. RSI calculation
13. Reversal confirmation
14. Candle confirmation
15. Signal generation
16. Position retrieval
17. Order management
18. TP/SL
19. P&L
20. Risk management
21. Session management
22. Daily trade management
23. Stop-file handling
24. Recovery
25. CLI dashboard
26. Graceful shutdown
27. Main loop
28. Entry point
```

Everything must remain in `main.py`.

---

# 46. FUNCTION DOCUMENTATION

Every important function must have a detailed docstring.

Use this style:

```python
def generate_signal(data, config):
    """
    Generate an RSI reversal signal.

    Purpose:
        Converts RSI and candle information into a LONG, SHORT,
        or NONE strategy decision.

    Why this function exists:
        Strategy logic should remain independent from broker execution.
        This makes the strategy easier to understand, test, tune,
        and maintain.

    Inputs:
        data:
            Market candle and RSI information.

        config:
            Strategy configuration.

    Returns:
        LONG, SHORT, or NONE.

    Safety:
        This function never places an order.
    """
```

For every major function explain:

* Purpose
* Why it exists
* Inputs
* Outputs
* Execution flow
* Trading use case
* Safety considerations

Comments should explain **why**, not merely repeat the code.

---

# 47. ARCHITECTURE.MD

Create a comprehensive `architecture.md`.

Write it as a standalone technical chapter explaining:

* RSI
* RSI reversal
* Strategy rules
* Entry
* Exit
* TP
* SL
* Risk
* Dhan integration
* Software architecture
* Functions
* CLI
* Session
* Polling
* Recovery
* Shutdown
* AWS deployment
* Parameter tuning

Use this structure:

```markdown
# RSI Reversal Algo

## 1. Introduction

## 2. Strategy Objective

## 3. What Is RSI?

## 4. RSI Formula

## 5. Wilder's RSI Calculation

## 6. RSI Period

## 7. Oversold and Overbought Levels

## 8. RSI Reversal Concept

## 9. Long Entry Rules

## 10. Short Entry Rules

## 11. Candle Confirmation

## 12. Completed Candle Principle

## 13. Strategy Flow

## 14. Example Long Trade

## 15. Example Short Trade

## 16. Example Trade Execution

## 17. Example Position Monitoring

## 18. Example TP Exit

## 19. Example SL Exit

## 20. Example P&L Calculation

## 21. System Architecture

## 22. Project File Structure

## 23. main.py Architecture

## 24. Configuration Architecture

## 25. Environment Variables

## 26. Dhan API Integration

## 27. Market Data Flow

## 28. RSI Calculation Flow

## 29. Signal Generation

## 30. Risk Validation

## 31. Order Execution

## 32. Order Verification

## 33. Position Management

## 34. P&L Monitoring

## 35. Take Profit

## 36. Stop Loss

## 37. TP/SL Monitoring

## 38. Why TP/SL Stops the Bot

## 39. Session Management

## 40. Day Trading Mode

## 41. Session Disabled Mode

## 42. Polling Architecture

## 43. Sci-Fi CLI

## 44. When Will the Algo Trade?

## 45. Why Is the Algo Not Trading?

## 46. Duplicate Order Prevention

## 47. Partial Fill Handling

## 48. Restart Recovery

## 49. State Machine

## 50. Graceful Shutdown

## 51. stop.py

## 52. Risk Management

## 53. Paper Trading

## 54. Live Trading

## 55. Error Handling

## 56. Retry Strategy

## 57. Parameter Tuning

## 58. Backtesting and Validation

## 59. Improving Strategy Quality

## 60. AWS 1 GB Deployment

## 61. Complete Program Execution Flow

## 62. Function-by-Function Explanation

## 63. Configuration Reference

## 64. Risk and Safety Considerations

## 65. Strategy Limitations

## 66. Future Improvements
```

---

# 48. ARCHITECTURE.MD — EXAMPLE TRADE

Provide realistic numerical examples.

For example, LONG:

```text
Entry = ₹1,000
Quantity = 10
TP = 1%
SL = 0.5%
```

Calculate:

```text
TP = ₹1,010
SL = ₹995
```

If TP is reached:

```text
Profit per share = ₹10
Quantity = 10

Gross P&L = ₹100
```

If SL is reached:

```text
Loss per share = ₹5
Quantity = 10

Gross P&L = -₹50
```

Explain that actual realized P&L can differ because of:

* Brokerage
* Taxes
* Fees
* Slippage
* Execution price

Do not present gross P&L as guaranteed net profit.

Also provide a SHORT example.

---

# 49. ARCHITECTURE.MD — PARAMETER TUNING

Include a detailed section explaining how traders can responsibly tune:

```text
RSI period
Oversold level
Overbought level
Timeframe
Candle confirmation
TP
SL
Quantity
Polling interval
Maximum trades
Session timing
```

Explain trade-offs.

For example:

### RSI Period

Lower period:

* More responsive
* More signals
* More noise
* Potentially more false reversals

Higher period:

* Smoother
* Fewer signals
* Slower response
* May miss quick reversals

### Oversold / Overbought

Explain why:

```text
20 / 80
```

may produce fewer but more extreme signals compared with:

```text
30 / 70
```

Do not claim that one setting is universally better.

---

# 50. PARAMETER TUNING FOR PROFITABILITY

Include a section explaining how a trader can attempt to improve strategy performance responsibly.

Do **not** promise or imply guaranteed profit.

Explain that profitability should be evaluated through:

* Historical backtesting
* Out-of-sample testing
* Walk-forward testing
* Paper trading
* Transaction-cost analysis
* Slippage analysis
* Different market regimes
* Different timeframes
* Different instruments

Explain metrics such as:

```text
Net Profit
Profit Factor
Win Rate
Average Win
Average Loss
Risk/Reward
Maximum Drawdown
Expectancy
Number of Trades
Sharpe Ratio where appropriate
```

Explain that optimizing only for historical profit can cause overfitting.

---

# 51. EXPECTANCY EXPLANATION

Include the basic expectancy concept:

```text
Expectancy =
(Win Rate × Average Win)
-
(Loss Rate × Average Loss)
```

Provide an example.

For example:

```text
Win rate = 55%
Average win = ₹100
Loss rate = 45%
Average loss = ₹80

Expectancy =
(0.55 × 100) - (0.45 × 80)
= ₹19 per trade
```

Clearly explain that this is a simplified theoretical example and does not include actual trading costs unless explicitly included.

---

# 52. RISK/REWARD DISCUSSION

Explain different TP/SL relationships.

Examples:

```text
TP 1% / SL 0.5%
TP 1.5% / SL 0.5%
TP 2% / SL 1%
```

Explain how changing TP/SL changes:

* Win rate
* Average win
* Average loss
* Drawdown
* Trade frequency
* Expectancy

Do not tell the trader that a specific combination guarantees profit.

---

# 53. PARAMETER TUNING EXAMPLE

Include a hypothetical tuning example:

```text
Configuration A
RSI = 14
Oversold = 30
Overbought = 70
TP = 1%
SL = 0.5%

Configuration B
RSI = 14
Oversold = 25
Overbought = 75
TP = 1.5%
SL = 0.75%
```

Explain how a trader might compare them using the same historical period and identical cost assumptions.

Do not cherry-pick results.

---

# 54. BACKTESTING GUIDANCE

Explain how to test the strategy before live trading.

Include:

```text
Historical data
    ↓
Generate signals
    ↓
Simulate execution
    ↓
Apply TP/SL
    ↓
Apply transaction costs
    ↓
Calculate P&L
    ↓
Calculate drawdown
    ↓
Evaluate expectancy
    ↓
Out-of-sample validation
```

Explain why live results can differ from backtest results.

---

# 55. STRATEGY IMPROVEMENT IDEAS

In `architecture.md`, explain possible future improvements without unnecessarily implementing them in the current bot.

Examples:

* Trend filter
* Volatility filter
* Volume confirmation
* ATR-based stop loss
* Dynamic position sizing
* Market regime filter
* Time-of-day filter
* Trailing stop
* Break-even stop
* Multi-timeframe confirmation
* Option-specific execution layer

Clearly distinguish these from the current baseline strategy.

Do not add these features to the current implementation unless they are explicitly required by the configuration.

---

# 56. PROFITABILITY WARNING

The documentation must explicitly explain:

**No trading strategy can guarantee profit.**

The purpose of parameter tuning is to improve robustness and risk-adjusted performance, not to guarantee profitable trades.

Emphasize:

```text
Robustness > Historical maximum profit
```

Avoid curve fitting.

---

# 57. ARCHITECTURE.MD — FUNCTION-BY-FUNCTION

For every major function in `main.py`, include:

```markdown
### function_name()

**Purpose**

**Why it exists**

**Inputs**

**Outputs**

**Step-by-step execution**

**Trading use case**

**Safety considerations**
```

The reader should be able to understand the entire program from startup to shutdown.

---

# 58. ARCHITECTURE.MD — CODE-TO-CONCEPT MAPPING

Explain which functions correspond to:

```text
Market Data
RSI
Reversal
Candle Confirmation
Signal
Risk Management
Order Execution
Order Verification
Position Management
P&L
TP
SL
Session
CLI
Shutdown
Recovery
```

This mapping must make it easy to connect the architecture explanation to the actual source code.

---

# 59. ARCHITECTURE.MD — COMPLETE EXECUTION FLOW

Explain the entire execution sequence:

```text
START
 ↓
LOAD CONFIG
 ↓
LOAD ENV
 ↓
VALIDATE CONFIG
 ↓
CONNECT TO DHAN
 ↓
START CLI
 ↓
RECOVER EXISTING POSITION
 ↓
CHECK SESSION
 ↓
CHECK STOP REQUEST
 ↓
FETCH DATA
 ↓
IDENTIFY CLOSED CANDLE
 ↓
CALCULATE RSI
 ↓
GENERATE SIGNAL
 ↓
RISK VALIDATION
 ↓
ORDER EXECUTION
 ↓
ORDER VERIFICATION
 ↓
POSITION VERIFICATION
 ↓
TP/SL MONITORING
 ↓
EXIT
 ↓
VERIFY POSITION CLOSED
 ↓
STOP BOT
```

Explain every stage.

---

# 60. ARCHITECTURE.MD — AWS DEPLOYMENT

Explain:

1. Install Python
2. Create directory
3. Create virtual environment
4. Install requirements
5. Configure `.env`
6. Configure `config.yaml`
7. Run `main.py`
8. Monitor CLI
9. Use `stop.py`
10. Shut down safely

Do not require Docker.

Do not require a database.

Do not require a web server.

---

# 61. REQUIREMENTS.TXT

Create a minimal requirements file.

Potential dependencies:

```text
dhanhq
python-dotenv
PyYAML
pandas
rich
```

Only include packages actually used.

Do not include unnecessary dependencies.

---

# 62. .ENV

Create:

```text
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Do not include actual credentials.

---

# 63. STARTUP DISPLAY

At startup display a futuristic configuration summary:

```text
╔══════════════════════════════════════════════════════╗
║        RSI REVERSAL // ALGO CORE INITIALIZING        ║
╠══════════════════════════════════════════════════════╣
║ MODE        : PAPER                                  ║
║ SYMBOL      : ...                                    ║
║ SECURITY ID : ...                                    ║
║ TIMEFRAME   : 5 MIN                                  ║
║ RSI         : 14                                     ║
║ OVERSOLD    : 30                                     ║
║ OVERBOUGHT  : 70                                     ║
║ TP          : 1.0%                                   ║
║ SL          : 0.5%                                   ║
║ POLLING     : 5 SEC                                  ║
║ SESSION     : 09:20 → 15:15                          ║
║ TIMEZONE    : Asia/Kolkata                           ║
╚══════════════════════════════════════════════════════╝
```

If LIVE:

```text
⚠ LIVE TRADING ENABLED ⚠
REAL ORDERS MAY BE PLACED
```

---

# 64. CLI AND API POLLING SEPARATION

The CLI refresh interval:

```yaml
cli:
  refresh_seconds: 1
```

must be independent from API polling:

```yaml
runtime:
  polling_interval_seconds: 5
```

The CLI may refresh every second without making a Dhan API request every second.

Only the configured trading polling cycle should perform market-data/trading API operations.

---

# 65. MEMORY AND CPU REQUIREMENTS

The application must remain suitable for:

```text
1 CPU
1 GB RAM
Linux
```

Avoid:

* Large DataFrames
* Unlimited event history
* Huge historical datasets
* Heavy ML libraries
* Multiprocessing
* Databases
* Redis
* Docker requirement
* Web servers

Limit CLI event history.

Only retain the data needed by the strategy.

---

# 66. NO EXTRA FILES

Do not create:

* Additional Python modules
* Database files
* Docker files
* README
* Web server
* Test framework requiring additional project files
* Temporary runtime source files

The application files must be:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

---

# 67. FINAL SAFETY REQUIREMENTS

The following are mandatory:

### TP

```text
TP reached
→ Exit
→ Verify closed
→ Stop bot
```

### SL

```text
SL reached
→ Exit
→ Verify closed
→ Stop bot
```

### Session

If enabled:

```text
Start time
→ Trade
→ Stop time
→ Stop entries
→ Close positions if configured
→ Verify
→ Stop bot
```

### Session disabled

```text
No mandatory time restriction
```

### Duplicate signal

```text
Same candle
→ No duplicate trade
```

### Restart

```text
Existing position
→ Recover
→ Monitor
→ No duplicate entry
```

### Ambiguous order

```text
Unknown result
→ Query broker
→ Reconcile
→ Do not blindly resubmit
```

---

# 68. FINAL CODE REVIEW

Before completing the implementation, verify:

## Strategy

* Correct Wilder RSI
* Oversold configurable
* Overbought configurable
* Reversal configurable
* Candle confirmation configurable
* Closed-candle processing
* Duplicate candle prevention

## Execution

* LONG
* SHORT
* Quantity
* Symbol
* Security ID
* Exchange
* Product
* Order type
* Order verification

## Position

* Current position
* Current P&L
* Entry price
* LTP
* Quantity
* TP
* SL
* Position age

## CLI

* Sci-fi interface
* RSI
* Signal
* Current position
* P&L
* TP
* SL
* Last trade
* Next action
* Why no trade
* Polling status
* API status
* Recent events

## Risk

* TP
* SL
* TP/SL shutdown
* Max trades
* Max positions
* Duplicate prevention
* Partial fills
* Unknown order states

## Session

* Start time
* Stop time
* Timezone
* Close positions
* Session disabled mode

## Shutdown

* Ctrl+C
* SIGTERM
* stop.py
* Configurable position closure
* Pending order handling
* Position verification

## Recovery

* Existing positions
* Restart
* No duplicate trade

## Deployment

* Local
* AWS Linux
* 1 GB RAM
* Minimal dependencies

---

# 69. NO PSEUDOCODE

Generate actual working implementation.

Do not leave:

```python
pass
```

for required functionality.

Do not leave:

```text
TODO: implement later
```

for core functionality.

Do not create fake Dhan API methods.

Use the available Dhan reference files to determine the correct SDK/API implementation.

If the reference code is outdated, adapt it appropriately.

---

# 70. FINAL FILES

Generate complete contents for exactly:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

The application must continue working after:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

are deleted.

---

# 71. FINAL DOCUMENTATION STANDARD

Write `architecture.md` with enough depth that a technically knowledgeable reader can follow the complete system from:

```text
Strategy Idea
→ Mathematical Indicator
→ Signal
→ Risk
→ Broker API
→ Order
→ Position
→ P&L
→ TP/SL
→ Exit
→ Shutdown
```

Include practical numerical examples showing:

* When a signal occurs
* When an order is placed
* What happens after execution
* Entry price
* Quantity
* TP
* SL
* P&L
* Exit reason
* Why the bot stops

Also explain how changing parameters can affect:

* Signal frequency
* False signals
* Win rate
* Average profit
* Average loss
* Drawdown
* Expectancy
* Overall robustness

Give responsible suggestions for improving strategy performance through testing and validation, but **never promise profitability or guaranteed profit**.

The implementation should be written with clear function names, detailed comments, docstrings, explanations of important design decisions, and a logical architecture so that the source code and its explanations are useful as high-quality technical reference material and can be adapted for inclusion in books.

**Now generate the complete implementation for all six required files.**
