You are an expert Python algorithmic-trading engineer specializing in the Indian stock market, Dhan trading APIs, robust order execution, risk management, and production-ready trading bots.

Build a complete **Opening Range Breakout (ORB) Intraday Trading Algo for Dhan**.

The application must be simple enough to understand, modify, test, and run locally, while also being stable enough to run continuously on an **AWS Linux VM with only 1 GB RAM**.

## 1. PROJECT OBJECTIVE

Implement an Opening Range Breakout (ORB) strategy for intraday trading through Dhan.

The strategy should:

1. Define an opening range using a configurable market-open period.
2. Capture the opening range high and low.
3. Detect a bullish breakout above the opening-range high.
4. Detect a bearish breakdown below the opening-range low.
5. Generate trades according to configurable strategy rules.
6. Place orders through Dhan.
7. Track order status.
8. Track open positions.
9. Calculate/display live P&L.
10. Apply configurable Take Profit (TP).
11. Apply configurable Stop Loss (SL).
12. Stop trading when TP or SL is reached.
13. Optionally operate as a strict day-trading system.
14. Optionally close all positions at a configured end-of-day time.
15. Support configurable polling frequency.
16. Display a clear live CLI dashboard.
17. Recover safely from temporary API/network failures.
18. Prevent duplicate orders.
19. Gracefully shut down.
20. Be easy to extend later.

This is a **single-strategy trading application**, not a generic multi-strategy framework.

---

# 2. REQUIRED FILE STRUCTURE

Create ONLY these application files:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

The project may read these optional reference files during development:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

These two files are reference material only.

The final application MUST NOT depend on them.

The application must continue working after the entire `docs/` directory is deleted.

Do not create additional Python modules.

All application logic must remain inside:

```text
main.py
```

---

# 3. REFERENCE FILES

If these files exist:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

inspect them first.

Use them only to understand:

* Dhan API conventions
* authentication
* security ID handling
* exchange segment handling
* order placement
* order modification/cancellation
* position retrieval
* market data retrieval
* historical/intraday data
* WebSocket usage if available
* API response structures
* error handling conventions

Do NOT blindly copy code.

Adapt the implementation to the current Dhan API usage represented by the reference files.

If the reference implementation and current Dhan SDK/API conventions differ, create a clean abstraction inside `main.py`.

Do not make the final implementation dependent on undocumented behavior.

---

# 4. TECHNOLOGY REQUIREMENTS

Use Python 3.10+.

Keep dependencies lightweight because the application must run on a 1 GB RAM Linux VM.

Prefer:

* Dhan official Python SDK/API where appropriate
* requests/httpx if required
* pandas/numpy only where genuinely necessary
* PyYAML
* python-dotenv
* standard Python libraries wherever possible

Avoid unnecessary frameworks.

Do not introduce:

* Django
* Flask
* FastAPI
* database servers
* Redis
* Celery
* Docker requirements
* heavy ML libraries
* unnecessary GUI frameworks

The bot must be a lightweight CLI application.

---

# 5. CONFIGURATION

Everything that a trader may reasonably want to change must be configurable through:

```text
config.yaml
```

Never hard-code strategy parameters in `main.py` when they should logically be configurable.

The `.env` file must contain secrets only.

Example:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Never put API credentials in `config.yaml`.

Never print API tokens in the terminal.

---

# 6. CONFIG.YAML

Create a complete, readable configuration.

Use a structure similar to:

```yaml
app:
  name: "Dhan ORB Algo"
  environment: "paper"
  log_level: "INFO"
  polling_seconds: 5

market:
  exchange_segment: "NSE_EQ"
  trading_symbol: "RELIANCE"
  security_id: "1333"

strategy:
  enabled: true

  opening_range:
    start_time: "09:15"
    end_time: "09:30"

  breakout:
    buffer_points: 0.0
    buffer_percent: 0.0
    confirmation_candles: 1

  direction:
    allow_long: true
    allow_short: true

  entry:
    order_type: "MARKET"
    product_type: "INTRADAY"

risk:
  quantity: 1

  stop_loss:
    enabled: true
    type: "PERCENT"
    value: 1.0

  take_profit:
    enabled: true
    type: "PERCENT"
    value: 2.0

  max_trades_per_day: 1

  max_daily_loss:
    enabled: true
    value: 2000

day_trading:
  enabled: true
  force_exit_enabled: true
  force_exit_time: "15:15"

trading_session:
  start_time: "09:15"
  stop_new_entries_time: "15:00"

execution:
  order_timeout_seconds: 15
  order_status_poll_seconds: 2
  retry_attempts: 3
  retry_delay_seconds: 2

safety:
  dry_run: true
  prevent_duplicate_orders: true
  require_market_hours: true
  close_positions_on_stop: false

logging:
  file_enabled: true
  file_name: "orb_algo.log"
```

