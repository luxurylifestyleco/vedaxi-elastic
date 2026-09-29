"""Recipe DAG Runner for Elastic Web (Phase 11/12).

Validates recipe step dependencies, computes topological execution order,
resolves input parameters and cross-step dependencies, executes steps via
a pluggable executor callable, emits telemetry events, and collects
per-step and aggregate execution metrics.
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

# Ensure sibling packages (recipe-schema, telemetry) are importable.
_PACKAGES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PACKAGES_DIR not in sys.path:
    sys.path.insert(0, _PACKAGES_DIR)

_RECIPE_SCHEMA_DIR = os.path.join(_PACKAGES_DIR, "recipe-schema")
if _RECIPE_SCHEMA_DIR not in sys.path:
    sys.path.insert(0, _RECIPE_SCHEMA_DIR)

_ASSURANCE_DIR = os.path.join(_PACKAGES_DIR, "assurance-protocol")
if _ASSURANCE_DIR not in sys.path:
    sys.path.insert(0, _ASSURANCE_DIR)

from assurance import OutcomeClaim  # noqa: E402
from recipe import Recipe, RecipeStatus, RecipeStep  # noqa: E402

# Executor callable: (capability_id, args) -> result
Executor = Callable[[str, Dict[str, Any]], Any]


@dataclass
class StepMetric:
    """Telemetry metrics collected for a single step execution."""

    step_id: str
    capability_id: str
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


class ExecutionResult(dict):
    """Dictionary-compatible execution result with attribute access.

    Attributes:
        recipe_id: The id of the executed recipe.
        intent_family: The family of the executed recipe.
        results: Mapping of step_id to step execution output.
        metrics: Standard metric dictionary matching Control A/B/C.
        success: Whether the entire DAG completed successfully.
        error: Error message if execution failed.
        step_metrics: Detailed per-step latency and status records.
    """

    def __init__(
        self,
        recipe_id: str,
        intent_family: str,
        results: Dict[str, Any],
        metrics: Dict[str, Any],
        success: bool = True,
        error: Optional[str] = None,
        step_metrics: Optional[List[StepMetric]] = None,
        outcome_claim: Optional[Dict[str, Any]] = None,
        failed_stage: Optional[str] = None,
        side_effect_state: Optional[str] = None,
        retryable: Optional[bool] = None,
    ) -> None:
        super().__init__(
            recipe_id=recipe_id,
            intent_family=intent_family,
            results=results,
            metrics=metrics,
            success=success,
            error=error,
            step_metrics=step_metrics or [],
            outcome_claim=outcome_claim,
            failed_stage=failed_stage,
            side_effect_state=side_effect_state,
            retryable=retryable,
        )

    @property
    def recipe_id(self) -> str:
        return self["recipe_id"]

    @property
    def intent_family(self) -> str:
        return self["intent_family"]

    @property
    def results(self) -> Dict[str, Any]:
        return self["results"]

    @property
    def metrics(self) -> Dict[str, Any]:
        return self["metrics"]

    @property
    def success(self) -> bool:
        return self["success"]

    @property
    def error(self) -> Optional[str]:
        return self.get("error")

    @property
    def step_metrics(self) -> List[StepMetric]:
        return self["step_metrics"]

    @property
    def outcome_claim(self) -> Optional[Dict[str, Any]]:
        return self.get("outcome_claim")


class RecipeDAGRunner:
    """Executes recipes according to their dependency Directed Acyclic Graph (DAG).

    Responsibilities:
      - Validates step dependency definitions and ensures absence of cycles.
      - Resolves topological order using Kahn's algorithm.
      - Resolves step arguments by combining declared defaults, external input
        parameters, and outputs from upstream steps.
      - Dispatches each step to an executor callable.
      - Emits telemetry events (recipe.started, recipe.step.started, tool.called,
        tool.completed, recipe.completed, execution.failed).
      - Collects fine-grained step metrics and benchmark-compatible aggregate metrics.
    """

    def __init__(
        self,
        executor: Optional[Executor] = None,
        bus: Optional[Any] = None,
    ) -> None:
        self.executor = executor or self._default_executor
        self.bus = bus

    @staticmethod
    def _default_executor(capability_id: str, args: Dict[str, Any]) -> Any:
        """Default no-op executor when none is supplied."""
        return {"ok": True, "capability": capability_id, "args": args}

    @staticmethod
    def _claim_outcome(
        requested_outcome: str,
        results: Dict[str, Any],
        trace_id: str,
    ) -> OutcomeClaim:
        """Describe provider evidence without promoting execution to outcome success."""
        if not results:
            return OutcomeClaim(
                requested_outcome=requested_outcome,
                achieved_state="unknown",
                verification_type="unknown",
                remaining_gap="No provider result was returned",
            )
        result = next(reversed(results.values()))
        if isinstance(result, dict):
            status = result.get("status")
            if not status and not (set(result) - {"ok"}):
                return OutcomeClaim(
                    requested_outcome=requested_outcome,
                    achieved_state="unknown",
                    verification_type="unknown",
                    evidence_refs=[trace_id],
                    remaining_gap="Provider returned no outcome evidence",
                )
            if isinstance(status, str) and status.strip():
                achieved = status.strip().lower()
            else:
                achieved = "result_returned"
            return OutcomeClaim(
                requested_outcome=requested_outcome,
                achieved_state=achieved,
                verification_type="provider_reported",
                evidence_refs=[trace_id],
                remaining_gap=(
                    None
                    if achieved.replace("_", " ") == requested_outcome.lower()
                    else "Requested outcome was not independently verified"
                ),
            )
        return OutcomeClaim(
            requested_outcome=requested_outcome,
            achieved_state="result_returned",
            verification_type="provider_reported",
            evidence_refs=[trace_id],
            remaining_gap="Requested outcome was not independently verified",
        )

    # ------------------------------------------------------------------
    # Validation & Topological Ordering
    # ------------------------------------------------------------------

    @staticmethod
    def validate_dependencies(steps: Sequence[RecipeStep]) -> None:
        """Validate that step dependencies exist and contain no cycles.

        Args:
            steps: Ordered or unordered list of RecipeStep objects.

        Raises:
            ValueError: If a depends_on points to an unknown step id,
                or if a cycle is detected.
        """
        step_ids = {s.step_id for s in steps}
        for step in steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(
                        f"Step '{step.step_id}' depends on unknown step '{dep}'"
                    )

        # Kahn's algorithm cycle check
        indegree: Dict[str, int] = {s.step_id: 0 for s in steps}
        dependents: Dict[str, List[str]] = {s.step_id: [] for s in steps}
        for step in steps:
            for dep in step.depends_on:
                indegree[step.step_id] += 1
                dependents[dep].append(step.step_id)

        ready = [sid for sid, deg in indegree.items() if deg == 0]
        visited_count = 0
        while ready:
            curr = ready.pop(0)
            visited_count += 1
            for child in dependents[curr]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)

        if visited_count != len(steps):
            raise ValueError("Recipe steps contain a cycle")

    @classmethod
    def topological_order(cls, steps: Sequence[RecipeStep]) -> List[str]:
        """Compute the topological sort order of step IDs.

        Args:
            steps: Collection of RecipeStep objects.

        Returns:
            List of step IDs ordered such that dependencies precede dependents.

        Raises:
            ValueError: If dependencies contain a cycle or unknown references.
        """
        cls.validate_dependencies(steps)
        indegree: Dict[str, int] = {s.step_id: 0 for s in steps}
        dependents: Dict[str, List[str]] = {s.step_id: [] for s in steps}
        for step in steps:
            for dep in step.depends_on:
                indegree[step.step_id] += 1
                dependents[dep].append(step.step_id)

        ready = [sid for sid, deg in indegree.items() if deg == 0]
        order: List[str] = []
        while ready:
            curr = ready.pop(0)
            order.append(curr)
            for child in dependents[curr]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        return order

    # ------------------------------------------------------------------
    # Parameter Resolution
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_parameters(
        step: RecipeStep,
        params: Optional[Dict[str, Any]] = None,
        step_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve inputs for a step by blending step args, runtime params,
        and upstream step results.

        Resolution strategy:
          1. Start with a shallow copy of declared ``step.args``.
          2. Apply runtime ``params``:
             - Any key in ``params`` that overrides an existing arg is updated.
             - Any key in ``params`` that provides an input not declared in ``step.args``
               is added.
          3. Interpolate string references:
             - Templated references like ``"${param_key}"`` or ``"$param_key"``
               are substituted with values from ``params``.
             - Cross-step references like ``"$steps.<step_id>.<key>"`` or
               ``"${<step_id>.<key>}"`` or ``"$<step_id>.<key>"`` are substituted
               from ``step_results``.
        """
        resolved: Dict[str, Any] = dict(step.args)
        params = params or {}
        step_results = step_results or {}

        # 1. Overlay runtime params
        for k, v in params.items():
            resolved[k] = v

        # 2. Value substitution for strings
        def _resolve_val(val: Any) -> Any:
            if not isinstance(val, str):
                return val

            # Check if value is a pure reference: e.g. "$step_id.key" or "${step_id.key}"
            ref_match = re.fullmatch(r"\$\{?([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\}?", val)
            if ref_match:
                ref_step, ref_field = ref_match.groups()
                if ref_step == "steps":
                    pass  # handled in broader match below
                elif ref_step in step_results:
                    source = step_results[ref_step]
                    if isinstance(source, dict) and ref_field in source:
                        return source[ref_field]

            steps_match = re.fullmatch(r"\$\{?steps\.([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\}?", val)
            if steps_match:
                ref_step, ref_field = steps_match.groups()
                if ref_step in step_results:
                    source = step_results[ref_step]
                    if isinstance(source, dict) and ref_field in source:
                        return source[ref_field]

            # Pure param reference: "$param_key" or "${param_key}"
            param_match = re.fullmatch(r"\$\{?([a-zA-Z0-9_]+)\}?", val)
            if param_match:
                pkey = param_match.group(1)
                if pkey in params:
                    return params[pkey]

            # In-string template replacement: "Hello ${user}"
            for pk, pv in params.items():
                val = val.replace(f"${{{pk}}}", str(pv)).replace(f"${pk}", str(pv))

            return val

        for k, v in list(resolved.items()):
            resolved[k] = _resolve_val(v)

        return resolved

    # ------------------------------------------------------------------
    # Step & DAG Execution
    # ------------------------------------------------------------------

    def execute_step(
        self,
        step: RecipeStep,
        args: Dict[str, Any],
        executor: Optional[Executor] = None,
        trace_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        bus: Optional[Any] = None,
    ) -> Any:
        """Run a single step using the executor callable with telemetry."""
        fn = executor or self.executor
        active_bus = bus or self.bus

        if active_bus is not None:
            active_bus.emit(
                "recipe.step.started",
                trace_id=trace_id,
                intent_id=intent_id,
                payload={
                    "step_id": step.step_id,
                    "capability_id": step.capability_id,
                },
            )
            active_bus.emit(
                "tool.called",
                trace_id=trace_id,
                intent_id=intent_id,
                payload={
                    "tool": step.capability_id,
                    "args": args,
                },
            )

        try:
            result = fn(step.capability_id, args)
            if active_bus is not None:
                active_bus.emit(
                    "tool.completed",
                    trace_id=trace_id,
                    intent_id=intent_id,
                    payload={
                        "tool": step.capability_id,
                        "status": "completed",
                    },
                )
            return result
        except Exception as exc:
            if active_bus is not None:
                active_bus.emit(
                    "tool.completed",
                    trace_id=trace_id,
                    intent_id=intent_id,
                    payload={
                        "tool": step.capability_id,
                        "status": "error",
                        "error": str(exc),
                    },
                )
            raise

    def run(
        self,
        recipe: Union[Recipe, Sequence[RecipeStep]],
        params: Optional[Dict[str, Any]] = None,
        executor: Optional[Executor] = None,
        trace_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        bus: Optional[Any] = None,
        raise_on_error: bool = True,
    ) -> ExecutionResult:
        """Execute all steps in the recipe according to topological DAG order.

        Args:
            recipe: A Recipe instance or a sequence of RecipeStep instances.
            params: Runtime parameters to merge into step inputs.
            executor: Callable (capability_id, args) -> result.
            trace_id: Correlation trace identifier.
            intent_id: Intent identifier for telemetry correlation.
            bus: EventBus for telemetry emission (defaults to self.bus).
            raise_on_error: If True, re-raises any step exception. If False,
                catches and returns an ExecutionResult with success=False.

        Returns:
            An ExecutionResult dictionary with results, metrics, and success status.
        """
        start_time = time.perf_counter()
        trace_id = trace_id or uuid.uuid4().hex
        active_bus = bus or self.bus

        # Normalize recipe metadata and steps
        if isinstance(recipe, Recipe):
            recipe_id = recipe.recipe_id
            intent_family = recipe.intent_family
            recipe_version = recipe.version
            steps = recipe.steps
            requested_outcome = (
                " and ".join(recipe.success_conditions) or recipe.intent_family
            )
            if recipe.status == RecipeStatus.RETIRED:
                raise ValueError(f"Recipe '{recipe_id}' is retired and cannot be executed")
        else:
            recipe_id = "ad_hoc"
            intent_family = "unknown"
            recipe_version = "1.0.0"
            steps = list(recipe)
            requested_outcome = intent_family

        step_map = {s.step_id: s for s in steps}
        order = self.topological_order(steps)

        if active_bus is not None:
            active_bus.emit(
                "recipe.started",
                trace_id=trace_id,
                intent_id=intent_id,
                payload={
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                },
            )

        results: Dict[str, Any] = {}
        step_metrics: List[StepMetric] = []
        overall_success = True
        error_msg: Optional[str] = None
        failed_stage: Optional[str] = None

        for sid in order:
            step = step_map[sid]
            t0 = time.perf_counter()
            try:
                resolved_args = self.resolve_parameters(
                    step, params=params, step_results=results
                )
                step_res = self.execute_step(
                    step,
                    args=resolved_args,
                    executor=executor or self.executor,
                    trace_id=trace_id,
                    intent_id=intent_id,
                    bus=active_bus,
                )
                results[sid] = step_res
                dt_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                step_metrics.append(
                    StepMetric(
                        step_id=sid,
                        capability_id=step.capability_id,
                        latency_ms=dt_ms,
                        success=True,
                    )
                )
            except Exception as exc:
                dt_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                error_msg = f"{type(exc).__name__}: {exc}"
                step_metrics.append(
                    StepMetric(
                        step_id=sid,
                        capability_id=step.capability_id,
                        latency_ms=dt_ms,
                        success=False,
                        error=error_msg,
                    )
                )
                overall_success = False
                failed_stage = sid

                if active_bus is not None:
                    active_bus.emit(
                        "execution.failed",
                        trace_id=trace_id,
                        intent_id=intent_id,
                        payload={
                            "recipe_id": recipe_id,
                            "step_id": sid,
                            "error": error_msg,
                            "failed_stage": sid,
                            "side_effect_state": "unknown",
                            "retryable": None,
                        },
                    )

                if raise_on_error:
                    raise
                break

        total_latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)
        claim = (
            self._claim_outcome(requested_outcome, results, trace_id)
            if overall_success
            else OutcomeClaim(
                requested_outcome=requested_outcome,
                achieved_state="execution_failed",
                verification_type="unknown",
                evidence_refs=[trace_id],
                remaining_gap=(
                    f"Execution failed at {failed_stage}; provider side effects are unknown"
                ),
            )
        )

        if overall_success and active_bus is not None:
            active_bus.emit(
                "recipe.completed",
                trace_id=trace_id,
                intent_id=intent_id,
                payload={
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "steps": order,
                    "outcome_claim": claim.model_dump(),
                },
            )
            active_bus.emit(
                (
                    "outcome.delivered"
                    if claim.verification_type == "verified"
                    and claim.remaining_gap is None
                    else "evaluation.completed"
                ),
                trace_id=trace_id,
                intent_id=intent_id,
                payload={"outcome_claim": claim.model_dump()},
            )

        # Standard Control benchmark metrics
        metrics: Dict[str, Any] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
            "tool_calls": len(step_metrics),
            "retrieval_calls": 1,
            "steps": len(order),
            "wall_clock_latency_ms": total_latency_ms,
            "success": overall_success,
            "estimated_model_cost": 0.0,
        }

        return ExecutionResult(
            recipe_id=recipe_id,
            intent_family=intent_family,
            results=results,
            metrics=metrics,
            success=overall_success,
            error=error_msg,
            step_metrics=step_metrics,
            outcome_claim=claim.model_dump(),
            failed_stage=failed_stage,
            side_effect_state="unknown" if not overall_success else None,
            retryable=None,
        )
