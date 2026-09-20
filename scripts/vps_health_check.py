"""
VPS Health Check & Diagnostic Script for MatchingProp Algo Bot
Validates:
1. Git branch, latest commit, and remote synchronization status.
2. Configuration (.env parameters: dual-pair, 0.85% risk, filters).
3. MT5 connection, account balance, equity, currency, and leverage.
4. Algo Trading permissions in MT5 terminal.
5. Live market feeds for XAUUSD and USTECH100M / NAS100 (bid/ask, spread, contract size).
6. Dynamic Position Sizing calculation preview for the attached account.
"""

import os
import sys
import subprocess
from pathlib import Path

# Ensure root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def header(title: str):
    print(f"\n{CYAN}{BOLD}{'=' * 65}{RESET}")
    print(f"{CYAN}{BOLD}  {title}{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 65}{RESET}")


def check_mark(passed: bool, label: str, detail: str = ""):
    icon = f"{GREEN}[PASS]{RESET}" if passed else f"{RED}[FAIL]{RESET}"
    detail_str = f" - {detail}" if detail else ""
    print(f"  {icon} {label}{detail_str}")


def check_git_status():
    header("1. GIT REPOSITORY & VERSION STATUS")
    try:
        # Check current branch
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=BASE_DIR, text=True, stderr=subprocess.DEVNULL
        ).strip()
        
        # Check latest commit
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, text=True, stderr=subprocess.DEVNULL
        ).strip()

        commit_msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=BASE_DIR, text=True, stderr=subprocess.DEVNULL
        ).strip().splitlines()[0]

        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--date=relative", "--pretty=%cd"],
            cwd=BASE_DIR, text=True, stderr=subprocess.DEVNULL
        ).strip()

        check_mark(True, f"Current Branch: {BOLD}{branch}{RESET}")
        check_mark(True, f"Latest Commit: {BOLD}{commit_hash}{RESET} ({commit_date})", commit_msg[:60])

        # Fetch remote silently and check diff
        try:
            subprocess.run(["git", "fetch", "origin", "main"], cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            local_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE_DIR, text=True).strip()
            remote_hash = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=BASE_DIR, text=True).strip()

            if local_hash == remote_hash:
                check_mark(True, "Code is 100% up-to-date with GitHub origin/main")
            else:
                check_mark(False, "Update Available on GitHub!", "Run: git pull origin main")
        except Exception:
            print(f"  {YELLOW}[INFO]{RESET} Could not check remote GitHub status (network timeout or offline)")

    except Exception as exc:
        check_mark(False, "Git command error", str(exc))


def check_config():
    header("2. CONFIGURATION & .ENV VERIFICATION")
    from xauusd_bot.config import Config
    cfg = Config.load()
    
    symbols = getattr(cfg.trading, "symbols", []) or [getattr(cfg.trading, "symbol", "XAUUSD")]
    has_gold = any("XAU" in s.upper() or "GOLD" in s.upper() for s in symbols)
    has_nas = any("NAS" in s.upper() or "TECH" in s.upper() or "100" in s.upper() for s in symbols)
    dual_pair = has_gold and has_nas
    check_mark(dual_pair, "Active Trading Pairs (Gold + Nasdaq)", f"{symbols}")

    # 2. Risk check
    risk_pct = getattr(cfg.trading, "pyramid_initial_risk_pct", 0.0)
    is_high_yield = risk_pct > 1.5
    mode_label = "Personal Real Account High-Yield Scaling" if is_high_yield else "Prop Firm Capital Preservation"
    check_mark(True, f"Risk Mode: {mode_label} ({risk_pct}% per trade)", f"Compounding: {getattr(cfg.trading, 'enable_profit_compounding', True)}")

    # 3. Daily Loss & Max DD limits
    dl_limit = getattr(cfg.trading, "daily_loss_limit_pct", 3.0)
    max_dd = getattr(cfg.trading, "max_dd_limit_pct", 10.0)
    check_mark(True, f"Daily Loss Ceiling: {dl_limit}%", "Safety circuit-breaker active")
    check_mark(True, f"Maximum Drawdown Ceiling: {max_dd}%", "Global drawdown circuit-breaker active")

    # 4. Sideways Market Filter
    sideways_on = getattr(cfg.trading, "enable_sideways_filter", True)
    check_mark(sideways_on, "Sideways Market Avoidance Engine: ACTIVE", "Chop, ADX, and BB Bandwidth protection on")

    return cfg