You may improve this structure if necessary.

Every configuration parameter must actually be used.

Do not create configuration settings that are ignored.

---

# 7. ORB STRATEGY

Implement the Opening Range Breakout strategy correctly.

Default market session:

```text
09:15 AM - 03:30 PM IST
```

Opening range:

```text
09:15 AM - 09:30 AM
```

The opening range high is:

```text
maximum price during opening-range period
```

The opening range low is:

```text
minimum price during opening-range period
```

After the opening range is completed:

### LONG SIGNAL

Generate a long signal when price breaks above:

```text
opening_range_high + configured_buffer
```

The buffer must support:

* points
* percentage

Do not apply both simultaneously unless explicitly configured.

### SHORT SIGNAL

Generate a short signal when price breaks below:

```text
opening_range_low - configured_buffer
```

Support configurable:

```yaml
allow_long: true
allow_short: true
```

---

# 8. BREAKOUT CONFIRMATION

Support configurable breakout confirmation.

Example:

```yaml
confirmation_candles: 1
```

The implementation must avoid entering repeatedly while price remains above the breakout level.

A breakout should be treated as an event, not as a condition that continuously generates new orders.

Example:

```text
Price crosses above OR high
        ↓
LONG signal
        ↓
Place order
        ↓
Mark trade as active
        ↓
Ignore additional long signals
```

---

# 9. OPENING RANGE CALCULATION

The bot must properly handle:

### Before opening range

Do not trade.

### During opening range

Collect/update:

```text
opening_range_high
opening_range_low
```

Do not enter breakout trades during the range-building period.

### After opening range

Freeze the opening range.

Do not continuously change the ORB high/low after the opening range has ended.

Display:

```text
ORB HIGH
ORB LOW
```

on the CLI.

---

# 10. DATA HANDLING

Every:

```text
app.polling_seconds
```

seconds:

1. Fetch required market data.
2. Process the latest price/candle.
3. Update ORB values if the opening range is still forming.
4. Evaluate breakout conditions.
5. Check current position.
6. Check TP.
7. Check SL.
8. Check daily risk limits.
9. Check force-exit conditions.
10. Update CLI dashboard.

Default:

```text
5 seconds
```

The polling interval must be configurable.

Do not busy-loop.

Use:

```python
time.sleep(...)
```

or an equivalent lightweight mechanism.

---

# 11. ORDER EXECUTION

Implement safe Dhan order execution.

Before placing an order:

1. Verify strategy is enabled.
2. Verify market hours.
3. Verify opening range is complete.
4. Verify no existing position.
5. Verify daily trade limit.
6. Verify daily loss limit.
7. Verify direction is enabled.
8. Verify duplicate-order protection.
9. Verify dry-run mode.
10. Place the order.

Handle:

* API failure
* timeout
* rejected order
* partially filled order
* cancelled order
* invalid response
* network error
* authentication failure

Never assume that an order was filled merely because the order-placement API returned successfully.

Confirm order status.

---

# 12. DUPLICATE ORDER PROTECTION

This is extremely important.

The bot must not place multiple orders because the polling loop sees the same breakout for several cycles.

Maintain internal state such as:

```text
NO_POSITION
ENTRY_PENDING
POSITION_OPEN
EXIT_PENDING
TRADE_COMPLETED
BOT_STOPPED
```

Use appropriate logic to prevent duplicate entries.

Also check actual Dhan positions/orders before submitting a new order whenever practical.

The actual broker state should take precedence over stale local state.

---

# 13. POSITION MANAGEMENT

The bot must periodically retrieve the actual position from Dhan.

Display:

```text
Symbol
Direction
Quantity
Average Entry Price
Current Price
Unrealized P&L
Realized P&L if available
```

