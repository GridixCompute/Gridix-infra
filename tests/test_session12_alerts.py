"""Session 12.7 — each top failure mode has an alert that fires in test."""

from pathlib import Path

from app.alerts import evaluate_alerts
from app.config import get_settings


def _names(signals) -> set[str]:
    return {a.name for a in evaluate_alerts(signals, get_settings())}


def test_healthy_snapshot_fires_nothing() -> None:
    assert _names({"queue_depth": 5, "providers_connected": 10, "ledger_discrepancies": 0}) == set()


def test_ledger_discrepancy_fires_critical() -> None:
    alerts = evaluate_alerts(
        {"queue_depth": 0, "providers_connected": 5, "ledger_discrepancies": 1}, get_settings()
    )
    ledger = next(a for a in alerts if a.name == "ledger_discrepancy")
    assert ledger.severity == "critical"


def test_mass_provider_dropout_fires() -> None:
    assert "mass_provider_dropout" in _names(
        {"queue_depth": 0, "providers_connected": 0, "ledger_discrepancies": 0}
    )


def test_scheduler_backlog_fires() -> None:
    s = get_settings()
    assert "scheduler_backlog" in _names(
        {
            "queue_depth": s.alert_queue_backlog + 1,
            "providers_connected": 5,
            "ledger_discrepancies": 0,
        }
    )


def test_runbooks_cover_each_alert() -> None:
    doc = (Path(__file__).resolve().parents[1] / "docs" / "RUNBOOKS.md").read_text()
    for name in ("ledger_discrepancy", "mass_provider_dropout", "scheduler_backlog"):
        assert name in doc, f"no runbook/alert entry for {name}"
