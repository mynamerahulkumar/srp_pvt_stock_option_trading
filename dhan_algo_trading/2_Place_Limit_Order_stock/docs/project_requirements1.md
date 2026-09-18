# GITHUB COPILOT / CURSOR MASTER PROMPT

## Build a Lightweight Dhan LIMIT Order Algo for HDFCBANK / Any NSE Equity

Build a **complete, working, production-oriented but simple Python LIMIT Order Algo using the Dhan API**.

The first configured stock will be **HDFCBANK**, but the application must be generic enough to trade any supported NSE equity by changing `config.yaml`.

The application must work on:

* Local Linux
* AWS Linux
* AWS EC2
* 1 GB RAM VM
* Headless SSH environment
* Python 3.x

Keep the architecture **simple, lightweight, readable, reliable, and easy to extend**.

Do not overengineer the solution.

---

# 1. IMPORTANT REFERENCE FILES

The following files are available only as **reference material**:

```text
docs/srp_dhan_helper.md
docs/Dhan_SRP.py
```

You MUST inspect these files before implementing the Dhan functionality.

They may contain useful information about:

* Dhan authentication
* Dhan SDK usage
* Dhan API methods
* Order placement
* Order modification
* Order cancellation
* Order status
* Order parameters
* Security IDs
* Exchange segments
* Product types
* Transaction types
* Existing implementation patterns

However, these files are **REFERENCE CODE ONLY**.

## CRITICAL REQUIREMENT

The final application MUST NOT depend on either file.

Do NOT:

```python
import docs.Dhan_SRP
```

Do NOT dynamically read either file at runtime.

Do NOT make the final application dependent on the `docs` directory.

After development, I will delete:

```text
docs/srp_dhan_helper.md
docs/Dhan_SRP.py
```

The application MUST continue to work normally after these files are deleted.

Therefore, extract the required knowledge from these files and implement the necessary functionality directly inside the final application.

The final runtime project must work with only:

```text
main.py
stop.py
config.yaml
.env
```

---

# 2. FINAL PROJECT STRUCTURE

The final application must contain:

```text
project/
│
├── main.py
├── stop.py
├── config.yaml
└── .env
```

The following are temporary development/reference files:

```text
docs/
├── srp_dhan_helper.md
└── Dhan_SRP.py
```

These reference files must be deletable after implementation.

Do not create unnecessary Python files.

---

# 3. FILE RESPONSIBILITIES

## main.py

All application and trading functionality must be in `main.py`.

It should contain:

* environment loading
* configuration loading
* configuration validation
* safety validation
* Dhan client initialization
* order request creation
* LIMIT order placement
* order ID handling
* order status retrieval
* order monitoring
* partial-fill handling
* order modification
* order cancellation
* timeout handling
* duplicate-order protection
* limited safe retries for read operations
* stop signal detection
* logging
* graceful shutdown

---

## stop.py

`stop.py` must ONLY create a local stop signal.

It must NOT:

* import `main.py`
* import Dhan SDK
* connect to Dhan
* load `.env`
* load `config.yaml`
* place orders
* modify orders
* cancel orders
* access the internet
* use Redis
* use a database
* kill a Linux process

It should use only the Python standard library.

---

## config.yaml

Contains all non-secret configuration.

---

## .env

Contains only secrets.

Example:

```env
DHAN_CLIENT_ID=your_client_id_here
DHAN_ACCESS_TOKEN=your_access_token_here
```

Never hard-code credentials anywhere.

Never log credentials.

---

# 4. INITIAL ALGO

Build:

```text
Dhan LIMIT Order Algo
```

Initial instrument:

```text
HDFCBANK
```

Market:

```text
NSE Equity
```

Initial transaction:

```text
BUY
```

Order type:

```text
LIMIT
```

The implementation must be generic.

The user should be able to change the stock by changing configuration only.

There must NOT be HDFCBANK-specific trading logic such as:

```python
if symbol == "HDFCBANK":
```

---

# 5. CONFIGURABLE VALUES

At minimum, these must be configurable:

```text
symbol
security_id
exchange_segment
transaction_type
quantity
entry_price
limit_price
order_type
product_type
validity
```