Calculate P&L correctly for:

### LONG

```text
(current_price - entry_price) × quantity
```

### SHORT

```text
(entry_price - current_price) × quantity
```

Use broker-provided P&L where reliable and appropriate, but ensure the application can understand and display the calculation.

---

# 14. TAKE PROFIT

Support:

```yaml
take_profit:
  enabled: true
  type: "PERCENT"
  value: 2.0
```

Also support:

```text
POINTS
PERCENT
```

For LONG:

```text
TP = entry_price + TP distance
```

For SHORT:

```text
TP = entry_price - TP distance
```

When TP is reached:

1. Exit the position.
2. Confirm exit order.
3. Confirm position is closed.
4. Record trade result.
5. Display final P&L.
6. Stop the bot.

The requirement is:

**When TP is reached, stop the bot.**

---

# 15. STOP LOSS

Support:

```yaml
stop_loss:
  enabled: true
  type: "PERCENT"
  value: 1.0
```

Also support:

```text
POINTS
PERCENT
```

For LONG:

```text
SL = entry_price - SL distance
```

For SHORT:

```text
SL = entry_price + SL distance
```

When SL is reached:

1. Exit the position.
2. Confirm exit.
3. Confirm position is closed.
4. Record trade result.
5. Display final P&L.
6. Stop the bot.

The requirement is:

**When SL is reached, stop the bot.**

---

# 16. TP/SL EXECUTION DESIGN

Implement TP/SL safely.

The bot must continuously monitor the live/current price.

Do not wait for the next candle if the polling configuration allows more frequent monitoring.

When TP/SL is triggered:

```text
POSITION OPEN
      ↓
TP/SL detected
      ↓
Submit exit order
      ↓
Confirm order
      ↓
Verify position closed
      ↓
Calculate final P&L
      ↓
STOP BOT
```

Protect against duplicate exit orders.

If the exit order fails:

* retry according to configuration
* keep checking position
* never falsely mark the position as closed
* report the problem prominently

---

# 17. DAILY TRADING MODE

Implement:

```yaml
day_trading:
  enabled: true
```

If enabled:

* only trade during the configured trading session
* do not create new entries after the configured entry cutoff
* close open positions at the configured force-exit time
* stop the bot after positions are closed

Example:

```yaml
force_exit_enabled: true
force_exit_time: "15:15"
```

At force-exit time:

```text
STOP NEW ENTRIES
        ↓
CHECK OPEN POSITION
        ↓
IF POSITION EXISTS
        ↓
CLOSE POSITION
        ↓
VERIFY CLOSED
        ↓
STOP BOT
```

If:

```yaml
day_trading.enabled: false
```

do not force a time-based exit merely because the day-trading mode is disabled.

The bot must still obey configured TP/SL and explicit stop conditions.

---

# 18. START/STOP TIME

Allow configuration of when the bot starts trading.

Example:

```yaml
trading_session:
  start_time: "09:15"
  stop_new_entries_time: "15:00"
```

Before start time:

```text
WAITING FOR MARKET SESSION
```

During trading session:

```text
ACTIVE
```

After new-entry cutoff:

```text
ENTRY DISABLED
```

At force exit:

```text
FORCE EXIT
```

Then:

```text
BOT STOPPED
```

Do not place trades outside configured trading hours.

Use Indian Standard Time consistently.

Use timezone-aware datetime handling where possible.

Do not depend on the server's local timezone.

---

# 19. STOP.PY

Create:

```text
stop.py
```

Its purpose is to safely request the running bot to stop.

Keep it lightweight.

The recommended design is a shared stop signal such as:

```text
STOP
```

or another simple local mechanism.

The main bot should check the stop signal during every polling cycle.

When a stop request is detected:

1. Stop new entries.
2. If configured:

```yaml
safety:
  close_positions_on_stop: false
```

close positions.

3. Otherwise leave existing positions untouched.
4. Print what action was taken.
5. Exit cleanly.

The stop mechanism must work on Linux and locally without requiring another server.

---

# 20. DRY-RUN MODE

Implement:

```yaml
safety:
  dry_run: true
```

When:

```text
dry_run = true
```

the bot must NOT send real orders to Dhan.

Instead, simulate:

```text
ENTRY
EXIT
TP
SL
POSITION
P&L
```

