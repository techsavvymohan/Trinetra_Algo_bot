import logging
from datetime import datetime, timezone
from typing import Optional

from ..models import AccountInfo, DailyState
from ..utils.time_utils import broker_date

log = logging.getLogger("xauusd_bot.risk.daily_loss")


class CallableFloat(float):
    """Float subclass that can also be invoked as a callable `()` for backwards compatibility."""
    def __call__(self) -> float:
        return float(self)


class DailyLossTracker:
    def __init__(self, daily_limit_pct: float = 3.0, buffer_pct: float = 1.0,
                 reset_hour: int = 0, reset_tz: str = "UTC"):
        self.limit_pct = daily_limit_pct
        self.buffer_pct = buffer_pct
        self.reset_hour = reset_hour
        self.reset_tz = reset_tz
        self.state: Optional[DailyState] = None

    def calibrate_from_broker(self, connector, account: AccountInfo):
        """Calibrate day start equity and daily PnL directly from live broker closed deals (Zero DB dependency)."""
        ref_time = account.server_time or datetime.now(timezone.utc).replace(tzinfo=None)
        today = broker_date(ref_time, self.reset_hour, self.reset_tz)

        today_pnl = 0.0
        trades_count = 0
        if connector and hasattr(connector, "history_deals_get"):
            try:
                today_midnight = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                deals = connector.history_deals_get(today_midnight, datetime.now(timezone.utc))
                if deals:
                    for d in deals:
                        entry_type = getattr(d, "entry", None)
                        if entry_type in (1, "out", "DEAL_ENTRY_OUT", 3, "DEAL_ENTRY_OUT_BY"):
                            today_pnl += (getattr(d, "profit", 0.0) + getattr(d, "swap", 0.0) + getattr(d, "commission", 0.0))
                            trades_count += 1
            except Exception as e:
                log.warning("Could not fetch broker history deals for calibration: %s", e)

        start_equity = max(1.0, account.balance - today_pnl)
        peak_equity = max(start_equity, account.equity)

        self.state = DailyState(
            date=today,
            start_equity=start_equity,
            current_equity=account.equity,
            peak_equity=peak_equity,
            daily_pnl=account.equity - start_equity,
            trades_today=trades_count,
            kill_switch_active=False,
        )
        log.info(
            "🎯 Dynamic Broker Daily Calibration: date=%s start_equity=%.2f current_equity=%.2f today_pnl=%.2f trades=%d",
            today, start_equity, account.equity, today_pnl, trades_count,
        )

    def update(self, account: AccountInfo, connector=None):
        today = broker_date(account.server_time or datetime.now(timezone.utc).replace(tzinfo=None),
                            self.reset_hour, self.reset_tz)
        if self.state is None or self.state.date != today:
            if connector is not None:
                self.calibrate_from_broker(connector, account)
            else:
                # FTMO/Prop-firm rule: anchor day start to max(balance, equity) to protect against midnight floating drawdown
                start_equity = max(account.balance, account.equity)
                self.state = DailyState(
                    date=today,
                    start_equity=start_equity,
                    current_equity=account.equity,
                    peak_equity=max(start_equity, account.equity),
                    daily_pnl=account.equity - start_equity,
                    trades_today=0,
                    kill_switch_active=False,
                )
                log.info("New daily state: date=%s start_equity=%.2f (balance=%.2f equity=%.2f)",
                         today, start_equity, account.balance, account.equity)
        else:
            self.state.current_equity = account.equity
            self.state.daily_pnl = account.equity - self.state.start_equity
            if account.equity > self.state.peak_equity:
                self.state.peak_equity = account.equity

    def loss_used_pct(self) -> CallableFloat:
        if self.state is None or self.state.start_equity <= 0:
            return CallableFloat(0.0)
        return CallableFloat(max(0.0, -self.state.daily_pnl / self.state.start_equity * 100))

    def current_daily_loss_pct(self) -> CallableFloat:
        return self.loss_used_pct()

    def remaining_budget_pct(self) -> float:
        used = self.loss_used_pct()
        return max(0.0, self.limit_pct - used)

    def remaining_budget_amount(self) -> float:
        if self.state is None:
            return 0.0
        used_amount = max(0.0, -self.state.daily_pnl)
        max_loss = self.state.start_equity * (self.limit_pct / 100.0)
        return max(0.0, max_loss - used_amount)

    def effective_remaining_pct(self) -> float:
        return max(0.0, self.limit_pct - self.buffer_pct - self.loss_used_pct())

    def kill_switch_engaged(self) -> bool:
        if self.state is None:
            return False
        if self.state.kill_switch_active:
            return True
        if self.loss_used_pct() >= (self.limit_pct - self.buffer_pct):
            self.state.kill_switch_active = True
            log.warning("DAILY LOSS KILL SWITCH — used=%.2f%% limit=%.2f%% buffer=%.2f%%",
                        self.loss_used_pct(), self.limit_pct, self.buffer_pct)
            return True
        return False

    def register_trade(self):
        if self.state:
            self.state.trades_today += 1

    def reset(self):
        self.state = None
