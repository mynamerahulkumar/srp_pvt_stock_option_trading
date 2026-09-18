Create a production-ready **Bollinger Band Mean-Reversion Algo for the Dhan trading API**, designed to run locally and on a lightweight **AWS Linux VM with 1 GB RAM**.

## 1. Objective

Build a complete, robust, configurable trading bot implementing a **Bollinger Band Mean-Reversion strategy**.

The final project must contain **only these files**:

```text
main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md
```

Do **not** create additional Python modules, packages, databases, JSON files, log configuration files, Docker files, or unnecessary project files.

The entire application logic must be contained in `main.py`.

Two reference files may exist temporarily:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

You may inspect and use them as references for Dhan API implementation patterns, authentication, instrument handling, order placement, position handling, WebSocket/API usage, error handling, etc.

**Do not depend on these files at runtime.** The final application must work after the `docs/` directory and those reference files are deleted.

---

# 2. Required Strategy

Implement a **Bollinger Band Mean-Reversion Algo**.

The strategy should be designed primarily for liquid Indian stocks, while the architecture should be flexible enough to support other Dhan-supported instruments later.

Use configurable Bollinger Band parameters:

```yaml
strategy:
  timeframe: "5m"
  bollinger_period: 20
  bollinger_stddev: 2.0
```

Calculate:

* Middle Band = SMA(period)
* Upper Band = Middle Band + stddev × Standard Deviation
* Lower Band = Middle Band - stddev × Standard Deviation

The core mean-reversion concept:

### Long entry

Consider a long trade when price moves to or below the lower Bollinger Band and the configured confirmation conditions are satisfied.

Example configurable conditions:

```text
price <= lower_band
```

Optionally support confirmation such as:

```text
close_back_inside_band
```

where price first touches/breaks the lower band and subsequently closes back inside the Bollinger Bands.

### Short entry

Consider a short trade when price moves to or above the upper Bollinger Band and the configured confirmation conditions are satisfied.

Example:

```text
price >= upper_band
```

Optionally support:

```text
close_back_inside_band
```

### Mean-reversion exit

The default strategy should target the middle Bollinger Band as the strategy's natural mean-reversion target.

However, TP/SL must remain configurable.

The code should clearly separate:

1. Entry signal
2. Position sizing
3. Order placement
4. Stop-loss management
5. Take-profit management
6. Strategy exit
7. Time-based exit
8. Emergency exit

---

# 3. Important Trading Safety Requirements

This is a **real trading application**, so implement strong safeguards.

The bot must:

* Never place duplicate orders because of repeated polling.
* Detect existing open positions before entering.
* Maintain a clear internal position state.
* Reconcile internal state with Dhan positions after restart.
* Never assume an order was filled simply because an order request was accepted.
* Verify order status/fill before treating a position as active.
* Handle rejected orders.
* Handle partially filled orders where supported.
* Handle API failures gracefully.
* Retry transient API failures with bounded retries and backoff.
* Avoid uncontrolled order loops.
* Have a configurable maximum number of trades per day.
* Have a configurable maximum daily loss.
* Have a configurable maximum open position count.
* Have an optional cooldown after an exit.
* Prevent new trades after the daily loss limit is reached.
* Support a global kill switch.
* Support graceful shutdown.
* Cancel/manage outstanding orders safely when stopping.
* Never expose API secrets in logs.

Use defensive programming throughout.

---

# 4. Day-Trading Mode

Implement:

```yaml
trading:
  intraday_mode: true
```

When:

```yaml
intraday_mode: true
```

the bot operates as a day-trading system.

Configure:

```yaml
trading:
  start_time: "09:20"
  stop_entry_time: "15:00"
  square_off_time: "15:15"
```

Behavior:

* Do not enter trades before `start_time`.
* Stop taking new entries at `stop_entry_time`.
* At `square_off_time`, close all open positions.
* After square-off, do not initiate new trades.
* Stop the bot after all positions are closed.
* Make all times configurable.
* Use India market timezone explicitly rather than relying on the Linux VM's system timezone.

If:

```yaml
trading:
  intraday_mode: false
```

then there should be **no mandatory time-based entry/exit restriction**.

The bot can continue operating without the intraday schedule, subject to the strategy and risk controls.

---