and clearly display:

```text
DRY RUN
```

in the CLI.

When:

```text
dry_run = false
```

use real Dhan order execution.

Never accidentally send live orders when dry-run is enabled.

---

# 21. CLI DESIGN

The CLI should feel modern and **sci-fi / futuristic**, while remaining lightweight and readable over SSH.

Do not build a heavy GUI.

Use terminal formatting where practical.

Example concept:

```text
╔══════════════════════════════════════════════════════════╗
║              DHAN // ORB TRADING ENGINE                 ║
╠══════════════════════════════════════════════════════════╣
║ STATUS       : ACTIVE                                   ║
║ MODE         : PAPER / LIVE                             ║
║ STRATEGY     : OPENING RANGE BREAKOUT                   ║
║ SYMBOL       : RELIANCE                                 ║
║ PRICE        : ₹2,845.20                                ║
║ ORB HIGH     : ₹2,850.00                                ║
║ ORB LOW      : ₹2,820.00                                ║
║ POSITION     : LONG 1                                   ║
║ ENTRY        : ₹2,851.00                                ║
║ CURRENT      : ₹2,858.00                                ║
║ P&L          : ₹7.00                                     ║
║ TP           : ₹2,908.02                                ║
║ SL           : ₹2,822.49                                ║
║ NEXT ACTION  : MONITOR                                  ║
╠══════════════════════════════════════════════════════════╣
║ LAST SIGNAL  : LONG BREAKOUT                            ║
║ LAST ORDER   : FILLED                                   ║
║ LAST UPDATE  : 09:36:25                                 ║
║ NEXT POLL   : 5 SEC                                     ║
╚══════════════════════════════════════════════════════════╝
```

The actual values must be dynamically updated.

The CLI should show at minimum:

* bot status
* live mode / dry-run mode
* symbol
* current price
* ORB high
* ORB low
* breakout levels
* position
* quantity
* entry price
* current price
* TP
* SL
* current P&L
* daily P&L if available
* number of trades today
* last signal
* last order
* order status
* polling interval
* next action
* current time
* important warnings/errors

Avoid excessive terminal output.

Prefer updating one dashboard rather than printing hundreds of lines.

Important events may still be logged.

---

# 22. LOGGING

Implement proper logging.

Log:

* startup
* configuration loaded
* authentication status
* market session
* ORB start
* ORB high/low updates
* ORB completed
* breakout detection
* order submission
* order response
* order status
* position changes
* TP trigger
* SL trigger
* force exit
* stop request
* API errors
* retries
* shutdown

Do not log:

* access tokens
* secrets
* sensitive credentials

Use Python's built-in `logging` module.

---

# 23. ERROR HANDLING

The bot must not crash because of a temporary API failure.

Implement:

```text
try/except
retry
backoff
safe recovery
```

for appropriate broker/API operations.

Differentiate between:

### Recoverable

* temporary network failure
* timeout
* temporary API error

and:

### Non-recoverable

* invalid credentials
* invalid security ID
* invalid configuration
* malformed API response
* critical initialization failure

For recoverable errors:

```text
ERROR
 ↓
LOG
 ↓
WAIT
 ↓
RETRY
 ↓
CONTINUE
```

For critical errors:

```text
ERROR
 ↓
SAFE SHUTDOWN
```

Never silently ignore exceptions.

Never use:

```python
except:
    pass
```

---

# 24. CONFIGURATION VALIDATION

Before starting the trading loop, validate the configuration.

Validate:

* security ID
* trading symbol
* exchange segment
* quantity
* polling interval
* opening range times
* session times
* TP
* SL
* max trades
* force-exit settings
* order type
* product type
* dry-run setting

If configuration is invalid:

```text
Do not start trading.
```

Display a clear error explaining what needs to be fixed.

---

# 25. TIMEZONE

The strategy is designed for Indian markets.

Use:

```text
Asia/Kolkata
```

for trading-session calculations.

Do not assume Linux server timezone is IST.

---

# 26. MARKET DATA

Build a clean internal market-data function.

For example:

```python
get_current_price()
```

and/or appropriate Dhan market-data functions.

The exact Dhan implementation should follow the available API/reference code.

Do not scatter Dhan API calls throughout every strategy function.

