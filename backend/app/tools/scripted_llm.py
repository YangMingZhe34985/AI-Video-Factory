"""Deterministic v3 Mock responses keyed by agent and zero-based step."""

from collections.abc import Mapping, Sequence
from copy import deepcopy

from flask import current_app

from app.api import AppError


class ScriptedLLM:
    """Explicit scripts never silently fall back after their final step.

    Accepted forms are {(agent, step): response} and {agent: [response, ...]}.
    A response can be text, a list of normalized tool calls, or a response dict.
    Steps are looked up rather than consumed, so a fresh process can replay the
    same script. The Registry, not this class, owns durable response replay.
    """

    def __init__(self, scripts: Mapping | None = None):
        self._responses = {}
        self._agents = set()
        self.calls = []
        for key, value in (scripts or {}).items():
            if isinstance(key, tuple) and len(key) == 2:
                agent, step = key
                self._validate_key(agent, step)
                self._agents.add(agent)
                self._responses[(agent, step)] = deepcopy(value)
            elif isinstance(key, str) and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                self._agents.add(key)
                for step, response in enumerate(value):
                    self._responses[(key, step)] = deepcopy(response)
            else:
                raise ValueError("Scripts must map (agent, step) to a response or agent to a response sequence")

    @staticmethod
    def _validate_key(agent, step):
        if not isinstance(agent, str) or not agent or type(step) is not int or step < 0:
            raise ValueError("Script keys require a nonempty agent and a nonnegative integer step")

    def has_script(self, agent: str) -> bool:
        return agent in self._agents

    def complete(self, agent: str, step: int, *, default_response=None, tools=None) -> dict:
        self._validate_key(agent, step)
        self.calls.append((agent, step))
        if self.has_script(agent):
            if (agent, step) not in self._responses:
                raise AppError("SCRIPT_EXHAUSTED", f"No scripted response for {agent} step {step}", 500)
            response = deepcopy(self._responses[(agent, step)])
        elif default_response is not None:
            response = deepcopy(default_response)
        else:
            response = self._example(agent, step, tools)
        if isinstance(response, str):
            response = {"content": response}
        elif isinstance(response, list):
            response = {"content": None, "tool_calls": response}
        if not isinstance(response, dict):
            raise AppError("INVALID_LLM_SCRIPT", "A scripted response must be text, tool calls, or an object", 500)
        response.setdefault("content", None)
        response.setdefault("tool_calls", [])
        response.setdefault("usage", {"prompt_tokens": 0, "completion_tokens": 0})
        if (not response["content"] and not response["tool_calls"] and not response.get("tool_call_errors")
                and response.get("finish_reason") != "length"):
            raise AppError("INVALID_LLM_SCRIPT", "A scripted response cannot silently finish empty", 500)
        return response

    @staticmethod
    def _example(agent, step, tools):
        message = "[Mock 示例结果] 已直接完成；此结果仅用于演示，不代表真实模型规划。"
        finish_available = tools is None or any(item.get("function", {}).get("name") == "finish" for item in tools)
        if not finish_available:
            return {"content": message, "tool_calls": []}
        if agent == "producer":
            arguments = {"kind": "completed", "outcome": "answer", "message": message}
        else:
            # Other agents cannot invent workspace references in a demo.
            arguments = {"kind": "returned", "reason": message,
                         "suggestion": "请提供该 Agent 的测试脚本以演示具体产物。"}
        return {"content": message,
                "tool_calls": [{"id": f"mock_{agent}_{step}_finish", "name": "finish", "arguments": arguments}]}


def get_scripted_llm() -> ScriptedLLM:
    value = current_app.extensions.get("agent_v3_scripted_llm")
    if value is None:
        value = ScriptedLLM(current_app.config.get("AGENT_V3_LLM_SCRIPTS"))
        current_app.extensions["agent_v3_scripted_llm"] = value
    if not isinstance(value, ScriptedLLM):
        raise AppError("INVALID_LLM_SCRIPT", "agent_v3_scripted_llm must be a ScriptedLLM instance", 500)
    return value