# 5. TP/SL

Implement configurable take-profit and stop-loss.

Example:

```yaml
risk:
  take_profit:
    enabled: true
    type: "percent"
    value: 1.0

  stop_loss:
    enabled: true
    type: "percent"
    value: 0.5
```

Support at least:

```text
percent
points
```

The implementation should make it straightforward to add other TP/SL methods later.

For a long position:

```text
SL = entry_price - configured risk
TP = entry_price + configured reward
```

For a short position:

```text
SL = entry_price + configured risk
TP = entry_price - configured reward
```

When TP or SL is reached:

1. Exit the position.
2. Verify the exit order.
3. Verify the position is closed.
4. Calculate/display realized P&L.
5. **Stop the bot completely**, as requested.

Do not allow the bot to immediately re-enter after TP/SL.

---

# 6. Strategy Exit

Support configurable mean-reversion exit.

For example:

```yaml
strategy:
  exit:
    mode: "middle_band"
```

Possible modes:

```text
middle_band
fixed_tp
middle_band_or_tp
```

The implementation should be clean enough that additional exit methods can be added later.

For the default `middle_band` mode:

* Long entered near/below lower band → exit around middle band.
* Short entered near/above upper band → exit around middle band.

The configured TP/SL must always remain available as protective controls.

If TP or SL occurs first, exit immediately and stop the bot.

---

# 7. Position Sizing

Everything must be configurable.

Support:

```yaml
position_sizing:
  mode: "fixed_quantity"
  quantity: 1
```

Also design the code so that later the following modes can be added easily:

```text
fixed_quantity
capital_percent
risk_based
```

For this implementation, `fixed_quantity` is sufficient unless the reference project already provides a reliable implementation of other sizing methods.

Validate quantity before placing an order.

---

# 8. Instrument Configuration

Everything related to the traded instrument must be configurable in YAML.

For example:

```yaml
instrument:
  exchange_segment: "NSE_EQ"
  security_id: "..."
  symbol: "RELIANCE"
  product_type: "INTRADAY"
```

Do not hard-code a particular stock.

The user must be able to change the instrument entirely through `config.yaml`.

Support configurable:

* exchange segment
* security ID
* trading symbol
* product type
* order type
* transaction type
* quantity
* price settings where relevant

Validate all required instrument fields before starting.

---

# 9. Dhan API Integration

Use the official/relevant Dhan API implementation patterns available in the supplied reference files.

Read:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

for guidance, but do not copy obsolete or unsafe implementation blindly.

Use the current Dhan-compatible API patterns where possible.

Credentials must come from `.env`.

Example:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Never put secrets in `config.yaml`.

Never print tokens.

Never commit credentials.

Add `.env` loading through an appropriate lightweight dependency.

---

# 10. Data Handling

The bot must fetch market data every configurable number of seconds.

Default:

```yaml
runtime:
  polling_seconds: 5
```

The user specifically wants the system to:

> fetch data every 5 seconds and evaluate whether to trade.

Therefore:

* Poll every `polling_seconds`.
* Do not hard-code 5 seconds.
* Read the value from YAML.
* Avoid excessive API calls.
* Use the minimum data required to calculate the strategy.
* Cache data where appropriate.
* Avoid downloading unnecessarily large historical datasets on every loop.
* Fetch enough historical candles to calculate the configured Bollinger period.
* Update the latest candle appropriately.
* Avoid look-ahead bias.
* Do not use future candle information.

If the Dhan API supports appropriate historical/intraday endpoints, use them correctly.

Clearly distinguish:

```text
historical candle data
latest market data
current position
order status
```

---

# 11. Polling and Duplicate Signal Protection

The polling loop must be robust.

Every cycle:

1. Check whether the bot is stopping.
2. Check trading schedule.
3. Check risk limits.
4. Fetch/update market data.
5. Calculate Bollinger Bands.
6. Determine current position from Dhan.
7. Manage an existing position.
8. If no position exists, evaluate entry.
9. Place an order only if all safety checks pass.
10. Verify order status.
11. Update state.
12. Display status.
13. Sleep for `polling_seconds`.

Do not place the same trade repeatedly during multiple polling cycles.

Use mechanisms such as:

