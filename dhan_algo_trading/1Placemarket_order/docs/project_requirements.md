# Build a Sci-Fi CLI Trading Application Using Dhan API

I want you to extend the existing trading codebase to create a **CLI-based stock trading application using the Dhan API**.

Use these existing files as the primary reference for understanding the current implementation:

* `Dhan_SRP.py`
* `srp_dhan_helper.md`

**Do not unnecessarily rewrite the existing Dhan integration. Reuse existing helper functions, authentication, API patterns, instrument handling, and order-management logic wherever possible.**

The application should initially support **HDFCBANK by default**, but the architecture must allow other stocks to be configured easily.

---

## 1. Core Objective

Build a CLI application that can:

1. Read the stock/instrument configuration from `config.yaml`.
2. Start with **HDFCBANK** as the default configured stock.
3. Place a **MARKET BUY order** using Dhan.
4. Use the `instrument_id` and `security_id` from `config.yaml`.
5. Support configurable:

   * Quantity
   * Exchange segment
   * Product type
   * Transaction type
   * Instrument ID
   * Security ID
   * Take Profit (TP)
   * Stop Loss (SL)
   * Polling interval
6. Continuously poll the latest market/order/position data.
7. Display the trading state in a **professional sci-fi terminal UI**.
8. Show:

   * Current market price
   * Entry price
   * Current quantity
   * Current position
   * Current P&L
   * P&L percentage
   * Take-profit price
   * Stop-loss price
   * Distance to TP
   * Distance to SL
   * Order status
   * Position status
   * Last market-data update time
   * Next polling countdown/status
9. Poll the latest information every **5 seconds by default**.
10. Make the polling interval configurable from `config.yaml`.
11. Handle API errors, rejected orders, network errors, missing data, and unexpected responses gracefully.
12. Never crash the CLI because of a temporary API failure.

---

# 2. Configuration

Create/use:

`config.yaml`

Example structure:

```yaml
trading:
  default_symbol: HDFCBANK
  quantity: 1

  polling:
    interval_seconds: 5

  risk:
    take_profit_percent: 2.0
    stop_loss_percent: 1.0

instruments:
  HDFCBANK:
    exchange_segment: NSE_EQ
    security_id: "<SECURITY_ID>"
    instrument_id: "<INSTRUMENT_ID>"

  # Future examples:
  # RELIANCE:
  #   exchange_segment: NSE_EQ
  #   security_id: "<SECURITY_ID>"
  #   instrument_id: "<INSTRUMENT_ID>"
```

Do not hard-code HDFCBANK's security ID or instrument ID inside Python code.

The values must come from `config.yaml`.

If the existing project uses a different configuration structure, adapt this structure while keeping the same principle:

**instrument/security identifiers must be configuration-driven.**

---

# 3. Dhan API Integration

Study `Dhan_SRP.py` and `srp_dhan_helper.md` first.

Determine:

* How authentication is currently implemented.
* How the Dhan client is initialized.
* How market data is retrieved.
* How orders are placed.
* How order status is retrieved.
* How positions are retrieved.
* How security/instrument IDs are handled.
* Existing exception/error handling.

Reuse the existing implementation where possible.

Do NOT create a second unrelated Dhan API abstraction if an existing helper already provides the required functionality.

---

# 4. Market Order

Implement a function conceptually similar to:

```python
place_market_order(...)
```

The application should place a **MARKET BUY order** for the configured stock.

The order parameters should be derived from configuration.

For example:

```text
Symbol: HDFCBANK
Transaction: BUY
Order Type: MARKET
Quantity: configured quantity
Exchange: configured exchange segment
Product: configured product type
Security ID: config.yaml
Instrument ID: config.yaml
```

Before placing the order, display a confirmation screen.

Example:

```text
╔══════════════════════════════════════════════════════╗
║              ⚠ ORDER EXECUTION REQUEST ⚠            ║
╠══════════════════════════════════════════════════════╣
║ Symbol       : HDFCBANK                              ║
║ Security ID  : XXXXX                                 ║
║ Instrument ID: XXXXX                                 ║
║ Side         : BUY                                   ║
║ Order Type   : MARKET                                ║
║ Quantity     : 1                                     ║
╚══════════════════════════════════════════════════════╝

Execute MARKET BUY order? [y/N]:
```

