"""Conservative, in-memory outcome status evaluation.

The evaluator consumes only an outcome envelope and verification results.  It
does not inspect tool success, execute providers, persist state, or mutate the
envelope.  Completion is evidence-driven and requires every named completion
criterion to have a VERIFIED result.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

try:  # Supports package imports and the repository's direct test imports.
    from .outcome import OutcomeEnvelope, OutcomeStatus, VerificationResult, VerificationStatus
except ImportError:  # pragma: no cover - exercised by direct pytest collection
    from outcome import OutcomeEnvelope, OutcomeStatus, VerificationResult, VerificationStatus


TERMINAL_FAILURES = frozenset({
    VerificationStatus.FAILED,
    VerificationStatus.EXPIRED,
    VerificationStatus.REVOKED,
})


def _recovery_permitted(outcome: OutcomeEnvelope) -> bool:
    """Read an explicit recovery opt-in without inferring policy from prose."""

    policy = outcome.recovery_policy
    return policy.get("allow_recovery") is True or policy.get("recovery_permitted") is True


def evaluate_outcome(
    outcome: OutcomeEnvelope,
    verification_results: Iterable[VerificationResult],
) -> OutcomeStatus:
    """Return the most conservative next status supported by verification.

    ``VerificationResult.checked`` is the only criterion mapping accepted by
    this slice. Results for another outcome are ignored for completion and
    treated as a failed correlation. Duplicate/conflicting result statuses for
    the same criterion produce ``DISPUTED``. A terminal failure wins over
    partial completion; recoverable non-terminal evidence can produce
    ``RECOVERY_REQUIRED`` only when the outcome explicitly permits recovery.
    """

    results = tuple(verification_results)
    if not results:
        return OutcomeStatus.RECOVERY_REQUIRED if _recovery_permitted(outcome) else OutcomeStatus.PARTIALLY_COMPLETED

    if any(result.outcome_id != outcome.outcome_id for result in results):
        return OutcomeStatus.FAILED

    by_criterion: dict[str, list[VerificationResult]] = defaultdict(list)
    for result in results:
        for criterion in result.checked:
            by_criterion[criterion].append(result)

    if any(result.status is VerificationStatus.CONFLICTING for result in results):
        return OutcomeStatus.DISPUTED

    # More than one result for a criterion is only safe when all agree. Any
    # disagreement is unresolved evidence, not a successful verification.
    for criterion in outcome.completion_criteria:
        statuses = {result.status for result in by_criterion.get(criterion, ())}
        if len(statuses) > 1:
            return OutcomeStatus.DISPUTED

    statuses = {result.status for result in results}
    if statuses & TERMINAL_FAILURES:
        return OutcomeStatus.RECOVERY_REQUIRED if _recovery_permitted(outcome) else OutcomeStatus.FAILED

    if statuses & {VerificationStatus.INSUFFICIENT, VerificationStatus.PENDING}:
        if _recovery_permitted(outcome):
            return OutcomeStatus.RECOVERY_REQUIRED

    verified_criteria = {
        criterion
        for criterion in outcome.completion_criteria
        if any(result.status is VerificationStatus.VERIFIED for result in by_criterion.get(criterion, ()))
    }
    required = set(outcome.completion_criteria)
    if verified_criteria == required:
        return OutcomeStatus.COMPLETED
    if verified_criteria:
        return OutcomeStatus.PARTIALLY_COMPLETED
    return OutcomeStatus.PARTIALLY_COMPLETED