* signal timestamp
* candle timestamp
* current position verification
* pending-order verification
* last processed signal
* order status checks

The strategy should normally evaluate entries using a **completed candle**, not repeatedly trigger from the same candle.

Make this configurable:

```yaml
strategy:
  signal_on_closed_candle: true
```

---

# 12. Current Position P&L

The CLI must show the user's current trading state.

At minimum display:

```text
Current Symbol
Position
Quantity
Average Entry Price
Current Price
Unrealized P&L
Realized P&L
Stop Loss
Take Profit
Bollinger Upper
Bollinger Middle
Bollinger Lower
Current Signal
Bot Status
Next Poll
```

If no position exists, clearly display:

```text
POSITION: FLAT
```

If a position exists:

```text
POSITION: LONG
QTY: 100
ENTRY: 2500.00
LTP: 2512.50
UNREALIZED P&L: +₹1,250
SL: 2487.50
TP: 2525.00
```

Use actual Dhan position data whenever available.

Do not rely solely on locally calculated P&L.

---

# 13. Sci-Fi CLI

Create an attractive **sci-fi trading terminal CLI**.

It should feel like an AI/quant trading command center while remaining lightweight and readable over SSH.

Example conceptual layout:

```text
╔══════════════════════════════════════════════════════════════╗
║        ██████╗ ██████╗ ███████╗ █████╗ ███╗   ██╗          ║
║       BB MEAN-REVERSION // DHAN QUANT TERMINAL             ║
╠══════════════════════════════════════════════════════════════╣
║ SYSTEM      : ONLINE                                        ║
║ STRATEGY    : BOLLINGER MEAN REVERSION                     ║
║ MARKET      : NSE                                           ║
║ SYMBOL      : RELIANCE                                      ║
║ MODE        : INTRADAY                                      ║
╠══════════════════════════════════════════════════════════════╣
║ POSITION    : LONG                                          ║
║ QTY         : 100                                           ║
║ ENTRY       : ₹2500.00                                      ║
║ LTP         : ₹2512.50                                      ║
║ P&L         : ₹+1250.00                                     ║
║ SL          : ₹2487.50                                      ║
║ TP          : ₹2525.00                                      ║
╠══════════════════════════════════════════════════════════════╣
║ BB UPPER    : 2530.20                                       ║
║ BB MIDDLE   : 2505.10                                       ║
║ BB LOWER    : 2480.00                                       ║
║ SIGNAL      : HOLD / LONG / SHORT / EXIT                   ║
╠══════════════════════════════════════════════════════════════╣
║ NEXT SCAN  : 5 SEC                                          ║
║ ENGINE     : ACTIVE                                         ║
╚══════════════════════════════════════════════════════════════╝
```

The actual design can be improved.

Use a lightweight CLI library only if necessary.

The interface should work correctly through:

```text
SSH
AWS Linux terminal
local macOS/Linux terminal
```

Avoid unnecessarily heavy GUI frameworks.

---

# 14. Logging

Implement useful structured console logging.

Examples:

```text
[INFO] Bot started
[INFO] Market session active
[DATA] Candle updated
[STRATEGY] BB Lower touched
[SIGNAL] LONG ENTRY
[ORDER] BUY order submitted
[ORDER] BUY order filled
[RISK] Stop loss calculated
[POSITION] LONG 100 @ 2500
[EXIT] Middle band reached
[ORDER] SELL order submitted
[EXIT] Position closed
[P&L] Realized P&L: ₹+520
[SYSTEM] Bot stopped
```

Never log:

* access tokens
* API credentials
* sensitive environment variables

---

# 15. Configurable YAML

Create a comprehensive `config.yaml`.

All reasonable trading parameters should be configurable.

Include sections similar to:

```yaml
bot:
  name: "BB Mean Reversion"
  environment: "paper"
  enabled: true

instrument:
  exchange_segment: "NSE_EQ"
  security_id: ""
  symbol: ""
  product_type: "INTRADAY"

strategy:
  timeframe: "5m"
  bollinger_period: 20
  bollinger_stddev: 2.0
  entry_mode: "touch"
  signal_on_closed_candle: true

  exit:
    mode: "middle_band"

trading:
  intraday_mode: true
  start_time: "09:20"
  stop_entry_time: "15:00"
  square_off_time: "15:15"

position_sizing:
  mode: "fixed_quantity"
  quantity: 1

risk:
  take_profit:
    enabled: true
    type: "percent"
    value: 1.0

  stop_loss:
    enabled: true
    type: "percent"
    value: 0.5

  max_trades_per_day: 3
  max_daily_loss: 2000
  max_open_positions: 1
  cooldown_seconds: 300

runtime:
  polling_seconds: 5
  order_status_poll_seconds: 2
  api_retry_attempts: 3
  api_retry_delay_seconds: 1

safety:
  require_confirmation: false
  dry_run: true
  kill_switch: false
  close_positions_on_shutdown: false
```

Improve this structure wherever necessary.

**Do not hard-code configuration values inside strategy functions if they belong in YAML.**

Validate configuration at startup.

Fail clearly with a useful error message when mandatory configuration is missing or invalid.

---

# 16. Dry Run / Safety Mode

Implement:

```yaml
safety:
  dry_run: true
```

When `dry_run: true`:

* Do not submit real orders.
* Calculate signals.
* Calculate theoretical entry/exit.
* Display what the bot WOULD do.
* Show simulated position/P&L where practical.
* Clearly display:

```text
MODE: DRY RUN
```

When:

```yaml
dry_run: false
```

real Dhan orders may be submitted.

Do not silently switch from dry run to live mode.

---

# 17. Start/Stop Controls

Implement a clean startup process.

On startup:

1. Load `.env`.
2. Load `config.yaml`.
3. Validate configuration.
4. Initialize Dhan API.
5. Verify connectivity.
6. Fetch current positions.
7. Fetch current orders.
8. Reconcile state.
9. Display account/trading status.
10. Start strategy loop.

Implement `stop.py`.

`stop.py` must provide a simple mechanism to signal `main.py` to stop gracefully.

The implementation must work on a lightweight Linux VM.

Possible mechanism:

* PID/signal-based shutdown
* lightweight stop-file mechanism
* OS signal handling

Choose a robust approach.

The stop mechanism should cause the main bot to:

1. Stop taking new trades.
2. Optionally close all positions if configured.
3. Cancel/manage pending orders if configured.
4. Verify positions.
5. Display final P&L/status.
6. Exit cleanly.

Do not kill the process abruptly unless explicitly required.

---

# 18. Close-All-On-Stop

Support:

```yaml
safety:
  close_positions_on_shutdown: false
```

If enabled and the bot is stopped:

```text
STOP REQUESTED
→ STOP NEW ENTRIES
→ CLOSE ALL OPEN POSITIONS
→ VERIFY POSITIONS CLOSED
→ BOT OFFLINE
```

If disabled:

```text
STOP REQUESTED
→ STOP NEW ENTRIES
→ LEAVE POSITIONS UNCHANGED
→ BOT OFFLINE
```

Make this behavior very clear in the CLI.

---

# 19. Intraday Square-Off

If:

```yaml
trading:
  intraday_mode: true
```

then at:

```yaml
square_off_time
```

the bot must:

* stop new entries
* close all open strategy positions
* verify closure
* calculate/display realized P&L
* stop the bot

If no position exists, simply stop after the configured square-off time.

---

# 20. Risk Management

Implement at minimum:

### Maximum daily loss

If:

```yaml
max_daily_loss: 2000
```

and realized + relevant trading losses reach the configured limit:

```text
RISK LIMIT REACHED
NEW TRADES DISABLED
```

Optionally close an existing position depending on configuration.

### Maximum trades per day

Do not exceed:

```yaml
max_trades_per_day
```

### Maximum open positions

Prevent additional positions beyond:

```yaml
max_open_positions
```

### Cooldown

After a trade closes, optionally wait:

```yaml
cooldown_seconds
```

before another entry.

### Duplicate order protection

Never submit duplicate entries because the same signal remains true.

---

# 21. State Management

Do not introduce a database unless absolutely necessary.

Use in-memory state plus reconciliation with Dhan.

The program should safely handle restarting the bot.

At startup:

```text
Dhan Position
      ↓
Read current position
      ↓
Reconcile local strategy state
      ↓
Determine whether bot should manage existing position
      ↓
Continue safely
```

Do not blindly open a new trade because local memory was lost after a restart.

