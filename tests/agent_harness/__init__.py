"""
Agent Regression Harness
========================
Real agent behaviour testing.  Proves "when an agent uses this skill, does it
actually behave as intended?" — not "does the validator script work?"

Architecture
------------
- AgentRunner      – spawns an actual AI agent (or stub in CI) and captures its
                     full trace / structured output.
- TraceAssert      – assertion helpers that operate on captured traces.
- ScenarioFixture  – lightweight git repo + source code scaffold per scenario.
- Scenario         – data-class describing one test case: prompt, fixture,
                     expected_behaviours.
- RegressionSuite  – discovers and runs Scenario lists, emits a structured
                     pass/fail report.

The harness is deliberately model-agnostic.  In real runs it shells out to the
``agy`` CLI (or any configured adapter).  In unit tests / CI without LLM
credentials it falls back to a deterministic stub whose responses are stored
alongside each fixture.
"""
