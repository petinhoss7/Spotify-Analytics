import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify_tags as ct

GENRES, EXACT_INDEX, AMBIGUOUS = ct.load_taxonomy()
FUZZY_KEYS = sorted(EXACT_INDEX)


class TestNormalize(unittest.TestCase):
    def test_accents(self):
        self.assertEqual(ct.normalize("variété française"), "variete francaise")

    def test_ampersand(self):
        self.assertEqual(ct.normalize("R&B"), "r and b")

    def test_punctuation(self):
        self.assertEqual(ct.normalize("Hip-Hop"), "hip hop")
        self.assertEqual(ct.normalize("drum'n'bass"), "drum n bass")
        self.assertEqual(ct.normalize("  Björk  "), "bjork")

    def test_empty(self):
        self.assertEqual(ct.normalize("---"), "")


class TestTaxonomy(unittest.TestCase):
    def test_counts(self):
        # 611 styles after the merge with the Quantixed Discogs export
        # (372 before). These numbers must be updated deliberately whenever
        # the taxonomy is rebuilt with scripts/build_taxonomy.py.
        self.assertEqual(len(GENRES), 15)
        self.assertEqual(sum(len(v) for v in GENRES.values()), 611)
        # a genre that is also its own style ("Classical", "Reggae") collapses
        # onto one key, so there are fewer keys than genre + style entries
        self.assertEqual(len(FUZZY_KEYS) + len(AMBIGUOUS), 608)

    def test_no_spelling_collisions(self):
        # two spellings of one style ("Norteño" / "Norteno") would fold onto a
        # single normalized key; build_taxonomy.py dedupes them, and this is
        # the invariant that guarantees it
        seen: dict[str, set] = {}
        for genre, styles in GENRES.items():
            for style in styles:
                seen.setdefault(ct.normalize(style), set()).add(style)
        collisions = {key: value for key, value in seen.items() if len(value) > 1}
        self.assertEqual(collisions, {})

    def test_no_style_is_another_genres_name(self):
        # "Hip Hop" as a style under Electronic would make the tag "hip hop"
        # ambiguous and send it to the LLM instead of resolving it
        genre_keys = {ct.normalize(g) for g in GENRES}
        offenders = [
            (genre, style)
            for genre, styles in GENRES.items()
            for style in styles
            if ct.normalize(style) in genre_keys and ct.normalize(style) != ct.normalize(genre)
        ]
        self.assertEqual(offenders, [])

    def test_genre_style_merges(self):
        self.assertEqual(EXACT_INDEX["classical"], ("Classical", "Classical"))
        self.assertEqual(EXACT_INDEX["reggae"], ("Reggae", "Reggae"))

    def test_known_ambiguous_keys(self):
        for key in ["dub", "disco", "rhythm and blues", "boom bap", "trip hop", "hardcore", "ska", "gospel", "afrobeat", "parody", "noise", "industrial"]:
            self.assertIn(key, AMBIGUOUS, key)

    def test_same_genre_collision_prefers_pair(self):
        self.assertEqual(EXACT_INDEX["classical"], ("Classical", "Classical"))

    def test_exact_lookups(self):
        self.assertEqual(EXACT_INDEX["funk"], ("Funk / Soul", "Funk"))
        self.assertEqual(EXACT_INDEX["soft rock"], ("Rock", "Soft Rock"))
        self.assertEqual(EXACT_INDEX["hip hop"], ("Hip Hop", None))
        self.assertEqual(EXACT_INDEX["drum n bass"], ("Electronic", "Drum n Bass"))


class TestAliases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aliases = ct.load_aliases(ct.ALIASES_PATH, GENRES, EXACT_INDEX, AMBIGUOUS)

    def test_real_file_loads(self):
        self.assertGreater(len(self.aliases), 30)

    def test_rewrite_to_genre(self):
        self.assertEqual(ct.alias_lookup("hiphop", self.aliases, EXACT_INDEX), ("Hip Hop", None))
        self.assertEqual(ct.alias_lookup("rap", self.aliases, EXACT_INDEX), ("Hip Hop", None))

    def test_rewrite_to_style(self):
        self.assertEqual(ct.alias_lookup("dnb", self.aliases, EXACT_INDEX), ("Electronic", "Drum n Bass"))
        self.assertEqual(ct.alias_lookup("kpop", self.aliases, EXACT_INDEX), ("Pop", "K-pop"))
        self.assertEqual(ct.alias_lookup("chanson francaise", self.aliases, EXACT_INDEX), ("Pop", "Chanson"))

    def test_unknown_alias_misses(self):
        self.assertIsNone(ct.alias_lookup("not-an-alias", self.aliases, EXACT_INDEX))

    def test_invalid_target_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "aliases.csv"
            p.write_text("alias,target\nfoo,Not A Real Style\n", encoding="utf-8")
            with self.assertRaises(ct.BuildError):
                ct.load_aliases(p, GENRES, EXACT_INDEX, AMBIGUOUS)

    def test_invalid_pair_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "aliases.csv"
            p.write_text("alias,target\nfoo,Pop|Techno\n", encoding="utf-8")
            with self.assertRaises(ct.BuildError):
                ct.load_aliases(p, GENRES, EXACT_INDEX, AMBIGUOUS)

    def test_valid_pair_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "aliases.csv"
            p.write_text("alias,target\nfoo,Pop|Chanson\n", encoding="utf-8")
            aliases = ct.load_aliases(p, GENRES, EXACT_INDEX, AMBIGUOUS)
            self.assertEqual(ct.alias_lookup("foo", aliases, EXACT_INDEX), ("Pop", "Chanson"))


