"""Synthetic, offline contract tests; actual source functions, no inference.

Failures expose only test names/counts and stable assertion messages, never a
text/mapping diff. Fixed expected vectors are independent of production code.
"""
import ast
import copy
import json
from pathlib import Path
import re
import unittest

from rm_app_harness import ROOT, definitions, fixed_candidates, load_app, post, restore

VECTORS = json.loads((Path(__file__).parent / "fixtures/rm-exact-surface-v1.json")
                     .read_text(encoding="utf-8"))["cases"]
FIELDS = {"segments", "anonymized_text", "mapping", "mapping_enabled", "n_chunks",
          "n_chars", "n_entities", "n_unique", "by_label", "by_source", "excluded_tags"}


def entity(start, end, *, label="FULLNAME", score=0.9, validated=False, source="modello"):
    return {"label": label, "start": start, "end": end, "score": score,
            "validated": validated, "source": source}


class ExactSurface(unittest.TestCase):
    def same(self, actual, expected, code):
        self.assertTrue(actual == expected, code)

    def test_app_has_no_unused_normalizer(self):
        tree = ast.parse((ROOT / "src/app/app.py").read_text(encoding="utf-8"))
        self.assertTrue(not any(isinstance(node, ast.FunctionDef) and node.name == "_norm"
                                for node in tree.body), "remove_unused_app_normalizer")

    def test_docs_scope_support_to_text_and_record_pdf_skips(self):
        doc = " ".join((ROOT / "RM_FORK.md").read_text(encoding="utf-8").split())
        self.assertTrue("PDF routes are outside the RM PoC contract and are not attested or supported" in doc,
                        "pdf_scope_must_be_explicit")
        self.assertTrue("other PDF/UI routes retain upstream behaviour" not in doc,
                        "no_unverified_pdf_behavior_claim")
        self.assertTrue("10 dependency-gated tests remain skipped" in doc,
                        "dependency_skips_must_be_explicit")
        guidance = " ".join((ROOT / "CLAUDE.md").read_text(encoding="utf-8").split())
        self.assertTrue("la risposta non ha `mapping`" not in guidance,
                        "mapping_off_keeps_empty_mapping_field")
        self.assertTrue("`source_text` continua a tornare" not in guidance,
                        "mapping_off_omits_source_text")

    def test_pdf_patterns_still_merge_forms_outside_text_contract(self):
        path = ROOT / "src/app/pdf_export.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        namespace = {"re": re}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in {"_HYPHEN_BREAK", "_UNANCHORED_MIN_ALNUM"}:
                    namespace[target.id] = ast.literal_eval(node.value)
        module = ast.Module(body=definitions(path, {"_norm", "_value_pattern"}), type_ignores=[])
        exec(compile(module, str(path), "exec"), namespace)
        forms = ["Mario Rossi", "MARIO ROSSI", "Mario  Rossi"]
        patterns = [namespace["_value_pattern"](value) for value in forms]
        self.same(len({(p.pattern, p.flags) for p in patterns}), 1, "pdf_still_normalizes_patterns")
        self.assertTrue(all(pattern.fullmatch(value) for pattern in patterns for value in forms),
                        "pdf_variants_share_matches")
        app = load_app()
        fixed_candidates(app, [entity(0, 11), entity(14, 25), entity(28, 40)])
        out = app["analyze"](" | ".join(forms))
        self.same(list(out["mapping"].values()), forms, "text_mappings_remain_distinct")

    def test_fixed_surface_vectors(self):
        for case in VECTORS:
            with self.subTest(case=case["id"]):
                app = load_app()
                fixed_candidates(app, case["entities"])
                out = app["analyze"](case["text"], case["excluded"], case["mappingEnabled"])
                self.same(out["anonymized_text"], case["expected"]["anonymized_text"], "exact_anonymized_text")
                self.same(out["mapping"], case["expected"]["mapping"], "exact_mapping")
                self.same(set(out), FIELDS, "response_shape")
                if case["mappingEnabled"]:
                    self.same(restore(out["anonymized_text"], out["mapping"]).encode("utf-8"),
                              case["text"].encode("utf-8"), "exact_utf8_round_trip")

    def test_json_route_preserves_outer_whitespace(self):
        app = load_app()
        # No detections isolates route loss from the independently tested dedup bug.
        fixed_candidates(app, [])
        text = "\t Riga sintetica. \r\n"
        out, status = post(app, {"text": text, "include_mapping": True, "exclude_tags": []})
        self.same(status, 200, "json_status")
        self.same(out["source_text"], text, "source_text_preserves_outer_whitespace")
        self.same(out["anonymized_text"], text, "route_preserves_outer_whitespace")
        self.same(out["n_chars"], len(text), "original_character_count")
        self.same(set(out), FIELDS | {"source_text"}, "json_response_shape")

    def test_blank_json_requests_still_return_400(self):
        for payload in [{}, {"text": None}, {"text": ""}, {"text": "\t \r\n\u00a0"}]:
            with self.subTest(kind=list(payload)):
                app = load_app()
                app["nlp"] = lambda chunks: self.fail("blank_input_reached_inference")
                out, status = post(app, payload)
                self.same(status, 400, "blank_status")
                self.same(set(out), {"error"}, "blank_error_shape")

    def test_uploaded_text_keeps_existing_trim_behavior(self):
        app = load_app()
        fixed_candidates(app, [])
        out, status = post(app, upload_text="\t Riga sintetica. \r\n",
                           form={"include_mapping": "true", "exclude_tags": ""})
        self.same(status, 200, "upload_status")
        self.same(out["source_text"], "Riga sintetica.", "upload_still_trimmed")
        self.same(out["anonymized_text"], "Riga sintetica.", "upload_output")

    def test_mapping_disabled_omits_entity_originals(self):
        app = load_app()
        fixed_candidates(app, [entity(0, 11)])
        out, status = post(app, {"text": "Mario Rossi", "include_mapping": False})
        self.same(status, 200, "mapping_off_status")
        self.same(set(out), FIELDS, "mapping_off_no_source_text")
        self.same(out["mapping"], {}, "mapping_off_empty_mapping")
        self.same(out["anonymized_text"], "[FULLNAME_1]", "mapping_off_placeholder")
        self.assertTrue(all("t" not in row for row in out["segments"] if "label" in row),
                        "mapping_off_no_entity_preview_values")

    def test_request_overrides_do_not_change_defaults(self):
        app = load_app()
        fixed_candidates(app, [entity(0, 11)])
        app["_get_prefs"] = lambda: (["FULLNAME"], False)
        overridden, _ = post(app, {"text": "Mario Rossi", "include_mapping": True, "exclude_tags": []})
        self.same(overridden["mapping"], {"[FULLNAME_1]": "Mario Rossi"}, "override_mapping")
        default, _ = post(app, {"text": "Mario Rossi"})
        self.same(default["anonymized_text"], "Mario Rossi", "default_exclusion_unchanged")
        self.same(default["mapping"], {}, "default_mapping_unchanged")
        self.assertTrue("source_text" not in default, "default_no_source_text")

    def test_each_request_starts_a_fresh_mapping(self):
        app = load_app()
        fixed_candidates(app, [entity(0, 11)])
        first, _ = post(app, {"text": "Mario Rossi"})
        second, _ = post(app, {"text": "MARIA ROSSI"})
        self.same(first["mapping"], {"[FULLNAME_1]": "Mario Rossi"}, "first_mapping")
        self.same(second["mapping"], {"[FULLNAME_1]": "MARIA ROSSI"}, "fresh_counter_and_value")

    def test_health_retains_fields_and_adds_fork_identity(self):
        app = load_app()
        expected = {
            "status": "ok", "model_loaded": True,
            "model": "a1c3c83827eca22e9675e30c1111c4641caf5901",
            "model_version": "1.5.0", "app_version": "2.0.0", "device": "cpu",
            "tags": 24, "excluded_tags": [], "mapping_enabled": True,
            "rm_fork_repository": "https://github.com/mauriziodalre-ai/rizzo-pii-rm",
            "rm_upstream_commit": "9057eeff88bdf0444e5d3361cf0766b60c5b8a95",
            "rm_surface_contract": "rm-exact-surface-v1",
            "rm_span_contract": "rm-span-surface-v1",
        }
        body, status = app["health"]()
        self.same(status, 200, "ready_status")
        self.same(body, expected, "fork_health_identity_and_shape")
        app["nlp"] = None
        body, status = app["health"]()
        self.same(status, 503, "loading_status")
        self.same(body, {**expected, "status": "loading", "model_loaded": False}, "loading_health")

    def test_overlap_priority_preserves_selected_surface(self):
        app = load_app()
        text = "Mario  Rossi | MARIO ROSSI"
        # Each table row has an unambiguous winner before any text/mapping patch.
        rows = [
            ("validated", entity(0, 12, validated=True, score=0.1), entity(0, 12, label="ORG", score=1.0, source="regex")),
            ("regex", entity(0, 12, score=0.1, source="regex"), entity(0, 12, label="ORG", score=1.0)),
            ("score", entity(0, 5, score=0.9), entity(0, 12, label="ORG", score=0.2)),
            ("length", entity(0, 12), entity(0, 5, label="ORG")),
            ("soft_regex", entity(0, 12, score=0.9), entity(0, 12, label="DATE", source="regex", score=0.1)),
        ]
        for kind, winner, loser in rows:
            for candidates in ([winner, loser], [loser, winner]):
                with self.subTest(priority=kind, first=candidates[0]["label"]):
                    selected = app["_merge"](copy.deepcopy(candidates), text)
                    self.same(len(selected), 1, "one_selected_overlap")
                    self.same((selected[0]["label"], selected[0]["start"], selected[0]["end"]),
                              (winner["label"], winner["start"], winner["end"]), "priority_and_offsets")
                    self.same(text[selected[0]["start"]:selected[0]["end"]],
                              "Mario" if kind == "score" else "Mario  Rossi", "selected_exact_slice")
        boundary = " \tMario  Rossi! "
        selected = app["_merge"]([entity(0, 14)], boundary)
        self.same((selected[0]["start"], selected[0]["end"]), (2, 14), "boundary_whitespace_trim")
        selected = app["_merge"]([entity(3, 6)], boundary)
        self.same((selected[0]["start"], selected[0]["end"]), (2, 7), "word_boundary_expansion")
        candidates = [entity(0, 12, validated=True, score=0.1), entity(0, 5, label="ORG", score=1.0),
                      entity(15, 26), entity(15, 20, label="DATE", score=0.1, source="regex")]
        fixed_candidates(app, candidates)
        out = app["analyze"](text)
        self.same(out["n_entities"], 2, "discard_overlapping_candidates")
        self.same(out["mapping"], {"[FULLNAME_1]": "Mario  Rossi", "[FULLNAME_2]": "MARIO ROSSI"},
                  "overlap_distinct_exact_mappings")
        self.same(out["anonymized_text"], "[FULLNAME_1] | [FULLNAME_2]", "overlap_single_replacement")
        self.same(restore(out["anonymized_text"], out["mapping"]).encode(), text.encode(), "overlap_round_trip")

    def test_overlapping_chunks_map_each_global_span_once(self):
        app = load_app()
        words = [f"parola{i}" for i in range(140)]
        words[0] = "caffè"
        words[110:112] = ["Mario", "Rossi"]
        words[130:132] = ["MARIO", "ROSSI"]
        text = "\t " + " ".join(words).replace("Mario Rossi", "Mario  Rossi") + " \r\n"
        surfaces = ("Mario  Rossi", "MARIO ROSSI")

        def inference(chunks):
            return [[{"entity_group": "FULLNAME", "start": match.start(), "end": match.end(), "score": 0.9}
                     for surface in surfaces for match in re.finditer(re.escape(surface), chunk)]
                    for chunk in chunks]

        app["nlp"] = inference
        app["detect_regex"] = lambda value: []
        chunks = app["chunk_text"](text)
        self.same(len(chunks), 2, "two_overlapping_chunks")
        self.same([offset for _, offset in chunks], [2, text.index("parola100")], "chunk_global_offsets")
        detected, count = app["detect_model"](text)
        self.same(count, 2, "detector_chunk_count")
        first = (text.index(surfaces[0]), text.index(surfaces[0]) + len(surfaces[0]))
        second = (text.index(surfaces[1]), text.index(surfaces[1]) + len(surfaces[1]))
        self.same([(e["start"], e["end"]) for e in detected], [first, first, second], "duplicate_global_spans")
        self.same([text[e["start"]:e["end"]] for e in detected], [surfaces[0], surfaces[0], surfaces[1]], "global_exact_slices")
        out = app["analyze"](text)
        self.same(out["n_chunks"], 2, "analysis_chunk_count")
        self.same(out["n_entities"], 2, "duplicate_detection_removed")
        self.same(out["mapping"], {"[FULLNAME_1]": surfaces[0], "[FULLNAME_2]": surfaces[1]}, "chunk_distinct_exact_mappings")
        self.same(out["n_unique"], 2, "two_unique_surface_forms")
        self.same(out["anonymized_text"].count("[FULLNAME_1]"), 1, "first_span_replaced_once")
        self.same(out["anonymized_text"].count("[FULLNAME_2]"), 1, "second_span_replaced_once")
        self.same(restore(out["anonymized_text"], out["mapping"]).encode(), text.encode(), "chunk_round_trip")


if __name__ == "__main__":
    unittest.main()