---

# 22. Functions in `main.py`

Organize `main.py` into clear functions.

At minimum, create functions conceptually similar to:

```python
load_environment()
load_config()
validate_config()
setup_logging()
create_dhan_client()
check_api_connection()
get_market_data()
get_historical_candles()
calculate_bollinger_bands()
generate_signal()
get_current_position()
get_open_orders()
calculate_position_size()
calculate_stop_loss()
calculate_take_profit()
check_risk_limits()
check_trading_window()
check_entry_conditions()
place_entry_order()
place_exit_order()
get_order_status()
wait_for_order_fill()
calculate_unrealized_pnl()
calculate_realized_pnl()
manage_open_position()
check_take_profit()
check_stop_loss()
check_strategy_exit()
square_off_all_positions()
reconcile_position_state()
handle_shutdown()
display_terminal_dashboard()
process_trading_cycle()
main()
```

You may add other functions when needed.

Do not put everything into `main()`.

Each function must have a clear single responsibility.

---

# 23. Function Documentation

Every important function in `main.py` must have useful comments/docstrings explaining:

1. What the function does.
2. Why it exists.
3. What inputs it expects.
4. What it returns.
5. Important trading/safety considerations.
6. A short practical example/use case where useful.

For example:

```python
def calculate_bollinger_bands(df, period, stddev):
    """
    Calculate the Bollinger Bands used by the mean-reversion strategy.

    Middle Band:
        SMA(period)

    Upper Band:
        Middle + stddev * standard_deviation

    Lower Band:
        Middle - stddev * standard_deviation

    Use case:
        The strategy uses the lower band to identify potentially
        oversold conditions and the upper band to identify potentially
        overbought conditions.

    Important:
        Signals should use completed candles when
        signal_on_closed_candle is enabled.
    """
```

Use comments to explain **why**, not merely restate the code.

Keep comments educational and technically accurate.

---

# 24. `architecture.md`

Create a comprehensive `architecture.md`.

It should explain the entire system as a structured technical chapter.

Use sections such as:

```markdown
# Bollinger Band Mean-Reversion Algo

## 1. Strategy Overview

## 2. What Are Bollinger Bands?

## 3. Mathematical Formula

## 4. How Mean Reversion Works

## 5. Long Entry Logic

## 6. Short Entry Logic

## 7. Exit Logic

## 8. Take Profit

## 9. Stop Loss

## 10. Position Sizing

## 11. Risk Management

## 12. Intraday Mode

## 13. System Architecture

## 14. Dhan API Flow

## 15. Main.py Function Architecture

## 16. Complete Trading Cycle

## 17. Order Lifecycle

## 18. Startup Sequence

## 19. Shutdown Sequence

## 20. Square-Off Sequence

## 21. Error Handling

## 22. Duplicate Order Protection

## 23. Restart Recovery

## 24. Dry Run Mode

## 25. CLI Dashboard

## 26. Example Trade

## 27. Example Profit Calculation

## 28. Example Loss Calculation

## 29. Parameter Tuning

## 30. Backtesting Considerations

## 31. Common Failure Modes

## 32. Practical Improvements

## 33. Production Deployment

## 34. AWS 1GB VM Deployment

## 35. Testing Checklist
```

The explanation should be sufficiently detailed to teach the strategy step by step.

---

# 25. Example Trade in `architecture.md`

Include a realistic example.

For example:

```text
Stock: Example Stock
Timeframe: 5 minutes
Bollinger Period: 20
Standard Deviation: 2

Middle Band: ₹1,000
Upper Band: ₹1,030
Lower Band: ₹970

Price falls to ₹968.

The lower-band entry condition is satisfied.

Bot:
→ verifies no existing position
→ verifies risk limits
→ calculates quantity
→ calculates SL
→ calculates TP
→ submits BUY order
→ waits for fill
→ confirms position
```

Then explain what happens if price returns toward the middle band.

Example:

```text
Entry = ₹968
Exit = ₹1,000
Quantity = 100

Gross P&L:
₹32 × 100 = ₹3,200
```

Also explain a losing example.

For example:

```text
Entry = ₹968
SL = ₹963
Quantity = 100

Gross loss:
₹5 × 100 = ₹500
```

Clearly state that actual realized P&L will differ after:

