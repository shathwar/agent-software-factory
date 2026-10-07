"""Prevent output checks and absent measurements from becoming behavioral proof."""
import unittest
from unittest.mock import patch

from tests.agent_harness.core import AgentRunner, BehaviourCheck, RegressionSuite, Scenario, Trace


class HarnessReportingTests(unittest.TestCase):
    def scenario(self, **kwargs):
        return Scenario(skill='review', id='report-contract', description='Output predicate',
                        prompt='Review', stub_response='ok', **kwargs)

    def test_success_reports_measurement_scope_in_each_mode(self):
        scenario = self.scenario(checks=[BehaviourCheck('output', lambda trace: trace.raw == 'ok')])
        for mode in ('stub', 'anthropic', 'live'):
            runner = AgentRunner(mode=mode)
            with self.subTest(mode=mode), patch.object(runner, 'run', return_value=Trace(raw='ok')):
                report = RegressionSuite([scenario], runner=runner).run()
                self.assertTrue(report['passed'])
                self.assertEqual(report['mode'], mode)
                self.assertEqual(report['assessment_kind'],
                                 'stub_response_contract' if mode == 'stub' else 'agent_output_contract')
                self.assertFalse(report['behavior_verified'])
                self.assertIn('output predicates only', report['summary'])

    def test_empty_selection_is_inconclusive(self):
        report = RegressionSuite([], runner=AgentRunner(mode='stub')).run()
        self.assertFalse(report['passed'])
        self.assertIsNone(report['pass_rate'])
        self.assertEqual(report['status'], 'inconclusive')

    def test_missing_checks_and_unexpected_exit_cannot_pass(self):
        runner = AgentRunner(mode='stub')
        self.assertFalse(RegressionSuite([self.scenario()], runner=runner).run()['passed'])
        scenario = self.scenario(checks=[BehaviourCheck('output', lambda trace: True)])
        with patch.object(runner, 'run', return_value=Trace(raw='ok', exit_code=1)):
            self.assertFalse(RegressionSuite([scenario], runner=runner).run()['passed'])
            scenario.expected_exit_code = 1
            self.assertTrue(RegressionSuite([scenario], runner=runner).run()['passed'])