Create clear internal functions inside `main.py`.

---

# 27. FUNCTION DESIGN

Keep `main.py` organized into logical sections.

Use functions with clear responsibilities.

At minimum, create functions similar to:

```python
load_environment()
load_config()
validate_config()
initialize_dhan_client()

get_current_price()
get_market_data()
get_opening_range_data()
calculate_opening_range()

calculate_breakout_levels()
check_long_breakout()
check_short_breakout()

get_positions()
get_current_position()

calculate_pnl()

calculate_stop_loss()
calculate_take_profit()

check_entry_conditions()
check_risk_conditions()

place_entry_order()
place_exit_order()

get_order_status()
wait_for_order_completion()

check_take_profit()
check_stop_loss()

check_force_exit()
check_stop_signal()

close_all_positions()

record_trade()
update_runtime_state()

render_dashboard()

setup_logging()
safe_shutdown()

run_trading_loop()
main()
```

You may add helper functions if necessary.

Do not create unnecessary abstractions.

---

# 28. FUNCTION DOCUMENTATION

Every important function in `main.py` must have a useful docstring.

The docstring should explain:

1. What the function does.
2. Why it exists.
3. What inputs it expects.
4. What it returns.
5. Important side effects.
6. Important failure conditions.

Example style:

```python
def calculate_take_profit(entry_price, direction, config):
    """
    Calculate the take-profit price for the active position.

    The function supports both percentage-based and point-based
    take-profit configurations.

    Args:
        entry_price: Filled entry price.
        direction: LONG or SHORT.
        config: Loaded strategy/risk configuration.

    Returns:
        Calculated take-profit price.

    Raises:
        ValueError: If the TP configuration is invalid.
    """
```

Use clear comments around important trading logic.

Comments should explain **why**, not merely repeat the code.

---

# 29. MAIN.PY ORGANIZATION

Organize the file in this order:

```text
1. Imports
2. Constants
3. Configuration/state definitions
4. Logging setup
5. Environment/config loading
6. Dhan client initialization
7. Market-data functions
8. ORB calculation functions
9. Strategy functions
10. Risk-management functions
11. Order-management functions
12. Position/P&L functions
13. Stop/force-exit functions
14. CLI/dashboard functions
15. Shutdown functions
16. Main trading loop
17. main()
```

Keep it readable.

Use type hints wherever practical.

Avoid unnecessarily advanced Python techniques.

---

# 30. RUNTIME STATE

Maintain a clear runtime state.

It should track information such as:

```text
bot_status
session_started
opening_range_complete
opening_range_high
opening_range_low
long_breakout_level
short_breakout_level
current_signal
trade_count
active_position
entry_price
position_quantity
take_profit_price
stop_loss_price
last_order_id
last_order_status
daily_pnl
last_update_time
stop_requested
```

Do not persist unnecessary state to a database.

For a single-process lightweight application, in-memory state is preferred.

At startup, reconcile important state with Dhan.

---

# 31. BROKER STATE VS LOCAL STATE

The broker's actual state must be treated as authoritative.

For example:

If local state says:

```text
NO POSITION
```

but Dhan reports an open position:

```text
POSITION OPEN
```

the bot must recognize the actual broker position.

Likewise, do not submit a new entry simply because local state says there is no position.

First check broker state where appropriate.

This is essential for restart safety.

---

# 32. RESTART SAFETY

If the bot is restarted while a position exists:

1. Query Dhan positions.
2. Detect the existing position.
3. Reconstruct relevant position information.
4. Calculate/restore TP and SL based on configuration and actual entry price.
5. Resume monitoring.
6. Do not place another entry.

The bot must not duplicate a trade after restart.

---

# 33. DAILY TRADE LIMIT

Support:

```yaml
max_trades_per_day: 1
```

When the limit is reached:

```text
NEW ENTRIES DISABLED
```

Do not place further entries.

The value must be configurable.

---

# 34. MAX DAILY LOSS

Support:

```yaml
max_daily_loss:
  enabled: true
  value: 2000
```

If daily realized/unrealized losses reach the configured threshold:

1. Stop new entries.
2. If configured by the risk policy, close an open position safely.
3. Stop the bot if appropriate.
4. Display a prominent warning.

Do not allow the bot to continue opening new trades after the daily loss threshold is breached.

