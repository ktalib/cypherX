import unittest

from app.services.spotify_service import normalize_spotify_uri


class TestSpotifyUri(unittest.TestCase):
    def test_accepts_spotify_uris(self):
        self.assertEqual(normalize_spotify_uri("spotify:track:abc123"), "spotify:track:abc123")
        self.assertEqual(
            normalize_spotify_uri("spotify:playlist:abc123"),
            "spotify:playlist:abc123",
        )

    def test_converts_track_and_localized_album_links(self):
        self.assertEqual(
            normalize_spotify_uri("https://open.spotify.com/track/abc123?si=share"),
            "spotify:track:abc123",
        )
        self.assertEqual(
            normalize_spotify_uri("https://open.spotify.com/intl-de/album/abc123"),
            "spotify:album:abc123",
        )

    def test_rejects_unrelated_or_unsupported_links(self):
        self.assertIsNone(normalize_spotify_uri("https://example.com/track/abc123"))
        self.assertIsNone(normalize_spotify_uri("https://open.spotify.com/search/song"))
        self.assertIsNone(normalize_spotify_uri("spotify:episode:abc123"))
        self.assertIsNone(normalize_spotify_uri(""))


if __name__ == "__main__":
    unittest.main()
