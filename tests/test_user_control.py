import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_coder.attachments import FileStore
from local_coder.chat import Chats
from local_coder.lan_gateway import password_hash
from local_coder.user_control import MemoryStore,KnowledgeStore,DatasetStore,BackupStore,change_credentials
from local_coder.work_queue import WorkQueue
from local_coder.search import resolved_public
from local_coder.preferences import set_preference_settings,append_pair,preference_records,redact_preference_records


class UserControlTests(unittest.TestCase):
    def test_memory_scope_edit_and_forget(self):
        with tempfile.TemporaryDirectory() as directory:
            store=MemoryStore(Path(directory)/'user')
            global_item=store.save('Prefer concise worked examples',source='Settings')
            project_item=store.save('Use SI units',scope='project',project='physics')
            self.assertEqual({item['id'] for item in store.list('physics')},{global_item['id'],project_item['id']})
            self.assertEqual([item['id'] for item in store.list('chemistry')],[global_item['id']])
            store.save('Prefer concise answers',item_id=global_item['id'])
            self.assertIn('concise',store.select('Give a concise explanation')[0]['text'])
            store.delete(project_item['id']);self.assertEqual(len(store.list()),1)

    def test_knowledge_retrieval_keeps_provenance_and_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);files=FileStore(root/'attachments');meta=files.save(b'Nebula calibration is 37.5 volts.','notes.txt')
            store=KnowledgeStore(root/'user',files);item=store.add(meta['id'],label='Lab notes',source='Course handout')
            passages=store.select('What is the nebula calibration?')
            self.assertIn('37.5',passages[0]['text']);self.assertEqual(passages[0]['source'],'Course handout');self.assertTrue(passages[0]['citation'].startswith('[K1:'))
            store.delete(item['id']);self.assertEqual(files.load(meta['id'])['name'],'notes.txt')

    def test_dataset_validation_deduplication_split_and_honest_training(self):
        with tempfile.TemporaryDirectory() as directory:
            store=DatasetStore(Path(directory)/'datasets')
            rows=[{'prompt':'p1','response':'r1'},{'prompt':'p1','response':'r1'},
                  {'prompt':'p2','chosen':'good','rejected':'bad'},{'bad':'row'}]
            result=store.import_rows('examples',rows,evaluation_percent=50)
            self.assertEqual(result['rows'],2);self.assertEqual(result['training_rows'],1);self.assertEqual(result['evaluation_rows'],1);self.assertEqual(result['rejected_rows'],2)
            saved=store.get(result['id']);self.assertNotEqual(saved['training'][0]['sha256'],saved['evaluation'][0]['sha256'])
            capability=store.training_capability();self.assertFalse(capability['available']);self.assertIn('does not train',capability['reason'])

    def test_credentials_require_current_password_and_rotate_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'lan';folder.mkdir();salt=b'1'*16
            (folder/'login.json').write_text(json.dumps({'username':'lumina','salt':salt.hex(),'hash':password_hash('old-password-123',salt),'version':4}))
            with self.assertRaisesRegex(ValueError,'incorrect'):change_credentials(root,'wrong','new-user','new-password-456')
            result=change_credentials(root,'old-password-123','new-user','new-password-456')
            saved=json.loads((folder/'login.json').read_text());self.assertEqual(saved['version'],5);self.assertEqual(result['username'],'new-user')
            self.assertEqual(password_hash('new-password-456',bytes.fromhex(saved['salt'])),saved['hash'])

    def test_queue_is_persisted_reorderable_and_cancelable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'queue.json';queue=WorkQueue(path)
            first=queue.add('chat',{'text':'first'},'first');second=queue.add('code',{'task':'second'},'second')
            queue.move(second['id'],'up');self.assertEqual(queue.claim()['id'],second['id'])
            queue.finish(second['id'],result_id='a'*32);queue.cancel(first['id'])
            self.assertFalse([item for item in WorkQueue(path).list() if item['status']=='queued'])

    def test_chat_history_search_archive_rename_and_reviewed_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            chats=Chats(Path(directory)/'chats',lambda *_:('Saved answer',{}));state=chats.start('Original calibration question',deep=False);chats.worker.join(2)
            chats.rename(state['id'],'Calibration notes');self.assertEqual(chats.list(query='calibration')[0]['title'],'Calibration notes')
            preview=chats.continuation_preview(state['id']);continued=chats.continue_from(state['id'],preview['context'])
            self.assertEqual(continued['parent']['action'],'continue');self.assertIn('Reviewed context',continued['messages'][0]['content'])
            chats.archive(state['id']);self.assertNotIn(state['id'],{item['id'] for item in chats.list()});self.assertEqual(chats.list(archived=True)[0]['id'],state['id'])

    def test_reference_aware_attachment_delete_and_backup_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);files=FileStore(root/'attachments');meta=files.save(b'Important course notes.','notes.txt')
            chat=root/'chats'/('a'*32);chat.mkdir(parents=True);(chat/'state.json').write_text(json.dumps({'id':'a'*32,'title':'Saved','messages':[{'attachments':[meta]}]}))
            self.assertEqual(files.inventory()['items'][0]['reference_count'],1)
            with self.assertRaisesRegex(ValueError,'referenced'):files.delete(meta['id'])
            memory=MemoryStore(root/'user');memory.save('Remember this')
            payload=BackupStore(root).export();other=Path(directory)/'restored';result=BackupStore(other).restore(payload)
            self.assertEqual(result['restored_chats'],1);self.assertEqual(MemoryStore(other/'user').list()[0]['text'],'Remember this')

    def test_private_resolved_addresses_and_disabled_preference_collection_are_rejected(self):
        with patch('local_coder.search.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',0))]):self.assertFalse(resolved_public('https://example.com/source'))
        with patch('local_coder.search.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',0))]):self.assertTrue(resolved_public('https://example.com/source'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);set_preference_settings(root,False)
            result=append_pair(root,{'task':'password=secret','acceptance':'ok'}, {'tool':'read_file'},{'error':'failed'}, {'tool':'search_code'})
            self.assertTrue(result['skipped']);self.assertFalse(preference_records(root))
            set_preference_settings(root,True);append_pair(root,{'task':'password=secret','acceptance':'ok'}, {'tool':'read_file'},{'error':'failed'}, {'tool':'search_code'})
            self.assertEqual(redact_preference_records(root)['fields_redacted'],1);self.assertIn('[REDACTED]',preference_records(root)[0]['task'])


if __name__=='__main__':unittest.main()
