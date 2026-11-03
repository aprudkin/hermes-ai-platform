"""Contract checks against genuine pinned Hermes source, with network denied."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'extensions/image-generation/openai-codex-25/__init__.py'

class ImageExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sdk=Path(os.environ['HERMES_SRC'])
        sys.path.insert(0,str(sdk))
        spec=importlib.util.spec_from_file_location('reviewed_codex25_provider',SOURCE)
        assert spec is not None and spec.loader is not None
        cls.module=importlib.util.module_from_spec(spec)
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            spec.loader.exec_module(cls.module)

    def test_real_provider_registration_and_model_catalog(self):
        registered=[]
        class Context:
            def register_image_gen_provider(self, provider):
                registered.append(provider)
        self.module.register(Context())
        self.assertEqual(len(registered),1)
        self.assertEqual(registered[0].provider_id,'openai-codex-25')
        self.assertEqual(len(self.module.MODELS),12)
        self.assertIn(self.module.DEFAULT_MODEL,self.module.MODELS)

    def test_empty_prompt_never_reads_auth_or_contacts_provider(self):
        with patch.object(self.module._base,'_read_codex_access_token',side_effect=AssertionError('Auth read forbidden')),patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            result=self.module.OpenAICodex25ImageGenProvider().generate('  ')
        self.assertIn('error',result)

    def test_missing_auth_fails_closed_without_request(self):
        with patch.object(self.module._base,'_read_codex_access_token',return_value=None),patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            result=self.module.OpenAICodex25ImageGenProvider().generate('Synthetic test prompt, never submitted')
        self.assertIn('auth_required',json.dumps(result))

if __name__=='__main__':
    unittest.main()
