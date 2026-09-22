import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PY"))
import zotero_llm_bridge
from zotero_llm_bridge import Zotero, ZoteroError, apply_references, build_bib, expand_shortcut, export_collection_bib


class FakeAPI:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.membership_changes = []
        self.external = {
            "key": "ABCD1234",
            "data": {
                "itemType": "journalArticle",
                "title": "Existing paper",
                "DOI": "10.1234/existing",
                "collections": [],
            },
        }
        self.pdf = {
            "key": "EFGH5678",
            "data": {"itemType": "attachment", "contentType": "application/pdf"},
            "links": {"enclosure": {"href": self.pdf_path.as_uri()}},
        }

    def resolve_collection(self, value):
        return {"key": "ZXCV9876"}

    def search_library(self, ref):
        return [self.external]

    def collection_items(self, key):
        return [self.external] if self.external["data"]["collections"] else []

    def canonical_item(self, key):
        return self.external

    def pdf_children(self, item):
        return [self.pdf] if item else []

    def change_membership(self, keys, target):
        self.membership_changes.append((keys, target))
        self.external["data"]["collections"] = ["ZXCV9876"]


class CLITests(unittest.TestCase):
    def test_delete_request_is_rejected_before_network(self):
        with self.assertRaisesRegex(ZoteroError, "does not delete"):
            Zotero().request("DELETE", "/users/0/items/ABCD1234")

    def test_direct_collection_bib_has_key8_and_unique_citekeys(self):
        api = Zotero()
        api.resolve_collection = lambda value: {"key": "ZXCV9876"}
        api.request = lambda method, path: (200, {"Total-Results": "2"}, [
            {"key": "ABCD1234", "data": {"itemType": "journalArticle"}},
            {"key": "EFGH5678", "data": {"itemType": "journalArticle"}}])
        api.get = lambda path: "@article{same,\n\ttitle = {Paper},\n}"
        bib, report = export_collection_bib(api, "PolicyIA")
        self.assertEqual(report["total"], 2)
        self.assertIn("@article{same,", bib)
        self.assertIn("@article{same_EFGH5678,", bib)
        self.assertIn("key8 = {ABCD1234}", bib)
        self.assertIn("key8 = {EFGH5678}", bib)

    def test_direct_bib_includes_standalone_pdf_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            attachment = {"key": "ABCD1234", "data": {
                "itemType": "attachment", "title": "Standalone paper",
                "contentType": "application/pdf"},
                "links": {"enclosure": {"href": pdf.as_uri()}}}
            api = Zotero()
            api.resolve_collection = lambda value: {"key": "ZXCV9876"}
            api.request = lambda method, path: (200, {"Total-Results": "1"}, [attachment])
            api.get = lambda path: "\n\n"
            bib, report = export_collection_bib(api, "PolicyIA")
            self.assertEqual(report["total"], 1)
            self.assertIn("@misc{zoteroABCD1234,", bib)
            self.assertIn(str(pdf), bib)
            self.assertIn("key8", bib)

    def test_collection_name_shortcut(self):
        self.assertEqual(expand_shortcut(["PolicyIA"]), ["search", "--collection", "PolicyIA"])
        self.assertEqual(expand_shortcut(["--json", "PolicyIA", "--tag", "AI"]),
                         ["--json", "search", "--collection", "PolicyIA", "--tag", "AI"])
        self.assertEqual(expand_shortcut(["collections", "PolicyIA"]), ["collections", "PolicyIA"])

    def test_move_is_idempotent_after_first_move(self):
        api = Zotero()
        api.resolve_collection = lambda value: {"key": "SOURCE12" if value == "source" else "TARGET34"}
        item = {"key": "ABCD1234", "data": {"version": 1, "collections": ["TARGET34"]}}
        api.canonical_item = lambda key: item
        api.item = lambda key: item
        api.post = lambda *args: self.fail("No write expected")
        result = api.change_membership(["ABCD1234"], "target", "source")
        self.assertEqual(result["changed"], 0)

    def test_pdf_hash_index_uses_local_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "index.json"
            api = Zotero()
            api.server_id = "server-one"
            calls = []
            def fake_request(method, path):
                calls.append(path)
                if "since=" in path:
                    return 200, {"Total-Results": "0", "Last-Modified-Version": "42"}, []
                if "sort=dateAdded" in path:
                    return 200, {"Total-Results": "1", "Last-Modified-Version": "42"}, [{
                        "key": "ABCD1234", "data": {"contentType": "application/pdf", "md5": "a" * 32}
                    }]
                return 200, {"Total-Results": "1", "Last-Modified-Version": "42"}, []
            api.request = fake_request
            with patch.object(zotero_llm_bridge, "INDEX_FILE", cache_file):
                self.assertEqual(api._pdf_hash_index()["a" * 32], ["ABCD1234"])
                calls.clear()
                self.assertEqual(api._pdf_hash_index()["a" * 32], ["ABCD1234"])
                self.assertEqual(len(calls), 1)

    def test_search_combines_collection_tag_text_and_pagination(self):
        api = Zotero()
        api.resolve_collection = lambda value: {"key": "ZXCV9876"}
        requests = []
        def fake_request(method, path):
            requests.append((method, path))
            return 200, {"Total-Results": "1"}, [{"key": "ABCD1234", "data": {
                "itemType": "journalArticle", "title": "Credit paper", "date": "2025",
                "DOI": "10.1234/example", "tags": [{"tag": "QEF"}],
                "collections": ["ZXCV9876"]}}]
        api.request = fake_request
        result = api.search_items(collection="Papers", tags=["QEF", "credit risk"],
                                  query="default", item_type="journalArticle", top=True,
                                  limit=10, start=20)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["key8"], "ABCD1234")
        self.assertIn("/collections/ZXCV9876/items/top?", requests[0][1])
        self.assertIn("tag=QEF&tag=credit+risk", requests[0][1])
        self.assertIn("q=default", requests[0][1])
        self.assertIn("start=20", requests[0][1])

    def test_search_requires_filter(self):
        with self.assertRaises(ZoteroError):
            Zotero().search_items()

    def test_apply_reuses_pdf_from_entire_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            manifest = root / "references.json"
            manifest.write_text(json.dumps({"references": [{"id": "1", "title": "Existing paper", "doi": "10.1234/existing"}]}))
            api = FakeAPI(pdf)
            result = apply_references(api, manifest, "New collection", None)
            self.assertEqual(result["results"][0]["status"], "added")
            self.assertEqual(api.membership_changes, [(["ABCD1234"], "ZXCV9876")])

    def test_bib_places_missing_before_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            api = FakeAPI(pdf)
            api.external["data"]["collections"] = ["ZXCV9876"]
            output = root / "references.bib"
            manifest = {"references": [
                {"id": "1", "citekey": "existing", "title": "Existing paper", "doi": "10.1234/existing"},
                {"id": "2", "citekey": "missing", "title": "Missing paper"},
            ]}
            result = build_bib(api, manifest, "New collection", output)
            content = output.read_text()
            self.assertEqual(result["missing"], ["2"])
            self.assertLess(content.index("@misc{missing"), content.index("@misc{existing"))
            self.assertIn("key8        = {ABCD1234}", content)


if __name__ == "__main__":
    unittest.main()