Default should be **NO** if the user simply presses Enter.

Do not silently place a live order.

---

# 5. Position Tracking

After successful order placement, continuously retrieve the latest position/order information.

The application should determine:

* Whether the order was accepted.
* Whether the order was rejected.
* Whether it is pending.
* Whether it was filled.
* Average executed price.
* Filled quantity.
* Current position.
* Current market price.
* Unrealized P&L.

Do not assume that the requested order price is the actual execution price.

Use the **actual average executed price** returned by Dhan whenever available.

---

# 6. Take Profit / Stop Loss

Support TP/SL configuration.

For a BUY position:

```text
TP = Entry Price × (1 + TP%)
SL = Entry Price × (1 - SL%)
```

Example:

```text
Entry Price = ₹1,000
TP = 2%
SL = 1%

Take Profit = ₹1,020
Stop Loss   = ₹990
```

Display these values clearly in the CLI.

The implementation should make it possible to eventually support absolute TP/SL prices as well.

Prefer an abstraction such as:

```python
calculate_take_profit(...)
calculate_stop_loss(...)
```

rather than embedding calculations throughout the application.

---

# 7. TP/SL Execution

The application should continuously monitor the position.

For a long position:

```text
IF current_price >= take_profit_price:
    trigger TP exit

IF current_price <= stop_loss_price:
    trigger SL exit
```

When TP or SL is triggered:

1. Clearly display the trigger.
2. Submit the appropriate exit order.
3. Monitor the exit order.
4. Confirm execution.
5. Display realized P&L.
6. Mark the trading session as completed.
7. Stop further automatic trading actions.

IMPORTANT:

Avoid duplicate exit orders.

The program must maintain an internal state such as:

```text
POSITION_OPEN
EXIT_TRIGGERED
EXIT_ORDER_SUBMITTED
EXIT_FILLED
POSITION_CLOSED
ERROR
```

An exit must not be submitted repeatedly on every polling cycle after TP/SL has triggered.

---

# 8. P&L

For a BUY position:

```text
P&L = (Current Market Price - Average Entry Price) × Quantity
```

Also calculate:

```text
P&L % =
((Current Market Price - Average Entry Price)
 / Average Entry Price) × 100
```

Display both.

Example:

```text
ENTRY       ₹1,950.25
CURRENT     ₹1,967.80
QUANTITY    10

UNREALIZED P&L
₹175.50
+0.90%
```

If Dhan provides a more authoritative P&L value through the position API, use that value where appropriate and clearly distinguish broker-reported P&L from locally calculated P&L if both are available.

---

# 9. Polling

The application must poll the latest data continuously.

Default:

```yaml
polling:
  interval_seconds: 5
```

The interval must NOT be hard-coded.

For example:

```python
polling_interval = config["trading"]["polling"]["interval_seconds"]
```

Every polling cycle should refresh:

* Market price
* Position
* P&L
* Order status
* TP/SL status

Display the timestamp of the most recent successful update.

Example:

```text
LAST UPDATE: 10:42:35
NEXT REFRESH: 4s
```

Avoid spawning uncontrolled threads/processes on every polling cycle.

Use a clean polling loop with appropriate exception handling.

---

# 10. Sci-Fi CLI Design

The CLI should look like a **professional futuristic trading terminal**, not a basic Python print-based application.

Prefer a library such as:

```text
rich
```

if it is not already available.

Use:

* Panels
* Tables
* Borders
* Status indicators
* Progress bars where useful
* Live updating
* Icons
* Monospace formatting
* Clear sections
* ANSI terminal effects supported by Rich

Do NOT overdo animations to the point where the terminal becomes difficult to use.

The CLI should feel similar to:

```text
╔════════════════════════════════════════════════════════════════════╗
║                 ◈ DHAN // QUANT TERMINAL ◈                       ║
║                    LIVE EXECUTION ENGINE                          ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║  ASSET             HDFCBANK                 STATUS   ● LIVE        ║
║  SECURITY ID       XXXXX                    MODE     PAPER/LIVE    ║
║                                                                    ║
║  MARKET PRICE      ₹1,985.40                                      ║
║  ENTRY PRICE       ₹1,970.20                                      ║
║  QUANTITY          10                                              ║
║                                                                    ║
║  ┌──────────────── POSITION ────────────────────────────────────┐  ║
║  │ LONG                                                        │  ║
║  │ Unrealized P&L        +₹152.00                              │  ║
║  │ P&L %                 +0.77%                                │  ║
║  └─────────────────────────────────────────────────────────────┘  ║
║                                                                    ║
║  ┌──────────────── RISK MATRIX ────────────────────────────────┐  ║
║  │ TAKE PROFIT         ₹2,009.60        +₹24.20                │  ║
║  │ STOP LOSS           ₹1,950.50        -₹19.70                │  ║
║  │                                                            │  ║
║  │ TP DISTANCE         +₹24.20                                 │  ║
║  │ SL DISTANCE         -₹34.90                                 │  ║
║  └─────────────────────────────────────────────────────────────┘  ║
║                                                                    ║
║  ORDER STATUS       FILLED                                        ║
║  POSITION STATUS    OPEN                                          ║
║  LAST UPDATE        10:42:35                                      ║
║  NEXT POLL          4s                                            ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

Use live screen refresh rather than continuously dumping thousands of lines into the terminal.

---

# 11. CLI Commands

Design the CLI so that it can eventually support multiple commands.

At minimum support something like:

```bash
python main.py
```

which starts the default configured symbol:

```text
HDFCBANK
```

Also consider:

```bash
python main.py --symbol HDFCBANK
```

and:

```bash
python main.py --config config.yaml
```

If practical, add:

```bash
python main.py --dry-run
```

The `--dry-run` option is HIGHLY recommended.

In dry-run mode:

* Do not submit live orders.
* Simulate order execution.
* Continue market-data polling.
* Show what would have happened.

---

# 12. Safety

Because this application can place real financial orders, implement strong safeguards.

Requirements:

### Explicit live-order confirmation

Never place a live order without user confirmation.

### Dry-run mode

Support:

```bash
--dry-run
```

### Configuration validation

Before execution validate:

* Symbol exists.
* Instrument exists.
* Security ID exists.
* Instrument ID exists.
* Quantity > 0.
* Polling interval > 0.
* TP/SL values are valid.

### Error handling

Gracefully handle:

* Authentication failure.
* Invalid configuration.
* API timeout.
* Network error.
* Rate limit.
* Order rejection.
* Missing market price.
* Missing position.
* Partial fill.
* Duplicate order conditions.
* Unexpected API response.

### Ctrl+C

Handle:

```text
CTRL+C
```

gracefully.

Do not immediately terminate in the middle of submitting an order.

Display:

```text
⚠ Shutdown requested.
Monitoring stopped.
Existing broker position was NOT automatically closed.
```

Do not automatically close a live position merely because the CLI exits unless explicitly configured to do so.

---

# 13. Project Structure

Prefer a clean modular structure.

For example:

```text
project/
│
├── main.py
├── config.yaml
├── Dhan_SRP.py
├── srp_dhan_helper.md
│
├── trading/
│   ├── __init__.py
│   ├── dhan_client.py
│   ├── order_manager.py
│   ├── position_manager.py
│   ├── risk_manager.py
│   ├── market_data.py
│   └── models.py
│
├── cli/
│   ├── __init__.py
│   ├── dashboard.py
│   └── styles.py
│
├── utils/
│   ├── config.py
│   └── logging.py
│
└── requirements.txt
```

However, **do not blindly create this exact structure**.

First inspect the existing project.

If the current architecture already has suitable modules, extend them instead of duplicating functionality.

---

# 14. Logging

Add structured logging.

Log important events such as:

```text
[INFO] Configuration loaded
[INFO] HDFCBANK selected
[INFO] Market data connection established
[INFO] Order submitted
[INFO] Order ID: XXXXX
[INFO] Order filled
[INFO] Entry price: ₹XXXX
[INFO] TP calculated
[INFO] SL calculated
[WARN] API request failed; retrying
[INFO] TP triggered
[INFO] Exit order submitted
[INFO] Position closed
```

Avoid logging secrets.

Never print:

* Access tokens
* Client secrets
* API credentials

---

# 15. Requirements

Inspect the current project dependencies first.

Only add packages that are actually required.

Likely dependencies may include:

```text
dhanhq
PyYAML
rich
```

Use the appropriate package/API version already compatible with the existing project.

Do not upgrade unrelated dependencies unnecessarily.

---

# 16. Testing

Create tests for the non-live components.

At minimum test:

### Configuration

```text
Valid HDFCBANK configuration
Missing security ID
Missing instrument ID
Invalid quantity
Invalid polling interval
```

### TP/SL

```text
Correct TP calculation
Correct SL calculation
TP trigger
SL trigger
```

### P&L

```text
Positive P&L
Negative P&L
Zero P&L
```

### State machine

```text
ORDER_PENDING
ORDER_FILLED
POSITION_OPEN
TP_TRIGGERED
SL_TRIGGERED
EXIT_FILLED
POSITION_CLOSED
```

Do NOT execute real Dhan orders from automated tests.

Mock the Dhan API.

---

# 17. Important Implementation Principle

Separate the following concerns:

```text
Configuration
      ↓