Also configure:

```text
order modification
order cancellation
polling interval
maximum order wait time
dry run
live trading permission
confirmation
maximum quantity
logging level
```

---

# 6. CONFIG.YAML

Create a configuration similar to:

```yaml
strategy:
  name: "Dhan Limit Order Algo"
  enabled: true

instrument:
  symbol: "HDFCBANK"
  security_id: ""
  exchange_segment: "NSE_EQ"

order:
  transaction_type: "BUY"
  quantity: 1
  order_type: "LIMIT"
  product_type: "CNC"
  validity: "DAY"

  entry_price: 1650.00
  limit_price: 1649.50

management:
  modification:
    enabled: false
    new_limit_price: 1648.00
    max_modifications: 2

  cancellation:
    enabled: false
    cancel_after_seconds: 300

runtime:
  poll_interval_seconds: 2
  max_order_wait_seconds: 900

safety:
  dry_run: true
  allow_live_trading: false
  require_confirmation: true
  max_quantity: 1000

logging:
  level: "INFO"
```

You may improve the structure if required by the actual Dhan API, but keep it simple.

Do not put secrets in this file.

---

# 7. ENTRY PRICE VS LIMIT PRICE

Treat:

```text
entry_price
```

and:

```text
limit_price
```

as separate concepts.

For example:

```yaml
entry_price: 1650.00
limit_price: 1649.50
```

`entry_price` is the desired strategy entry level.

`limit_price` is the actual LIMIT price submitted to Dhan.

Do not automatically make them equal.

Logs must clearly distinguish them.

---

# 8. SECURITY ID

Do NOT guess or invent the HDFCBANK security ID.

Start with:

```yaml
security_id: ""
```

if the correct ID is not already available.

If it is empty, the application must stop before placing an order:

```text
ERROR: security_id is not configured for HDFCBANK.
No order was placed.
```

Never fabricate an instrument/security ID.

---

# 9. DHAN IMPLEMENTATION

First inspect:

```text
docs/srp_dhan_helper.md
docs/Dhan_SRP.py
```

Use them to understand the existing Dhan implementation.

Then verify the implementation against the current supported Dhan Python SDK/API where necessary.

Determine the correct implementation for:

* authentication
* client initialization
* LIMIT order placement
* order status
* order book if needed
* order modification
* order cancellation
* required parameters
* exchange segment
* product type
* transaction type
* order type
* validity

## IMPORTANT

Do NOT blindly copy reference code.

Do NOT assume old API methods are still correct.

Do NOT invent Dhan API methods.

Do NOT invent parameter names.

Use the correct Dhan API/SDK implementation.

Then make the final application independent of the reference files.

---

# 10. DEPENDENCIES

Use the minimum required dependencies.

Prefer:

```text
Python standard library
PyYAML
python-dotenv
Current supported Dhan Python SDK
```

Avoid unnecessary packages.

Do NOT introduce:

```text
Redis
Celery
PostgreSQL
MySQL
MongoDB
FastAPI
Flask
Django
Docker
Kubernetes
WebSocket infrastructure
Dashboard
```

unless absolutely required by the Dhan implementation.

The target machine may have only 1 GB RAM.

---

# 11. PROJECT PATH

Use:

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
```

All local project files must be resolved relative to `BASE_DIR`.

For example:

```python
CONFIG_FILE = BASE_DIR / "config.yaml"
STOP_FILE = BASE_DIR / ".stop"
ENV_FILE = BASE_DIR / ".env"
```

Do NOT depend on the current shell working directory.

Both must work:

```bash
python3 main.py
```

and:

```bash
python3 /home/ec2-user/algo/main.py
```

even when executed from another directory.

---

# 12. LOAD CONFIGURATION

Implement:

```python
def load_config():
    ...
```

Load:

```text
config.yaml
```

from `BASE_DIR`.

If missing, show a clear error.

If YAML is invalid, show a clear error.

Never continue to trading with invalid configuration.

---

# 13. LOAD ENVIRONMENT

Implement:

```python
def load_environment():
    ...
