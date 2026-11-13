import hashlib

import pytest

from agent.services.production_rule_compliance import split_rule_findings, verify_rule_snapshot


def test_verify_rule_snapshot_accepts_exact_snapshotted_content():
    content = "# Brand\n\n---\n\n# Video Rule"
    digest = hashlib.sha256(content.encode()).hexdigest()

    assert verify_rule_snapshot(content, digest, digest) == digest


@pytest.mark.parametrize(
    "content,snapshot,stored",
    [
        (None, "hash", "hash"),
        ("rule", None, "hash"),
        ("rule", "wrong", hashlib.sha256(b"rule").hexdigest()),
    ],
)
def test_verify_rule_snapshot_blocks_missing_or_changed_rule(content, snapshot, stored):
    with pytest.raises(RuntimeError, match="Rule snapshot"):
        verify_rule_snapshot(content, snapshot, stored)


def test_asset_and_workflow_findings_are_warnings_not_content_blockers():
    hard, warnings = split_rule_findings([
        "WORKFLOW_CONFLICT: voice provider differs",
        "NEEDS_INPUT: missing footage and logo",
        "FACT_ERROR: unverified price",
        "LANGUAGE_ERROR: narration is English",
    ])

    assert hard == ["FACT_ERROR: unverified price", "LANGUAGE_ERROR: narration is English"]
    assert warnings == [
        "WORKFLOW_CONFLICT: voice provider differs",
        "NEEDS_INPUT: missing footage and logo",
    ]