Dhan API Client
      ↓
Market Data
      ↓
Order Manager
      ↓
Position Manager
      ↓
Risk / TP-SL Engine
      ↓
CLI Dashboard
```

The CLI should not directly contain Dhan API business logic.

For example, avoid:

```python
# BAD
dashboard.py

dhan.place_order(...)
dhan.get_positions(...)
calculate_tp(...)
print(...)
```

Instead:

```python
# BETTER

market_data = market_service.get_latest_price()
position = position_manager.get_position()
risk = risk_manager.evaluate(position, market_data)

dashboard.render(
    market_data=market_data,
    position=position,
    risk=risk
)
```

---

# 18. First Step — Inspect Before Coding

Before modifying files:

1. Inspect `Dhan_SRP.py`.
2. Inspect `srp_dhan_helper.md`.
3. Inspect the complete existing project structure.
4. Identify reusable Dhan functions.
5. Identify the current authentication mechanism.
6. Identify existing dependencies.
7. Identify how security IDs and instrument IDs are currently handled.
8. Identify existing order-placement functionality.
9. Identify existing market-data functionality.

Then produce a short implementation plan.

After that, implement the solution.

Do not ask unnecessary questions if the existing code contains enough information to proceed.

---

# 19. Final Acceptance Criteria

The implementation is complete only when the following workflow works:

```text
$ python main.py
```

Application starts with:

```text
HDFCBANK
```

Then:

```text
1. Load config
2. Validate configuration
3. Connect to Dhan
4. Display current market price
5. Display proposed order
6. Ask for explicit confirmation
7. Place MARKET BUY order
8. Track order until filled/rejected
9. Obtain actual entry price
10. Calculate TP
11. Calculate SL
12. Start live dashboard
13. Poll every configured N seconds
14. Update market price
15. Update P&L
16. Update position
17. Monitor TP
18. Monitor SL
19. Trigger only one exit order
20. Confirm exit
21. Display final realized P&L
22. End trading session
```

The final terminal experience should be **clean, futuristic, readable, and suitable for a real trading-tool prototype**.

Most importantly:

**Do not hard-code instrument IDs/security IDs.**
**Do not place live orders without confirmation.**
**Do not create duplicate exit orders.**
**Do not expose API credentials.**
**Do not assume the requested price is the execution price.**
**Do not let temporary API failures crash the application.**

Use `Dhan_SRP.py` and `srp_dhan_helper.md` as the authoritative reference for the existing Dhan implementation and adapt the new architecture around what is already working.
