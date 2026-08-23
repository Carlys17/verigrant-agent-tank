"""Direct-mode tests for the VeriGrant intelligent contract package."""

import json
import os

from tests.direct.conftest import to_hex

# Single-file deploy path so direct mode can load it.
CONTRACT_PACKAGE = "contracts/VeriGrant_flat.py"


def _mock_evidence(vm, accepted: bool, confidence: int = 80, reasoning: str = "ok"):
    payload = json.dumps({
        "accepted": accepted,
        "reasoning": reasoning,
        "confidence": confidence,
    })
    vm.mock_web(
        r"github\.com/carlys17/.*",
        {"status": 200, "body": "<html>README, docs and tests</html>"},
    )
    vm.mock_llm(r".*Evaluate whether.*", payload)


def test_create_grant_and_view(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice

    contract.create_grant("grant-open-source", 1000)
    assert contract.get_welfare_state("grant-open-source") == "locked"

    stats = contract.get_stats()
    assert stats["total_grants"] == 1


def test_submit_requires_existing_grant(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Grant does not exist"):
        contract.submit_milestone(
            "ghost-grant",
            "Deploy docs",
            "https://github.com/carlys17/x",
            10,
        )


def test_submit_rejects_bad_url(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)

    with direct_vm.expect_revert("Invalid evidence_url"):
        contract.submit_milestone(
            "g1", "x", "ftp://bad", 10
        )


def test_accept_milestone_awards_welfare(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)

    contract.submit_milestone(
        "g1",
        "Ship a documented primitive with tests",
        "https://github.com/carlys17/verigrant-contract",
        10,
    )
    milestones = contract.get_milestones_by_submitter(to_hex(direct_alice))
    assert len(milestones) == 1
    mid = list(milestones.keys())[0]
    assert milestones[mid]["status"] == "pending"

    _mock_evidence(direct_vm, accepted=True, confidence=92)
    result = contract.resolve_milestone(mid)

    assert result["accepted"] is True
    assert result["confidence"] == 92
    assert contract.get_welfare_state("g1") == "distributed"


def test_reject_milestone_no_welfare(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)

    contract.submit_milestone(
        "g1",
        "Ship a documented primitive with tests",
        "https://github.com/carlys17/verigrant-tests",
        10,
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_alice)).keys())[0]

    _mock_evidence(direct_vm, accepted=False, confidence=20, reasoning="no evidence")
    result = contract.resolve_milestone(mid)

    assert result["accepted"] is False
    assert contract.get_welfare_state("g1") == "locked"


def test_validator_rejects_on_disagreement(direct_vm, direct_deploy, direct_alice):
    """Leader says accepted, validator says rejected => validator disagrees.

    Note: direct mode applies the leader's result immediately (no consensus
    rollback simulation), so we only assert the validator's independent
    verdict is False. On a real network this disagreement would rotate the
    leader / leave the transaction undetermined.
    """
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.submit_milestone(
        "g1", "x", "https://github.com/carlys17/verigrant-contract", 10
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_alice)).keys())[0]

    # Leader mock: accepted
    _mock_evidence(direct_vm, accepted=True, confidence=90)
    # Fire the resolve as leader and capture the validator function
    contract.resolve_milestone(mid)

    # Now swap to a dissenting validator (rejected)
    direct_vm.clear_mocks()
    _mock_evidence(direct_vm, accepted=False, confidence=10)
    assert direct_vm.run_validator() is False


def test_cannot_resolve_twice(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.submit_milestone(
        "g1", "x", "https://github.com/carlys17/verigrant-contract", 10
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_alice)).keys())[0]

    _mock_evidence(direct_vm, accepted=True)
    contract.resolve_milestone(mid)

    with direct_vm.expect_revert("already resolved"):
        contract.resolve_milestone(mid)


def test_destroy_grant(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    assert contract.get_stats()["total_grants"] == 1

    contract.destroy_grant("g1")
    assert contract.get_stats()["total_grants"] == 0
