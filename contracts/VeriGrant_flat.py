# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
from dataclasses import dataclass, field
from genlayer import *
from genlayer.py.types import Address


@allow_storage
@dataclass
class Grant:
    id: str
    granter: Address
    total_budget: u256
    welfare_distributed: bool


@allow_storage
@dataclass
class Milestone:
    id: str
    grant_key: str
    submitter: Address
    target_criteria: str
    evidence_url: str
    predicted_points: u256
    reviewed_by: Address
    status: str = "pending"
    resolution_reasoning: str = ""
    resolution_confidence: u256 = 0


class VeriGrant(gl.Contract):
    """VeriGrant — escrow & verification of grant milestone submissions.

    A granter registers a Grant; contributors submit milestone evidence
    (docs, repos, posts) with target criteria; a reviewer triggers live
    web-fetch + LLM judgement that is agreed by validator consensus through
    the GenLayer Equivalence Principle, then the milestone is marked
    accepted/rejected and welfare is released only on acceptance.

    Identity & permissions (steward feedback, Aug 2026):
    - Every grant is identified by the composite key ``{owner}_{grant_id}``
      (owner address + grant id). Milestones reference that exact key, and
      the same key is used for lookup and welfare state, so a submitter can
      never associate with an unrelated same-named grant.
    - The grant owner is automatically contributor and reviewer. Additional
      contributors/reviewers are registered explicitly by the owner.
      ``submit_milestone`` requires contributor role; ``resolve_milestone``
      requires reviewer role and can never be called by the milestone's own
      submitter (no self-resolution).
    - On acceptance the referenced grant's ``welfare_distributed`` flag is
      set and the welfare ledger (keyed by grant key) is updated.
    """

    grants: TreeMap[Address, TreeMap[str, Grant]]
    milestones: TreeMap[Address, TreeMap[str, Milestone]]
    welfare: TreeMap[str, bool]
    contributors: TreeMap[str, TreeMap[Address, bool]]
    reviewers: TreeMap[str, TreeMap[Address, bool]]
    milestone_seq: TreeMap[Address, u256]

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _grant_key(self, owner: Address, grant_id: str) -> str:
        """Composite, unambiguous grant identifier: owner + grant id."""
        return f"{owner.as_hex}_{grant_id}"

    def _get_grant(self, owner: Address, grant_id: str) -> Grant:
        grants_for_owner = self.grants.get_or_insert_default(owner)
        if grant_id not in grants_for_owner:
            raise gl.vm.UserError("Grant not found")
        return grants_for_owner[grant_id]

    def _is_contributor(self, grant_key: str, addr: Address) -> bool:
        return self.contributors.get_or_insert_default(grant_key).get(addr, False)

    def _is_reviewer(self, grant_key: str, addr: Address) -> bool:
        return self.reviewers.get_or_insert_default(grant_key).get(addr, False)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    @gl.public.view
    def get_stats(self) -> dict:
        total_grants = 0
        total_milestones = 0
        pending = 0
        accepted = 0
        rejected = 0
        for _, grants in self.grants.items():
            total_grants += len(grants)
        for _, milestones in self.milestones.items():
            for _, m in milestones.items():
                total_milestones += 1
                if m.status == "pending":
                    pending += 1
                elif m.status == "accepted":
                    accepted += 1
                elif m.status == "rejected":
                    rejected += 1
        return {
            "total_grants": total_grants,
            "total_milestones": total_milestones,
            "pending": pending,
            "accepted": accepted,
            "rejected": rejected,
        }

    @gl.public.view
    def get_milestones_by_submitter(self, submitter: str) -> dict:
        addr = Address(submitter)
        return {
            mid: {"id": m.id, "grant_key": m.grant_key, "status": m.status}
            for mid, m in self.milestones.get(addr, {}).items()
        }

    @gl.public.view
    def get_welfare_state(self, owner: str, grant_id: str) -> str:
        """Welfare state of one unambiguous grant (owner + grant id).

        'distributed' if the grant's welfare ledger is released (set when a
        milestone of that grant is accepted), else 'locked'.
        """
        grant_key = self._grant_key(Address(owner), grant_id)
        if self.welfare.get(grant_key, False):
            return "distributed"
        return "locked"

    @gl.public.view
    def get_grant(self, owner: str, grant_id: str) -> dict:
        grant = self._get_grant(Address(owner), grant_id)
        return {
            "id": grant.id,
            "granter": grant.granter.as_hex,
            "total_budget": int(grant.total_budget),
            "welfare_distributed": grant.welfare_distributed,
        }

    @gl.public.view
    def get_roles(self, owner: str, grant_id: str) -> dict:
        grant_key = self._grant_key(Address(owner), grant_id)
        return {
            "contributors": [
                a.as_hex for a, ok in self.contributors.get_or_insert_default(grant_key).items() if ok
            ],
            "reviewers": [
                a.as_hex for a, ok in self.reviewers.get_or_insert_default(grant_key).items() if ok
            ],
        }

    # ------------------------------------------------------------------
    # Grant management
    # ------------------------------------------------------------------
    @gl.public.write
    def create_grant(self, grant_id: str, total_budget: u256) -> None:
        sender = gl.message.sender_address
        grants_for_sender = self.grants.get_or_insert_default(sender)
        if grant_id in grants_for_sender:
            raise gl.vm.UserError("Grant already exists")
        grants_for_sender[grant_id] = Grant(
            id=grant_id, granter=sender, total_budget=total_budget, welfare_distributed=False
        )
        # Owner is automatically contributor and reviewer for their grant.
        grant_key = self._grant_key(sender, grant_id)
        self.contributors.get_or_insert_default(grant_key)[sender] = True
        self.reviewers.get_or_insert_default(grant_key)[sender] = True

    @gl.public.write
    def destroy_grant(self, grant_id: str) -> None:
        sender = gl.message.sender_address
        grants_for_sender = self.grants.get_or_insert_default(sender)
        if grant_id not in grants_for_sender:
            raise gl.vm.UserError("Grant not found")
        del grants_for_sender[grant_id]

    # ------------------------------------------------------------------
    # Role management (owner-only)
    # ------------------------------------------------------------------
    @gl.public.write
    def add_contributor(self, grant_id: str, contributor: str) -> None:
        sender = gl.message.sender_address
        self._get_grant(sender, grant_id)  # owner-only: reverts otherwise
        grant_key = self._grant_key(sender, grant_id)
        self.contributors.get_or_insert_default(grant_key)[Address(contributor)] = True

    @gl.public.write
    def add_reviewer(self, grant_id: str, reviewer: str) -> None:
        sender = gl.message.sender_address
        self._get_grant(sender, grant_id)  # owner-only: reverts otherwise
        grant_key = self._grant_key(sender, grant_id)
        self.reviewers.get_or_insert_default(grant_key)[Address(reviewer)] = True

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_milestone(
        self,
        grant_owner: str,
        grant_id: str,
        target_criteria: str,
        evidence_url: str,
        predicted_points: int = 10,
    ) -> None:
        if not (evidence_url.startswith("http://") or evidence_url.startswith("https://")):
            raise gl.vm.UserError("Invalid evidence_url: must be an http(s) URL")
        sender = gl.message.sender_address

        # Milestone references one unambiguous grant: owner + grant id.
        owner = Address(grant_owner)
        grant = self._get_grant(owner, grant_id)
        grant_key = self._grant_key(owner, grant_id)

        # Contributor permission: submitter must be registered for THIS grant.
        if not self._is_contributor(grant_key, sender):
            raise gl.vm.UserError("Not a contributor of this grant")

        seq = self.milestone_seq.get_or_insert_default(sender)
        self.milestone_seq[sender] = seq + 1
        mid = f"{sender.as_hex}_{seq}"

        milestones = self.milestones.get_or_insert_default(sender)
        milestones[mid] = Milestone(
            id=mid,
            grant_key=grant_key,
            submitter=sender,
            target_criteria=target_criteria,
            evidence_url=evidence_url,
            predicted_points=predicted_points,
            reviewed_by=sender,
        )

    # ------------------------------------------------------------------
    # Equivalence-Principle resolution (web + LLM + consensus)
    # ------------------------------------------------------------------
    @gl.public.write
    def resolve_milestone(self, submitter: str, midpoint: str) -> dict:
        sender = gl.message.sender_address
        sub_addr = Address(submitter)
        milestones = self.milestones.get_or_insert_default(sub_addr)
        if midpoint not in milestones:
            raise gl.vm.UserError("Milestone not found")
        ms = milestones[midpoint]
        if ms.status != "pending":
            raise gl.vm.UserError(f"Milestone already resolved: {ms.status}")

        # Reviewer permission: caller must be a registered reviewer of the
        # grant this milestone references, and can never be the submitter
        # (no self-resolution).
        if sender == ms.submitter:
            raise gl.vm.UserError("Submitter cannot resolve their own milestone")
        if not self._is_reviewer(ms.grant_key, sender):
            raise gl.vm.UserError("Not a reviewer of this grant")

        # Leader: fetch live evidence and judge it. Both leader and validators
        # run this independently inside the equivalence block.
        def leader_fn() -> dict:
            web_data = gl.nondet.web.render(ms.evidence_url, mode="html")
            task = f"""You are a grants steward on GenLayer.

Evaluate whether this milestone evidence satisfies the stated criteria.

Grant key: {ms.grant_key}
Milestone target criteria: "{ms.target_criteria}"
Evidence URL: {ms.evidence_url}
Evidence page content (HTML - may be truncated): {web_data[:12000]}

Respond in JSON with EXACTLY these fields:
{{
  "accepted": bool,     // true if criteria met, false if not
  "reasoning": "brief justification",
  "confidence": 0-100   // integer confidence in the decision
}}

Rules:
- Only accept if the evidence clearly demonstrates the criteria are met.
- Reject if the page is missing, unrelated, or does not demonstrate completion.
- Never invent evidence that is not in the page content.
It is mandatory that you respond ONLY with valid JSON and nothing else.
"""
            # In production, response_format="json" makes the node return a
            # dict. Direct mode auto-parses the mocked JSON string the same way.
            result = gl.nondet.exec_prompt(task, response_format="json")

            if isinstance(result, dict):
                return result

            s = str(result).strip()
            if s.startswith("```"):
                lines = [ln for ln in s.splitlines() if not ln.strip().startswith("```")]
                s = "\n".join(lines)
            start, end = s.find("{"), s.rfind("}") + 1
            if start >= 0 and end > start:
                s = s[start:end]
            return json.loads(s)

        # Validator: leader and validator both judge independently; they must
        # agree on the binary decision and be within tolerance on confidence.
        def validator_fn(leader_result) -> bool:
            try:
                leader = leader_result.calldata
            except Exception:
                return False
            try:
                mine = leader_fn()
            except Exception:
                return False
            try:
                if leader["accepted"] != mine["accepted"]:
                    return False
                if abs(int(leader.get("confidence", 0)) - int(mine.get("confidence", 0))) > 40:
                    return False
                return True
            except Exception:
                return False

        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        accepted = bool(result.get("accepted"))
        ms.status = "accepted" if accepted else "rejected"
        ms.reviewed_by = sender
        ms.resolution_reasoning = str(result.get("reasoning", ""))
        ms.resolution_confidence = u256(int(result.get("confidence", 0)))
        milestones[midpoint] = ms

        if accepted:
            # Update the referenced grant's welfare state (same composite
            # key used for lookup) and record it in the welfare ledger.
            self.welfare[ms.grant_key] = True
            owner_hex, _, gid = ms.grant_key.partition("_")
            grants_for_owner = self.grants.get_or_insert_default(Address(owner_hex))
            if gid in grants_for_owner:
                g = grants_for_owner[gid]
                g.welfare_distributed = True
                grants_for_owner[gid] = g

        return {
            "accepted": accepted,
            "reasoning": ms.resolution_reasoning,
            "confidence": int(ms.resolution_confidence),
        }
