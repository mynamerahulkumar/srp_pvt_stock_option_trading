```text
You are an expert Python algorithmic-trading engineer specializing in the Dhan trading API, robust automated execution, risk management, and production-quality trading systems.

Build a complete, production-ready **EMA Crossover Algo for Dhan**.

The project must be simple enough to run locally on a developer machine and on a small **AWS Linux VM with 1 GB RAM**, while keeping the architecture clean, reliable, configurable, and easy to understand.

IMPORTANT PROJECT STRUCTURE
============================

The final project must contain ONLY these files at the project root:

1. main.py
2. config.yaml
3. .env
4. stop.py
5. requirements.txt
6. architecture.md

There must be NO requirement for any other Python/source/configuration file.

The following files may exist initially and may be used ONLY as reference while developing:

- docs/project_requirements.md
- docs/Dhan_SRP.py

Assume those reference files may be deleted later. Therefore:

- Do not import them.
- Do not depend on them at runtime.
- Do not require them to start the application.
- Extract only useful Dhan API patterns from them.
- The final application must work independently using only the six files listed above.

Do not create additional modules, packages, helper files, JSON databases, SQLite databases, log configuration files, Docker files, systemd files, or documentation files.

==================================================
1. CORE STRATEGY — EMA CROSSOVER
==================================================

Implement a configurable EMA Crossover trading strategy.

Default concept:

- Fast EMA crosses above Slow EMA → LONG/BUY signal.
- Fast EMA crosses below Slow EMA → SHORT/SELL signal, if short trading is enabled.
- If only long trading is enabled:
  - Bullish crossover → BUY.
  - Bearish crossover → EXIT existing long position.
- If short trading is enabled:
  - Bullish crossover → BUY/close short and optionally enter long according to configuration.
  - Bearish crossover → SELL/short and optionally close long according to configuration.

The strategy must detect an actual crossover rather than simply checking:

fast_ema > slow_ema

For a bullish crossover, use logic equivalent to:

previous_fast <= previous_slow
AND
current_fast > current_slow

For a bearish crossover:

previous_fast >= previous_slow
AND
current_fast < current_slow

Make all important strategy parameters configurable in config.yaml.

At minimum:

- symbol
- exchange segment
- security ID
- instrument type
- quantity
- fast EMA period
- slow EMA period
- timeframe
- polling interval
- product type
- transaction type
- enable_long
- enable_short
- reverse_on_signal
- allow_reentry
- TP
- SL
- TP/SL mode
- trading start time
- trading end time
- enable_trading_window
- close_all_positions_at_end
- max trades per day
- cooldown after trade
- order type
- price settings if required
- dry_run/paper trading mode
- logging level

Do NOT hard-code these values in main.py.

==================================================
2. DHAN API
==================================================

Use the official/current Dhan API/Python SDK patterns available from the reference files where appropriate.

Before writing code:

1. Inspect docs/project_requirements.md.
2. Inspect docs/Dhan_SRP.py.
3. Understand how authentication, market data, orders, positions, and order status are handled.
4. Adapt the useful patterns into the single main.py file.

Do not blindly copy old code.

The implementation should isolate Dhan-specific operations inside clearly named functions/classes in main.py so that the strategy logic remains easy to understand.

Use environment variables from .env for secrets.

At minimum:

DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=

Never place credentials directly inside config.yaml or main.py.

==================================================
3. MAIN.PY ARCHITECTURE
==================================================

All application logic must be inside main.py.

Use a clean, beginner-friendly structure.

Prefer a small class-based architecture if it makes the code clearer, for example:

- ConfigManager
- DhanTradingBot
- EMA strategy functions

But do not over-engineer the application.

The code should clearly separate:

A. Configuration
B. Dhan API connection
C. Market-data retrieval
D. Indicator calculation
E. Signal generation
F. Position detection
G. Order execution
H. TP/SL management
I. Trading-window management
J. Risk controls
K. CLI/status display
L. Main polling loop
M. Graceful shutdown

Every important function must have a clear docstring explaining:

- What the function does
- Why it exists
- Important inputs
- Important outputs
- Any trading/risk implications

Add useful inline comments around the trading logic.

Do not comment every trivial Python line.

==================================================
4. MARKET DATA
==================================================

The bot must fetch the required market data from Dhan.

Polling interval must be configurable through config.yaml.

Example:

polling:
  interval_seconds: 5

Every polling cycle:

1. Fetch current/recent market data.
2. Build/update candles as required.
3. Calculate EMA values.
4. Detect crossover.
5. Check current position.
6. Check TP/SL.
7. Check trading window.
8. Check risk limits.
9. Execute a trade if all conditions are satisfied.
10. Update CLI.

IMPORTANT:

Do not treat every polling cycle as a new signal.

A crossover should only trigger once.

The bot must avoid duplicate orders caused by polling.

Use candle timestamps / signal state / position state appropriately.

If the latest candle is still forming, handle it carefully so that the strategy does not repeatedly enter and exit because of intra-candle EMA fluctuations.

Make the candle-handling approach explicit in architecture.md.

==================================================
5. EMA CALCULATION
==================================================

Implement EMA calculation using pandas where appropriate.

The strategy must calculate:

Fast EMA
Slow EMA

For example:

EMA_FAST = 9
EMA_SLOW = 21

But these are configurable.

Do not hard-code 9 and 21.

The bot must validate:

fast EMA period < slow EMA period

unless deliberately supporting the opposite configuration.

Fail safely with a clear configuration error.

Display current EMA values in the CLI.

==================================================
6. SIGNAL ENGINE
==================================================

Create a dedicated strategy function such as:

generate_signal(...)

It should return a clear signal:

- BUY
- SELL
- EXIT
- HOLD

The strategy must use previous and current EMA values.

Example:

Previous candle:
Fast EMA = 100
Slow EMA = 101

Current candle:
Fast EMA = 102
Slow EMA = 101

Signal = BUY

Another example:

Previous:
Fast EMA = 102
Slow EMA = 101

Current:
Fast EMA = 100
Slow EMA = 101

Signal = SELL

Do not generate BUY simply because fast EMA remains above slow EMA.

Only the crossing event should create the new entry signal.

==================================================
7. POSITION MANAGEMENT
==================================================

The bot must always attempt to determine the actual live position from Dhan rather than relying only on an internal variable.

The CLI must show:

- Symbol
- Current position
- Quantity
- Average entry price
- Current market price
- Unrealized P&L
- P&L percentage if available
- Position side
- Current EMA values
- Current signal
- Bot status
- Trading-window status
- TP
- SL
- Next polling time/countdown if practical
- Last order
- Last error
- Number of trades today

Example CLI:

╔══════════════════════════════════════════════════════════╗
║             ⚡ EMA CROSSOVER TRADING CORE ⚡             ║
╠══════════════════════════════════════════════════════════╣
║ SYSTEM       : ONLINE                                    ║
║ MARKET       : OPEN                                      ║
║ STRATEGY     : EMA 9 / EMA 21                            ║
║ SYMBOL       : RELIANCE                                  ║
║ PRICE        : ₹1,245.50                                 ║
║ FAST EMA     : ₹1,242.80                                 ║
║ SLOW EMA     : ₹1,241.95                                 ║
║ SIGNAL       : 🟢 BULLISH CROSSOVER                      ║
╠══════════════════════════════════════════════════════════╣
║ POSITION     : LONG 25                                   ║
║ ENTRY        : ₹1,238.00                                 ║
║ CURRENT P&L  : ₹187.50                                   ║
║ TP           : ₹1,262.76                                 ║
║ SL           : ₹1,225.62                                 ║
╠══════════════════════════════════════════════════════════╣
║ TRADES TODAY : 2                                         ║
║ NEXT CHECK   : 5 sec                                     ║
║ ENGINE       : RUNNING                                   ║
╚══════════════════════════════════════════════════════════╝

Make the CLI clean, readable, and visually appealing.

Use Unicode/ANSI styling only when supported.

The application must still work correctly when terminal styling is unavailable.

Do not make the CLI consume excessive CPU or memory.

==================================================
8. P&L DISPLAY
==================================================

The user must be able to see current position P&L continuously.

If Dhan provides unrealized P&L directly, use the broker value.

Otherwise calculate approximately:

For LONG:

P&L = (LTP - average_entry_price) × quantity

For SHORT:

P&L = (average_entry_price - LTP) × quantity

Clearly label calculated versus broker-reported values if necessary.

Do not confuse realized P&L with unrealized P&L.

==================================================
9. TAKE PROFIT / STOP LOSS
==================================================

Implement configurable TP/SL.

Support configuration such as:

risk_management:
  take_profit_enabled: true
  stop_loss_enabled: true
  take_profit_percent: 2.0
  stop_loss_percent: 1.0

Make TP/SL configurable.

For LONG:

TP = entry_price × (1 + TP%)

SL = entry_price × (1 - SL%)

For SHORT:

TP = entry_price × (1 - TP%)

SL = entry_price × (1 + SL%)

If configured as price-based instead of percentage-based, support that cleanly.

The implementation should make the TP/SL mode configurable.

Example:

tp_sl:
  mode: percentage

Possible modes:

- percentage
- points
- disabled

Validate configuration.

==================================================
10. IMPORTANT: STOP BOT AFTER TP/SL
==================================================

When TP or SL is reached:

1. Close the active position.
2. Confirm the exit order/result as far as the API allows.
3. Display the reason:
   - TAKE PROFIT
   - STOP LOSS
4. Mark the trading session as stopped.
5. Do not initiate another trade.
6. Exit the bot gracefully.

This is mandatory.

Example:

🚨 TAKE PROFIT HIT
Position closed.
Session P&L: ₹2,450
Reason: TAKE_PROFIT
Bot status: STOPPED

The same applies to STOP LOSS.

The bot must not immediately re-enter after TP/SL.

==================================================
11. TP/SL SAFETY
==================================================

TP/SL monitoring must be performed on every polling cycle.

Do not depend exclusively on receiving another EMA crossover to exit a position when TP/SL is enabled.

Use live market price / broker position data.

Handle cases where:

- API temporarily fails.
- LTP is unavailable.
- Position disappears.
- Order status is delayed.
- Network timeout occurs.

Never close a position based on an invalid/zero price.

Fail safely.

==================================================
12. TRADING WINDOW
==================================================

Make day-trading mode configurable.

Example:

trading_window:
  enabled: true
  start_time: "09:20"
  end_time: "15:15"
  close_all_positions_at_end: true

If enabled:

- Do not enter trades before start_time.
- Allow strategy execution only during the configured window.
- At end_time:
  - stop opening new trades.
  - if close_all_positions_at_end = true, close all bot-managed positions.
  - stop the bot after positions are closed.

If:

enabled: false

then there should be NO time restriction.

The bot can continue operating according to the strategy and other configured controls.

Do not force a day-trading schedule when the feature is disabled.

==================================================
13. CLOSE ALL POSITIONS
==================================================

Implement a safe function:

close_all_positions()

It should:

1. Fetch current positions.
2. Identify open positions.
3. Close the relevant position(s).
4. Verify order submission/result.
5. Handle no-position cases gracefully.

For safety, distinguish between:

- bot-managed position
- existing position that existed before bot startup

Add configuration controlling whether the bot may manage only positions created by itself.

For example:

position_management:
  manage_only_bot_positions: true

Default to the safer behavior.

If the bot cannot reliably identify ownership of a position, do NOT blindly close unrelated positions.

Document this clearly.

==================================================
14. START / STOP CONTROL
==================================================

Support configurable startup and shutdown behavior.

The bot must be stoppable through:

stop.py

stop.py should provide a clean mechanism to request the running bot to stop.

Because the system is designed for a Linux VM, use a simple robust mechanism such as a PID/control file or another lightweight local mechanism.

Do NOT require Redis, PostgreSQL, Docker, or another service.

The stop mechanism must be safe.

When stop.py is executed:

- Request graceful shutdown.
- main.py detects the stop request.
- Stop opening new trades.
- Optionally close positions according to configuration.
- Exit cleanly.

Make this behavior configurable.

Example:

shutdown:
  close_positions_on_manual_stop: false

If true:

- close bot-managed positions before stopping.

If false:

- stop trading but leave positions open.

Clearly display the behavior.

==================================================
15. START TIME
==================================================

Allow optional automatic strategy start time.

Example:

startup:
  wait_for_start_time: true
  start_time: "09:20"

If enabled:

- main.py starts safely.
- It waits until the configured start time.
- It does not trade before that time.

If disabled:

- strategy can begin immediately.

Do not confuse startup time with the trading-window end time.

==================================================
16. ORDER EXECUTION
==================================================

Implement a clean order execution function such as:

place_entry_order(...)
place_exit_order(...)

or equivalent.

Support configuration for:

- market order
- limit order where practical
- quantity
- product type
- exchange segment
- security ID
- transaction type

Use the correct Dhan API parameters.

Never assume an order was filled merely because an order request was submitted.

Where possible:

1. Submit order.
2. Obtain order ID.
3. Check order status.
4. Determine whether it was filled/rejected/pending.
5. Update internal state accordingly.

Handle:

- rejected orders
- insufficient funds
- invalid quantity
- market closed
- rate limits
- API timeout
- authentication failure
- network errors

Do not repeatedly submit duplicate orders after uncertain API responses.

==================================================
17. ORDER IDEMPOTENCY / DUPLICATE PROTECTION
==================================================

This is critical.

The 5-second polling loop must never produce multiple orders from the same crossover.

Implement protection using:

- current position state
- last processed signal/candle timestamp
- order-in-flight state
- cooldown
- broker position confirmation

Before entering a trade:

- verify no conflicting order is already being processed.
- verify the current broker position.
- verify the signal is new.

After submitting an order:

- wait/verify appropriately before allowing another entry.

==================================================
18. REVERSE TRADING
==================================================

Make reversal configurable.

Example:

strategy:
  reverse_on_signal: true

If LONG and bearish crossover occurs:

1. Close long.
2. Confirm exit as far as practical.
3. If reverse_on_signal is enabled:
   - enter SHORT.

If false:

- close existing position.
- do not automatically open the opposite side.

Similarly for SHORT → LONG.

Avoid opening the new position if the closing order failed or the existing position remains unexpectedly open.

==================================================
19. RE-ENTRY
==================================================

Make re-entry configurable.

Example:

strategy:
  allow_reentry: false

Prevent unnecessary repeated entries while the same signal remains active.

A new trade should require a new valid crossover unless the configuration explicitly allows another behavior.

==================================================
20. RISK CONTROLS
==================================================

Implement lightweight but meaningful risk controls.

At minimum:

- max trades per day
- cooldown between trades
- maximum configured quantity
- optional daily loss limit
- optional daily profit target
- optional maximum open positions

Example:

risk:
  max_trades_per_day: 5
  cooldown_seconds: 60
  daily_loss_limit: 0
  daily_profit_target: 0

Interpret 0 as disabled where appropriate.

When a daily loss limit is reached:

- close bot-managed position if configured.
- stop trading.
- stop the bot.

When daily profit target is reached:

- optionally close position.
- stop trading.

Make behavior configurable.

Do not promise profitability.

==================================================
21. DRY RUN / PAPER MODE
==================================================

Provide:

execution:
  dry_run: true

When dry_run = true:

- Do not submit real orders.
- Simulate order execution.
- Display what would have happened.
- Calculate simulated P&L where practical.

When false:

- submit real Dhan orders.

The default should be safe for testing.

Clearly show:

MODE: DRY RUN

or

MODE: LIVE

in the CLI.

==================================================
22. CONFIG.YAML
==================================================

Everything that a trader may reasonably want to tune must be configurable.

Create a complete, well-commented config.yaml.

Organize it into sections such as:

app:
market:
strategy:
polling:
execution:
risk_management:
tp_sl:
trading_window:
startup:
shutdown:
position_management:
logging:
cli:

Use sensible example defaults.

Do not put API credentials in config.yaml.

Use placeholders for:

symbol
security_id

Make the configuration easy for a trader to modify without touching Python.

Validate configuration on startup.

If an invalid value is detected:

- display a clear error.
- do not start trading.

==================================================
23. .ENV
==================================================

Create:

.env

with:

DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=

Include comments explaining that actual credentials must be supplied by the user.

Do not print access tokens in CLI/logs.

Do not commit secrets.

==================================================
24. STOP.PY
==================================================

Create a lightweight stop.py.

Its purpose is to safely request main.py to stop.

It should:

- find the running bot/control state.
- create the stop request.
- display a clear confirmation.
- work on Linux and locally.

It must NOT directly kill the process with SIGKILL.

Prefer graceful shutdown.

If no bot is running, show a friendly message.

==================================================
25. REQUIREMENTS.TXT
==================================================

Create a minimal requirements.txt.

Only include packages genuinely required.

Likely dependencies may include:

- dhanhq
- pandas
- PyYAML
- python-dotenv

But inspect the reference code and use versions/SDK names appropriate for the implementation.

Do not add unnecessary packages.

Keep memory usage low enough for a 1 GB RAM Linux VM.

==================================================
26. ERROR HANDLING
==================================================

The bot must never crash unnecessarily because of temporary API/network errors.

Implement clear handling for:

- API errors
- HTTP errors
- authentication errors
- invalid market data
- empty dataframe
- missing candles
- missing LTP
- order rejection
- order timeout
- malformed configuration
- keyboard interrupt
- stop request
- unexpected exceptions

Use retries where appropriate, but avoid aggressive retry loops.

Respect polling interval.

Do not create a tight infinite loop consuming CPU.

==================================================
27. LOGGING
==================================================

Use Python's built-in logging module.

Do not require an external logging configuration file.

Logs should include:

- startup
- configuration validation
- Dhan connection
- market-data errors
- EMA calculation status where useful
- signal detection
- order submission
- order result
- TP/SL event
- shutdown
- exceptions

Never log:

- access token
- secrets
- sensitive authentication information

Keep logs concise enough for an AWS 1 GB VM.

==================================================
28. CLI / SCI-FI TERMINAL
==================================================

Create a polished sci-fi trading terminal experience using standard Python terminal capabilities.

The CLI should refresh approximately every polling interval.

Show:

- bot state
- LIVE/DRY RUN
- symbol
- price
- EMA fast
- EMA slow
- crossover signal
- position
- quantity
- average entry
- current P&L
- TP
- SL
- trading window
- max trades
- trades today
- last action
- API status
- next polling cycle
- uptime

Use simple ANSI/Unicode symbols where supported.

Do not make the application dependent on advanced terminal libraries unless genuinely necessary.

It must remain readable over SSH on AWS Linux.

==================================================
29. STARTUP EXPERIENCE
==================================================

When main.py starts, show something like:

╔══════════════════════════════════════════════════════╗
║       ███████╗███╗   ███╗ █████╗                    ║
║       EMA CROSSOVER TRADING ENGINE                  ║
║       DHAN AUTOMATED EXECUTION CORE                 ║
╚══════════════════════════════════════════════════════╝

Then display:

- configuration loaded
- strategy parameters
- symbol
- timeframe
- EMA periods
- polling interval
- trading window
- TP/SL
- risk controls
- LIVE/DRY RUN

Never display secrets.

Require a safe confirmation before LIVE trading if appropriate.

For example, when dry_run=false, optionally require:

LIVE TRADING ENABLED

unless configuration disables confirmation.

Make this configurable.

==================================================
30. GRACEFUL SHUTDOWN
==================================================

Handle:

Ctrl+C

and stop.py requests.

Shutdown sequence:

1. Stop generating new signals.
2. Stop opening trades.
3. If configured, close bot-managed positions.
4. Print final status.
5. Clean up control/PID state.
6. Exit.

Never leave stale control state if the process shuts down normally.

Handle unexpected termination as safely as practical.

==================================================
31. RESTART SAFETY
==================================================

The bot may restart after a crash or AWS reboot.

At startup:

- query Dhan for existing positions.
- do not blindly assume there is no position.
- detect whether an existing position may belong to this strategy.
- avoid immediately placing duplicate orders.

If ownership cannot be established safely, default to observation mode and clearly warn the user.

Document the limitation.

==================================================
32. PERFORMANCE REQUIREMENTS
==================================================

Target:

- AWS Linux VM
- 1 GB RAM
- low CPU consumption
- one strategy instance
- polling every 5 seconds by default

Do not:

- spawn unnecessary threads
- create unnecessary processes
- repeatedly initialize API clients
- download excessive historical data on every loop

Cache what can safely be cached.

Fetch only the amount of historical data required to calculate the configured EMA values plus a reasonable warm-up period.

==================================================
33. CODE QUALITY
==================================================

Write idiomatic Python.

Use:

- type hints where useful
- dataclasses where useful
- functions with clear responsibilities
- constants/configuration
- exception handling
- docstrings

Avoid:

- giant unreadable functions
- unnecessary abstractions
- duplicated code
- magic numbers
- hard-coded strategy parameters
- hidden global state

The complete implementation must remain in main.py.

==================================================
34. ARCHITECTURE.MD
==================================================

Create a comprehensive architecture.md.

This document should explain the complete strategy and application in a clear, educational, chapter-like structure.

Use Markdown headings, tables, diagrams using Mermaid where useful, formulas, examples, and step-by-step explanations.

Include at minimum:

# EMA Crossover Algo

## 1. Strategy Overview

Explain:

- what EMA is
- why EMA is used
- fast EMA
- slow EMA
- crossover
- bullish crossover
- bearish crossover
- trend-following nature
- strengths
- weaknesses

## 2. Strategy Logic

Explain the exact logic.

Include formulas:

EMA = Price × α + Previous EMA × (1 − α)

where:

α = 2 / (N + 1)

Explain N.

## 3. Example Trade

Provide a realistic numerical example.

Example:

Capital: ₹100,000
Quantity: 25
Fast EMA: 9
Slow EMA: 21

Show several candles and EMA values.

Explain:

- previous candle
- current candle
- bullish crossover
- BUY execution
- entry price
- quantity
- TP
- SL
- exit
- final P&L

Use a worked example.

For example:

Entry = ₹1,000
Quantity = 25
TP = 2%
SL = 1%

TP = ₹1,020
SL = ₹990

If TP is reached:

Profit = (₹1,020 − ₹1,000) × 25
= ₹500

If SL is reached:

Loss = (₹1,000 − ₹990) × 25
= ₹250

Clearly state this is an illustrative example and actual results depend on execution, slippage, brokerage, taxes, liquidity, and market conditions.

## 4. End-to-End Execution Flow

Explain:

START
↓
Load configuration
↓
Load environment
↓
Validate configuration
↓
Connect to Dhan
↓
Check existing position
↓
Wait for startup/trading window
↓
Fetch market data
↓
Build candle
↓
Calculate EMA
↓
Detect crossover
↓
Check risk controls
↓
Check TP/SL
↓
Execute order
↓
Monitor position
↓
Exit
↓
Shutdown

## 5. Function-by-Function Explanation

Explain every important function in main.py.

For each function explain:

- purpose
- inputs
- output
- how it works
- when it is called
- why it is important
- trading/risk implications

The explanation must match the actual code.

## 6. Configuration Guide

Explain every important config.yaml parameter.

Create a table:

Parameter | Purpose | Example | Effect of Increasing/Decreasing

Include:

- fast EMA
- slow EMA
- timeframe
- polling interval
- TP
- SL
- quantity
- cooldown
- max trades
- trading window
- reverse_on_signal
- allow_reentry
- daily loss limit
- daily profit target

## 7. Parameter Tuning

Explain how a trader can experiment with parameters.

Discuss:

### Fast EMA

Lower value:
- reacts faster
- more signals
- more noise

Higher value:
- smoother
- fewer signals
- slower response

### Slow EMA

Lower:
- reacts faster

Higher:
- identifies broader trends

### EMA combinations

Examples:

5/20
9/21
12/26
20/50
50/200

Explain that these are examples, not guaranteed optimal settings.

### TP/SL

Explain:

- tight TP
- wide TP
- tight SL
- wide SL
- risk/reward

### Timeframe

Explain:

- 1-minute
- 5-minute
- 15-minute
- 1-hour

Discuss noise, signal frequency, and holding period.

## 8. How to Improve the Strategy

Suggest ways to improve robustness rather than promising profits.

Examples:

- volume filter
- higher-timeframe trend filter
- RSI confirmation
- ATR-based stop loss
- volatility filter
- VWAP filter
- market regime filter
- trading-session filter
- slippage assumptions
- transaction-cost modeling

Explain that adding filters may reduce false signals but can also reduce trade frequency and potentially miss profitable trades.

## 9. Backtesting

Explain why the strategy should be backtested before live deployment.

Discuss:

- historical data
- transaction costs
- slippage
- survivorship bias
- look-ahead bias
- overfitting
- walk-forward testing
- out-of-sample testing

## 10. Risk Management

Explain:

- position sizing
- stop loss
- daily loss limit
- max trades
- cooldown
- avoiding revenge trading
- avoiding over-optimization

Do not claim that any configuration will guarantee profit.

## 11. Live Trading Safety

Explain:

- dry_run first
- small quantity
- API failures
- order rejection
- network interruption
- broker position mismatch
- duplicate orders
- stale market data
- AWS restart
- manual intervention

## 12. Example Scenarios

Provide examples for:

A. Bullish crossover → BUY → TP

B. Bullish crossover → BUY → SL

C. Bullish crossover → BUY → bearish crossover → EXIT

D. Long → bearish crossover → reverse to short

E. Trading window closes → close position

F. stop.py manually stops the bot

G. API temporarily fails

H. Duplicate signal during polling

For every example explain what the bot does and why.

## 13. P&L Calculation

Explain:

Long P&L
Short P&L

Include formulas and examples.

Explain realized versus unrealized P&L.

## 14. Operational Checklist

Before live trading:

- API credentials
- security ID
- quantity
- EMA parameters
- timeframe
- TP
- SL
- trading window
- dry run
- risk limits
- AWS clock/timezone
- market hours
- network connectivity

## 15. Troubleshooting

Include common issues:

- authentication failure
- invalid security ID
- no market data
- order rejected
- bot does not trade
- repeated signal
- position mismatch
- TP/SL not triggered
- stop.py not working
- configuration error

## 16. Future Extensions

Explain possible future upgrades:

- multiple symbols
- options
- portfolio-level risk
- ATR
- RSI
- MACD
- machine learning
- AI signal scoring
- backtesting engine
- database
- web dashboard

Do not implement those future extensions unless required by this project.

==================================================
35. EDUCATIONAL CODE STYLE
==================================================

Although this is a production-oriented trading bot, write the code and architecture documentation with clarity.

The code should be understandable line-by-line by someone learning algorithmic trading and Python.

Use comments and function-level explanations to make:

strategy → data → signal → risk → order → position → exit

very easy to follow.

At the end of architecture.md, include a section titled:

## Learning and Extension Notes

Explain how the implementation can be studied function-by-function and extended later.

The code should be written in a way that it is useful for educational material, including the actual code together with explanations, examples, diagrams, and parameter-tuning discussions.

==================================================
36. IMPORTANT TRADING SAFETY REQUIREMENTS
==================================================

Never state or imply that the EMA crossover strategy guarantees profit.

Do not optimize parameters to manufacture a guaranteed profitable result.

Use language such as:

- historical performance is not a guarantee
- live execution differs from backtests
- slippage and costs matter
- parameters should be validated with out-of-sample testing
- risk management is essential

The objective is a robust, configurable trading engine, not a guaranteed-profit system.

==================================================
37. FINAL VALIDATION
==================================================

After generating all files, review the complete project for consistency.

Verify:

1. main.py imports only available dependencies.
2. No code imports docs/project_requirements.md.
3. No code imports docs/Dhan_SRP.py.
4. No additional project files are required.
5. config.yaml contains every configurable parameter.
6. .env contains credentials only.
7. Secrets are never printed.
8. stop.py can request graceful shutdown.
9. TP/SL closes the position and stops the bot.
10. Trading-window behavior is correct.
11. Trading-window can be disabled.
12. Startup-time behavior is correct.
13. Duplicate-order protection exists.
14. EMA crossover detection uses previous/current EMA relationship.
15. Current position P&L is visible in CLI.
16. CLI refreshes according to configurable polling interval.
17. API errors do not cause uncontrolled loops.
18. LIVE and DRY RUN modes are clearly separated.
19. Existing positions are handled safely.
20. Configuration validation is implemented.
21. The code can run on a 1 GB RAM Linux VM.
22. architecture.md accurately describes the actual implementation.
23. All function explanations correspond to actual functions.
24. All examples in architecture.md are internally consistent.
25. No undocumented hard-coded trading parameters remain.

==================================================
38. EXPECTED FINAL OUTPUT
==================================================

Create the following six files:

main.py
config.yaml
.env
stop.py
requirements.txt
architecture.md

Do not create anything else.

Before finishing, perform a final code-review pass specifically looking for:

- duplicate orders
- incorrect crossover detection
- position-side mistakes
- incorrect LONG/SHORT P&L calculations
- TP/SL calculation errors
- trading-window bugs
- shutdown bugs
- stop.py race conditions
- API error handling
- configuration mismatches
- unsafe live-trading behavior
- unnecessary memory/CPU usage

The final result must be a complete, runnable, configurable Dhan EMA Crossover trading bot whose code is clean enough to be studied function-by-function and whose architecture.md provides detailed explanations, examples, formulas, execution flows, risk-management guidance, and parameter-tuning guidance.
```
