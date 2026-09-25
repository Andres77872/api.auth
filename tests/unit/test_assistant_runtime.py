"""Exercise actual Deep Agents graphs using a deterministic local model."""
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("deepagents")
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from src.assistant import runtime

pytestmark = pytest.mark.unit


class ScriptedModel(BaseChatModel):
    responses: list[Any] = Field(default_factory=list)
    seen_tools: list[list[str]] = Field(default_factory=list)
    seen_messages: list[list[Any]] = Field(default_factory=list)
    index: int = 0

    @property
    def _llm_type(self):
        return "scripted-local-test"

    def bind_tools(self, tools, **kwargs):
        self.seen_tools.append([tool.get("name", "") if isinstance(tool, dict) else tool.name for tool in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_messages.append(messages)
        response = self.responses[self.index]
        self.index += 1
        if callable(response):
            response = response(messages)
        response.usage_metadata = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        return ChatResult(generations=[ChatGeneration(message=response)])


def call(name, args=None, ident="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": ident, "type": "tool_call"}])


class MemoryCheckpointSaver(InMemorySaver):
    """Keep graph state between runtime invocations without external storage."""

    async def setup(self):
        pass


@pytest.fixture
def environment(monkeypatch):
    from src.assistant import catalog, tools
    skill = {"id": "users", "name": "Users", "description": "Manage users.",
             "path": "/skills/users/SKILL.md", "content": "---\nname: users\ndescription: Manage users.\n---\nRead and manage users."}
    monkeypatch.setattr(catalog, "skill_catalog", lambda: [skill])
    monkeypatch.setattr(catalog, "skill_files", lambda enabled: {skill["path"]: skill["content"]} if "users" in enabled else {})
    count = {"read": 0, "write": 0}

    async def read_users():
        count["read"] += 1
        return {"users": [{"id": 1, "name": "Test"}]}

    async def change_users():
        count["write"] += 1
        return {"updated": True}

    definitions = [
        StructuredTool.from_function(coroutine=read_users, name="read_users", description="Read users",
                                     metadata={"skill": "users", "mutates": False}),
        StructuredTool.from_function(coroutine=change_users, name="change_users", description="Change users",
                                     metadata={"skill": "users", "mutates": True}),
    ]
    monkeypatch.setattr(tools, "build_agent_tools", lambda *a, **kw: definitions)
    saver = MemoryCheckpointSaver()
    context = runtime.RuntimeContext(session_id="session-one", run_id="run-one", message="Test",
                                     profile={}, settings={"enabled_skills": ["users"], "enabled_tools": ["read_users", "change_users"],
                                                           "mutations_enabled": False, "features": {}},
                                     executor=SimpleNamespace(), checkpoint_factory=lambda: saver)
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    return context, count, events, emit