---

# 35. SINGLE POSITION

The initial strategy should support one active position at a time.

Do not allow:

```text
LONG + LONG
LONG + SHORT
SHORT + SHORT
```

simultaneously.

After a trade is completed, the strategy should obey:

```text
max_trades_per_day
```

before considering another trade.

---

# 36. SIGNAL PRIORITY

If both long and short conditions appear due to unusual market-data behavior:

Do not blindly execute both.

Implement deterministic handling.

For example:

```text
LONG first detected → LONG
SHORT first detected → SHORT
```

or another clearly documented rule.

Document this behavior in `architecture.md`.

---

# 37. FORCE EXIT

When:

```text
force_exit_time
```

is reached and day-trading mode is enabled:

```text
No new entries
       ↓
Check position
       ↓
Close position if present
       ↓
Verify position closed
       ↓
Display realized P&L
       ↓
Stop bot
```

Do not repeatedly submit exit orders every polling cycle.

---

# 38. BOT STOPPING AFTER TP/SL

This requirement is mandatory.

If TP occurs:

```text
EXIT → VERIFY → RECORD P&L → STOP
```

If SL occurs:

```text
EXIT → VERIFY → RECORD P&L → STOP
```

After TP/SL:

```text
No further trades.
```

The bot must terminate its trading loop cleanly.

---

# 39. MANUAL STOP

When `stop.py` is executed:

The running bot should detect the stop request within approximately one polling cycle.

It should then:

```text
STOP NEW ORDERS
```

and optionally:

```text
CLOSE OPEN POSITIONS
```

based on:

```yaml
close_positions_on_stop
```

Then shut down cleanly.

---

# 40. AWS 1 GB RAM REQUIREMENTS

Optimize for:

```text
1 GB RAM
Linux
SSH terminal
Long-running Python process
```

Do not maintain unnecessary in-memory historical datasets.

Only retain the data needed for:

* opening range
* current strategy calculations
* current position
* recent order state

Avoid memory leaks.

Do not continuously append unlimited logs/data to Python lists.

---

# 41. REQUIREMENTS.TXT

Create a minimal:

```text
requirements.txt
```

with only dependencies actually used.

Pin compatible versions where appropriate, but avoid unnecessary over-pinning that creates installation problems.

---

# 42. ARCHITECTURE.MD

Create:

```text
architecture.md
```

This must be a complete technical explanation of the ORB strategy and application architecture.

Write it as a polished educational chapter.

Include:

## 42.1 Strategy Overview

Explain:

* What ORB is.
* Why the opening range matters.
* How the strategy identifies the range.
* How breakouts are detected.
* LONG setup.
* SHORT setup.
* TP.
* SL.
* Force exit.

## 42.2 Example Trade

Use a realistic hypothetical example.

For example:

```text
Stock: Example Stock
Opening Range: 09:15–09:30

ORB High = ₹1,000
ORB Low  = ₹980

Price breaks ₹1,000

Entry = ₹1,002

Stop Loss = ₹992
Take Profit = ₹1,022
```

Then explain step-by-step:

```text
09:15 → market opens
09:30 → ORB calculated
09:35 → breakout detected
09:35 → order submitted
09:35 → order filled
09:40 → price moves upward
09:45 → TP reached
09:45 → exit order submitted
09:45 → position closed
09:45 → P&L calculated
09:45 → bot stopped
```

Calculate the hypothetical P&L using quantity.

Clearly state that the example is hypothetical and does not guarantee profit.

---

# 43. LOSING TRADE EXAMPLE

Also provide an example where SL is hit.

Explain:

```text
Entry
↓
Breakout fails
↓
Price reverses
↓
SL reached
↓
Exit
↓
Loss calculated
↓
Bot stops
```

Explain why this is important.

---

# 44. P&L EXPLANATION

Explain:

### LONG

```text
P&L = (Exit Price - Entry Price) × Quantity
```

### SHORT

```text
P&L = (Entry Price - Exit Price) × Quantity
```

Also explain that real-world P&L can differ after:

* brokerage
* taxes
* exchange charges
* STT
* GST
* slippage
* other transaction costs

Do not claim a strategy guarantees profit.

---

# 45. PARAMETER TUNING

Create a detailed section explaining how traders can tune:

```text
Opening range duration
Breakout buffer
Confirmation candles
Stop loss
Take profit
Risk/reward ratio
Polling interval
Quantity
Maximum trades
Maximum daily loss
Entry cutoff
Force-exit time
Long/short filters
```

For each parameter explain:

```text
What it controls
What happens if increased
What happens if decreased
Potential benefit
Potential drawback
When it may be useful
```

Do NOT claim that any parameter will necessarily make the strategy profitable.

Explain that parameter tuning must be performed using:

* historical backtesting
* out-of-sample testing
* walk-forward testing
* paper trading
* realistic transaction costs
* slippage assumptions

---

# 46. PROFITABILITY DISCUSSION

Include a section:

```text
How to Improve the Probability of a Profitable ORB System
```

Explain practical improvements such as:

* avoiding extremely low-liquidity stocks
* using liquid instruments
* controlling risk per trade
* avoiding oversized positions
* using realistic slippage
* avoiding overtrading
* testing different ORB durations
* testing breakout buffers
* testing trend filters
* testing volume confirmation
* testing volatility filters
* testing market-regime filters
* controlling daily loss
* using disciplined exits

Make it clear:

**No trading algorithm can guarantee profit.**

Do not write language promising guaranteed returns.

---

# 47. BACKTESTING / OPTIMIZATION SECTION

Explain how to test the strategy properly.

Include:

```text
In-sample period
Out-of-sample period
Walk-forward testing
Transaction costs
Slippage
Gap risk
Market regime changes
Parameter sensitivity
Maximum drawdown
Win rate
Average win
Average loss
Profit factor
Expectancy
Sharpe ratio where appropriate
Number of trades
```

Explain why optimizing parameters only on historical data can cause overfitting.

---

# 48. ARCHITECTURE DIAGRAM

Include an ASCII architecture diagram such as:

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

Also explain the role of:

```text
stop.py
.env
requirements.txt
architecture.md
```

---

# 49. FUNCTION-BY-FUNCTION EXPLANATION

In `architecture.md`, explain every major function from `main.py`.

For each function explain:

```text
Function name
Purpose
Input
Output
When it runs
Why it is needed
What can go wrong
```

Follow the actual implementation.

Do not document functions that do not exist.

Do not create documentation that contradicts the code.

---

# 50. COMPLETE TRADE LIFECYCLE

Document the entire lifecycle:

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
Check broker state
 ↓
Wait for trading session
 ↓
Build opening range
 ↓
Freeze ORB
 ↓
Monitor breakout
 ↓
Generate signal
 ↓
Risk checks
 ↓
Place order
 ↓
Confirm fill
 ↓
Track position
 ↓
Monitor TP/SL
 ↓
Exit
 ↓
Confirm position closed
 ↓
Calculate P&L
 ↓
Record trade
 ↓