class TestStaticClassify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = ct.build_containment_index(EXACT_INDEX, GENRES)

    def test_l1_exact(self):
        pair, method, score = ct.static_classify("funk", EXACT_INDEX, {}, self.entries)
        self.assertEqual((pair, method, score), (("Funk / Soul", "Funk"), "exact", 100))

    def test_l2_alias(self):
        aliases = ct.load_aliases(ct.ALIASES_PATH, GENRES, EXACT_INDEX, AMBIGUOUS)
        pair, method, _ = ct.static_classify("hiphop", EXACT_INDEX, aliases, self.entries)
        self.assertEqual((pair, method), (("Hip Hop", None), "alias"))

    def test_l3_containment_longest_key_wins(self):
        pair, method, score = ct.static_classify("old school thrash", EXACT_INDEX, {}, self.entries)
        self.assertEqual((pair, method, score), (("Rock", "Thrash"), "fuzzy", 90))
        pair, _, _ = ct.static_classify("salsa 1990 2000", EXACT_INDEX, {}, self.entries)
        self.assertEqual(pair, ("Latin", "Salsa"))
        pair, _, _ = ct.static_classify("underground greek hip hop", EXACT_INDEX, {}, self.entries)
        self.assertEqual(pair, ("Hip Hop", None))
        pair, _, _ = ct.static_classify("gangsta funk", EXACT_INDEX, {}, self.entries)
        self.assertEqual(pair, ("Funk / Soul", "Funk"))

    def test_l3_no_substring_garbage(self):
        for tag in ["draincore", "frecnh rap", "tgaoatcore", "zzz"]:
            self.assertIsNone(ct.static_classify(tag, EXACT_INDEX, {}, self.entries), tag)

    def test_l3_never_resolves_ambiguous_keys(self):
        for tag in ["sunny dub", "modern gospel", "garage disco", "comedy rap", "opera rock"]:
            self.assertIsNone(ct.static_classify(tag, EXACT_INDEX, {}, self.entries), tag)

    def test_l3_genre_name_containment(self):
        pair, method, _ = ct.static_classify("instrumental rock", EXACT_INDEX, {}, self.entries)
        self.assertEqual((pair, method), (("Rock", None), "fuzzy"))
        pair, _, _ = ct.static_classify("mississippi blues", EXACT_INDEX, {}, self.entries)
        self.assertEqual(pair, ("Blues", None))
        pair, _, _ = ct.static_classify("classical piano", EXACT_INDEX, {}, self.entries)
        self.assertEqual(pair, ("Classical", "Classical"))

    def test_ambiguous_key_as_exact_phrase_is_fine(self):
        pair, method, _ = ct.static_classify("italo disco", EXACT_INDEX, {}, self.entries)
        self.assertEqual((pair, method), (("Electronic", "Italo-Disco"), "exact"))

    def test_no_match(self):
        self.assertIsNone(ct.static_classify("zzzqqqwww", EXACT_INDEX, {}, self.entries))