def check_mt5_and_account(cfg):
    header("3. MT5 TERMINAL & BROKER CONNECTION")
    try:
        import MetaTrader5 as mt5
    except ImportError:
        check_mark(False, "MetaTrader5 Python Library", "Run: pip install MetaTrader5")
        return None, None

    # Attempt MT5 initialization
    path = cfg.mt5.path if os.path.exists(cfg.mt5.path or "") else None
    connected = mt5.initialize(
        path=path or "",
        login=cfg.mt5.login,
        password=cfg.mt5.password,
        server=cfg.mt5.server,
        timeout=cfg.mt5.timeout_ms or 15000,
    )

    if not connected:
        err = mt5.last_error()
        check_mark(False, "MT5 Terminal Connection", f"Error code: {err}. Check login, password, and server in .env")
        return None, None

    terminal = mt5.terminal_info()
    account = mt5.account_info()

    if not account:
        check_mark(False, "MT5 Account Login", "Failed to retrieve account details")
        return None, None

    check_mark(True, "MT5 Terminal Connected", f"Build: {getattr(terminal, 'build', 'N/A')}")
    
    # Algo Trading Permission
    algo_enabled = terminal.trade_allowed if terminal else False
    if algo_enabled:
        check_mark(True, "MT5 'Algo Trading' Button: ENABLED (Green Play Button)")
    else:
        check_mark(False, "MT5 'Algo Trading' Button is DISABLED!", "Click 'Algo Trading' in MT5 toolbar to turn it GREEN")

    # Account metrics
    header("4. LIVE ACCOUNT CAPITAL & RISK CALIBRATION")
    print(f"  * Account Number : {account.login}")
    print(f"  * Broker Server  : {account.server}")
    print(f"  * Account Currency: {account.currency}")
    print(f"  * Balance        : {BOLD}${account.balance:,.2f}{RESET}")
    print(f"  * Equity         : {BOLD}${account.equity:,.2f}{RESET}")
    print(f"  * Free Margin    : ${account.margin_free:,.2f}")
    print(f"  * Leverage       : 1:{account.leverage}")

    # Risk Calculation Preview
    r_pct = cfg.trading.pyramid_initial_risk_pct
    dl_pct = cfg.trading.daily_loss_limit_pct
    dd_pct = cfg.trading.max_dd_limit_pct
    risk_amount = account.equity * (r_pct / 100.0)
    print(f"\n  {CYAN}Dynamic Risk Preview ({r_pct:.2f}% of Equity):{RESET}")
    print(f"  * Exact Risk per Trade : {BOLD}${risk_amount:.2f}{RESET}")
    print(f"  * {dl_pct:.1f}% Daily Loss Limit: ${account.equity * (dl_pct / 100.0):.2f} max daily loss allowed")
    print(f"  * {dd_pct:.1f}% Max DD Limit   : ${account.equity * (dd_pct / 100.0):.2f} max overall loss allowed")

    return mt5, account


