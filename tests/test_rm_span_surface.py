"""Synthetic contract tests for the text-only RM code-point span route."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from rm_app_harness import fixed_candidates, load_app, post_spans


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/rm-span-surface-v1.json").read_text(encoding="utf-8")
)


def tag_of(placeholder):
    match = re.fullmatch(r"\[([A-Z][A-Z0-9_]*)_[1-9][0-9]*\]", placeholder)
    if not match:
        raise AssertionError("invalid_placeholder")
    return match.group(1)


class SpanSurface(unittest.TestCase):
    def response(self, case):
        app = load_app()
        fixed_candidates(app, case["entities"])
        body, status = post_spans(
            app, {"text": case["text"], "exclude_tags": []}
        )
        self.assertEqual(status, 200, "span_status")
        return app, body

    def test_spans_match_analyze_mapping_surfaces(self):
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                app, body = self.response(case)
                analyzed = app["analyze"](case["text"], [], True)
                actual = sorted(
                    (span["tag"], case["text"][span["start"]:span["end"]])
                    for span in body["spans"]
                )
                expected = sorted(
                    (tag_of(placeholder), value)
                    for placeholder, value in analyzed["mapping"].items()
                )
                self.assertEqual(actual, expected, "span_mapping_surfaces")

    def test_offsets_are_raw_codepoints(self):
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                _app, body = self.response(case)
                surfaces = [case["text"][span["start"]:span["end"]] for span in body["spans"]]
                self.assertEqual(surfaces, case["values"], "raw_codepoint_slices")

    def test_multi_chunk_text_offsets_are_global(self):
        app = load_app()
        words = [f"parola{i}" for i in range(140)]
        words[130:132] = ["Mario", "Rossi"]
        text = " ".join(words)

        def inference(chunks):
            return [[{
                "entity_group": "FULLNAME",
                "start": chunk.index("Mario Rossi"),
                "end": chunk.index("Mario Rossi") + len("Mario Rossi"),
                "score": 0.97,
            }] if "Mario Rossi" in chunk else [] for chunk in chunks]

        app["nlp"] = inference
        app["detect_regex"] = lambda _text: []
        body, status = post_spans(app, {"text": text, "exclude_tags": []})
        self.assertEqual(status, 200, "multi_chunk_status")
        self.assertEqual(len(body["spans"]), 1, "multi_chunk_dedup")
        span = body["spans"][0]
        self.assertEqual(text[span["start"]:span["end"]], "Mario Rossi", "global_offset")

    def test_response_contains_no_values(self):
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                _app, body = self.response(case)
                serialized = json.dumps(body, ensure_ascii=False)
                for value in case["values"]:
                    self.assertNotIn(value, serialized, "value_leaked")
                for key in ("anonymized_text", "mapping", "source_text"):
                    self.assertNotIn(key, body, "forbidden_response_key")

    def test_text_sha256_is_of_received_text(self):
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                _app, body = self.response(case)
                expected = hashlib.sha256(case["text"].encode("utf-8")).hexdigest()
                self.assertEqual(body["text_sha256"], expected, "received_text_hash")

    def test_contract_shape_and_sources(self):
        case = FIXTURE["cases"][2]
        _app, body = self.response(case)
        self.assertEqual(body["contract"], FIXTURE["contract"], "contract")
        self.assertEqual(body["offset_unit"], "codepoint", "offset_unit")
        self.assertEqual(set(body), {"contract", "offset_unit", "text_sha256", "spans"})
        self.assertEqual(set(body["spans"][0]), {"start", "end", "tag", "score", "source"})
        self.assertEqual(body["spans"][0]["source"], "regex", "regex_source")
        self.assertIsNone(body["spans"][0]["score"], "regex_score")

    def test_whitespace_only_is_400(self):
        app = load_app()
        app["nlp"] = lambda _chunks: self.fail("blank_reached_inference")
        for text in ("", " \t\r\n", "\u00a0"):
            with self.subTest(text_length=len(text)):
                body, status = post_spans(app, {"text": text, "exclude_tags": []})
                self.assertEqual(status, 400, "blank_status")
                self.assertEqual(set(body), {"error"}, "blank_error_shape")


if __name__ == "__main__":
    unittest.main()
