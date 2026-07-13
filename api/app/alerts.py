"""Alerting on symptoms (Session 12.7).

Alerts fire on user-visible symptoms tied to the top failure modes in the runbooks:
a stuck scheduler (queue backing up), mass provider dropout (too few connected), and a
ledger discrepancy (money invariant broken). ``evaluate_alerts`` is pure over a signal
snapshot so it's trivially testable and can drive Prometheus rules or an inline check.
"""

from dataclasses import dataclass
from typing import Literal

from app.config import Settings

Severity = Literal["warning", "critical"]


@dataclass(frozen=True)
class Alert:
    name: str
    severity: Severity
    message: str


def evaluate_alerts(signals: dict, settings: Settings) -> list[Alert]:
    """Return the alerts firing for a snapshot of ``signals``.

    Signals: ``queue_depth``, ``providers_connected``, ``ledger_discrepancies``,
    ``chain_divergences``.
    """
    alerts: list[Alert] = []

    if int(signals.get("chain_divergences", 0)) > 0:
        alerts.append(
            Alert(
                "chain_ledger_divergence",
                "critical",
                f"{signals['chain_divergences']} on-chain vs off-chain divergence(s) — settlement "
                "and the ledger disagree; freeze settlement and reconcile (see RUNBOOKS.md).",
            )
        )

    if int(signals.get("ledger_discrepancies", 0)) > 0:
        alerts.append(
            Alert(
                "ledger_discrepancy",
                "critical",
                f"{signals['ledger_discrepancies']} unbalanced ledger group(s) — money "
                "invariant broken; freeze settlement and investigate (see RUNBOOKS.md).",
            )
        )

    if int(signals.get("providers_connected", 0)) < settings.alert_min_connected_providers:
        alerts.append(
            Alert(
                "mass_provider_dropout",
                "critical",
                f"only {signals.get('providers_connected', 0)} provider(s) connected — "
                "below the floor; jobs will stall.",
            )
        )

    if int(signals.get("queue_depth", 0)) > settings.alert_queue_backlog:
        alerts.append(
            Alert(
                "scheduler_backlog",
                "warning",
                f"queue depth {signals['queue_depth']} over {settings.alert_queue_backlog} — "
                "scheduler may be stuck or under-provisioned.",
            )
        )

    return alerts