```

Load `.env` from `BASE_DIR`.

Required:

```text
DHAN_CLIENT_ID
DHAN_ACCESS_TOKEN
```

If either is missing:

```text
ERROR: Dhan credentials are missing.
No order was placed.
```

Never display the access token.

---

# 14. CONFIGURATION VALIDATION

Implement:

```python
def validate_config(config):
    ...
```

Validate all important configuration before trading.

Validate:

```text
symbol
security_id
exchange_segment
transaction_type
quantity
order_type
product_type
validity
entry_price
limit_price
max_quantity
poll_interval_seconds
max_order_wait_seconds
modification settings
cancellation settings
```

Examples:

```text
quantity > 0
entry_price > 0
limit_price > 0
quantity <= max_quantity
transaction_type = BUY or SELL
order_type = LIMIT
```

Fail early.

---

# 15. SAFETY VALIDATION

Live trading must require BOTH:

```text
dry_run == false
```

and:

```text
allow_live_trading == true
```

If:

```yaml
dry_run: true
```

the Dhan order-placement API must NEVER be called.

If:

```yaml
dry_run: false
allow_live_trading: false
```

do not place an order.

---

# 16. DRY RUN MODE

Dry run must be the default:

```yaml
safety:
  dry_run: true
```

When dry run is enabled:

* validate configuration
* display the complete order information
* do NOT create/place a real order

Example:

```text
============================================================
DRY RUN MODE
============================================================

Symbol          : HDFCBANK
Security ID     : XXXXX
Exchange        : NSE_EQ
Transaction     : BUY
Quantity        : 1
Order Type      : LIMIT
Product Type    : CNC
Validity        : DAY
Entry Price     : 1650.00
Limit Price     : 1649.50

NO REAL ORDER HAS BEEN PLACED.

============================================================
```

---

# 17. LIVE ORDER CONFIRMATION

If:

```yaml
require_confirmation: true
```

show the complete order details.

Ask:

```text
Type YES to place this LIVE order:
```

Only exact:

```text
YES
```

should proceed.

Anything else must abort safely.

---

# 18. DHAN CLIENT

Implement:

```python
def create_dhan_client():
    ...
```

Use credentials from `.env`.

Never expose credentials in logs or exception output.

---

# 19. BUILD ORDER REQUEST

Implement:

```python
def build_order_request(config):
    ...
```

This function must clearly convert the configuration into the correct Dhan order request.

Keep the mapping easy to understand.

For example:

```text
config.yaml
     ↓
instrument configuration
     ↓
order configuration
     ↓
Dhan request parameters
```

Use the actual Dhan SDK/API parameter names.

---

# 20. PLACE LIMIT ORDER

Implement:

```python
def place_limit_order(dhan, config):
    ...
```

Responsibilities:

1. Check stop signal.
2. Read order configuration.
3. Build request.
4. Log non-sensitive parameters.
5. Submit exactly one LIMIT order.
6. Validate the response.
7. Extract order ID.
8. Return order ID.

Do not mix monitoring logic into this function.

---

# 21. ORDER ID

After successful placement:

```python
order_id = place_limit_order(dhan, config)
```

Use the returned Dhan order ID for:

```text
status
modification
cancellation
```

Do not rely only on symbol/price to identify an order.

---

# 22. ORDER STATUS

Implement:

```python
def get_order_status(dhan, order_id):
    ...
```

Use the actual Dhan API response.

Determine:

```text
order status
filled quantity
remaining quantity
current order price where available
```

Do not invent a response format.

---

# 23. ORDER STATES

Support common states such as:

```text
PENDING
OPEN
PARTIALLY_FILLED
FILLED
CANCELLED
REJECTED
EXPIRED
FAILED
```

Use the actual status values returned by Dhan.

Normalize them only if useful.

Terminal states:

```text
FILLED
CANCELLED
REJECTED
EXPIRED
FAILED
```

When a terminal state is reached, stop monitoring.

---

# 24. PARTIAL FILL HANDLING

Correctly handle partial fills.

Example:

```text
Requested Quantity = 100
Filled Quantity    = 40
Remaining Quantity = 60
```

Never submit another full quantity order.

Never automatically re-enter.

Log:

```text
requested quantity
filled quantity
remaining quantity
order status
```

---

# 25. ORDER MONITORING

Implement:

```python
def monitor_order(dhan, config, order_id):
    ...
