"""No Telegram network: verifies the profile-local native callback plugin."""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

PLUGIN=Path(__file__).resolve().parents[1] / 'plugin/__init__.py'


def load():
    spec=importlib.util.spec_from_file_location('cycle_button_plugin',PLUGIN)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PLUGIN.exists(),'Native button plugin absent')
        self.mod=load()
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        (self.home/'cycle-tracker').mkdir()
        (self.home/'cycle-tracker/state.json').write_text(json.dumps({'stage':'active','delivery_enabled':True,'planned_destination':'telegram:-1001234567890','confirmer_id':'222','runner':{'expected_bot_id':'111'}}))
        self.factory=None
        test=self
        class Context:
            def register_platform_handler(self, platform, factory):
                test.assertEqual(platform,'telegram')
                test.factory=factory
        with patch.object(self.mod,'_profile_home',return_value=self.home):
            self.mod.register(Context())
        self.native=types.SimpleNamespace(add_handler=Mock())
        self.adapter=types.SimpleNamespace(_is_callback_user_authorized=Mock(return_value=True))
        self.factory(self.native,self.adapter)
        self.handler=self.native.add_handler.call_args.args[0]

    def query(self,actor=222,chat=-1001234567890,bot=111):
        message=types.SimpleNamespace(chat_id=chat,message_id=333,chat=types.SimpleNamespace(id=chat,type='supergroup'),from_user=types.SimpleNamespace(id=bot,is_bot=True),message_thread_id=None)
        return types.SimpleNamespace(id='callback-fixture',data='ct1:fixture:today',from_user=types.SimpleNamespace(id=actor,first_name='Fixture'),message=message,answer=AsyncMock(),edit_message_reply_markup=AsyncMock(return_value=types.SimpleNamespace(chat_id=chat,message_id=333,reply_markup=None)))

    def call(self,q,result=None):
        callback=Mock(return_value=result or {'accepted':True,'text':'Записано','clear_keyboard':True})
        with patch.object(self.mod,'_load_buttons',return_value=types.SimpleNamespace(handle_button=callback)):
            asyncio.run(self.handler.callback(types.SimpleNamespace(callback_query=q),None))
        return callback

    def test_pattern_does_not_intercept_core_buttons(self):
        self.assertTrue(self.handler.pattern.match('ct1:abc:today'))
        self.assertIsNone(self.handler.pattern.match('cl:abc:0'))
        self.assertIsNone(self.handler.pattern.match('ea:once:10'))
        self.assertEqual(self.native.add_handler.call_args.kwargs.get('group',0),0)

    def test_real_actor_and_message_identity_forwarded(self):
        q=self.query()
        callback=self.call(q)
        args=callback.call_args
        self.assertEqual(args.args[0],self.home/'cycle-tracker/state.json')
        self.assertEqual(args.kwargs['actor_id'],'222')
        self.assertEqual(args.kwargs['chat_id'],'-1001234567890')
        self.assertEqual(args.kwargs['message_id'],333)
        self.assertEqual(args.kwargs['callback_id'],'callback-fixture')
        q.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
        q.answer.assert_awaited_once()

    def test_wrong_actor_no_processing(self):
        q=self.query(actor=999)
        self.call(q).assert_not_called()
        q.edit_message_reply_markup.assert_not_awaited()

    def test_wrong_group_or_bot_no_processing(self):
        for q in (self.query(chat=-1009999999999),self.query(bot=999)):
            self.call(q).assert_not_called()

    def test_adapter_authorization_fails_closed(self):
        self.adapter._is_callback_user_authorized.return_value=False
        self.call(self.query()).assert_not_called()

    def test_other_date_keeps_keyboard(self):
        q=self.query()
        self.call(q,{'accepted':True,'text':'Ответь датой ДД.ММ','clear_keyboard':False,'show_alert':True})
        q.edit_message_reply_markup.assert_not_awaited()
        self.assertTrue(q.answer.call_args.kwargs.get('show_alert'))

    def test_factory_writes_runtime_probe_not_health_state(self):
        probe=json.loads((self.home/'cycle-tracker/button-handler-runtime.json').read_text())
        self.assertTrue(probe['wired'])
        self.assertEqual(probe['prefix'],'ct1:')
        self.assertGreater(probe['pid'],0)
        state=json.loads((self.home/'cycle-tracker/state.json').read_text())
        self.assertNotIn('button_handler',state)


if __name__=='__main__':
    unittest.main(verbosity=2)
