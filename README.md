# VeriGrant — Grant Milestone Verification on GenLayer

An Intelligent Contract primitive that turns grant milestone review into a
trustless, consensus-verified process. Granters register grants, contributors
submit milestone evidence (repos, docs, posts), and a reviewer triggers a
live web-fetch + LLM judgement that is agreed by validator consensus through
the GenLayer **Equivalence Principle** before any welfare is released.

Built for the GenLayer Points program — **Intelligent Contracts** category
(contribution type 52).

## Why this is not a demo

- **Real consensus logic.** `resolve_milestone` uses a custom
  `leader_fn` / `validator_fn` pair with `gl.vm.run_nondet_unsafe`. The
  validator independently re-fetches the evidence and re-runs the judgement;
  it only accepts the leader's result if both agree on the binary decision
  and are within a confidence tolerance. A validator that always returns
  `True` would defeat consensus — this one does not.
- **Clear state design.** Grants, milestones, welfare ledger, and a
  deterministic milestone-id counter are stored in typed `TreeMap` storage
  with `@allow_storage` dataclasses. No `dict`/`list` in storage, no
  non-deterministic writes outside the equivalence block.
- **Thoughtful validator.** The validator checks the decision fields
  (`accepted`, `confidence`) rather than free-text reasoning, tolerates LLM
  nondeterminism, and rejects on doubt.
- **A use case that matters beyond a one-off.** Grant milestone verification
  is a recurring, real problem for every grant program (including GenLayer's
  own). This primitive is reusable by any grant/funding dApp.

## What it does

1. `create_grant(grant_id, total_budget)` — a granter registers a grant.
   The grant's unambiguous identity is the composite key
   `{owner}_{grant_id}`; the owner is automatically contributor and
   reviewer of their own grant.
2. `add_contributor(grant_id, address)` / `add_reviewer(grant_id, address)`
   — owner-only role registration.
3. `submit_milestone(grant_owner, grant_id, target_criteria, evidence_url, predicted_points)`
   — a registered contributor submits milestone evidence against stated
   criteria. The milestone stores the exact composite grant key, so it can
   never be associated with an unrelated same-named grant.
4. `resolve_milestone(submitter, midpoint)` — a registered reviewer (never
   the submitter) triggers live evidence fetch + LLM judgement under the
   Equivalence Principle. On consensus acceptance the milestone is marked
   `accepted`, the referenced grant's `welfare_distributed` flag is set and
   the welfare ledger (keyed by the same composite grant key) is released;
   otherwise `rejected`.
5. Views: `get_stats`, `get_milestones_by_submitter`,
   `get_welfare_state(owner, grant_id)`, `get_grant(owner, grant_id)`,
   `get_roles(owner, grant_id)`.

## Consensus flow

```
resolve_milestone(midpoint)
  └─ leader_fn():  gl.nondet.web.render(evidence_url)  →  gl.nondet.exec_prompt(...)
                   → {"accepted": bool, "reasoning": str, "confidence": 0-100}
  └─ validator_fn(leader_result):
        re-run leader_fn() independently
        accept only if:
          leader.accepted == mine.accepted
          |leader.confidence - mine.confidence| <= 40
  └─ gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        → majority of validators must agree, else leader rotates / undetermined
```

## Project structure

```
contracts/
  VeriGrant_flat.py        # The intelligent contract (single-file, deployable)
tests/
  direct/
    test_verigrant.py      # 8 direct-mode tests (web + LLM mocked)
    conftest.py            # shared helpers
gltest.config.yaml         # network config for integration tests
requirements.txt           # genlayer-py, genlayer-test, genvm-linter
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Lint the contract
genvm-lint check contracts/VeriGrant_flat.py

# Run direct-mode tests (fast, no Studio needed)
pytest tests/direct/test_verigrant.py -v
```

## Testing

Direct mode runs the contract in-memory with mocked web/LLM responses:

| Test | What it verifies |
|------|------------------|
| `test_create_grant_and_view` | grant creation + stats |
| `test_submit_requires_existing_grant` | revert on unknown grant |
| `test_submit_rejects_bad_url` | URL validation |
| `test_submit_requires_contributor_role` | contributor permission enforced |
| `test_same_name_grant_isolation` | same-named grants from different owners stay distinct |
| `test_accept_milestone_awards_welfare` | accepted → grant welfare flag + ledger released |
| `test_reject_milestone_no_welfare` | rejected → welfare stays locked |
| `test_submitter_cannot_self_resolve` | no self-resolution |
| `test_resolve_requires_reviewer_role` | reviewer permission enforced |
| `test_validator_rejects_on_disagreement` | validator independently disagrees |
| `test_cannot_resolve_twice` | idempotency guard |
| `test_destroy_grant` | grant teardown |

```
$ pytest tests/direct/ -q
12 passed in 1.08s
```

## Deploying

```bash
genlayer network set studionet     # or testnet
genlayer deploy --contract contracts/VeriGrant_flat.py
```

Or paste `contracts/VeriGrant_flat.py` into [GenLayer Studio](https://studio.genlayer.com/)
and deploy from the browser IDE.

**Current deployment (studionet):**
`0xc64a0C81e434c76FEb2DB244681a717556A11097`
([explorer](https://explorer-studio.genlayer.com/address/0xc64a0C81e434c76FEb2DB244681a717556A11097))
— deployed from `contracts/VeriGrant_flat.py` at commit `71b28cc`, source
hash-verified identical to this repo.

## Security notes

- The validator never trusts the leader; it re-fetches and re-judges.
- Confidence tolerance (±40) absorbs LLM nondeterminism without letting a
  rejection flip into an acceptance.
- `gl.vm.UserError` is used for all user-facing reverts (not bare `Exception`).
- Evidence HTML is truncated to 12k chars before prompting to bound cost.

## License

MIT
