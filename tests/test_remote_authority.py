import os
import unittest
from unittest.mock import patch

from schwab_agent import remote_authority


class RemoteAuthorityTests(unittest.TestCase):
    def test_auto_mode_uses_goliath_callback_off_host(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("schwab_agent.config.load_config", return_value={
                 "callback_url": "https://goliath.tailffd98c.ts.net/callback",
                 "apps": {},
             }), \
             patch("schwab_agent.remote_authority._hostname", return_value="macbook"):
            self.assertTrue(remote_authority.remote_enabled())

    def test_auto_mode_disables_remote_on_goliath(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("schwab_agent.config.load_config", return_value={
                 "callback_url": "https://goliath.tailffd98c.ts.net/callback",
                 "apps": {},
             }), \
             patch("schwab_agent.remote_authority._hostname", return_value="goliath"):
            self.assertFalse(remote_authority.remote_enabled())

    def test_env_can_force_local(self):
        with patch.dict(os.environ, {"SCHWAB_TOKEN_AUTHORITY": "local"}, clear=True), \
             patch("schwab_agent.config.load_config", return_value={
                 "callback_url": "https://goliath.tailffd98c.ts.net/callback",
                 "apps": {},
             }), \
             patch("schwab_agent.remote_authority._hostname", return_value="macbook"):
            self.assertFalse(remote_authority.remote_enabled())


if __name__ == "__main__":
    unittest.main()
