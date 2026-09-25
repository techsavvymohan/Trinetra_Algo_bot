import logging
from typing import Optional

from ..models import PyraCluster, TradeDirection, TradeStatus, ExitReason
from ..risk.capital_adapter import CapitalAdapter, TrancheMode

log = logging.getLogger("xauusd_bot.order.partial")


class PartialCloseManager:
    def __init__(
        self,
        take_profit_r: float = 1.0,
        close_pct: float = 50.0,
        tranche2_r: Optional[float] = 2.2,
        tranche2_pct: Optional[float] = 35.0,
        enable_capital_adapter: bool = True,
    ):
        self.take_profit_r = take_profit_r
        self.close_pct = close_pct
        self.tranche2_r = tranche2_r
        self.tranche2_pct = tranche2_pct
        self.enable_capital_adapter = enable_capital_adapter
        self._tp_hit: set = set()
        self._tranche2_hit: set = set()
        self._clusters: list = []

    def check_partial_tp(self, cluster: PyraCluster, current_price: float) -> bool:
        if cluster not in self._clusters:
            self._clusters.append(cluster)
        cluster_id = cluster.cluster_id
        if getattr(cluster, "partial_tp1_hit", False) or cluster_id in self._tp_hit:
            return False
        avg_entry = cluster.avg_entry_price()
        if avg_entry <= 0:
            return False
        r_dist = cluster.r_distance() if hasattr(cluster, "r_distance") else 0.0
        if r_dist <= 0:
            r_dist = abs(avg_entry - cluster.collective_sl) if cluster.collective_sl else 0.0
        if r_dist <= 0:
            return False
        if cluster.direction == TradeDirection.BUY:
            move_r = (current_price - avg_entry) / r_dist
        else:
            move_r = (avg_entry - current_price) / r_dist

        target_r = cluster.dynamic_t1_r if getattr(cluster, "dynamic_t1_r", None) is not None else self.take_profit_r
        effective_close_pct = cluster.dynamic_t1_pct if getattr(cluster, "dynamic_t1_pct", None) is not None else self.close_pct
        if self.enable_capital_adapter:
            tot_vol = sum(getattr(l, "lot_size", 0.0) for l in cluster.legs if l.status == TradeStatus.OPEN)
            plan = CapitalAdapter.adapt_tranches(tot_vol, base_t1_pct=effective_close_pct, base_t1_r=target_r)
            target_r = plan.be_trigger_r

        if move_r >= target_r:
            cluster.partial_tp1_hit = True
            self._tp_hit.add(cluster_id)
            log.info("Partial TP Tranche 1 triggered: cluster=%s move=%.2fR (target=%.2fR) pct=%.0f%%",
                     cluster_id[:8], move_r, target_r, self.close_pct)
            return True
        return False

    def check_tranche2_tp(self, cluster: PyraCluster, current_price: float) -> bool:
        if not self.tranche2_r:
            return False
        if cluster not in self._clusters:
            self._clusters.append(cluster)
        cluster_id = cluster.cluster_id
        if not (getattr(cluster, "partial_tp1_hit", False) or cluster_id in self._tp_hit):
            return False
        if getattr(cluster, "partial_tp2_hit", False) or cluster_id in self._tranche2_hit:
            return False
        avg_entry = cluster.avg_entry_price()
        if avg_entry <= 0:
            return False
        r_dist = cluster.r_distance() if hasattr(cluster, "r_distance") else 0.0
        if r_dist <= 0:
            r_dist = abs(avg_entry - cluster.collective_sl) if cluster.collective_sl else 0.0
        if r_dist <= 0:
            return False
        if cluster.direction == TradeDirection.BUY:
            move_r = (current_price - avg_entry) / r_dist
        else:
            move_r = (avg_entry - current_price) / r_dist
        if move_r >= self.tranche2_r:
            cluster.partial_tp2_hit = True
            self._tranche2_hit.add(cluster_id)
            log.info("Partial TP Tranche 2 triggered: cluster=%s move=%.2fR pct=%.0f%%",
                     cluster_id[:8], move_r, self.tranche2_pct or 35.0)
            return True
        return False

    def reset(self):
        self._tp_hit.clear()
        self._tranche2_hit.clear()
        for c in self._clusters:
            c.partial_tp1_hit = False
            c.partial_tp2_hit = False
        self._clusters.clear()
