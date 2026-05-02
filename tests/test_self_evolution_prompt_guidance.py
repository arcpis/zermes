"""Tests for self-evolution guidance in the system prompt.

The guidance is prompt-only routing: it should appear when the approval
planning tool is available and disappear when that tool is not in the active
toolset. These tests avoid full agent initialization so they stay focused on
prompt assembly behavior.
"""

from run_agent import AIAgent


def _build_agent_with_tools(tool_names):
    """Create the smallest AIAgent instance needed for system prompt assembly."""
    agent = AIAgent.__new__(AIAgent)
    agent.valid_tool_names = list(tool_names)
    agent.skip_context_files = True
    agent._tool_use_enforcement = False
    agent._memory_store = None
    agent._memory_enabled = False
    agent._user_profile_enabled = False
    agent._memory_manager = None
    agent.pass_session_id = False
    agent.model = "test-model"
    agent.provider = ""
    agent.platform = ""
    return agent


def test_self_evolution_guidance_is_injected_when_approval_tool_is_available():
    """The prompt should route clear repository-improvement requests to approval."""
    agent = _build_agent_with_tools(["complete_code_task"])

    prompt = agent._build_system_prompt()

    assert "# Self-evolution trigger guidance" in prompt
    assert "use `complete_code_task`" in prompt
    assert "It must not modify product code" in prompt
    assert "explicitly approves the generated plan" in prompt


def test_self_evolution_guidance_is_not_injected_without_approval_tool():
    """The prompt must not mention unavailable tools."""
    agent = _build_agent_with_tools(["read_file", "search_files"])

    prompt = agent._build_system_prompt()

    assert "# Self-evolution trigger guidance" not in prompt
    assert "complete_code_task" not in prompt


def test_self_evolution_guidance_covers_clarification_and_non_trigger_cases():
    """The guidance should prevent vague requests and read-only work from misrouting."""
    agent = _build_agent_with_tools(["complete_code_task"])

    prompt = agent._build_system_prompt()

    assert "If the request is vague" in prompt
    assert "ask a short clarification question first" in prompt
    assert "ordinary Q&A" in prompt
    assert "read-only code explanation" in prompt
    assert "status checks" in prompt
