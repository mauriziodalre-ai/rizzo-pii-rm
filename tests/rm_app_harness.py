"""Run actual text functions without app startup, model libraries or a server.

Only named function definitions, literal app constants and the fork-identity
import are compiled from app.py. Function bodies are never rewritten. Regex
helpers are the real stdlib-only detectors; individual tests may supply fixed
detections or fake nlp outputs at the inference boundary.
"""
import ast
import bisect
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/app/app.py"
FUNCTIONS = {
    "_is_word", "_merge", "chunk_text", "detect_model", "detect_spans", "analyze",
    "analyze_route", "span_route", "health",
}
CONSTANTS = {"MAX_WORDS", "OVERLAP", "APP_VERSION", "APP_MODEL_VERSION", "TAGS"}


def definitions(path, names):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise AssertionError("required_source_function_missing")
    for node in nodes:
        node.decorator_list = []
    return nodes


def load_app():
    detector_path = ROOT / "src/app/detectors.py"
    spec = importlib.util.spec_from_file_location("rm_test_detectors", detector_path)
    detectors = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detectors)
    config = {}
    config_path = ROOT / "src/app/server_config.py"
    exec(compile(ast.Module(body=definitions(config_path, {"parse_tag_list", "parse_bool"}),
                            type_ignores=[]), str(config_path), "exec"), config)
    namespace = {
        "bisect": bisect, "re": re, "os": os, "hashlib": hashlib,
        "SOFT_REGEX_LABELS": detectors.SOFT_REGEX_LABELS,
        "complete_time": detectors.complete_time,
        "detect_regex": detectors.detect_regex,
        "nlp": lambda chunks: [[] for _ in chunks],
        "jsonify": lambda body: body,
        "server_config": SimpleNamespace(**{name: config[name] for name in
                                            ("parse_tag_list", "parse_bool")}),
        "_get_prefs": lambda: ([], True),
        "MODEL_DIR": "/synthetic/model/a1c3c83827eca22e9675e30c1111c4641caf5901",
        "device": -1,
    }
    tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
    found = set()
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in CONSTANTS:
                namespace[target.id] = ast.literal_eval(node.value)
                found.add(target.id)
        if isinstance(node, ast.ImportFrom) and node.module == "rm_fork_identity":
            imports.append(node)
    if found != CONSTANTS:
        raise AssertionError("required_source_constant_missing")
    namespace["TAG_NAMES"] = [row[0] for row in namespace["TAGS"]]
    module = ast.Module(body=imports + definitions(APP, FUNCTIONS), type_ignores=[])
    sys.path.insert(0, str(APP.parent))
    try:
        exec(compile(module, str(APP), "exec"), namespace)
    finally:
        del sys.path[0]
    return namespace


def fixed_candidates(app, entities):
    """Bypass inference only; analyze still executes actual _merge and assembly."""
    app["detect_model"] = lambda text: (copy.deepcopy(entities), 1)
    app["detect_regex"] = lambda text: []


def post(app, payload=None, *, upload_text=None, form=None):
    """Invoke the actual route with request/file dependencies, without HTTP."""
    app["request"] = SimpleNamespace(get_json=lambda silent: payload, form=form or {})
    app["_uploaded_file"] = lambda: None if upload_text is None else object()
    app["_extract_upload"] = lambda upload: upload_text
    result = app["analyze_route"]()
    return result if isinstance(result, tuple) else (result, 200)


def post_spans(app, payload=None):
    """Invoke the RM span route without HTTP or Flask startup."""
    app["request"] = SimpleNamespace(get_json=lambda silent: payload)
    result = app["span_route"]()
    return result if isinstance(result, tuple) else (result, 200)


def restore(text, mapping):
    """Independent one-pass consumer, never rescanning inserted values."""
    return re.sub(r"\[[A-Z][A-Z0-9_]*_[1-9][0-9]*\]",
                  lambda match: mapping[match.group()], text)
