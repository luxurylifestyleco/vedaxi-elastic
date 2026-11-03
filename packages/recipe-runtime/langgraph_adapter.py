"""Optional LangGraph adapter for the existing Elastic recipe runner.

LangGraph owns graph state and checkpointing; RecipeDAGRunner remains the
single execution and telemetry authority. A durable checkpointer must be
provided by the caller for crash-resumable runs.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, Optional, TypedDict

from recipe import Recipe

from .runner import Executor, RecipeDAGRunner


class RecipeGraphState(TypedDict, total=False):
    params: Dict[str, Any]
    trace_id: Optional[str]
    intent_id: Optional[str]
    result: Dict[str, Any]
    status: str
    error: Optional[str]


def build_recipe_graph(
    recipe: Recipe,
    executor: Executor,
    *,
    checkpointer: Any = None,
    runner: Optional[RecipeDAGRunner] = None,
) -> Any:
    """Compile one Elastic recipe behind a LangGraph checkpoint boundary.

    ``checkpointer`` is intentionally caller-supplied. Use a durable LangGraph
    saver for resume semantics; omitting it creates an in-process graph only.
    """

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - exercised without extra
        raise RuntimeError(
            "LangGraph is optional; install with `uv sync --extra orchestration`"
        ) from exc

    recipe_runner = runner or RecipeDAGRunner(executor=executor)

    def execute(state: RecipeGraphState) -> RecipeGraphState:
        result = recipe_runner.run(
            recipe,
            params=state.get("params"),
            executor=executor,
            trace_id=state.get("trace_id"),
            intent_id=state.get("intent_id"),
            raise_on_error=False,
        )
        # LangGraph's default msgpack serializer cannot safely persist the
        # recipe model or StepMetric dataclasses. Keep checkpoint state made
        # only of ordinary mappings and scalars so durable savers remain
        # compatible with strict serialization.
        checkpoint_result = dict(result)
        checkpoint_result["step_metrics"] = [
            asdict(metric) if is_dataclass(metric) else metric
            for metric in result["step_metrics"]
        ]
        return {
            "result": checkpoint_result,
            "status": "COMPLETED" if result.success else "FAILED",
            "error": result.error,
        }

    graph = StateGraph(RecipeGraphState)
    graph.add_node("execute_recipe", execute)
    graph.add_edge(START, "execute_recipe")
    graph.add_edge("execute_recipe", END)
    return graph.compile(checkpointer=checkpointer)


def run_recipe_graph(
    recipe: Recipe,
    executor: Executor,
    *,
    config: Optional[Dict[str, Any]] = None,
    checkpointer: Any = None,
    params: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    intent_id: Optional[str] = None,
) -> RecipeGraphState:
    """Run the adapter and return the same result shape as Elastic runtime.

    For a resumable run, pass a durable checkpointer and a stable
    ``configurable.thread_id`` in ``config``.
    """

    graph = build_recipe_graph(recipe, executor, checkpointer=checkpointer)
    return graph.invoke(
        {
            "params": params or {},
            "trace_id": trace_id,
            "intent_id": intent_id,
        },
        config=config,
    )


__all__ = ["RecipeGraphState", "build_recipe_graph", "run_recipe_graph"]
