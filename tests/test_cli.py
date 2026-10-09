import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PY"))
import zotero_llm_bridge
from zotero_llm_bridge import Zotero, ZoteroError, blind_snippets, compare_verdicts, screen_items, text_windows, apply_references, build_bib, expand_shortcut, export_collection_bib


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
    def test_text_windows_case_sensitive_terms_and_merge(self):
        text = "epic tale. The think tank EPIC said. " + "x " * 400 + "European Policy Innovation Council"
        snippets, count = text_windows(text, ["EPIC", "Epic"], ["european policy innovation council"], width=20)
        self.assertEqual(count, 2)
        self.assertIn("think tank EPIC", snippets[0])
        self.assertNotIn("epic tale", snippets[0][:5])

    def test_screen_items_phrase_llm_and_compare(self):
        texts = {"AAAA1111": "Report by the European Policy Innovation Council.",
                 "BBBB2222": "Il think tank Epic di Bruxelles.",
                 "CCCC3333": "Fortnite by Epic Games.",
                 "DDDD4444": "nothing relevant"}

        class API:
            def search_items(self, *args):
                items = [{"key8": k, "item_type": "attachment", "title": k, "tags": [], "parent_item": None} for k in texts]
                items.append({"key8": "EEEE5555", "item_type": "webpage", "title": "page", "tags": [], "parent_item": None})
                return {"total": len(items), "items": items}

            def item(self, key):
                return {"key": key}

        judged = []

        def judge(about, snippets, model):
            judged.append(snippets[0])
            return ("Bruxelles" in snippets[0], "ok")

        with patch.object(zotero_llm_bridge, "attachment_text", lambda item: texts[item["key"]]):
            screen = screen_items(API(), "Epic", "EPIC think tank", ["Epic", "EPIC"],
                                  ["European Policy Innovation Council"], judge=judge)
        status = {r["key8"]: r["status"] for r in screen["results"]}
        self.assertEqual(status, {"AAAA1111": "phrase", "BBBB2222": "llm", "CCCC3333": "llm",
                                  "DDDD4444": "no-term", "EEEE5555": "not-attachment"})
        self.assertEqual(len(judged), 2)
        self.assertEqual(screen["counts"]["llm-yes"], 1)
        blind = blind_snippets(screen)
        self.assertNotIn("llm_match", json.dumps(blind))
        report = compare_verdicts(screen, {"AAAA1111": {"match": True}, "BBBB2222": False, "CCCC3333": {"match": True, "reason": "x"}})
        self.assertEqual(report["counts"], {"agree_yes": 1, "agree_no": 0, "only_local": 1, "only_other": 1, "unjudged": 0})
        self.assertAlmostEqual(report["agreement"], 0.333)

    def test_add_tags_keeps_existing_and_skips_present(self):
        store = {
            "ABCD1234": {"key": "ABCD1234", "data": {"version": 3, "tags": [{"tag": "Old"}]}},
            "EFGH5678": {"key": "EFGH5678", "data": {"version": 5, "tags": [{"tag": "New"}]}},
        }
        posts = []
        api = Zotero()
        api.item = lambda key: store[key]

        def post(path, body, content_type):
            updates = json.loads(body)
            posts.append(updates)
            for update in updates:
                store[update["key"]]["data"]["tags"] = update["tags"]
            return {"success": {str(i): u["key"] for i, u in enumerate(updates)}, "failed": {}}

        api.post = post
        result = api.add_tags(["ABCD1234", "EFGH5678"], ["New", " ", "New"])
        self.assertEqual(result["changed"], 1)
        self.assertEqual(posts, [[{"key": "ABCD1234", "version": 3, "tags": [{"tag": "Old"}, {"tag": "New"}]}]])
        self.assertEqual(api.add_tags(["ABCD1234"], ["New"])["changed"], 0)
        with self.assertRaisesRegex(ZoteroError, "non-empty"):
            api.add_tags(["ABCD1234"], [" "])

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
