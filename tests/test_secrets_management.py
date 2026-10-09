"""Unit tests for SecretsBroker, SecretManifest, command checking, and output scrubbing."""

import os
import json
import unittest

from ship.lifecycle.secrets import (
    SecretRequirement,
    SecretManifest,
    SecretsBroker,
)


class TestSecretsManagement(unittest.TestCase):
    def setUp(self):
        self.broker = SecretsBroker()

    def test_preflight_checks_missing_and_optional_secrets(self):
        """Preflight accurately identifies missing mandatory secrets while ignoring satisfied or optional ones."""
        manifest = SecretManifest(
            skill="deploy",
            requirements=[
                SecretRequirement(name="TEST_VAR_PRESENT", description="Present secret", optional=False),
                SecretRequirement(name="TEST_VAR_MISSING", description="Missing deployment token", optional=False),
                SecretRequirement(name="TEST_VAR_OPTIONAL", description="Optional webhook", optional=True),
            ],
        )

        os.environ["TEST_VAR_PRESENT"] = "some-token"
        if "TEST_VAR_MISSING" in os.environ:
            del os.environ["TEST_VAR_MISSING"]

        ok, missing = self.broker.check_preflight(manifest)
        self.assertFalse(ok)
        self.assertEqual(len(missing), 1)
        self.assertIn("TEST_VAR_MISSING", missing[0])

    def test_scrub_text_redacts_credentials(self):
        """Scrubbing removes sensitive passwords, tokens, API keys, and private keys from output."""
        sample_text = (
            "Connecting to db with password='SuperSecretPassword123' and api_key=sk-1234567890abcdef1234567890abcdef.\n"
            "GitHub token: ghp_1111222233334444555566667777888899990000.\n"
            "Auth header: Bearer my-auth-bearer-token-value."
        )

        scrubbed = self.broker.scrub_text(sample_text)
        self.assertNotIn("SuperSecretPassword123", scrubbed)
        self.assertNotIn("sk-1234567890abcdef1234567890abcdef", scrubbed)
        self.assertNotIn("ghp_1111222233334444555566667777888899990000", scrubbed)
        self.assertNotIn("my-auth-bearer-token-value", scrubbed)
        self.assertIn("[REDACTED]", scrubbed)

    def test_malformed_log_fields_do_not_prevent_other_redaction(self):
        receipt = r'bad "invalid\q": 1; {"password": "synthetic"}'
        clean = self.broker.scrub_text(receipt)
        self.assertNotIn('synthetic', clean)
        self.assertIn('[REDACTED]', clean)

    def test_json_credentials_in_log_text(self):
        for key in ('password', 'api_key', 'Access-Token', 'private_key'):
            for value in ('synthetic secret with spaces', 'escaped "secret"',
                          ['synthetic'], {'data': 'synthetic'}, 12345):
                with self.subTest(key=key, value=value):
                    payload = {key: value, 'token_count': 12, 'password_policy': 'strict'}
                    receipt = 'FAILED test_login: ' + json.dumps(payload)
                    clean = self.broker.scrub_text(receipt)
                    expected = dict(payload, **{key: '[REDACTED]'})
                    self.assertEqual(json.loads(clean.split(': ', 1)[1]), expected)
                    self.assertEqual(self.broker.scrub_text(clean), clean)

    def test_inspect_command_blocks_environment_dump(self):
        """Commands that attempt to dump all process environment variables are intercepted."""
        allowed, reason = self.broker.inspect_command("env")
        self.assertFalse(allowed)
        self.assertIn("dumps full process environment", reason)

        allowed2, reason2 = self.broker.inspect_command("printenv")
        self.assertFalse(allowed2)

        # Normal commands are allowed
        ok_cmd, _ = self.broker.inspect_command("pytest tests/")
        self.assertTrue(ok_cmd)

    def test_structured_field_names_redact_containers_and_preserve_metadata(self):
        for name in ('PASSWORD', 'api-key', 'apiKey', 'access_token', 'refreshToken',
                     'client_secret', 'aws_secret_access_key', 'Authorization', 'private_key'):
            for value in ('synthetic', 1234, ['synthetic'], {'value': 'synthetic'}):
                with self.subTest(name=name, value=value):
                    payload = {'entries': [{name: value}], 'token_count': 12, 'password_policy': 'strict', 'ok': True}
                    result = self.broker.scrub_value(payload)
                    self.assertEqual(result['entries'][0][name], '[REDACTED]')
                    self.assertEqual(result['token_count'], 12)
                    self.assertEqual(result['password_policy'], 'strict')
                    self.assertIs(result['ok'], True)
                    self.assertEqual(payload['entries'][0][name], value)
                    self.assertEqual(self.broker.scrub_value(result), result)


if __name__ == "__main__":
    unittest.main()
