import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

class UserPipelineSafetyTest(unittest.TestCase):
    def test_user_sync_refuses_empty_catalog_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            user_dir = tmp_dir / "user1"
            user_dir.mkdir()
            cat_path = user_dir / "catalog.json"
            list_path = user_dir / "list.json"
            
            # Previous catalog had 10 items
            prev_catalog = [{"title": f"Movie {i}", "movie_id": f"id{i}"} for i in range(10)]
            cat_path.write_text(json.dumps(prev_catalog))
            list_path.write_text("[]")
            
            env = {
                "USER_DIR": str(user_dir),
                "CATALOG_PATH": str(cat_path),
            }
            with patch.dict(os.environ, env, clear=False):
                import user_sync
                with self.assertRaises(SystemExit):
                    user_sync.main()
            
            # Verify previous catalog was not overwritten
            current = json.loads(cat_path.read_text())
            self.assertEqual(len(current), 10)

    def test_user_resolve_refuses_empty_list_when_worklist_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            user_dir = tmp_dir / "user2"
            user_dir.mkdir()
            raw_path = user_dir / "library_raw.json"
            list_path = user_dir / "list.json"
            cookies_path = user_dir / "cookies.txt"
            cookies_path.write_text("# Netscape HTTP Cookie File\n")
            
            raw_path.write_text(json.dumps([{"slug": "test-movie", "title": "Test", "kind": "movies", "article_id": "p123"}]))
            list_path.write_text(json.dumps([{"title": "Test", "movie_id": "prev_id"}]))
            
            env = {
                "USER_DIR": str(user_dir),
                "COOKIES_PATH": str(cookies_path),
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("user_resolve.call_player_ajax", return_value={"status": "http_429_giveup", "movie_id": "", "embed_url": ""}):
                    import user_resolve
                    with self.assertRaises(SystemExit):
                        user_resolve.main()
            
            # Verify previous list.json was preserved
            current = json.loads(list_path.read_text())
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["movie_id"], "prev_id")


if __name__ == "__main__":
    unittest.main()
