import os
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

os.environ["KH_DIAMOND_BASE_DIR"] = str(Path(tempfile.gettempdir()) / "khdiamond_web_test")

from web_ui import (  # noqa: E402
    FULL_CATALOG_PATH,
    USERS_DIR,
    app,
    episode_videos,
    find_purchased_item,
    public_item_id,
    stremio_meta,
    user_catalog,
    user_catalog_extra,
    user_manifest,
    user_meta,
    user_stream,
    usable_poster_url,
)


class FakeRequest:
    query_params = {}


def response_json(response):
    return json.loads(response.body)


class WebCatalogTest(unittest.TestCase):
    def setUp(self):
        self.movie = {
            "type": "movie",
            "slug": "doctor-strange",
            "imdb_id": "tt1211837",
            "title_english": "Doctor Strange",
            "title_khmer": "ដុកទ័រស្ត្រេង",
            "poster": "https://khdiamond.net/poster.jpg",
        }
        self.series = {
            "type": "series",
            "slug": "example-show",
            "imdb_id": "tt1234567",
            "title_english": "Example Show",
            "episodes": [{
                "season": 1,
                "episode": 2,
                "title": "Episode Two",
                "page_url": "https://khdiamond.net/episodes/example-show-1x2/",
            }],
        }

    def test_verified_imdb_id_is_public_catalog_id(self):
        self.assertEqual(public_item_id(self.movie), "tt1211837")
        self.assertEqual(stremio_meta(self.movie)["poster"], self.movie["poster"])
        malformed = dict(self.movie, imdb_id="tt123")
        self.assertEqual(public_item_id(malformed), "khdcat_doctor-strange")
        self.assertEqual(usable_poster_url(
            "https://khdiamond.net/wp-content/themes/dooplay/assets/img/ssss2.png"
        ), "")

    def test_movie_stream_maps_by_site_slug_not_stale_imdb(self):
        personal = [{
            "type": "movie",
            "slug": "doctor-strange",
            "imdb_id": "tt9999999",
            "movie_id": "stream123",
        }]
        found = find_purchased_item(personal, self.movie, "tt1211837")
        self.assertEqual(found["movie_id"], "stream123")

    def test_series_meta_and_episode_stream_mapping(self):
        videos = episode_videos(self.series)
        self.assertEqual(videos[0]["id"], "tt1234567:1:2")
        personal = [{
            "type": "series",
            "slug": "example-show-1x2",
            "movie_id": "episode123",
        }]
        found = find_purchased_item(personal, self.series, "tt1234567:1:2")
        self.assertEqual(found["movie_id"], "episode123")

    def test_unowned_title_has_no_khdiamond_stream(self):
        self.assertIsNone(find_purchased_item([], self.movie, "tt1211837"))

    def test_duplicate_imdb_id_uses_the_owned_site_slug(self):
        token = "duplicateuser"
        user_path = USERS_DIR / token
        user_path.mkdir(parents=True, exist_ok=True)
        duplicate_unowned = dict(self.movie, slug="first-unowned-copy")
        duplicate_owned = dict(self.movie, slug="second-owned-copy")
        personal = [{
            "type": "movie",
            "slug": "second-owned-copy",
            "movie_id": "ownedDuplicateStream",
            "movie_id_4k": "",
            "title_english": "Doctor Strange",
        }]
        (user_path / "catalog.json").write_text(json.dumps(personal))
        FULL_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        FULL_CATALOG_PATH.write_text(json.dumps([duplicate_unowned, duplicate_owned]))

        streams = response_json(asyncio.run(
            user_stream(token, "movie", "tt1211837")
        ))["streams"]
        self.assertTrue(streams)

    def test_http_catalog_meta_and_entitled_stream_split(self):
        token = "testuser"
        user_path = USERS_DIR / token
        user_path.mkdir(parents=True, exist_ok=True)
        personal = [{
            "type": "movie",
            "slug": "doctor-strange",
            "movie_id": "stream123",
            "movie_id_4k": "",
            "title_english": "Doctor Strange",
        }]
        (user_path / "catalog.json").write_text(json.dumps(personal))
        unowned = dict(self.movie, slug="unowned", imdb_id="tt7654321", title_english="Unowned")
        FULL_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        FULL_CATALOG_PATH.write_text(json.dumps([self.movie, unowned, self.series]))

        manifest = response_json(asyncio.run(user_manifest(token)))
        self.assertIn("khdcat_", manifest["idPrefixes"])

        movies = response_json(asyncio.run(user_catalog(
            token, "movie", f"khdiamond_movies_{token}", FakeRequest()
        )))["metas"]
        self.assertEqual({meta["id"] for meta in movies}, {"tt1211837", "tt7654321"})

        meta = response_json(asyncio.run(user_meta(token, "series", "tt1234567")))["meta"]
        self.assertEqual(meta["videos"][0]["id"], "tt1234567:1:2")

        owned = response_json(asyncio.run(user_stream(token, "movie", "tt1211837")))["streams"]
        unowned_streams = response_json(asyncio.run(
            user_stream(token, "movie", "tt7654321")
        ))["streams"]
        self.assertTrue(owned)
        self.assertEqual(unowned_streams, [])

    def test_native_stremio_search_extra_path(self):
        token = "searchuser"
        user_path = USERS_DIR / token
        user_path.mkdir(parents=True, exist_ok=True)
        (user_path / "catalog.json").write_text("[]")
        FULL_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        FULL_CATALOG_PATH.write_text(json.dumps([self.movie, self.series]))

        result = response_json(asyncio.run(user_catalog_extra(
            token, "movie", f"khdiamond_movies_{token}", "search=Doctor+Strange"
        )))
        self.assertEqual([meta["id"] for meta in result["metas"]], ["tt1211837"])


if __name__ == "__main__":
    unittest.main()