```

Use simple polling.

Conceptually:

```text
while order is not terminal:

    check stop signal

    get latest status

    log status

    if modification is configured:
        modify if appropriate

    if cancellation timeout is reached:
        cancel if appropriate

    sleep

finish
```

Use:

```python
time.sleep(poll_interval_seconds)
```

Do not busy-loop.

---

# 26. POLLING INTERVAL

Use:

```yaml
runtime:
  poll_interval_seconds: 2
```

The value must be configurable.

Do not poll excessively fast.

Keep API calls and CPU usage low.

---

# 27. ORDER MODIFICATION

Implement:

```python
def modify_order(dhan, order_id, new_limit_price):
    ...
```

Configuration:

```yaml
management:
  modification:
    enabled: false
    new_limit_price: 1648.00
    max_modifications: 2
```

Before modifying:

1. Check stop signal.
2. Get latest order status.
3. Confirm the order is still modifiable.
4. Perform modification.
5. Verify the response if possible.
6. Increment modification count.

Track:

```text
modification_count
current_limit_price
```

Never exceed:

```text
max_modifications
```

Never modify terminal orders.

---

# 28. ORDER CANCELLATION

Implement:

```python
def cancel_order(dhan, order_id):
    ...
```

Configuration:

```yaml
management:
  cancellation:
    enabled: false
    cancel_after_seconds: 300
```

Before cancelling:

1. Check stop signal.
2. Get latest status.
3. Confirm the order is still cancellable.
4. Cancel it.
5. Verify response/status if possible.

Never cancel a FILLED order.

---

# 29. MODIFICATION + CANCELLATION

If both are enabled:

* never perform both simultaneously
* always retrieve current status before action
* modify only modifiable orders
* cancel only cancellable orders
* do not modify terminal orders
* do not cancel terminal orders

Keep the logic deterministic.

---

# 30. MAXIMUM WAIT TIME

Support:

```yaml
runtime:
  max_order_wait_seconds: 900
```

When the maximum wait is reached:

1. Retrieve the latest status.
2. If terminal, finish.
3. If still open and cancellation is enabled, cancel.
4. If cancellation is disabled, stop monitoring and clearly report that the broker order may remain open.
5. Never create a replacement order.

---

# 31. DUPLICATE ORDER PROTECTION

This is extremely important.

Consider:

```text
Dhan order request sent
        ↓
network timeout
        ↓
response unknown
```

DO NOT submit another order.

The request may already have been accepted.

Instead:

```text
Check order status/order book
```

before deciding what happened.

There must be no blind retry of an order-placement request.

One execution of:

```bash
python3 main.py
```

must create at most one entry order.

---

# 32. RETRY POLICY

Read operations may have limited retries.

Examples:

```text
order status
order book
```

However:

**Never blindly retry order placement.**

A network timeout after submitting an order is an uncertain state.

The safe behavior is:

```text
Do not resubmit.
Check broker state.
```

---

# 33. ONE ENTRY ORDER PER RUN

The bot must manage one configured entry order lifecycle.

Flow:

```text
START
  ↓
LOAD CONFIG
  ↓
VALIDATE
  ↓
SAFETY CHECK
  ↓
DRY RUN / LIVE
  ↓
CREATE DHAN CLIENT
  ↓
PLACE ONE LIMIT ORDER
  ↓
GET ORDER ID
  ↓
MONITOR
  ↓
MODIFY/CANCEL IF CONFIGURED
  ↓
FINISH
```

Do not build continuous strategy re-entry.

---

# 34. NO AUTOMATIC RE-ENTRY

Never automatically place another order after:

```text
CANCELLED
REJECTED
EXPIRED
FAILED
```

Never create a second order simply because:

```text
the first order was not filled
```

Never create a replacement order after:

```text
.stop
CTRL+C
SIGTERM
```

---

# 35. STOP SYSTEM

Create:

```text
stop.py
```

using a filesystem signal:

```text
.stop
```

Both scripts must use:

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STOP_FILE = BASE_DIR / ".stop"
```

