import os
import tempfile
import unittest
from pathlib import Path

from khdiamond_credentials import (delete_credentials, load_credentials,
                                    save_credentials)


class CredentialsTest(unittest.TestCase):
    def test_encrypted_round_trip_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = os.environ.get("KH_DIAMOND_CREDENTIAL_KEY_FILE")
            os.environ["KH_DIAMOND_CREDENTIAL_KEY_FILE"] = str(root / "master.key")
            try:
                save_credentials(root, "test-user", "test-password")
                encrypted = (root / "credentials.enc").read_bytes()
                self.assertNotIn(b"test-password", encrypted)
                self.assertEqual(load_credentials(root), ("test-user", "test-password"))
                self.assertEqual((root / "credentials.enc").stat().st_mode & 0o777, 0o600)
                self.assertEqual((root / "master.key").stat().st_mode & 0o777, 0o600)
                delete_credentials(root)
                self.assertIsNone(load_credentials(root))
            finally:
                if old is None:
                    os.environ.pop("KH_DIAMOND_CREDENTIAL_KEY_FILE", None)
                else:
                    os.environ["KH_DIAMOND_CREDENTIAL_KEY_FILE"] = old


if __name__ == "__main__":
    unittest.main()
