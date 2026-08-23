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
    grant_id: str
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
    """

    grants: TreeMap[Address, TreeMap[str, Grant]]
    milestones: TreeMap[Address, TreeMap[str, Milestone]]
    welfare: TreeMap[Address, TreeMap[str, bool]]
    milestone_seq: TreeMap[Address, u256]

    def __init__(self) -> None:
        pass

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
            mid: {"id": m.id, "grant_id": m.grant_id, "status": m.status}
            for mid, m in self.milestones.get(addr, {}).items()
        }

    @gl.public.view
    def get_welfare_state(self, grant_id: str) -> str:
        """Return 'distributed' if any accepted milestone exists for the grant."""
        for _, milestones in self.milestones.items():
            for _, m in milestones.items():
                if m.grant_id == grant_id and m.status == "accepted":
                    return "distributed"
        return "locked"

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

    @gl.public.write
    def destroy_grant(self, grant_id: str) -> None:
        sender = gl.message.sender_address
        grants_for_sender = self.grants.get_or_insert_default(sender)
        if grant_id not in grants_for_sender:
            raise gl.vm.UserError("Grant not found")
        del grants_for_sender[grant_id]

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------
    @gl.public.write
    def submit_milestone(
        self,
        grant_id: str,
        target_criteria: str,
        evidence_url: str,
        predicted_points: int = 10,
    ) -> None:
        if not (evidence_url.startswith("http://") or evidence_url.startswith("https://")):
            raise gl.vm.UserError("Invalid evidence_url: must be an http(s) URL")
        sender = gl.message.sender_address

        grant_found = False
        for _, grants in self.grants.items():
            if grant_id in grants:
                grant_found = True
                break
        if not grant_found:
            raise gl.vm.UserError("Grant does not exist")

        seq = self.milestone_seq.get_or_insert_default(sender)
        self.milestone_seq[sender] = seq + 1
        mid = f"{sender}_{seq}"

        milestones = self.milestones.get_or_insert_default(sender)
        milestones[mid] = Milestone(
            id=mid,
            grant_id=grant_id,
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
    def resolve_milestone(self, midpoint: str) -> dict:
        sender = gl.message.sender_address
        milestones = self.milestones.get_or_insert_default(sender)
        if midpoint not in milestones:
            raise gl.vm.UserError("Milestone not found for sender")
        ms = milestones[midpoint]
        if ms.status != "pending":
            raise gl.vm.UserError(f"Milestone already resolved: {ms.status}")

        # Leader: fetch live evidence and judge it. Both leader and validators
        # run this independently inside the equivalence block.
        def leader_fn() -> dict:
            web_data = gl.nondet.web.render(ms.evidence_url, mode="html")
            task = f"""You are a grants steward on GenLayer.

Evaluate whether this milestone evidence satisfies the stated criteria.

Grant ID: {ms.grant_id}
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
            welfare = self.welfare.get_or_insert_default(sender)
            welfare[midpoint] = True

        return {
            "accepted": accepted,
            "reasoning": ms.resolution_reasoning,
            "confidence": int(ms.resolution_confidence),
        }