---

# 36. stop.py IMPLEMENTATION

Keep `stop.py` extremely simple.

Example:

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STOP_FILE = BASE_DIR / ".stop"

STOP_FILE.touch()

print("Stop signal created.")
print("The trading bot will stop safely.")
```

It must be safe to run repeatedly.

It must work without:

* Dhan SDK
* YAML
* `.env`
* network
* database

---

# 37. STOP DETECTION IN MAIN.PY

Implement:

```python
def stop_requested() -> bool:
    return STOP_FILE.exists()
```

Check it:

* at startup
* before order placement
* before modification
* before cancellation
* during monitoring
* before any new trading action

---

# 38. STOP DURING MONITORING

If:

```bash
python3 stop.py
```

is executed while the bot is monitoring:

```text
.stop detected
       ↓
stop monitoring
       ↓
check current order status if possible
       ↓
do not place another order
       ↓
do not modify another order
       ↓
exit cleanly
```

---

# 39. STOP DURING ORDER PLACEMENT

Before sending an order request, check `.stop`.

If it exists:

```text
Do not place order.
```

If the request has already been sent and the response is uncertain:

```text
Do not resubmit.
```

Check broker state if possible.

---

# 40. STOP DOES NOT AUTOMATICALLY CANCEL BROKER ORDER

This is important.

Creating:

```text
.stop
```

means:

```text
STOP THE PYTHON BOT
```

It does NOT automatically mean:

```text
CANCEL THE DHAN ORDER
```

By default, when the bot stops:

* stop the local process gracefully
* do not create new orders
* do not automatically cancel an existing broker order
* report the current broker order state if available

Example:

```text
Bot stop requested.

Existing Dhan order:
Order ID: XXXXX
Status: OPEN

The bot has stopped monitoring.
The broker order was not automatically cancelled.
```

---

# 41. NO OS PROCESS KILLING

Do NOT use:

```text
os.kill()
kill
kill -9
pkill
killall
```

The bot must stop cooperatively.

---

# 42. GRACEFUL SHUTDOWN

Handle where practical:

```text
.stop
CTRL+C
SIGTERM
```

On shutdown:

* stop loops
* do not place new orders
* do not re-enter
* log current order ID/status if available
* exit cleanly

Do not leave unnecessary processes or threads running.

---

# 43. STOP FILE RACE CONDITION

Handle `.stop` carefully.

Do not blindly delete `.stop` during runtime.

Avoid this dangerous situation:

```text
stop.py creates .stop
        ↓
main.py simultaneously deletes .stop
        ↓
