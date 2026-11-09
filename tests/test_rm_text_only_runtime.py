"""Source contract for RM's dependency-minimal text-only runtime."""
import ast
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/app/app.py"


def load_runtime_app():
    try:
        import flask  # noqa: F401
    except ImportError:
        return None
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: False)
    transformers = ModuleType("transformers")
    transformers.pipeline = lambda *args, **kwargs: object()
    name = "rm_text_only_runtime_test_app"
    spec = importlib.util.spec_from_file_location(name, APP)
    module = importlib.util.module_from_spec(spec)
    previous = {key: sys.modules.get(key) for key in ("torch", "transformers")}
    old_model = os.environ.get("PII_MODEL_DIR")
    sys.modules["torch"] = torch
    sys.modules["transformers"] = transformers
    sys.path.insert(0, str(APP.parent))
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.path[0]
        if old_model is None:
            os.environ.pop("PII_MODEL_DIR", None)
        else:
            os.environ["PII_MODEL_DIR"] = old_model
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    module.nlp = lambda chunks: [[] for _ in chunks]
    return module


def load_decision():
    tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef)
             and node.name == "_rm_text_only_request_decision"]
    if len(nodes) != 1:
        raise AssertionError("text_only_decision_missing")
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace["_rm_text_only_request_decision"]