async def test_faq_uses_real_deep_agent_without_app_tools(environment, monkeypatch):
    context, count, events, emit = environment
    model = ScriptedModel(responses=[AIMessage(content="A general answer.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    result = await runtime.run_agent(context, emit)
    assert result.status == "completed"
    assert result.content == "A general answer."
    assert "task" in model.seen_tools[0]
    assert "read_users" not in model.seen_tools[0]
    assert "change_users" not in model.seen_tools[0]
    assert "execute" not in model.seen_tools[0]
    assert "write_file" not in model.seen_tools[0]
    assert result.usage == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5, "model_calls": 1}
    assert count == {"read": 0, "write": 0}
    assert any(kind == "message.delta" for kind, _ in events)


async def test_skill_read_progressively_enables_tools_and_resets_next_turn(environment, monkeypatch):
    context, count, events, emit = environment
    model = ScriptedModel(responses=[call("read_file", {"file_path": "/skills/users/SKILL.md"}),
                                     call("read_users", ident="call-2"), AIMessage(content="One user."),
                                     AIMessage(content="Hello.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    result = await runtime.run_agent(context, emit)
    assert result.content == "One user."
    assert "read_users" not in model.seen_tools[0]
    assert "read_users" in model.seen_tools[1]
    assert count["read"] == 1
    context.message = "Hello"
    context.run_id = "run-two"
    await runtime.run_agent(context, emit)
    assert "read_users" not in model.seen_tools[-1]


async def test_tool_call_without_skill_is_denied_even_when_model_invents_it(environment, monkeypatch):
    context, count, _, emit = environment
    model = ScriptedModel(responses=[call("read_users"), AIMessage(content="Denied.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    assert count["read"] == 0
    assert any(isinstance(msg, ToolMessage) and msg.status == "error" for msg in model.seen_messages[-1])


async def test_ask_user_checkpoint_survives_new_graph_and_resumes(environment, monkeypatch):
    context, count, _, emit = environment
    model = ScriptedModel(responses=[call("ask_user", {"question": "Which group?", "options": ["Staff", "Guests"]})])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    result = await runtime.run_agent(context, emit)
    assert result.status == "waiting_input"
    assert result.interrupts[0]["type"] == "ask_user"
    assert result.interrupts[0]["question"] == "Which group?"
    next_model = ScriptedModel(responses=[AIMessage(content="Staff selected.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: next_model)
    context.message = None
    context.resume = runtime.normalize_resume(result.interrupts, {"answer": "Staff"})
    resumed = await runtime.run_agent(context, emit)
    assert resumed.content == "Staff selected."
    assert any(isinstance(m, ToolMessage) and m.content == "Staff" for m in next_model.seen_messages[0])


@pytest.mark.parametrize("decision,expected", [("approve", 1), ("reject", 0)])
async def test_mutation_interrupt_requires_explicit_human_decision(environment, monkeypatch, decision, expected):
    context, count, _, emit = environment
    context.settings["mutations_enabled"] = True
    model = ScriptedModel(responses=[call("read_file", {"file_path": "/skills/users/SKILL.md"}),
                                     call("change_users", ident="write-1")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    result = await runtime.run_agent(context, emit)
    assert result.status == "waiting_input"
    assert count["write"] == 0
    assert result.interrupts[0]["action_requests"][0]["name"] == "change_users"
    context.message = None
    context.resume = runtime.normalize_resume(result.interrupts, {"decisions": [{"type": decision}]})
    monkeypatch.setattr(runtime, "build_model", lambda _: ScriptedModel(responses=[AIMessage(content="Done.")]))
    resumed = await runtime.run_agent(context, emit)
    assert resumed.status == "completed"
    assert count["write"] == expected


async def test_subagent_uses_scoped_skills_and_aggregate_usage(environment, monkeypatch):
    context, count, events, emit = environment
    model = ScriptedModel(responses=[call("task", {"description": "Count users", "subagent_type": "users-specialist"}),
                                     call("read_file", {"file_path": "/skills/users/SKILL.md"}, ident="child-read"),
                                     call("read_users", ident="child-app"), AIMessage(content="One user."),
                                     AIMessage(content="The specialist found one user.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    result = await runtime.run_agent(context, emit)
    assert count["read"] == 1
    assert result.usage["model_calls"] == 5
    assert result.usage["total_tokens"] == 25
    assert result.content == "The specialist found one user."
    assert any(kind == "subagent.started" for kind, _ in events)
    # Child text is not interleaved into the root's generated answer.
    assert "One user." not in [event[1]["content"] for event in events if event[0] == "message.delta"]


def test_resume_rejects_missing_or_edited_decisions():
    pending = [{"id": "i", "type": "approval", "action_requests": [{"name": "change_users"}]}]
    with pytest.raises(ValueError):
        runtime.normalize_resume(pending, {"answer": "sure"})
    with pytest.raises(ValueError):
        runtime.normalize_resume(pending, {"decisions": [{"type": "edit", "edited_action": {}}]})


def test_loaded_skill_requires_success_and_resets_on_user_turn():
    read = call("read_file", {"file_path": "/skills/users/SKILL.md"})
    paths = {"/skills/users/SKILL.md": "users"}
    assert runtime.loaded_skills([read, ToolMessage(content="Error: missing", tool_call_id="call-1")], paths) == set()
    assert runtime.loaded_skills([read, ToolMessage(content="instructions", tool_call_id="call-1")], paths) == {"users"}
    assert runtime.loaded_skills([read, ToolMessage(content="instructions", tool_call_id="call-1"), HumanMessage(content="Hi")], paths) == set()


async def test_multiple_skill_toolsets_load_independently(environment, monkeypatch):
    context, count, _, emit = environment
    from src.assistant import catalog, tools
    user_skill = catalog.skill_catalog()[0]
    group_skill = {"id": "groups", "name": "Groups", "description": "Manage groups.",
                   "path": "/skills/groups/SKILL.md", "content": "---\nname: groups\ndescription: Manage groups.\n---\nRead groups."}
    monkeypatch.setattr(catalog, "skill_catalog", lambda: [user_skill, group_skill])
    monkeypatch.setattr(catalog, "skill_files", lambda enabled: {skill["path"]: skill["content"] for skill in [user_skill, group_skill] if skill["id"] in enabled})
    original = tools.build_agent_tools()

    async def read_groups():
        return {"groups": []}

    group_tool = StructuredTool.from_function(coroutine=read_groups, name="read_groups", description="Read groups",
                                             metadata={"skill": "groups", "mutates": False})
    monkeypatch.setattr(tools, "build_agent_tools", lambda *a, **kw: [*original, group_tool])
    context.settings["enabled_skills"].append("groups")
    model = ScriptedModel(responses=[call("read_file", {"file_path": "/skills/users/SKILL.md"}),
                                     call("read_file", {"file_path": "/skills/groups/SKILL.md"}, ident="groups-file"),
                                     AIMessage(content="Both domains available.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    assert "read_groups" not in model.seen_tools[1]
    assert {"read_users", "read_groups"}.issubset(model.seen_tools[2])


async def test_subagent_mutation_keeps_approval_gate_across_resume(environment, monkeypatch):
    context, count, _, emit = environment
    context.settings["mutations_enabled"] = True
    model = ScriptedModel(responses=[call("task", {"description": "Update user", "subagent_type": "users-specialist"}),
                                     call("read_file", {"file_path": "/skills/users/SKILL.md"}, ident="child-file"),
                                     call("change_users", ident="child-write")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    paused = await runtime.run_agent(context, emit)
    assert paused.status == "waiting_input"
    assert count["write"] == 0
    assert paused.interrupts[0]["type"] == "approval"
    context.resume = runtime.normalize_resume(paused.interrupts, {"decisions": [{"type": "approve"}]})
    context.message = None
    monkeypatch.setattr(runtime, "build_model", lambda _: ScriptedModel(responses=[AIMessage(content="Updated."), AIMessage(content="The specialist updated the user.")]))
    result = await runtime.run_agent(context, emit)
    assert result.status == "completed"
    assert count["write"] == 1


async def test_planning_streams_tasks_and_can_be_disabled(environment, monkeypatch):
    context, _, events, emit = environment
    todos = [{"content": "Inspect users", "status": "in_progress"}]
    model = ScriptedModel(responses=[call("write_todos", {"todos": todos}), AIMessage(content="Planned.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    assert any(kind == "task.updated" and event["todos"] == todos for kind, event in events), events
    context.settings["features"]["planning"] = False
    context.run_id = "no-plan"
    model = ScriptedModel(responses=[AIMessage(content="No planning.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    assert "write_todos" not in model.seen_tools[0]
    assert "task" in model.seen_tools[0]


async def test_fresh_checkpoint_uses_safe_completed_history_only(environment, monkeypatch):
    context, _, _, emit = environment
    context.checkpoint_thread_id = "session:recovery"
    context.history = [{"role": "user", "content": "Previous completed question"},
                       {"role": "assistant", "content": "Previous completed answer"}]
    model = ScriptedModel(responses=[AIMessage(content="Recovered.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    contents = [message.content for message in model.seen_messages[0]]
    assert "Previous completed answer" in contents
    context.settings["features"]["memory"] = False
    context.checkpoint_thread_id = "session:no-history"
    model = ScriptedModel(responses=[AIMessage(content="Isolated.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    assert "Previous completed answer" not in [message.content for message in model.seen_messages[0]]


@pytest.mark.parametrize("provider,base_url", [("ollama", "http://localhost:11434"), ("openai", "http://localhost:8001/v1"), ("anthropic", "https://api.anthropic.com")])
def test_provider_adapters_construct_without_network(provider, base_url):
    model = runtime.build_model({"provider": provider, "base_url": base_url, "model": "configured-test-model",
                                 "temperature": 0.1, "max_tokens": 1024, "api_key": "test-only-key"})
    assert model is not None
    assert hasattr(model, "bind_tools")


def test_interrupt_redacts_sensitive_arguments():
    pending = runtime.normalize_interrupt(SimpleNamespace(id="action", value={"action_requests": [
        {"name": "create", "args": {"body": {"password": "sensitive-password"}}}]}))
    assert "sensitive-password" not in str(pending)
    assert pending["id"] == "action"


async def test_cancellation_closes_graph_and_allows_an_independent_recovery_run(environment, monkeypatch):
    import asyncio
    context, count, _, emit = environment
    started = asyncio.Event()

    class BlockingModel(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "build_model", lambda _: BlockingModel())
    task = asyncio.create_task(runtime.run_agent(context, emit))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert count == {"read": 0, "write": 0}
    context.checkpoint_thread_id = "session:after-cancel"
    monkeypatch.setattr(runtime, "build_model", lambda _: ScriptedModel(responses=[AIMessage(content="Recovered safely.")]))
    result = await runtime.run_agent(context, emit)
    assert result.content == "Recovered safely."


def test_parallel_questions_require_explicit_per_interrupt_answers():
    pending = [{"id": "one", "type": "ask_user"}, {"id": "two", "type": "ask_user"}]
    with pytest.raises(ValueError):
        runtime.normalize_resume(pending, {"answer": "Same for everything"})
    assert runtime.normalize_resume(pending, {"responses": {"one": "Staff", "two": "Production"}}) == {"one": "Staff", "two": "Production"}


def test_ollama_context_window_is_explicit_and_configurable():
    profile = {"provider": "ollama", "model": "test-local"}
    assert runtime.build_model(profile).num_ctx == 32768
    assert runtime.build_model({**profile, "context_window": 65536}).num_ctx == 65536


async def test_large_combined_toolsets_are_bounded_and_latest_domain_prioritized(environment, monkeypatch):
    context, _, _, emit = environment
    from src.assistant import catalog, tools
    users = catalog.skill_catalog()[0]
    groups = {"id": "groups", "name": "Groups", "description": "Manage groups.",
              "path": "/skills/groups/SKILL.md", "content": "---\nname: groups\ndescription: Manage groups.\n---\nRead groups."}
    monkeypatch.setattr(catalog, "skill_catalog", lambda: [users, groups])
    monkeypatch.setattr(catalog, "skill_files", lambda enabled: {s["path"]: s["content"] for s in [users, groups]})

    async def read():
        return {"ok": True}

    definitions = [StructuredTool.from_function(coroutine=read, name=f"{skill}_{index}", description="Read domain data",
                   metadata={"skill": skill, "mutates": False}) for skill in ["users", "groups"] for index in range(60)]
    monkeypatch.setattr(tools, "build_agent_tools", lambda *a, **kw: definitions)
    context.settings["enabled_skills"] = ["users", "groups"]
    model = ScriptedModel(responses=[call("read_file", {"file_path": users["path"]}),
                                     call("read_file", {"file_path": groups["path"]}, ident="groups-file"),
                                     AIMessage(content="Use specialists for remaining operations.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    await runtime.run_agent(context, emit)
    exposed = set(model.seen_tools[-1])
    assert len(exposed & {tool.name for tool in definitions}) == 96
    assert {f"groups_{index}" for index in range(60)} <= exposed
    assert "task" in exposed
    assert "some enabled operations for users" in str(model.seen_messages[-1][0].content)