* brokerage
* STT
* exchange charges
* GST
* SEBI charges
* stamp duty
* slippage
* taxes/other applicable costs

Do not promise profitability.

---

# 26. Parameter Tuning Section

In `architecture.md`, explain how traders can experiment with:

```text
Bollinger period
Standard deviation
timeframe
entry mode
closed-candle confirmation
stop loss
take profit
middle-band exit
position size
maximum trades/day
daily loss limit
cooldown
```

Explain the trade-offs.

For example:

### Smaller Bollinger period

Potentially:

* more responsive
* more signals
* more noise
* potentially more false signals

### Larger Bollinger period

Potentially:

* smoother bands
* fewer signals
* slower adaptation

### Lower standard deviation

Potentially:

* bands are closer
* more touches
* more signals
* potentially more noise

### Higher standard deviation

Potentially:

* fewer extreme signals
* fewer trades
* potentially stronger extremes

Explain that parameter optimization should use:

* out-of-sample testing
* walk-forward testing
* transaction costs
* slippage
* different market regimes

Do not write the documentation as if tuning guarantees profit.

---

# 27. Profitability Guidance

In `architecture.md`, provide practical guidance on improving strategy quality, but **never guarantee profits**.

Explain that a trader should evaluate:

* expectancy
* win rate
* average win
* average loss
* profit factor
* maximum drawdown
* Sharpe/Sortino where appropriate
* number of trades
* transaction costs
* slippage
* market regime sensitivity

Explain why simply increasing TP or decreasing SL is not automatically an improvement.

Provide sensible ideas such as:

* avoid illiquid stocks
* use appropriate timeframes
* avoid trading around abnormal events unless specifically designed for them
* test different volatility regimes
* use volume/liquidity filters
* use trend filters if mean reversion performs poorly during strong trends
* limit trades after repeated failed reversions
* evaluate session-specific behavior
* test costs and slippage
* use walk-forward validation

Make it clear that mean-reversion strategies can perform poorly during strong directional trends.

---

# 28. Backtesting / Look-Ahead Bias

Explain in `architecture.md` that the live strategy should not use future information.

Explain:

```text
Candle N
↓
Calculate indicators using information available at Candle N
↓
Generate signal
↓
Execute at realistic next available price
```

Avoid:

```text
Using Candle N's final information
and assuming execution at Candle N's opening/high/low
```

unless the execution model legitimately supports it.

Explain slippage and order execution assumptions.

---

# 29. AWS 1GB RAM Compatibility

Keep the application lightweight.

It must comfortably run on:

```text
AWS Linux
1 GB RAM
```

Avoid:

* large ML frameworks
* unnecessary data science packages
* large databases
* heavyweight GUI frameworks
* unnecessary background services

Use lightweight dependencies.

The bot should run using:

```bash
python3 main.py
```

and:

```bash
python3 stop.py
```

It should also work inside a virtual environment.

---

# 30. Requirements

Create `requirements.txt` containing only necessary dependencies.

Potential dependencies may include:

```text
requests
pandas
numpy
PyYAML
python-dotenv
```

Use Dhan's official SDK if the reference implementation/current API requires it.

Do not add libraries merely for convenience.

Pin versions only when there is a strong compatibility reason.

---

# 31. `.env`

Create a template `.env`:

```env
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
```

Do not put actual credentials in it.

If other credentials are genuinely required by the implementation, include them as placeholders.

---

# 32. Error Handling

Implement graceful handling for:

* invalid YAML
* missing environment variables
* invalid security ID
* invalid quantity
* API timeout
* API connection failure
* malformed API response
* order rejection
* partial fills
* insufficient funds
* market closed
* stale data
* unexpected position
* unexpected open order
* keyboard interrupt
* shutdown request

The bot should not crash on a recoverable API error.

Use bounded retry logic.

If a critical safety condition occurs, stop trading rather than continuing blindly.

---

# 33. Testing

Before considering the implementation complete, reason through and test these scenarios:

### Scenario 1

No position + no signal.

Expected:

```text
No order.
```

### Scenario 2

Lower Bollinger Band signal.

Expected:

```text
BUY signal → risk checks → order → fill verification → position management
```

### Scenario 3

Upper Bollinger Band signal.

