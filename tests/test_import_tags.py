import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'PY'))
import zotero_llm_bridge as z


class ImportTagTests(unittest.TestCase):
    def select(self, ids, vocabulary=None, count=10):
        response = io.BytesIO(json.dumps({'response': json.dumps({'tag_ids': ids})}).encode())
        with patch.object(z.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'PMI crescita credito Italia')), patch.object(z, 'urlopen', return_value=response):
            return z.select_import_tags(Path('paper.pdf'), 'PMI', vocabulary or ['PMI', 'credito', 'Italia', 'unrelated'], count)

    def test_model_can_only_select_existing_ids_and_respects_count(self):
        selected = self.select([0, 0, 1, 2], count=2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0], 'PMI')
        self.assertTrue(set(selected) <= {'PMI', 'credito', 'Italia'})

    def test_invented_out_of_range_or_malformed_ids_fail(self):
        for ids in ([999], ['new tag'], [True], [-1], 'PMI'):
            with self.subTest(ids=ids), self.assertRaisesRegex(z.ZoteroError, 'before import'):
                self.select(ids)

    def test_fewer_or_no_relevant_tags_are_allowed(self):
        self.assertEqual(self.select([]), [])
        self.assertEqual(self.select([0]), ['PMI'])

    def test_remote_model_is_rejected_without_extraction(self):
        with patch.object(z, 'OLLAMA', 'https://example.org'), patch.object(z.subprocess, 'run') as run:
            with self.assertRaisesRegex(z.ZoteroError, 'local Ollama'):
                z.select_import_tags(Path('paper.pdf'), 'PMI', ['PMI'])
            run.assert_not_called()

    def test_missing_extractor_and_scans_fail_before_import(self):
        with patch.object(z.subprocess, 'run', side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(z.ZoteroError, 'extract PDF'):
                z.select_import_tags(Path('paper.pdf'), 'PMI', ['PMI'])
        with patch.object(z.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '')):
            with self.assertRaisesRegex(z.ZoteroError, 'no extractable text'):
                z.select_import_tags(Path('paper.pdf'), 'PMI', ['PMI'])

    def test_empty_vocabulary_and_disabled_tagging_need_no_model(self):
        with patch.object(z, 'urlopen') as network, patch.object(z.subprocess, 'run') as run:
            self.assertEqual(z.select_import_tags(Path('paper.pdf'), 'PMI', []), [])
            self.assertEqual(z.select_import_tags(Path('paper.pdf'), 'PMI', ['PMI'], 0), [])
            network.assert_not_called()
            run.assert_not_called()

    def test_library_vocabulary_pagination_and_deduplication(self):
        api = z.Zotero()
        api.get = Mock(side_effect=[[{'tag': f'tag{i}'} for i in range(1000)], [{'tag': 'PMI'}, {'tag': 'tag1'}]])
        self.assertEqual(len(api.library_tags()), 1001)
        self.assertIn('start=1000', api.get.call_args.args[0])

    def test_upload_tags_new_attachment_only_and_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'paper.pdf'
            pdf.write_bytes(b'%PDF-1.4\n')
            api = z.Zotero()
            api.resolve_collection = lambda _: {'key': 'COLL1234'}
            api.find_pdf_by_md5 = Mock(return_value=None)
            api.library_tags = Mock(return_value=['PMI', 'credito'])
            attachment = {'key': 'ATTACH12', 'data': {'tags': [{'tag': 'credito'}, {'tag': 'PMI'}], 'collections': ['COLL1234']}, 'links': {'enclosure': {'href': pdf.as_uri()}}}
            api.item = lambda _: attachment
            api.canonical_item = lambda _: attachment
            writes = []
            def post(path, body, content_type, extra=None):
                if path.endswith('/items'):
                    writes.append(json.loads(body)[0])
                    return {'success': {'0': 'ATTACH12'}}
                return {'exists': True}
            api.post = post
            with patch.object(z, 'select_import_tags', return_value=['PMI']) as select:
                result = api.upload_pdf(pdf, 'collection', tags=['credito'], tag_count=10)
                self.assertEqual(select.call_args.args[3], 10)
            self.assertEqual(result['tags'], ['credito', 'PMI'])
            self.assertEqual(writes[0]['tags'], [{'tag': 'credito'}, {'tag': 'PMI'}])
            # An identical PDF is reused without invoking vocabulary/model or adding tags.
            api.find_pdf_by_md5.return_value = (attachment, attachment)
            api.library_tags.reset_mock()
            with patch.object(z, 'select_import_tags') as select:
                self.assertEqual(api.upload_pdf(pdf, 'collection')['status'], 'already_present')
                select.assert_not_called()
                api.library_tags.assert_not_called()

    def test_unknown_explicit_tag_fails_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'paper.pdf'
            pdf.write_bytes(b'%PDF-1.4\n')
            api = z.Zotero()
            api.resolve_collection = lambda _: {'key': 'COLL1234'}
            api.find_pdf_by_md5 = lambda *args: None
            api.library_tags = lambda: ['PMI']
            api.post = Mock()
            with self.assertRaisesRegex(z.ZoteroError, 'already exist'):
                api.upload_pdf(pdf, 'collection', tags=['invented'], tag_count=0)
            api.post.assert_not_called()

    def test_apply_forwards_import_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'refs.json'
            manifest.write_text(json.dumps({'references': [{'id': '1', 'title': 'New paper', 'pdf_path': '/tmp/new.pdf'}]}))
            api = Mock()
            api.resolve_collection.return_value = {'key': 'COLL1234'}
            api.collection_items.return_value = []
            api.search_library.return_value = []
            api.upload_pdf.return_value = {'status': 'imported', 'item_key': 'ATTACH12', 'tags': ['PMI']}
            result = z.apply_references(api, manifest, 'collection', None, 4, 'local-model')
            self.assertEqual(api.upload_pdf.call_args.kwargs['tag_count'], 4)
            self.assertEqual(api.upload_pdf.call_args.kwargs['tag_model'], 'local-model')
            self.assertEqual(result['results'][0]['tags'], ['PMI'])