stop request is lost
```

Choose a simple and deterministic startup/restart policy.

The user must be able to restart the application after a previous stop.

Document clearly how `.stop` is handled when starting a new run.

Do not overengineer this with databases or distributed locking.

---

# 44. LOGGING

Use Python's standard:

```python
logging
```

Example:

```text
2026-09-10 10:30:02 | INFO | Application started
2026-09-10 10:30:02 | INFO | Mode: DRY RUN
2026-09-10 10:30:02 | INFO | Symbol: HDFCBANK
2026-09-10 10:30:02 | INFO | Transaction: BUY
2026-09-10 10:30:02 | INFO | Quantity: 1
2026-09-10 10:30:02 | INFO | Entry Price: 1650.00
2026-09-10 10:30:02 | INFO | Limit Price: 1649.50
```

Log:

* startup
* mode
* configuration summary
* order parameters
* order submission
* order ID
* order status
* filled quantity
* remaining quantity
* modification
* cancellation
* timeout
* stop signal
* shutdown
* errors

Never log:

```text
DHAN_ACCESS_TOKEN
```

or any credential.

---

# 45. ERROR HANDLING

Handle gracefully:

```text
missing config.yaml
invalid YAML
missing .env
missing credentials
missing security ID
invalid quantity
invalid price
invalid configuration
Dhan authentication failure
Dhan API failure
network error
timeout
unexpected response
order rejection
modification failure
cancellation failure
CTRL+C
SIGTERM
.stop
```

Errors should be understandable.

Do not dump sensitive information.

---

# 46. PRICE/TICK VALIDATION

Where required by the actual Dhan/NSE rules, validate the configured LIMIT price against the applicable tick size.

Do not invent exchange rules.

Do not silently modify the user's price.

If the price is invalid:

```text
ERROR: Invalid LIMIT price.
No order was placed.
```

---

# 47. NO MARKET DATA ENGINE

This version does not need a complex market-data engine.

The user supplies:

```text
entry_price
limit_price
```

through `config.yaml`.

Do not add:

* WebSocket infrastructure
* historical database
* OHLC database
* indicator engine
* market-data storage

unless absolutely required.

---

# 48. NO OPTIONS / FUTURES

This version is for NSE equity.

Do NOT implement:

* options
* futures
* option chain
* Greeks
* expiry selection

---

# 49. NO AI

Do NOT implement:

* ChatGPT
* OpenAI
* LLM
* machine learning
* AI prediction
* sentiment analysis

---

# 50. NO STOP LOSS / TAKE PROFIT

Do NOT implement:

* stop loss
* take profit
* trailing stop loss

This version is strictly:

```text
LIMIT ENTRY
+
ORDER MONITORING
+
OPTIONAL LIMIT MODIFICATION
+
OPTIONAL CANCELLATION
```

---

# 51. LOW RESOURCE ARCHITECTURE

Target:

```text
AWS Linux
1 GB RAM
```

Therefore:

* one Python process
* synchronous execution
* minimal dependencies
* no database
* no Redis
* no Celery
* no dashboard
* no web server
* no unnecessary threads
* no unnecessary processes
* no busy loops
* no large in-memory datasets

Use:

```python
time.sleep(...)
```

for polling.

---

# 52. AWS COMPATIBILITY

These must work:

```bash
python3 main.py
```

Background:

```bash
nohup python3 main.py > algo.log 2>&1 &
```

Stop:

```bash
python3 stop.py
```

No GUI.

No desktop environment.

No web browser.

---

# 53. LOCAL LINUX COMPATIBILITY

These must work:

```bash
python3 main.py
```

and:

```bash
python3 stop.py
```

---

# 54. CODE ORGANIZATION

Organize `main.py` into clearly identifiable sections:

```python
# ============================================================
# IMPORTS
# ============================================================

# ============================================================
# PROJECT PATHS
# ============================================================

# ============================================================
# ENVIRONMENT
# ============================================================

# ============================================================
# CONFIGURATION
# ============================================================

# ============================================================
# VALIDATION
# ============================================================

# ============================================================
# STOP SIGNAL
# ============================================================

# ============================================================
# DHAN CLIENT
# ============================================================

# ============================================================
# ORDER CREATION
# ============================================================

# ============================================================
# ORDER PLACEMENT
# ============================================================

# ============================================================
# ORDER STATUS
# ============================================================

# ============================================================
# ORDER MODIFICATION
# ============================================================

# ============================================================
# ORDER CANCELLATION
# ============================================================

# ============================================================
# ORDER MONITORING
# ============================================================

# ============================================================
# DRY RUN
# ============================================================

# ============================================================
# SHUTDOWN
# ============================================================

# ============================================================
# MAIN
# ============================================================
```

Keep the structure easy to follow.

---

# 55. RECOMMENDED FUNCTIONS

Use functions similar to:

```python
load_environment()
load_config()
validate_config()
validate_safety_config()

stop_requested()

create_dhan_client()

print_order_summary()

build_order_request()
place_limit_order()

get_order_status()

modify_order()
cancel_order()

monitor_order()

run_dry_run()
confirm_live_order()

graceful_shutdown()

main()
```

Add helper functions only when they genuinely improve clarity.

Avoid unnecessary classes.

---

# 56. TYPE HINTS

Use simple type hints where helpful.

For example:

```python
def stop_requested() -> bool:
    ...

def load_config() -> dict:
    ...
```

Do not introduce complicated type systems.

---

# 57. DOCSTRINGS

Important functions should have short docstrings.

Example:

```python
def cancel_order(dhan, order_id):
    """
    Cancel an open Dhan order using its order ID.
    """