Expected:

```text
SHORT signal → risk checks → order → fill verification
```

### Scenario 4

Existing position.

Expected:

```text
Do not open another position.
Manage existing position.
```

### Scenario 5

TP reached.

Expected:

```text
Exit → verify closed → calculate P&L → stop bot.
```

### Scenario 6

SL reached.

Expected:

```text
Exit → verify closed → calculate P&L → stop bot.
```

### Scenario 7

Square-off time reached.

Expected:

```text
Close positions → verify → stop bot.
```

### Scenario 8

Manual stop requested.

Expected behavior must follow:

```yaml
close_positions_on_shutdown
```

### Scenario 9

Daily loss limit reached.

Expected:

```text
No new trades.
```

### Scenario 10

Bot restarts with an existing Dhan position.

Expected:

```text
Reconcile position → manage existing position safely.
```

### Scenario 11

API temporarily unavailable.

Expected:

```text
Retry with bounded backoff.
Do not submit duplicate orders.
```

### Scenario 12

Order rejected.

Expected:

```text
Mark trade as unsuccessful.
Do not assume position exists.
Continue safely or stop if configured as critical.
```

---

# 34. Code Quality

Write clean, readable Python.

Use:

* type hints where useful
* clear function names
* constants where appropriate
* structured configuration
* meaningful exceptions
* clear logging
* defensive validation

Do not over-engineer the project.

The goal is a compact but production-oriented algo suitable for a small AWS machine.

Do not put strategy parameters directly into random functions.

Do not scatter magic numbers throughout the code.

---

# 35. Important Architecture Principle

Keep these layers conceptually separated inside `main.py`:

```text
CONFIGURATION
      ↓
Dhan API
      ↓
MARKET DATA
      ↓
INDICATOR CALCULATION
      ↓
SIGNAL ENGINE
      ↓
RISK ENGINE
      ↓
ORDER ENGINE
      ↓
POSITION MANAGEMENT
      ↓
EXIT ENGINE
      ↓
CLI / MONITORING
```

Even though all code is in `main.py`, preserve this logical separation using functions and clearly marked sections.

---

# 36. Final Project Structure

The final result must be exactly:

```text
project/
├── main.py
├── config.yaml
├── .env
├── stop.py
├── requirements.txt
└── architecture.md
```

Do not require:

```text
docs/project_requirements.md
docs/Dhan_SRP.py
```

after implementation.

The application must run independently.

---

# 37. Final Validation

Before finishing, review the entire implementation for:

* syntax errors
* missing imports
* invalid configuration keys
* incorrect API parameters
* duplicate order possibilities
* position reconciliation problems
* TP/SL logic
* short-position calculations
* intraday timing
* timezone handling
* graceful shutdown
* stop.py communication
* dry-run behavior
* API retry behavior
* CLI failures
* restart behavior
* AWS compatibility

Make sure all functions called by `main.py` actually exist.

Make sure all configuration keys used by the code exist in `config.yaml`.

Make sure no secret is hard-coded.

Make sure the project can be started with:

```bash
python3 main.py
```

and stopped with:

```bash
python3 stop.py
```

---

# 38. Educational Code Style

Write `main.py` with exceptionally clear organization and explanations.

Use section headers such as:

```python
# ============================================================
# CONFIGURATION
# ============================================================

# ============================================================
# DHAN API
# ============================================================

# ============================================================
# MARKET DATA
# ============================================================

# ============================================================
# BOLLINGER BAND CALCULATION
# ============================================================

# ============================================================
# SIGNAL ENGINE
# ============================================================

# ============================================================
# RISK MANAGEMENT
# ============================================================

# ============================================================
# ORDER MANAGEMENT
# ============================================================

# ============================================================
# POSITION MANAGEMENT
# ============================================================

# ============================================================
# CLI DASHBOARD
# ============================================================

# ============================================================
# MAIN TRADING LOOP
# ============================================================
```

The code should be understandable by someone learning algorithmic trading and Python.

At the end, ensure the implementation and its explanations are written clearly enough that the code, comments, function explanations, architecture, formulas, examples, execution flow, and parameter-tuning discussion can be reused as high-quality educational technical material, while remaining technically accurate and avoiding any claim that the strategy guarantees profits.
