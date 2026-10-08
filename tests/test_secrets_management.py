"""Unit tests for SecretsBroker, SecretManifest, command checking, and output scrubbing."""

import os
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


if __name__ == "__main__":
    unittest.main()
