import pytest
import os
from xauusd_bot.config import Config, TradingConfig

def test_symbol_specific_defaults():
    tc = TradingConfig()
    # Gold defaults
    assert tc.get_target_r("XAUUSD") == 2.0
    assert tc.get_breakeven_trigger_r("XAUUSD") == 1.5
    assert tc.get_max_holding_bars("XAUUSD") == 0
    assert tc.xau_session_cutoff_hour == 24

    # Nasdaq 100 dedicated defaults
    assert tc.get_target_r("USTECH100M") == 2.0
    assert tc.get_breakeven_trigger_r("USTECH100M") == 1.5
    assert tc.get_max_holding_bars("USTECH100M") == 0
    assert tc.get_risk_per_trade("USTECH100M") == 0.02
    assert tc.nas_session_start_hour == 13
    assert tc.nas_session_start_minute == 30
    assert tc.nas_session_end_hour == 16

def test_symbol_specific_case_insensitivity():
    tc = TradingConfig()
    assert tc.get_target_r("ustech100m") == 2.0
    assert tc.get_target_r("NAS100") == 2.0
    assert tc.get_target_r("xauusd") == 2.0
    assert tc.get_max_holding_bars("nas100") == 0
    assert tc.get_max_holding_bars("xauusd") == 0
    assert tc.get_risk_per_trade("ustech100m") == 0.02

def test_symbol_specific_env_overrides(monkeypatch):
    monkeypatch.setenv("NAS_TARGET_R", "1.8")
    monkeypatch.setenv("NAS_BREAKEVEN_TRIGGER_R", "1.3")
    monkeypatch.setenv("NAS_MAX_HOLDING_BARS", "240")
    monkeypatch.setenv("NAS_RISK_PER_TRADE", "0.02")
    monkeypatch.setenv("XAU_SESSION_CUTOFF_HOUR", "12")

    tc = TradingConfig.from_env()
    assert tc.xau_session_cutoff_hour == 12
    assert tc.nas_target_r == 1.8
    assert tc.nas_breakeven_trigger_r == 1.3
    assert tc.nas_max_holding_bars == 240
    assert tc.nas_risk_per_trade == 0.02

    assert tc.get_target_r("USTECH100M") == 1.8
    assert tc.get_breakeven_trigger_r("USTECH100M") == 1.3
    assert tc.get_max_holding_bars("USTECH100M") == 240
    assert tc.get_risk_per_trade("USTECH100M") == 0.02

    # Ensure Gold remains unchanged
    assert tc.get_target_r("XAUUSD") == 2.0
    assert tc.get_breakeven_trigger_r("XAUUSD") == 1.5
    assert tc.get_max_holding_bars("XAUUSD") == 0

def test_symbol_specific_min_sl_distance():
    tc = TradingConfig()
    assert tc.get_min_sl_distance("XAUUSD") == 5.0
    assert tc.get_min_sl_distance("USTECH100M") == 10.0

def test_symbol_specific_min_sl_distance_env_overrides(monkeypatch):
    monkeypatch.setenv("XAU_MIN_SL_DISTANCE", "6.5")
    monkeypatch.setenv("NAS_MIN_SL_DISTANCE", "8.0")

    tc = TradingConfig.from_env()
    assert tc.xau_min_sl_distance == 6.5
    assert tc.nas_min_sl_distance == 8.0
    assert tc.get_min_sl_distance("XAUUSD") == 6.5
    assert tc.get_min_sl_distance("USTECH100M") == 8.0


def test_resolve_broker_symbol_scenarios(monkeypatch):
    from types import SimpleNamespace
    from xauusd_bot.broker.mt5_connector import MT5Connector
    from xauusd_bot.config import MT5Config

    connector = MT5Connector(MT5Config())

    # Mock MT5 module with custom symbol catalogs
    class MockMT5:
        SYMBOL_TRADE_MODE_DISABLED = 0
        SYMBOL_TRADE_MODE_FULL = 4

        def __init__(self, catalog):
            self._catalog = {s.name: s for s in catalog}

        def symbol_info(self, name):
            return self._catalog.get(name)

        def symbol_select(self, name, enable):
            return name in self._catalog

        def symbols_get(self):
            return list(self._catalog.values())

    import xauusd_bot.broker.mt5_connector as mc

    # Scenario 1: Broker with .x suffix (e.g. FundedSquad)
    fundedsquad_catalog = [
        SimpleNamespace(name="XAUUSD.x", trade_mode=4),
        SimpleNamespace(name="USTECH100M.x", trade_mode=4),
    ]
    monkeypatch.setattr(mc, "mt5", MockMT5(fundedsquad_catalog))

    assert connector.resolve_broker_symbol("XAUUSD") == "XAUUSD.x"
    assert connector.resolve_broker_symbol("USTECH100M") == "USTECH100M.x"
    assert connector.resolve_broker_symbol("GOLD") == "XAUUSD.x"
    assert connector.resolve_broker_symbol("XAUUSD.x") == "XAUUSD.x"

    # Scenario 2: Broker with .pro suffix (e.g. Vantage)
    vantage_catalog = [
        SimpleNamespace(name="XAUUSD.pro", trade_mode=4),
        SimpleNamespace(name="USTECH100M.pro", trade_mode=4),
    ]
    monkeypatch.setattr(mc, "mt5", MockMT5(vantage_catalog))

    assert connector.resolve_broker_symbol("XAUUSD.x") == "XAUUSD.pro"
    assert connector.resolve_broker_symbol("USTECH100M.x") == "USTECH100M.pro"
    assert connector.resolve_broker_symbol("XAUUSD") == "XAUUSD.pro"

    # Scenario 3: Standard broker without suffixes (e.g. MetaQuotes-Demo)
    standard_catalog = [
        SimpleNamespace(name="XAUUSD", trade_mode=4),
        SimpleNamespace(name="USTECH100M", trade_mode=4),
    ]
    monkeypatch.setattr(mc, "mt5", MockMT5(standard_catalog))

    assert connector.resolve_broker_symbol("XAUUSD.x") == "XAUUSD"
    assert connector.resolve_broker_symbol("USTECH100M.x") == "USTECH100M"
    assert connector.resolve_broker_symbol("GOLD") == "XAUUSD"