class TestValidateEntries(unittest.TestCase):
    def test_valid(self):
        requested = ["funk", "seen live"]
        parsed = {"classifications": [
            {"tag": "funk", "is_genre_tag": True, "genre": "Funk / Soul", "style": "Funk"},
            {"tag": "seen live", "is_genre_tag": False, "genre": None, "style": None},
        ]}
        accepted, invalid, problems = ct.validate_entries(requested, parsed, GENRES)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(invalid, [])
        self.assertEqual(accepted["seen live"], {"is_genre_tag": False, "genre": None, "style": None})

    def test_empty_string_style_treated_as_null(self):
        parsed = {"classifications": [{"tag": "rap", "is_genre_tag": True, "genre": "Hip Hop", "style": ""}]}
        accepted, invalid, _ = ct.validate_entries(["rap"], parsed, GENRES)
        self.assertEqual(accepted["rap"], {"is_genre_tag": True, "genre": "Hip Hop", "style": None})

    def test_genre_not_in_list(self):
        parsed = {"classifications": [{"tag": "x", "is_genre_tag": True, "genre": "Made Up", "style": None}]}
        accepted, invalid, problems = ct.validate_entries(["x"], parsed, GENRES)
        self.assertEqual(accepted, {})
        self.assertEqual(invalid, ["x"])

    def test_style_wrong_genre(self):
        parsed = {"classifications": [{"tag": "x", "is_genre_tag": True, "genre": "Pop", "style": "Techno"}]}
        accepted, invalid, _ = ct.validate_entries(["x"], parsed, GENRES)
        self.assertEqual(accepted, {})
        self.assertEqual(invalid, ["x"])

    def test_non_genre_with_genre_is_invalid(self):
        parsed = {"classifications": [{"tag": "x", "is_genre_tag": False, "genre": "Pop", "style": None}]}
        accepted, invalid, _ = ct.validate_entries(["x"], parsed, GENRES)
        self.assertEqual(accepted, {})
        self.assertEqual(invalid, ["x"])

    def test_missing_entry(self):
        parsed = {"classifications": []}
        accepted, invalid, _ = ct.validate_entries(["a", "b"], parsed, GENRES)
        self.assertEqual(accepted, {})
        self.assertEqual(sorted(invalid), ["a", "b"])

    def test_not_a_dict(self):
        accepted, invalid, _ = ct.validate_entries(["a"], ["nope"], GENRES)
        self.assertEqual(accepted, {})
        self.assertEqual(invalid, ["a"])


class TestParseLlmJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(ct.parse_llm_json('{"classifications": []}'), {"classifications": []})

    def test_fenced(self):
        self.assertEqual(ct.parse_llm_json('```json\n{"classifications": []}\n```'), {"classifications": []})

    def test_with_prose(self):
        self.assertEqual(ct.parse_llm_json('Here you are: {"classifications": []} hope it helps'), {"classifications": []})


class TestCache(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cache.json"
            ct.save_cache(p, {"funk": {"is_genre_tag": True, "genre": "Funk / Soul", "style": "Funk"}})
            self.assertEqual(ct.load_cache(p)["funk"]["genre"], "Funk / Soul")

    def test_corrupt_cache_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cache.json"
            p.write_text("{not json", encoding="utf-8")
            self.assertEqual(ct.load_cache(p), {})


class TestLLMClient(unittest.TestCase):
    def _ok_response(self):
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": '{"classifications": []}'}}]}
        return resp

    def test_retries_then_succeeds(self):
        client = ct.LLMClient("k", "m")
        timeout = __import__("requests").Timeout
        with mock.patch.object(ct.requests, "post", side_effect=[timeout(), timeout(), self._ok_response()]), \
             mock.patch.object(ct.time, "sleep"):
            self.assertEqual(client.chat([{"role": "user", "content": "x"}]), '{"classifications": []}')

    def test_circuit_opens_after_consecutive_failures(self):
        client = ct.LLMClient("k", "m")
        timeout = __import__("requests").Timeout
        with mock.patch.object(ct.requests, "post", side_effect=timeout()), \
             mock.patch.object(ct.time, "sleep"):
            with self.assertRaises(ct.CircuitOpen):
                client.chat([{"role": "user", "content": "x"}])
            self.assertEqual(client._consecutive_failures, ct.CIRCUIT_THRESHOLD)

    def test_circuit_open_short_circuits(self):
        client = ct.LLMClient("k", "m")
        client._consecutive_failures = ct.CIRCUIT_THRESHOLD
        with mock.patch.object(ct.requests, "post", side_effect=AssertionError("must not be called")):
            with self.assertRaises(ct.CircuitOpen):
                client.chat([{"role": "user", "content": "x"}])

    def test_http_400_disables_json_mode(self):
        client = ct.LLMClient("k", "m")
        bad = mock.Mock()
        bad.status_code = 400
        bad.text = "response_format not supported"
        bodies = []
        def fake_post(url, headers=None, json=None, timeout=None):
            bodies.append(json)
            if "response_format" in json:
                return bad
            return self._ok_response()
        with mock.patch.object(ct.requests, "post", side_effect=fake_post):
            out = client.chat([{"role": "user", "content": "x"}])
        self.assertEqual(out, '{"classifications": []}')
        self.assertFalse(client.json_mode)
        self.assertNotIn("response_format", bodies[-1])


class TestNoise(unittest.TestCase):
    def test_numbers_years_hex(self):
        for tag in ["112", "1920s", "00 s", "00c04fd7d062", "18100", "'00s"]:
            self.assertTrue(ct.is_noise(ct.normalize(tag)), tag)

    def test_real_tags_not_noise(self):
        for tag in ["hard rock", "12 string", "1052 chill", "140bpm"]:
            self.assertFalse(ct.is_noise(ct.normalize(tag)), tag)


class TestSystemPrompt(unittest.TestCase):
    def test_taxonomy_embedded(self):
        prompt = ct.build_system_prompt(GENRES)
        self.assertIn("Psy-Trance", prompt)
        self.assertIn("Funk / Soul", prompt)
        self.assertNotIn("{TAXONOMY}", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
