"""One checkpointed LangGraph instance per durable delegation."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.budget import TERMINAL


class DelegationState(TypedDict):
    delegation_id: int
    completed_steps: int
    status: str


def build_delegation_graph(saver, advance_round):
    def step(state):
        result = advance_round(state["delegation_id"], state["completed_steps"])
        if result["status"] == "awaiting_input":
            # The round and local tool receipts were persisted before this
            # interrupt. Replay only acknowledges the already durable round.
            interrupt({"kind": "clarify", "delegation_id": state["delegation_id"]})
        return result

    builder = StateGraph(DelegationState)
    builder.add_node("agent_round", step)
    builder.add_edge(START, "agent_round")
    builder.add_conditional_edges("agent_round", lambda state: END if state["status"] in TERMINAL else "agent_round")
    return builder.compile(checkpointer=saver, interrupt_after=["agent_round"])
