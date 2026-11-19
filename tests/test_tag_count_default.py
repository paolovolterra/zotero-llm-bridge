import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'PY'))
import zotero_llm_bridge as z


class DefaultTagCountTests(unittest.TestCase):
    def env(self, directory, **values):
        clean = {k: v for k, v in os.environ.items() if k not in ('ZLB_TAG_COUNT', 'ZLB_CONFIG_FILE')}
        clean['ZLB_CONFIG_FILE'] = str(Path(directory) / 'config.json')
        clean.update(values)
        return patch.dict(os.environ, clean, clear=True)

    def test_off_without_env_or_config(self):
        with tempfile.TemporaryDirectory() as d, self.env(d):
            self.assertEqual(z.default_tag_count(), 0)

    def test_config_file_opt_in(self):
        with tempfile.TemporaryDirectory() as d, self.env(d):
            (Path(d) / 'config.json').write_text(json.dumps({'tag_count': 10}))
            self.assertEqual(z.default_tag_count(), 10)

    def test_env_overrides_config(self):
        with tempfile.TemporaryDirectory() as d, self.env(d, ZLB_TAG_COUNT='3'):
            (Path(d) / 'config.json').write_text(json.dumps({'tag_count': 10}))
            self.assertEqual(z.default_tag_count(), 3)

    def test_invalid_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.env(d, ZLB_TAG_COUNT='many'):
            with self.assertRaises(z.ZoteroError):
                z.default_tag_count()
        with tempfile.TemporaryDirectory() as d, self.env(d, ZLB_TAG_COUNT='-1'):
            with self.assertRaises(z.ZoteroError):
                z.default_tag_count()

    def test_library_defaults_are_off(self):
        import inspect
        self.assertEqual(inspect.signature(z.Zotero.upload_pdf).parameters['tag_count'].default, 0)
        self.assertEqual(inspect.signature(z.apply_references).parameters['tag_count'].default, 0)

    def test_cli_upload_uses_resolved_default(self):
        with tempfile.TemporaryDirectory() as d, self.env(d):
            with patch.object(z.Zotero, 'connect', return_value={}), \
                 patch.object(z.Zotero, 'upload_pdf', return_value={'status': 'imported'}) as upload, \
                 patch('builtins.print'):
                z.main(['upload', '--file', 'paper.pdf', '--collection', 'X'])
            self.assertEqual(upload.call_args.args[5], 0)
            os.environ['ZLB_TAG_COUNT'] = '7'
            with patch.object(z.Zotero, 'connect', return_value={}), \
                 patch.object(z.Zotero, 'upload_pdf', return_value={'status': 'imported'}) as upload, \
                 patch('builtins.print'):
                z.main(['upload', '--file', 'paper.pdf', '--collection', 'X', '--tag-count', '2'])
            self.assertEqual(upload.call_args.args[5], 2)


if __name__ == '__main__':
    unittest.main()