class TextOnlyRuntime(unittest.TestCase):
    def test_boundary_is_registered_and_uses_the_request_triplet(self):
        tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_rm_text_only_boundary"]
        self.assertEqual(len(nodes), 1, "boundary_function_missing")
        boundary = nodes[0]
        self.assertTrue(any(
            isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and item.value.id == "app"
            and item.attr == "before_request"
            for item in boundary.decorator_list
        ), "before_request_wiring_missing")
        source = ast.unparse(boundary)
        for value in ("request.method", "request.path", "request.is_json",
                      "_rm_text_only_request_decision"):
            self.assertIn(value, source, "boundary_request_triplet_incomplete")

    def test_document_dependencies_are_not_imported(self):
        tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
        imported = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertTrue("fitz" not in imported, "pymupdf_must_not_load")
        self.assertTrue("pdf_export" not in imported, "pdf_export_must_not_load")
        self.assertTrue("pdf_text" not in imported, "pdf_text_must_not_load")

    def test_document_runtime_code_is_absent(self):
        tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
        definitions = {
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        forbidden = {
            "_safe_name", "_store_doc", "_get_doc", "_page_png", "_page",
            "index", "assets", "favicon", "not_found", "_is_pdf",
            "_text_from_bytes", "PdfLocked", "_extract_upload", "_uploaded_file",
            "_pdf_response", "_ReqError", "_build_anonymized_pdf", "pdf_route",
            "pdf_preview_route", "preview_route", "doc_page", "doc_file",
            "settings_post", "config_get", "config_post", "port_check",
        }
        self.assertFalse(definitions & forbidden, "document_or_ui_runtime_code_remains")
        source = APP.read_text(encoding="utf-8")
        self.assertNotIn("request.files", source, "upload_surface_remains")
        self.assertNotIn("fitz.", source, "pymupdf_runtime_reference_remains")
        self.assertNotIn("pdf_export.", source, "pdf_export_runtime_reference_remains")
        self.assertNotIn("pdf_text.", source, "pdf_text_runtime_reference_remains")
        self.assertNotIn("_MEIPASS", source, "desktop_pyinstaller_path_remains")
        self.assertFalse(any(
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PAGE"
                    for target in node.targets)
            for node in tree.body
        ), "dead_ui_payload_remains")

    def test_packaging_excludes_pymupdf(self):
        files = [
            ROOT / "requirements.txt", ROOT / "Dockerfile",
        ]
        for path in files:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8").lower()
                self.assertNotIn("pymupdf", source, "pymupdf_package_remains")
                self.assertNotIn('"fitz"', source, "fitz_hidden_import_remains")
        unsupported = [
            ROOT / "Dockerfile.linux", ROOT / "build.spec", ROOT / "build_sidecar.spec",
            ROOT / "build_linux.sh", ROOT / "build_macos.sh",
            ROOT / ".github/workflows/build-windows.yml",
            ROOT / "build_mac.sh", ROOT / "installer.iss", ROOT / "tauri",
            ROOT / "src/app/serve.py", ROOT / "src/app/desktop_app.py",
            ROOT / "docs/BUILD.md",
        ]
        self.assertFalse([str(path.relative_to(ROOT)) for path in unsupported if path.exists()],
                         "desktop_packaging_must_not_ship")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("COPY src/app/ /app", dockerfile, "broad_runtime_copy_remains")

    def test_ci_executes_the_real_flask_boundary(self):
        workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertIn("pip install --no-cache-dir 'flask==3.1.2'", workflow,
                      "flask_test_dependency_missing")
        self.assertIn("python -m unittest tests.test_rm_text_only_runtime -v", workflow,
                      "real_http_boundary_not_run_in_ci")

    @unittest.skipIf(load_runtime_app() is None, "Flask is not installed")
    def test_real_flask_surface_and_error_contract(self):
        runtime = load_runtime_app()
        rules = {rule.rule for rule in runtime.app.url_map.iter_rules()}
        self.assertEqual(rules, {"/health", "/healthz", "/settings", "/analyze", "/rm/spans"})
        client = runtime.app.test_client()
        for path in ("/health", "/healthz", "/settings"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.is_json, path)
        for path in ("/health", "/healthz"):
            self.assertEqual(client.head(path).status_code, 200, path)
        self.assertEqual(client.post("/analyze", json={"text": "synthetic"}).status_code, 200)
        self.assertEqual(client.post("/rm/spans", json={"text": "synthetic", "exclude_tags": []}).status_code, 200)
        for method, path in (("get", "/"), ("post", "/pdf"), ("post", "/settings"),
                             ("get", "/config"), ("get", "/static/app.js")):
            response = getattr(client, method)(path, json={} if method == "post" else None)
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.get_json(), {"error": "not_found"}, path)
        self.assertEqual(client.post("/analyze", data="synthetic").status_code, 415)
        self.assertEqual(client.options("/analyze").status_code, 404)
        self.assertEqual(client.get("/health/").status_code, 404)
        for payload in ([], {"text": 7}):
            response = client.post("/analyze", json=payload)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
        runtime.app.config["MAX_CONTENT_LENGTH"] = 16
        response = client.post("/analyze", data=b"x" * 17,
                               content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json(), {"error": "request_too_large"})
        runtime.app.config["MAX_CONTENT_LENGTH"] = None
        runtime.nlp = lambda _chunks: (_ for _ in ()).throw(RuntimeError("synthetic secret"))
        response = client.post("/analyze", json={"text": "synthetic"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "internal_error"})
        self.assertNotIn(b"synthetic secret", response.data)

    def test_only_required_text_and_readiness_routes_are_reachable(self):
        decide = load_decision()
        for path in ("/health", "/healthz", "/settings"):
            with self.subTest(path=path):
                self.assertIsNone(decide("GET", path, False))
        for path in ("/health", "/healthz"):
            self.assertIsNone(decide("HEAD", path, False))
        for path in ("/analyze", "/rm/spans"):
            with self.subTest(path=path):
                self.assertIsNone(decide("POST", path, True))
                self.assertEqual(decide("POST", path, False), ("json_required", 415))

    def test_pdf_upload_ui_and_mutating_settings_are_closed(self):
        decide = load_decision()
        cases = [
            ("GET", "/", False), ("GET", "/assets/app.js", False),
            ("POST", "/pdf", False), ("POST", "/preview", False),
            ("POST", "/pdf/preview", False), ("GET", "/doc/x/file.pdf", False),
            ("GET", "/config", False), ("POST", "/config", True),
            ("POST", "/settings", True), ("POST", "/tags", True),
            ("POST", "/analyze", False), ("GET", "/analyze", False),
            ("GET", "/tags", False), ("GET", "/port-check", False),
            ("OPTIONS", "/analyze", False), ("PUT", "/rm/spans", True),
            ("DELETE", "/settings", False), ("GET", "/health/", False),
            ("GET", "//health", False),
        ]
        for method, path, is_json in cases:
            with self.subTest(method=method, path=path):
                decision = decide(method, path, is_json)
                self.assertIsNotNone(decision)
                if path != "/analyze" or method != "POST":
                    self.assertEqual(decision, ("not_found", 404))

    def test_read_only_settings_do_not_disclose_a_host_path(self):
        tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "settings_get"]
        self.assertEqual(len(nodes), 1, "settings_get_missing")
        self.assertNotIn("config_path", ast.unparse(nodes[0]))


if __name__ == "__main__":
    unittest.main()
