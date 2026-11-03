import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from recipe_runtime import Recipe, RecipeStep
from recipe_runtime.langgraph_adapter import run_recipe_graph


def test_langgraph_adapter_preserves_elastic_runner_result_shape():
    recipe = Recipe(
        recipe_id="graph-test",
        intent_family="test",
        steps=[
            RecipeStep(
                step_id="one",
                action="lookup",
                capability_id="catalog.lookup",
            )
        ],
    )

    result = run_recipe_graph(
        recipe,
        lambda capability_id, args: {"capability": capability_id},
    )

    assert result["status"] == "COMPLETED"
    assert result["result"]["results"]["one"] == {"capability": "catalog.lookup"}
    assert result["result"]["step_metrics"][0]["step_id"] == "one"


def test_langgraph_adapter_persists_checkpoint_safe_state():
    recipe = Recipe(
        recipe_id="checkpoint-test",
        intent_family="test",
        steps=[
            RecipeStep(
                step_id="one",
                action="lookup",
                capability_id="catalog.lookup",
            )
        ],
    )
    config = {"configurable": {"thread_id": "checkpoint-thread"}}
    saver = MemorySaver()

    result = run_recipe_graph(
        recipe,
        lambda capability_id, args: {"capability": capability_id},
        checkpointer=saver,
        config=config,
    )

    checkpoint = saver.get_tuple(config)
    assert checkpoint is not None
    assert checkpoint.checkpoint["channel_values"]["status"] == "COMPLETED"
    assert result["result"]["step_metrics"][0]["capability_id"] == "catalog.lookup"