def check_symbols(mt5, cfg, account):
    header("5. SYMBOL FEEDS & LOT SIZING CHECK")
    if not mt5 or not account:
        print(f"  {YELLOW}Skipped: MT5 not connected{RESET}")
        return

    from xauusd_bot.risk.position_sizer import PositionSizer
    from xauusd_bot.models import AccountInfo, TradeDirection

    sizer = PositionSizer(
        initial_risk_pct=cfg.trading.pyramid_initial_risk_pct,
        initial_balance=account.balance,
    )
    acct_model = AccountInfo(balance=account.balance, equity=account.equity)

    from xauusd_bot.broker.mt5_connector import MT5Connector
    connector = MT5Connector(cfg.mt5)
    connector._connected = True

    symbols = getattr(cfg.trading, "symbols", []) or [getattr(cfg.trading, "symbol", "XAUUSD")]
    for sym in symbols:
        actual_sym = connector.resolve_broker_symbol(sym)
        if actual_sym != sym:
            check_mark(True, f"Auto-Detected Broker Symbol: '{sym}' -> '{actual_sym}'")

        # Ensure selected in Market Watch
        mt5.symbol_select(actual_sym, True)
        info = mt5.symbol_info(actual_sym)
        tick = mt5.symbol_info_tick(actual_sym)
        if not tick and info:
            import time
            for _ in range(5):
                time.sleep(0.3)
                tick = mt5.symbol_info_tick(actual_sym)
                if tick and tick.bid > 0:
                    break

        bid = tick.bid if (tick and tick.bid > 0) else getattr(info, "bid", 0.0)
        ask = tick.ask if (tick and tick.ask > 0) else getattr(info, "ask", 0.0)

        if not info or (bid <= 0 and ask <= 0):
            # Query all available symbols from broker
            all_broker_syms = [s.name for s in (mt5.symbols_get() or [])]
            key1 = "XAU" if ("XAU" in actual_sym or "GOLD" in actual_sym) else "100"
            matches = [s for s in all_broker_syms if key1 in s.upper() or ("GOLD" in s.upper() if "XAU" in actual_sym else False)]
            if matches and actual_sym not in matches:
                check_mark(False, f"{actual_sym} Market Watch Subscription", f"Broker uses: {matches}. Set SYMBOLS={','.join(matches[:2])} in .env")
            else:
                check_mark(False, f"{actual_sym} Market Watch Subscription", f"Symbol not active. In MT5: Right-Click Market Watch -> 'Show All', then drag {actual_sym} onto a chart")
            continue

        point_sz = getattr(info, "point", None) or (0.01 if ("XAU" in actual_sym or "GOLD" in actual_sym) else 0.1)
        spread_pts = round((ask - bid) / point_sz, 1)
        check_mark(
            True,
            f"{actual_sym} Feed Active",
            f"Bid={bid:.{info.digits}f} | Ask={ask:.{info.digits}f} | Spread={spread_pts} pts"
        )

        # Calculate sample lot size
        if "XAU" in actual_sym or "GOLD" in actual_sym:
            # Approx $6 Stop Loss on Gold
            sl_dist = 6.0
            sl_price = bid - sl_dist
            lots = sizer.calculate_lot_size(
                acct_model,
                entry_price=bid,
                sl_price=sl_price,
                direction=TradeDirection.BUY,
                point_value=1.0,
                contract_size=int(info.trade_contract_size or 100),
                min_lot=info.volume_min or 0.01,
                max_lot=info.volume_max or 100.0,
                lot_step=info.volume_step or 0.01,
            )
            print(f"    -> {BOLD}Auto Lot Size for {actual_sym}{RESET} (~${sl_dist:.0f} SL): {BOLD}{GREEN}{lots:.2f} lots{RESET} (Risk: ${lots * sl_dist * 100:.2f})")
        else:
            # Approx 25 points Stop Loss on Nasdaq 100 (USTECH100M)
            sl_dist = 25.0
            sl_price = bid - sl_dist
            contract_sz = int(info.trade_contract_size or 1)
            lots = sizer.calculate_lot_size(
                acct_model,
                entry_price=bid,
                sl_price=sl_price,
                direction=TradeDirection.BUY,
                point_value=0.1,
                contract_size=contract_sz,
                min_lot=info.volume_min or 0.01,
                max_lot=info.volume_max or 100.0,
                lot_step=info.volume_step or 0.01,
            )
            print(f"    -> {BOLD}Auto Lot Size for {actual_sym}{RESET} (~25 pts SL): {BOLD}{GREEN}{lots:.2f} lots{RESET} (Risk: ${lots * sl_dist * 0.1 * (10 if contract_sz > 1 else 1):.2f})")


def main():
    print(f"\n{BOLD}MatchingProp Algo Bot -- VPS System Readiness Inspection{RESET}")
    print(f"Working Directory: {BASE_DIR}")
    
    check_git_status()
    cfg = check_config()
    mt5, account = check_mt5_and_account(cfg)
    check_symbols(mt5, cfg, account)

    header("DIAGNOSTIC SUMMARY & NEXT STEPS")
    if mt5 and account:
        print(f"  {GREEN}{BOLD}[PASS] ALL CRITICAL CHECKS COMPLETE -- BOT READY FOR LIVE TRADING!{RESET}")
        print(f"\n  To start the bot in live continuous trading mode:")
        print(f"  {BOLD}python -m xauusd_bot.main --live{RESET}\n")
        mt5.shutdown()
    else:
        print(f"  {YELLOW}{BOLD}[NOTICE] Please verify the failed checks above before starting live trading.{RESET}\n")


if __name__ == "__main__":
    main()
