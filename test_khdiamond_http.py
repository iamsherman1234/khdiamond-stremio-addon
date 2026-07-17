import unittest

from khdiamond_http import (extract_media_id, extract_nonce, extract_post_id,
                            library_rows, response_embed_url)


class FakeResponse:
    def __init__(self, text, data=None):
        self.text = text
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class KhDiamondHelpersTest(unittest.TestCase):
    def test_current_dooplay_nonce_and_post_id(self):
        page = '''<script>var dtAjax = {"url":"/wp-admin/admin-ajax.php",
        "nonce":"0c7f8939eb","player_api":"/wp-json/dooplayer/v2/"};</script>
        <body class="single postid-848846">'''
        self.assertEqual(extract_nonce(page), "0c7f8939eb")
        self.assertEqual(extract_post_id(page), "848846")

    def test_json_and_html_player_responses(self):
        response = FakeResponse("json", {"embed_url": "https://player.kh-diamond.net/1/2/AbC_123"})
        self.assertEqual(extract_media_id(response_embed_url(response)), "AbC_123")
        response = FakeResponse('<iframe src="https://cdn.example/hls/movieABC/1080p.m3u8"></iframe>')
        self.assertEqual(extract_media_id(response_embed_url(response)), "movieABC")

    def test_library_layout_variants_and_relative_urls(self):
        page = '''
        <article id="post-42"><a href="/movies/movie-slug/"><img alt="Movie title"></a>
          <div class="data"><h3>Movie title</h3><span>2026</span></div></article>
        <div class="items"><div><a href="/series/show-slug/"><span class="title">Show</span></a></div></div>'''
        rows = library_rows(page)
        self.assertEqual([(r["kind"], r["slug"]) for r in rows],
                         [("movies", "movie-slug"), ("tvshows", "show-slug")])
        self.assertEqual(rows[0]["article_id"], "post-42")


if __name__ == "__main__":
    unittest.main()