```

Keep them concise and useful.

---

# 58. READABLE VARIABLE NAMES

Use clear names such as:

```text
symbol
security_id
entry_price
limit_price
order_id
filled_quantity
remaining_quantity
modification_count
current_limit_price
cancel_after_seconds
poll_interval_seconds
```

Avoid unnecessarily cryptic names.

---

# 59. MAIN FUNCTION FLOW

Keep `main()` very easy to understand.

Use approximately:

```python
def main():

    config = load_config()

    load_environment()

    validate_config(config)

    validate_safety_config(config)

    if stop_requested():
        return

    print_order_summary(config)

    if config["safety"]["dry_run"]:
        run_dry_run(config)
        return

    if config["safety"]["require_confirmation"]:
        if not confirm_live_order(config):
            return

    if stop_requested():
        return

    dhan = create_dhan_client()

    if stop_requested():
        return

    order_id = place_limit_order(dhan, config)

    if not order_id:
        return

    monitor_order(dhan, config, order_id)
```

Adapt it to the actual implementation.

The final `main()` should clearly show the application's overall lifecycle.

---

# 60. ORDER LIFECYCLE

The code should follow this logical lifecycle:

```text
START
  ↓
LOAD ENVIRONMENT
  ↓
LOAD CONFIGURATION
  ↓
VALIDATE
  ↓
SAFETY CHECK
  ↓
DRY RUN / LIVE
  ↓
CREATE DHAN CLIENT
  ↓
PLACE LIMIT ORDER
  ↓
GET ORDER ID
  ↓
MONITOR ORDER
  ↓
MODIFY IF CONFIGURED
  ↓
CANCEL IF CONFIGURED
  ↓
FILLED / CANCELLED / REJECTED / EXPIRED
  ↓
EXIT
```

---

# 61. NO PERSISTENT DATABASE

Do not use:

* PostgreSQL
* MySQL
* MongoDB
* SQLite
* Redis

for this version.

Order state can remain in memory during the process.

The `.stop` filesystem signal is sufficient for stopping the bot.

---

# 62. SECURITY

Credentials must be:

```text
.env only
```

Never:

```text
hard-code credentials
store credentials in YAML
store credentials in Python
print credentials
log credentials
commit credentials
```

Create `.env` only with placeholders:

```env
DHAN_CLIENT_ID=your_client_id_here
DHAN_ACCESS_TOKEN=your_access_token_here
```

---

# 63. FINAL CONFIGURATION

The initial configuration should contain:

```yaml
instrument:
  symbol: "HDFCBANK"
  security_id: ""
  exchange_segment: "NSE_EQ"
