import sys
import MetaTrader5 as mt5

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")
from xauusd_bot.config import Config

cfg = Config.load()
print(f"Loaded from .env:")
print(f"  Login:    {cfg.mt5.login}")
print(f"  Server:   {cfg.mt5.server}")
print(f"  Path:     {cfg.mt5.path}")
print(f"  Timeout:  {cfg.mt5.timeout_ms} ms")

print("\nAttempt 1: mt5.initialize() without credentials (attach to currently running terminal)...")
res1 = mt5.initialize()
if res1:
    term = mt5.terminal_info()
    acc = mt5.account_info()
    print(f"  ✅ Attached to terminal successfully!")
    print(f"  Terminal Path: {term.path if term else 'N/A'}")
    print(f"  Current Account in Terminal: {acc.login if acc else 'None'} on {acc.server if acc else 'None'}")
    
    # Now try mt5.login() to switch account inside the attached terminal
    print(f"\nAttempt 2: mt5.login(login={cfg.mt5.login}, server='{cfg.mt5.server}') inside attached terminal...")
    logged_in = mt5.login(login=cfg.mt5.login, password=cfg.mt5.password, server=cfg.mt5.server)
    if logged_in:
        acc2 = mt5.account_info()
        print(f"  🎉 SUCCESS! Switched to: {acc2.login} on {acc2.server} | Balance: {acc2.balance} | Equity: {acc2.equity}")
    else:
        err = mt5.last_error()
        print(f"  ❌ mt5.login() failed: {err}")
    mt5.shutdown()
else:
    err = mt5.last_error()
    print(f"  ❌ mt5.initialize() attach failed: {err}")

print("\nAttempt 3: mt5.initialize(path=..., login=..., timeout=30000)...")
res3 = mt5.initialize(
    path=cfg.mt5.path,
    login=cfg.mt5.login,
    password=cfg.mt5.password,
    server=cfg.mt5.server,
    timeout=30000,
)
if res3:
    acc3 = mt5.account_info()
    print(f"  🎉 SUCCESS with 30s timeout! Account: {acc3.login} on {acc3.server}")
    mt5.shutdown()
else:
    err3 = mt5.last_error()
    print(f"  ❌ Failed with 30s timeout: {err3}")
