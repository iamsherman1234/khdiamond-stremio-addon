import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("FULL_CATALOG_PATH", str(Path(tempfile.gettempdir()) / "full_catalog_test.json"))
os.environ.setdefault("FULL_CATALOG_CACHE", str(Path(tempfile.gettempdir()) / "full_catalog_cache_test.json"))

from scrape_full_catalog import (  # noqa: E402
    CACHE_VERSION,
    acceptable_tmdb_candidate,
    catalog_size_is_safe,
    cache_entry_is_current,
    scrape_page_details,
    score_tmdb_candidate,
    source_signature,
    valid_poster_url,
)


class FakeResponse:
    status_code = 200
    text = """
      <div class="data"><h1>( ទី19 ) ដុកទ័រស្ត្រេង</h1></div>
      <div class="custom_fields"><b class="variante">ចំណងជើងដើម</b>
        <span class="valor">Doctor Strange</span></div>
      <span class="date">Oct. 25, 2016</span>
      <div class="wp-content"><p>Khmer overview</p></div>
    """


class FakeSession:
    def get(self, *_args, **_kwargs):
        return FakeResponse()


class NotFoundSession:
    def get(self, *_args, **_kwargs):
        response = FakeResponse()
        response.status_code = 404
        response.text = ""
        return response


class FullCatalogTest(unittest.TestCase):
    def test_cache_rejects_reused_slug_with_new_title(self):
        old = {"slug": "opaque", "title_khmer": "Old", "page_url": "https://khdiamond.net/movies/opaque/"}
        new = dict(old, title_khmer="Doctor Strange")
        entry = {
            "_cache_version": CACHE_VERSION,
            "_source_signature": source_signature(old, "movie"),
            "slug": "opaque",
            "type": "movie",
        }
        self.assertTrue(cache_entry_is_current(entry, old, "movie"))
        self.assertFalse(cache_entry_is_current(entry, new, "movie"))

    def test_large_transient_catalog_shrink_is_rejected(self):
        self.assertTrue(catalog_size_is_safe(460, 461))
        self.assertFalse(catalog_size_is_safe(392, 461))

    def test_dooplay_placeholder_is_not_a_poster(self):
        self.assertFalse(valid_poster_url(
            "https://khdiamond.net/wp-content/themes/dooplay/assets/img/ssss2.png"
        ))
        self.assertTrue(valid_poster_url(
            "https://khdiamond.net/wp-content/uploads/2026/05/Poster-1-scaled.jpg"
        ))

    def test_tmdb_requires_close_title_and_matching_year(self):
        candidate = {
            "title": "Doctor Strange",
            "release_date": "2016-10-25",
            "popularity": 20,
            "overview": "",
        }
        score = score_tmdb_candidate(candidate, "Doctor Strange", "2016")
        self.assertTrue(acceptable_tmdb_candidate(candidate, "Doctor Strange", "2016", score))
        self.assertFalse(acceptable_tmdb_candidate(candidate, "Doctor Strange", "2025", score))
        self.assertFalse(acceptable_tmdb_candidate(candidate, "Unrelated Film", "2016", score))

    def test_tmdb_accepts_exact_non_latin_original_title(self):
        for title, year in (("히트맨", "2020"), ("好东西", "2024")):
            candidate = {
                "original_title": title,
                "release_date": f"{year}-01-01",
                "popularity": 10,
                "overview": "",
            }
            score = score_tmdb_candidate(candidate, title, year)
            self.assertTrue(acceptable_tmdb_candidate(candidate, title, year, score))

    def test_original_title_is_scraped_from_site_field(self):
        details = scrape_page_details(FakeSession(), "https://khdiamond.net/movies/opaque/")
        self.assertEqual(details["original_title"], "Doctor Strange")
        self.assertEqual(details["year"], "2016")

    def test_detail_page_reports_not_found(self):
        details = scrape_page_details(NotFoundSession(), "https://khdiamond.net/movies/deleted/")
        self.assertEqual(details["status_code"], 404)
        self.assertFalse(details["poster"])


if __name__ == "__main__":
    unittest.main()
