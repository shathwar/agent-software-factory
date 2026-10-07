"""
Agent Regression Harness
========================
Response predicates over canned outputs (default) or explicitly selected model/CLI
output. Passing these predicates does not independently verify agent behavior.

Architecture
------------
- AgentRunner      – spawns an actual AI agent (or stub in CI) and captures its
                     output text, not a host-instrumented execution trace.
- BehaviourCheck   – predicates over captured output.
- ScenarioFixture  – lightweight git repo + source code scaffold per scenario.
- Scenario         – data-class describing one test case: prompt, fixture,
                     expected_behaviours.
- RegressionSuite  – discovers and runs Scenario lists, emits a structured
                     pass/fail report.

Stub mode remains the default even with credentials. Explicit anthropic mode
requests model text without a tool loop; live mode shells out to the agy CLI and
relies on host skill setup. Neither independently verifies tool/edit chronology.
"""
