"""Session 9.7 — the threat-model doc exists and covers every data tier."""

from pathlib import Path

from app.models import DataTier

_DOC = Path(__file__).resolve().parents[1] / "docs" / "THREAT_MODEL.md"


def test_threat_model_documents_every_tier() -> None:
    assert _DOC.exists(), "docs/THREAT_MODEL.md is missing"
    text = _DOC.read_text()
    # Every data tier the code supports must be documented.
    for tier in DataTier:
        assert str(tier) in text, f"threat model does not cover tier {tier}"
    # It must not overpromise: state that non-TEE tiers expose runtime plaintext.
    assert "runtime" in text.lower()
    assert "does not defend" in text.lower() or "does NOT defend" in text