```

Do not invent a security ID.

The bot must refuse to place an order until the user provides a valid security ID.

---

# 64. INSTALLATION REQUIREMENTS

After implementation, determine the actual minimum dependencies required by the Dhan SDK used.

Provide the correct installation command.

Do not blindly assume a package name.

`stop.py` must require only Python standard library.

---

# 65. FINAL COMMANDS

## Dry Run

```bash
python3 main.py
```

with:

```yaml
dry_run: true
```

## Live

Only after the user explicitly configures:

```yaml
dry_run: false
allow_live_trading: true
```

then:

```bash
python3 main.py
```

## AWS Background

```bash
nohup python3 main.py > algo.log 2>&1 &
```

## Stop

From another SSH session:

```bash
python3 stop.py
```

---

# 66. FINAL PROJECT

After implementation, the application must be runnable with:

```text
main.py
stop.py
config.yaml
.env
```

The reference files:

```text
docs/srp_dhan_helper.md
docs/Dhan_SRP.py
```

must NOT be required.

I will delete them later.

After deleting:

```text
docs/srp_dhan_helper.md
docs/Dhan_SRP.py
```

this command must still work:

```bash
python3 main.py
```

and:

```bash
python3 stop.py
```

---

# 67. FINAL TESTING REQUIREMENTS

Before considering the implementation complete, test at least:

## Configuration

```text
[ ] config.yaml loads
[ ] invalid YAML fails safely
[ ] missing config fails safely
[ ] missing security ID prevents trading
[ ] invalid quantity prevents trading
[ ] invalid price prevents trading
```

## Credentials

```text
[ ] .env loads
[ ] missing credentials fail safely
[ ] credentials are never logged
```

## Dry Run

```text
[ ] dry_run=true prevents real order placement
[ ] order summary is displayed
[ ] no Dhan order-placement call is made
```

## Live Safety

```text
[ ] live requires dry_run=false
[ ] live requires allow_live_trading=true
[ ] confirmation works
[ ] anything other than exact YES aborts
```

## Order

```text
[ ] correct LIMIT order request
[ ] correct order ID extraction
[ ] correct status handling
[ ] partial fills handled
[ ] modification works
[ ] modification limit works
[ ] cancellation works
[ ] cancellation timeout works
[ ] terminal states handled
```

## Duplicate Protection

```text
[ ] no blind placement retry
[ ] uncertain placement checks broker state
[ ] one entry order maximum per run
[ ] no automatic re-entry
```

## Stop

```text
[ ] stop.py creates .stop
[ ] main.py detects .stop
[ ] stop.py has no Dhan dependency
[ ] stop.py has no network dependency
[ ] no process killing
[ ] graceful shutdown
[ ] existing broker order is not automatically cancelled
```

## Deployment

```text
[ ] local Linux works
[ ] AWS Linux works
[ ] nohup works
[ ] low memory usage
[ ] headless operation
```

## Reference independence

```text
[ ] docs/srp_dhan_helper.md is not imported
[ ] docs/Dhan_SRP.py is not imported
[ ] docs directory is not required at runtime
[ ] deleting both reference files does not break the application
```

---

# 68. CODE QUALITY AND TECHNICAL EXPLANATION REQUIREMENT

Write the implementation so that the code can later be presented together with **clear explanations, code snippets, and step-by-step technical descriptions**.

The code should therefore be:

* logically organized
* readable
* easy to follow
* easy to explain line-by-line
* easy to extend
* based on meaningful function names
* based on meaningful variable names
* divided into clearly identifiable sections

Avoid:

* unnecessary abstractions
* unnecessarily complex classes
* clever one-liners
* overly compact code
* unnecessary design patterns
* unnecessary frameworks

Prefer straightforward code that makes the trading lifecycle obvious.

Important concepts should be clearly visible in the implementation:

```text
Configuration
Environment variables
Dhan authentication
Instrument details
Security ID
Order parameters
Entry price
Limit price
Order placement
Order ID
Order status
Partial fills
Order modification
Order cancellation
Timeout
Duplicate-order protection
Dry-run mode
Live-trading protection
Stop signal
Graceful shutdown
```

Use short comments when they explain an important **reason or design decision**.

For example:

```python
# Do not blindly retry order placement.
# A network timeout does not prove that Dhan rejected the order.
# The broker may already have accepted the order.
```

Comments should explain important decisions rather than simply repeating what the code does.

Keep the implementation technically reliable while also keeping it easy to understand.

The code should be suitable for being shown alongside detailed technical explanations and step-by-step code walkthroughs without requiring major rewriting.

---

# 69. FINAL IMPLEMENTATION INSTRUCTION

Now implement the complete application.

Do NOT return pseudocode.

Do NOT leave core functionality as TODO.

Do NOT create unnecessary files.

Do NOT invent Dhan APIs.

Do NOT invent Dhan parameters.

Do NOT blindly copy outdated reference code.

First inspect:

```text
docs/srp_dhan_helper.md
docs/Dhan_SRP.py
```

Then implement the required functionality directly in:

```text
main.py
stop.py
config.yaml
.env
```

The reference files are temporary and will later be deleted.

The final application MUST continue working after they are deleted.

Prioritize:

1. **Correct Dhan API/SDK implementation**
2. **Safe trading behavior**
3. **No duplicate orders**
4. **Correct order lifecycle**
5. **Simple architecture**
6. **Configuration-driven design**
7. **Low CPU/memory usage**
8. **Linux/AWS compatibility**
9. **Readable and explainable code**
10. **Easy future extension**

Do not add functionality outside the scope of this LIMIT Order Algo.
