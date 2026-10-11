"""Local document ingestion and API role-mapping checks; no model calls or publishing."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))
import ingest
import build
from compile import Api
from extract import enum_of, enum_of_response, tool_summary


class IngestTests(unittest.TestCase):
    def test_office_fixture(self):
        case = ingest.load_case([ROOT / "lab/fake-case"])
        self.assertEqual(set(case["files"]), {"BRIEF.md", "conversation.docx", "customers.xlsx", "services.md"})
        for name in case["files"]:
            self.assertIn("=== FILE: " + name + " ===", case["text"])
        for text in ("Örnek Bank", "Agent | Merhaba", "Customer | Evet", "## SHEET: Customers",
                     "## SHEET: Scenarios", "c_fake_01 | 1250.50", "scenario |  | expected"):
            self.assertIn(text, case["text"])
        self.assertEqual(case["text"], case["contract_text"])
        self.assertIsNone(case["openapi"])

    def test_recursive_files_and_openapi(self):
        doc = {"openapi": "3.0.3", "paths": {}}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "nested").mkdir()
            (root / "nested/api.json").write_text(json.dumps(doc))
            (root / "nested/notes.csv").write_text("id,amount\na,10")
            (root / "image.png").write_bytes(b"not an image")
            case = ingest.load_case([root, root / "nested/api.json"])
        self.assertEqual(case["files"], ["nested/api.json", "nested/notes.csv"])
        self.assertEqual(case["openapi"], doc)

    def test_pdf(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "contract.pdf"
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72, 72), "Synthetic PDF contract")
                pdf.save(path)
            self.assertIn("Synthetic PDF contract", ingest.load_case(path)["text"])

    def test_old_api_needs_no_model_call(self):
        doc = json.loads((ROOT / "tools/openapi.json").read_text())
        with patch.object(build, "ask_json", side_effect=AssertionError("unexpected model call")):
            self.assertEqual(build.prepare_openapi({"contract_text": ""}, openapi=copy.deepcopy(doc)), doc)

    def test_role_mapping_preserves_contract(self):
        operation = {"summary": "Verify identity", "requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {"field": {"type": "string", "enum": ["birth_year"]}}, "required": ["field"]}}}},
            "responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"verified": {"type": "boolean"}}}}}}}}
        doc = {"openapi": "3.0.3", "paths": {"/kimlik-dogrula": {"post": operation}}}
        result = {"roles": [{"path": "/kimlik-dogrula", "method": "post", "role": "verify_identity"}]}
        with patch.object(build, "ask_json", return_value=result):
            mapped = build.prepare_openapi({"contract_text": ""}, "https://mock.example", copy.deepcopy(doc))
        api = Api(mapped)
        self.assertIs(api.ops["verify_identity"], api.ops["kimlik-dogrula"])
        self.assertEqual(api.url("verify_identity"), "https://mock.example/kimlik-dogrula")
        self.assertEqual(api.required("verify_identity"), ["field"])
        self.assertEqual(enum_of(mapped, "verify_identity", "field"), ["birth_year"])
        self.assertEqual(enum_of_response(mapped), [])
        self.assertIn("compiler tool role: verify_identity", tool_summary(mapped))
        actual = copy.deepcopy(mapped["paths"]["/kimlik-dogrula"]["post"])
        actual.pop("x-role")
        self.assertEqual(actual, operation)


if __name__ == "__main__":
    unittest.main()
