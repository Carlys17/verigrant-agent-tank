"""Direct-mode tests for the VeriGrant intelligent contract package."""

import json

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
    assert contract.get_welfare_state(to_hex(direct_alice), "grant-open-source") == "locked"

    stats = contract.get_stats()
    assert stats["total_grants"] == 1


def test_submit_requires_existing_grant(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("Grant not found"):
        contract.submit_milestone(
            to_hex(direct_alice),
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
            to_hex(direct_alice), "g1", "x", "ftp://bad", 10
        )


def test_submit_requires_contributor_role(direct_vm, direct_deploy, direct_alice, direct_bob):
    """A submitter who is not a registered contributor cannot submit."""
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Not a contributor"):
        contract.submit_milestone(
            to_hex(direct_alice), "g1", "x", "https://github.com/carlys17/x", 10
        )


def test_same_name_grant_isolation(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """Two grants with the same id from different owners are distinct.

    Charlie is contributor of bob's 'g1' only; submitting against alice's
    same-named 'g1' must revert, not silently associate.
    """
    contract = direct_deploy(CONTRACT_PACKAGE)

    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)

    direct_vm.sender = direct_bob
    contract.create_grant("g1", 200)
    contract.add_contributor("g1", to_hex(direct_charlie))

    direct_vm.sender = direct_charlie
    # Against alice's g1: charlie is not a contributor there.
    with direct_vm.expect_revert("Not a contributor"):
        contract.submit_milestone(
            to_hex(direct_alice), "g1", "x", "https://github.com/carlys17/x", 10
        )
    # Against bob's g1: allowed.
    contract.submit_milestone(
        to_hex(direct_bob), "g1", "x", "https://github.com/carlys17/x", 10
    )
    assert len(contract.get_milestones_by_submitter(to_hex(direct_charlie))) == 1


def test_accept_milestone_awards_welfare(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.add_contributor("g1", to_hex(direct_bob))
    contract.add_reviewer("g1", to_hex(direct_charlie))

    direct_vm.sender = direct_bob
    contract.submit_milestone(
        to_hex(direct_alice),
        "g1",
        "Ship a documented primitive with tests",
        "https://github.com/carlys17/verigrant-contract",
        10,
    )
    milestones = contract.get_milestones_by_submitter(to_hex(direct_bob))
    assert len(milestones) == 1
    mid = list(milestones.keys())[0]
    assert milestones[mid]["status"] == "pending"

    _mock_evidence(direct_vm, accepted=True, confidence=92)
    direct_vm.sender = direct_charlie
    result = contract.resolve_milestone(to_hex(direct_bob), mid)

    assert result["accepted"] is True
    assert result["confidence"] == 92
    assert contract.get_welfare_state(to_hex(direct_alice), "g1") == "distributed"
    grant = contract.get_grant(to_hex(direct_alice), "g1")
    assert grant["welfare_distributed"] is True


def test_reject_milestone_no_welfare(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.add_contributor("g1", to_hex(direct_bob))
    contract.add_reviewer("g1", to_hex(direct_charlie))

    direct_vm.sender = direct_bob
    contract.submit_milestone(
        to_hex(direct_alice),
        "g1",
        "Ship a documented primitive with tests",
        "https://github.com/carlys17/verigrant-tests",
        10,
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_bob)).keys())[0]

    _mock_evidence(direct_vm, accepted=False, confidence=20, reasoning="no evidence")
    direct_vm.sender = direct_charlie
    result = contract.resolve_milestone(to_hex(direct_bob), mid)

    assert result["accepted"] is False
    assert contract.get_welfare_state(to_hex(direct_alice), "g1") == "locked"
    grant = contract.get_grant(to_hex(direct_alice), "g1")
    assert grant["welfare_distributed"] is False


def test_submitter_cannot_self_resolve(direct_vm, direct_deploy, direct_alice, direct_bob):
    """The milestone submitter must not be able to resolve their own milestone."""
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.add_contributor("g1", to_hex(direct_bob))

    direct_vm.sender = direct_bob
    contract.submit_milestone(
        to_hex(direct_alice), "g1", "x", "https://github.com/carlys17/x", 10
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_bob)).keys())[0]

    _mock_evidence(direct_vm, accepted=True)
    with direct_vm.expect_revert("Submitter cannot resolve"):
        contract.resolve_milestone(to_hex(direct_bob), mid)


def test_resolve_requires_reviewer_role(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """A caller who is not a registered reviewer cannot resolve."""
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.add_contributor("g1", to_hex(direct_bob))

    direct_vm.sender = direct_bob
    contract.submit_milestone(
        to_hex(direct_alice), "g1", "x", "https://github.com/carlys17/x", 10
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_bob)).keys())[0]

    _mock_evidence(direct_vm, accepted=True)
    direct_vm.sender = direct_charlie  # not a reviewer
    with direct_vm.expect_revert("Not a reviewer"):
        contract.resolve_milestone(to_hex(direct_bob), mid)


def test_validator_rejects_on_disagreement(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """Leader says accepted, validator says rejected => validator disagrees."""
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.add_contributor("g1", to_hex(direct_bob))
    contract.add_reviewer("g1", to_hex(direct_charlie))

    direct_vm.sender = direct_bob
    contract.submit_milestone(
        to_hex(direct_alice), "g1", "x", "https://github.com/carlys17/verigrant-contract", 10
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_bob)).keys())[0]

    _mock_evidence(direct_vm, accepted=True, confidence=90)
    direct_vm.sender = direct_charlie
    contract.resolve_milestone(to_hex(direct_bob), mid)

    direct_vm.clear_mocks()
    _mock_evidence(direct_vm, accepted=False, confidence=10)
    assert direct_vm.run_validator() is False


def test_cannot_resolve_twice(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    contract.add_contributor("g1", to_hex(direct_bob))
    contract.add_reviewer("g1", to_hex(direct_charlie))

    direct_vm.sender = direct_bob
    contract.submit_milestone(
        to_hex(direct_alice), "g1", "x", "https://github.com/carlys17/verigrant-contract", 10
    )
    mid = list(contract.get_milestones_by_submitter(to_hex(direct_bob)).keys())[0]

    _mock_evidence(direct_vm, accepted=True)
    direct_vm.sender = direct_charlie
    contract.resolve_milestone(to_hex(direct_bob), mid)

    with direct_vm.expect_revert("already resolved"):
        contract.resolve_milestone(to_hex(direct_bob), mid)


def test_destroy_grant(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT_PACKAGE)
    direct_vm.sender = direct_alice
    contract.create_grant("g1", 100)
    assert contract.get_stats()["total_grants"] == 1

    contract.destroy_grant("g1")
    assert contract.get_stats()["total_grants"] == 0