STOP
```

Explain every step.

---

# 51. FAILURE SCENARIOS

Document what happens if:

1. Dhan API is unavailable.
2. Internet disconnects.
3. Entry order is rejected.
4. Entry order is partially filled.
5. Exit order fails.
6. Bot restarts with an open position.
7. TP is reached.
8. SL is reached.
9. Force-exit time is reached.
10. `stop.py` is executed.
11. Configuration is invalid.
12. Authentication fails.
13. Market data is unavailable.
14. The same breakout is observed repeatedly.
15. Broker position differs from local state.

The documentation should describe the safety behavior.

---

# 52. CODE QUALITY

Write production-quality but understandable Python.

Use:

* type hints
* docstrings
* meaningful names
* small focused functions
* defensive error handling
* logging
* configuration-driven behavior

Avoid:

* unnecessary classes
* excessive abstraction
* deeply nested logic
* global mutable state where avoidable
* duplicated broker API code
* magic numbers
* hard-coded credentials

A trader who understands Python should be able to follow the code.

---

# 53. EDUCATIONAL CODE STYLE

Although this is a production-oriented trading bot, write the implementation so that the code and explanations are clear enough to be studied line-by-line.

Use comments around important areas such as:

```text
ORB construction
breakout detection
entry validation
risk checks
TP/SL calculation
order confirmation
position reconciliation
force exit
shutdown
```

Comments must add useful context.

Do not fill the code with obvious comments like:

```python
# Add 1 to x
x += 1
```

Instead explain trading/business logic.

---

# 54. SECURITY

Never:

* hard-code Dhan credentials
* print API tokens
* commit secrets
* expose `.env` contents in logs
* store credentials in architecture.md

The `.env` file should contain placeholders only if generated as a template.

---

# 55. LIVE VS PAPER MODE

The bot must clearly display:

```text
PAPER / DRY RUN
```

or:

```text
LIVE
```

in the CLI.

Before live trading, make sure the configuration explicitly requires:

```yaml
dry_run: false
```

Do not silently default to live trading.

The safer default is:

```yaml
dry_run: true
```

---

# 56. STARTUP CHECKLIST

When starting, print a concise startup checklist:

```text
[OK] Configuration loaded
[OK] Environment loaded
[OK] Dhan client initialized
[OK] Symbol validated
[OK] Trading session configured
[OK] Risk controls loaded
[OK] Dry-run mode enabled
[OK] ORB strategy ready
```

If something fails:

```text
[FAIL] ...
```

and do not trade.

---

# 57. TESTABILITY

Structure functions so that pure calculations can be tested independently.

For example:

```python
calculate_breakout_levels()
calculate_stop_loss()
calculate_take_profit()
calculate_pnl()
```

should not require a live Dhan connection.

Do not create a separate test file because the requested project structure is fixed.

---

# 58. IMPORTANT BROKER SAFETY RULE

Never assume:

```text
order submitted = order filled
```

Always distinguish:

```text
SUBMITTED
OPEN
PARTIALLY_FILLED
FILLED
REJECTED
CANCELLED
UNKNOWN
```

Do not calculate final P&L using an assumed fill price when actual fill information is available.

---

# 59. SHUTDOWN BEHAVIOR

Implement graceful shutdown for:

* Ctrl+C
* stop.py
* TP
* SL
* force exit
* critical errors

On shutdown:

```text
Stop new entries
↓
Handle configured open-position policy
↓
Cancel/avoid duplicate pending orders where appropriate
↓
Print final status
↓
Close resources
↓
Exit
```

Do not terminate abruptly unless absolutely necessary.

---

# 60. FINAL VALIDATION

Before considering the implementation complete, verify:

* All required files exist.
* No additional Python files are required.
* `docs/project_requirements.md` is not required at runtime.
* `docs/Dhan_SRP.py` is not required at runtime.
* `.env` contains secrets only.
* `config.yaml` contains all configurable parameters.
* `stop.py` works.
* `requirements.txt` contains required dependencies.
* `architecture.md` matches the actual implementation.
* Dry-run mode cannot accidentally submit real orders.
* Duplicate entries are prevented.
* TP exits the position and stops the bot.
* SL exits the position and stops the bot.
* Day-trading mode force exits at configured time.
* Day-trading mode can be disabled.
* Manual stop works.
* Restart with an existing position is handled safely.
* API failures are handled.
* CLI displays live position P&L.
* Polling interval is configurable.
* Application can run on a 1 GB AWS Linux VM.
* No credentials are logged.
* No hidden dependency on documentation files exists.

---

# 61. README-LIKE STARTUP INFORMATION

Do not create a README file.

Instead, make `architecture.md` include:

```text
Installation
Configuration
Environment variables
Dry-run usage
Live trading usage
Stopping the bot
AWS Linux execution
Troubleshooting
```

Include commands such as:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

and:

```bash
python stop.py
```

Only include commands that are compatible with the final implementation.

---

# 62. FINAL OUTPUT EXPECTATION

Create the complete contents of:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

Do not leave:

```text
TODO
FIXME
implement later
pseudo-code
```

in critical trading functionality.

Where the exact Dhan API method depends on the available SDK/reference implementation, inspect:

```text
docs/Dhan_SRP.py
```

and implement the correct working integration rather than inventing API methods.

The final code should be directly usable after:

1. Installing dependencies.
2. Setting Dhan credentials in `.env`.
3. Configuring the instrument and strategy in `config.yaml`.
4. Running `python main.py`.

Make the code practical, robust, readable, and well explained. Write the implementation and its explanations in a way that the code, comments, architecture, examples, and function descriptions remain useful as clear educational technical material for explaining the system step-by-step, while keeping the actual application focused on reliable Dhan ORB trading.
