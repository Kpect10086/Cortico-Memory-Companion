"""Cortico-owned compatibility host for the unmodified AstrBot plugin entrypoints."""
from __future__ import annotations

import argparse
import base64
import asyncio
from collections import OrderedDict
from contextvars import ContextVar
import functools
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import secrets
import shutil
import sqlite3
import socket
import time
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

manual_provider_test = ContextVar('cortico_manual_provider_test',default=False)


def package(name, root):
    module = ModuleType(name)
    module.__path__ = [str(root)]
    sys.modules[name] = module


def tool_schema(tool):
    schema=deepcopy(tool.parameters)
    signature=inspect.signature(tool.handler)
    properties=schema.get('properties',{})
    for key in list(properties):
        parts=key.split('/')
        if len(parts)>1 and all(part in signature.parameters for part in parts):
            field=properties.pop(key)
            for part in parts: properties[part]=deepcopy(field)
    schema['required']=[name for name,param in signature.parameters.items() if name not in ('event','self','context') and param.default is inspect.Parameter.empty and param.kind not in (inspect.Parameter.VAR_KEYWORD,inspect.Parameter.VAR_POSITIONAL)]
    return {'name':tool.name,'description':tool.description,'parameters':schema}


async def create_host(root: Path, state: Path, callback, settings=None):
    os.environ['ASTRBOT_ROOT'] = str(state)
    from astrbot.api.star import Context, StarTools
    from astrbot.core import astrbot_config, db_helper, sp, html_renderer
    from astrbot.core.astrbot_config_mgr import AstrBotConfigManager
    from astrbot.core.conversation_mgr import ConversationManager
    from astrbot.core.cron import CronJobManager
    from astrbot.core.knowledge_base.kb_mgr import KnowledgeBaseManager
    from astrbot.core.persona_mgr import PersonaManager
    from astrbot.core.platform.manager import PlatformManager
    from astrbot.core.platform_message_history_mgr import PlatformMessageHistoryManager
    from astrbot.core.provider.manager import ProviderManager
    from astrbot.core.provider.provider import Provider, TTSProvider, EmbeddingProvider
    from astrbot.core.provider.entities import LLMResponse, ProviderMeta, ProviderType
    from astrbot.core.star.context import Context
    from astrbot.core.star.star import star_map
    from astrbot.core.star.star_handler import star_handlers_registry
    from astrbot.core.star.star_manager import PluginManager
    from astrbot.core.star.star_tools import StarTools
    from astrbot.core.umop_config_router import UmopConfigRouter
    from astrbot.core.config.astrbot_config import AstrBotConfig
    from astrbot.core.platform.platform import Platform, PlatformStatus
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.message.components import Plain, Image, Record, At

    settings = settings or {}

    class OneBotClient:
        def __init__(self): self.api=self
        async def call_action(self, action, **parameters):
            from astrbot.core.platform.astr_message_event import current_message_event
            event=current_message_event.get()
            result=await callback('onebot', {'action': action, 'parameters': parameters,
                'callerConv':('group:'+event.get_group_id() if event.get_group_id() else 'private:'+event.get_sender_id()) if event else None,
                'proactive':event is None or bool(getattr(event,'private_companion_proactive_framework',False))})
            if action=='get_login_info' and isinstance(result,dict) and result.get('user_id'): platform.client_self_id=str(result['user_id'])
            return result

        def __getattr__(self, action):
            async def execute(**parameters): return await self.call_action(action, **parameters)
            return execute

    class CorticoPlatform(Platform):
        def __init__(self, queue):
            super().__init__({'id':'cortico','type':'aiocqhttp','enable':True}, queue)
            self.client = OneBotClient()
            self.status = PlatformStatus.RUNNING
            self.client_self_id = settings.get('qqSelfId', settings.get('botId', 'cortico'))

        def meta(self): return PlatformMetadata(name='aiocqhttp', description='Cortico QQ World', id='cortico', support_streaming_message=False)
        def get_client(self): return self.client
        async def run(self): await asyncio.Event().wait()
        async def send_by_session(self, session, message_chain):
            from astrbot.core.platform.astr_message_event import current_message_event
            event=current_message_event.get()
            return await callback('send', {'session':str(session), 'components':[json.loads(p.json()) for p in message_chain.chain],
                'proactive':event is None or bool(getattr(event,'private_companion_proactive_framework',False))})

    class CorticoMessageEvent(AstrMessageEvent):
        def __init__(self, value, platform):
            obj = AstrBotMessage()
            obj.type = MessageType.GROUP_MESSAGE if value.get('groupId') else MessageType.FRIEND_MESSAGE
            obj.self_id = platform.client_self_id
            obj.session_id = value.get('groupId') or value['userId']
            obj.message_id = value.get('platformMessageId') or value['id']
            obj.sender = MessageMember(user_id=value['userId'], nickname=value.get('userName') or value['userId'])
            obj.message = [Plain(value['text'])]
            if value.get('groupId') and value.get('atMe'):obj.message.insert(0,At(qq=platform.client_self_id))
            for attachment in value.get('attachments', []):
                if attachment.get('type') == 'image': obj.message.append(Image(file=attachment['url']))
                elif attachment.get('type') == 'audio': obj.message.append(Record(file=attachment['url']))
            obj.message_str = value['text']
            obj.raw_message = value.get('raw', {})
            obj.timestamp = int(value['at'])
            obj.group_id = value.get('groupId', '')
            super().__init__(value['text'], obj, platform.meta(), obj.session_id)
            self.value = value
            self.persona_id='cortico'
            self.bot = platform.get_client()
            self.is_wake = self.is_at_or_wake_command = False
            self.role = 'admin' if value.get('internal') else 'member'
            self._s4_source_capture_enabled = not value.get('internal') and not value.get('observedChannel')
            self.private_companion_proactive_framework = bool(value.get('internal'))

        def get_platform_name(self): return 'cortico'
        async def send(self, message):
            result=await callback('send', {'session':self.unified_msg_origin, 'components':[json.loads(p.json()) for p in message.chain],
                'proactive':bool(self.private_companion_proactive_framework)})
            if not isinstance(result,dict) or result.get('confirmed') is not True: raise RuntimeError('Cortico did not confirm delivery')
            self._has_send_oper=True
            self.set_extra('cortico_receipts',self.get_extra('cortico_receipts',[])+[result])
            return result

    class CorticoProvider(Provider):
        def __init__(self, entry):
            super().__init__({'id':entry['id'],'type':'cortico','model':entry['model'],'modalities':entry.get('modalities',['text'])}, {})
            self.set_model(entry['model'])

        def get_current_key(self): return ''
        def set_key(self, value): raise ValueError('Configure credentials in Cortico')
        async def get_models(self): return [self.get_model()]
        def meta(self): return ProviderMeta(id=self.provider_config['id'],model=self.get_model(),type='cortico',provider_type=ProviderType.CHAT_COMPLETION)
        async def text_chat(self, **args):
            from astrbot.core.platform.astr_message_event import current_message_event
            tools = args.pop('func_tool',None)
            event = current_message_event.get()
            token = secrets.token_urlsafe(24)
            selected = {tool.name:tool for tool in tools or [] if getattr(tool,'handler_module_path','').startswith('data.plugins.')}
            context.provider_calls[token] = (event, selected)
            payload = {**args,'providerId':self.provider_config['id'],'toolToken':token,'toolSchemas':[tool_schema(t) for t in selected.values()] if event else [],'manualProviderTest':manual_provider_test.get()}
            try:
                response = await callback('model', payload)
                from astrbot.core.provider.entities import TokenUsage
                return LLMResponse(role='assistant',completion_text=response['text'],usage=TokenUsage(**response['usage']) if response.get('usage') else None)
            finally: context.provider_calls.pop(token,None)

    class CorticoContext(Context):
        def get_platform(self,name):
            if name=='aiocqhttp':return self.platform_manager.platform_insts[0]
            return super().get_platform(name)
        async def send_message(self, session, message_chain):
            from astrbot.core.platform.astr_message_event import current_message_event
            event=current_message_event.get()
            result = await callback('send', {'session': str(session), 'components': [json.loads(part.json()) for part in message_chain.chain],
                'proactive':event is None or bool(getattr(event,'private_companion_proactive_framework',False))})
            if not isinstance(result,dict) or result.get('confirmed') is not True: raise RuntimeError('Cortico did not confirm delivery')
            return True

    class CorticoTTS(TTSProvider):
        def __init__(self): super().__init__({'id':'cortico-tts','type':'cortico'}, {})
        def meta(self): return ProviderMeta(id='cortico-tts',model='QQ 当前语音服务',type='cortico',provider_type=ProviderType.TEXT_TO_SPEECH)
        async def get_audio(self,text):
            value=await callback('tts',{'text':text})
            audio=base64.b64decode(value['base64'],validate=True)
            if not audio.startswith(b'RIFF') or len(audio)>20*1024*1024: raise ValueError('Invalid Cortico TTS WAV')
            folder=state/'audio';folder.mkdir(exist_ok=True,parents=True)
            path=folder/(secrets.token_hex(12)+'.wav');path.write_bytes(audio)
            return str(path)

    class CorticoEmbedding(EmbeddingProvider):
        def __init__(self):
            from fastembed import TextEmbedding
            super().__init__({'id':'cortico-local-embedding','type':'cortico','model':'BAAI/bge-small-zh-v1.5'}, {})
            self.engine=TextEmbedding(model_name='BAAI/bge-small-zh-v1.5',cache_dir=str(root/'embedding-cache'),threads=2,providers=['CPUExecutionProvider'],cuda=False,local_files_only=True)
            self.lock=asyncio.Lock()
        def meta(self):return ProviderMeta(id='cortico-local-embedding',model='BAAI/bge-small-zh-v1.5',type='cortico',provider_type=ProviderType.EMBEDDING)
        def get_dim(self):return 512
        async def get_embedding(self,text):return (await self.get_embeddings([text]))[0]
        async def get_embeddings(self,texts):
            async with self.lock:
                return await asyncio.to_thread(lambda:[vector.tolist() for vector in self.engine.embed(texts)])

    await db_helper.initialize()
    await sp.initialize()
    router = UmopConfigRouter(sp=sp)
    await router.initialize()
    acm = AstrBotConfigManager(astrbot_config, router, sp)
    await acm.initialize()
    personas = PersonaManager(db_helper, acm)
    await personas.initialize()
    if settings.get('persona'):
        try: await personas.get_persona('cortico')
        except ValueError: await personas.create_persona('cortico',system_prompt=settings['persona'])
        await personas.update_persona('cortico',system_prompt=settings['persona'])
        personas.default_persona='cortico'
        acm.default_conf.setdefault('agent_runner',{}).setdefault('config',{}).setdefault('persona',{})['persona_id']='cortico'
        personas.get_v3_persona_data()
    providers = ProviderManager(acm, db_helper, personas)
    for entry in settings.get('providers') or [{'id':'cortico','model':'Cortico'}]:
        provider=CorticoProvider(entry)
        providers.provider_insts.append(provider)
        providers.inst_map[entry['id']]=provider
    if 'cortico' not in providers.inst_map:
        active=providers.inst_map.get(settings.get('activeProvider'),providers.provider_insts[0])
        default=CorticoProvider({'id':'cortico','model':active.get_model(),'modalities':active.provider_config.get('modalities',['text'])})
        providers.provider_insts.insert(0,default);providers.inst_map['cortico']=default
    providers.curr_provider_inst = providers.inst_map['cortico']
    providers.default_chat_provider_id = 'cortico'
    if settings.get('localEmbeddingEnabled'):
        embedding=await asyncio.to_thread(CorticoEmbedding)
        providers.embedding_provider_insts.append(embedding);providers.inst_map['cortico-local-embedding']=embedding
    if settings.get('ttsEnabled'):
        tts=CorticoTTS();providers.tts_provider_insts.append(tts);providers.inst_map['cortico-tts']=tts;providers.curr_tts_provider_inst=tts
    queue = asyncio.Queue()
    platforms = PlatformManager(astrbot_config, queue)
    platform = CorticoPlatform(queue)
    platforms.platform_insts.append(platform)
    try: await platform.client.call_action('get_login_info')
    except Exception: pass  # QQ may still be reconnecting during supervised startup.
    context = CorticoContext(queue, astrbot_config, db_helper, providers, platforms,
        ConversationManager(db_helper), PlatformMessageHistoryManager(db_helper), personas,
        acm, KnowledgeBaseManager(providers), CronJobManager(db_helper))
    context.html_renderer = html_renderer
    context.registered_web_apis = []
    context.provider_calls = {}
    StarTools.initialize(context)
    context.create_cortico_event = lambda value: CorticoMessageEvent(value, platform)
    package('data', state / 'data')
    package('data.plugins', root)
    plugins = []
    sources = [('astrbot_plugin_memory_companion', 'astrbot_plugin_memory_companion', 'MemoryCompanionPlugin'),
        ('astrbot_plugin_private_companion', 'astrbot_plugin_private_companion_6_7_0', 'PrivateCompanionPlugin')]
    addons=settings.get('addons',{})
    if 'content' in addons:sources.append(('astrbot_plugin_content_companion','astrbot_plugin_content_companion','ContentCompanionPlugin'))
    if 'memewiki' in addons:sources.append(('astrbot_plugin_memewiki','astrbot_plugin_memewiki','MemeWiki'))
    context.cortico_configs={}
    for name, directory, cls in sources:
        module_name = 'data.plugins.' + name
        package(module_name, root / directory)
        module = importlib.import_module(module_name + '.main')
        config_file=state/(name+'.json')
        fresh_config=not config_file.exists()
        config = AstrBotConfig(str(config_file), schema=json.loads((root / directory / '_conf_schema.json').read_text(encoding='utf-8')))
        if fresh_config and name=='astrbot_plugin_private_companion':
            helper=importlib.import_module(module_name+'.helpers')
            proactive=settings.get('legacyProactive',{})
            for key,value in {'bot_name':settings.get('displayName','Cortico'),'target_platform':'cortico',
                'target_user_ids':[str(v) for v in settings.get('privateTargets',[]) if str(v).isdigit()],
                'group_whitelist_ids':[str(v) for v in settings.get('groupTargets',[]) if str(v).isdigit()],
                'default_proactive_enabled':bool(proactive.get('enabled',False)),
                'default_proactive_daily_limit':min(30,max(0,int(proactive.get('dailyQuota',0))))}.items():
                helper._set_into_config(config,key,value)
            config.save_config()
        metadata = star_map[module.__name__]
        metadata.name = name
        metadata.root_dir_name = name
        metadata.module = module
        metadata.config = config
        metadata.activated = True
        plugin = getattr(module, cls)(context, config)
        context.cortico_configs[name]=config
        metadata.star_cls = plugin
        for handler in star_handlers_registry:
            if handler.handler_module_path == module.__name__:
                method = getattr(plugin, handler.handler_name, None)
                if method is not None: handler.handler = method
        for group in context.get_llm_tool_manager().func_list:
            for tool in PluginManager._iter_concrete_llm_tools(group):
                if tool.handler and getattr(tool.handler, '__module__', None) == module.__name__:
                    tool.handler_module_path = module.__name__
                    tool.handler = functools.partial(tool.handler, plugin)
        plugins.append(plugin)
    if addons:
        addon_spec=importlib.util.spec_from_file_location('cortico_native_addons',Path(__file__).with_name('native-addons.py'))
        addon_module=importlib.util.module_from_spec(addon_spec);addon_spec.loader.exec_module(addon_module)
        context.cortico_addons=addon_module.Addons(context,plugins,root,state,callback,settings)
        await context.cortico_addons.prepare()
    for plugin in plugins:
        if plugin.__class__.__name__!='MemeWiki' or addons.get('memewiki'):await plugin.initialize()
    if addons:context.cortico_addons.bind_content_storage()
    original_identity=plugins[0].service.identity.resolve_event_context
    async def cortico_memory_identity(event):
        identity=await original_identity(event)
        if isinstance(event,CorticoMessageEvent): identity.bot_id=settings.get('botId','cortico')
        return identity
    plugins[0].service.identity.resolve_event_context=cortico_memory_identity
    from astrbot.core.pipeline.context import PipelineContext
    from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
    from astrbot.core.pipeline.result_decorate.stage import ResultDecorateStage
    from astrbot.core.pipeline.respond.stage import RespondStage
    pipeline=PipelineContext(astrbot_config,SimpleNamespace(context=context),'default',db_helper)
    context.cortico_stages=[]
    for stage_class in (WakingCheckStage,ResultDecorateStage,RespondStage):
        stage=stage_class();await stage.initialize(pipeline);context.cortico_stages.append(stage)
    return context, plugins


class NativeRuntime:
    def __init__(self, callback):
        self.callback = callback
        self.events = OrderedDict()
        self.latest = {}
        self.context = None
        self.plugins = []
        self.base = None
        self.web_stop = asyncio.Event()
        self.web_task = None
        self.projection_task=None
        self.projection_lock=asyncio.Lock()

    async def initialize(self, args):
        self.args = args
        root = Path(args['sources'])
        data = Path(args['dataDir'])
        os.environ['ASTRBOT_ROOT']=str(data/'native')
        self.port=int(args.get('port',7790))
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as port_check:
            port_check.bind(('127.0.0.1',self.port))
        spec = importlib.util.spec_from_file_location('cortico_legacy_companion', Path(args['legacyBridgeFile']))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.base = module.Runtime()
        async def model(arguments):
            response = await self.callback('model', arguments)
            return response['text'] if isinstance(response, dict) else response
        self.base.model = model
        result = await self.base.initialize(args)
        await self.base.service.aclose()
        native_state = data / 'native'
        destination = native_state / 'data' / 'plugin_data' / 'astrbot_plugin_memory_companion'
        if not destination.exists():
            staging=destination.with_name(destination.name+'.migrating-'+secrets.token_hex(4))
            staging.mkdir(parents=True)
            for file in (data / 'memory').rglob('*'):
                if not file.is_file() or file.name.endswith(('-wal','-shm')): continue
                target = staging / file.relative_to(data / 'memory')
                target.parent.mkdir(parents=True, exist_ok=True)
                if file.suffix == '.db':
                    source = sqlite3.connect(file.as_uri()+'?mode=ro', uri=True)
                    dest = sqlite3.connect(target)
                    source.backup(dest)
                    assert dest.execute('pragma integrity_check').fetchone()[0] == 'ok'
                    dest.close(); source.close()
                else: shutil.copy2(file, target)
            (staging/'cortico-migration.json').write_text(json.dumps({'completed':True,'source':str(data/'memory'),'at':time.time()}),encoding='utf-8')
            staging.rename(destination)
        self.context, self.plugins = await create_host(root, native_state, self.callback, args)
        self.companion_enabled=bool(args.get('companionEnabled',True))
        self.companion_original_enabled=self.plugins[1].enabled
        await self.dispatch('companion_activation',{'enabled':self.companion_enabled})
        self.base.service = self.plugins[0].service
        self.base.db.execute('CREATE TABLE IF NOT EXISTS native_projection(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,body_hash TEXT NOT NULL,state TEXT NOT NULL)')
        self.base.db.execute('CREATE TABLE IF NOT EXISTS native_tombstones(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL)')
        if self.base.db.execute('SELECT count(*) FROM native_projection').fetchone()[0]==0:
            for row in self.base.service.store._conn.execute("SELECT id,metadata FROM memories WHERE source_plugin='cortico_weighted_memory'"):
                self.base.db.execute('INSERT OR IGNORE INTO native_projection VALUES(?,?,?,?)',(row['id'],json.loads(row['metadata']).get('cortico_import_hash',''),'','active'))
        self.base.db.commit()
        self.launch_secret = secrets.token_urlsafe(32)
        self.port = int(args.get('port', 7790))
        from hypercorn.asyncio import serve
        from hypercorn.config import Config
        app = make_app(self.context, self.plugins, root, self.launch_secret, after_write=self.synchronize_projection)
        config = Config()
        config.bind = ['127.0.0.1:'+str(self.port)]
        config.accesslog = None
        self.web_task = asyncio.create_task(serve(app, config, shutdown_trigger=self.web_stop.wait))
        for _ in range(100):
            if self.web_task.done(): await self.web_task; raise RuntimeError('Native web server exited before readiness')
            try:
                reader,writer=await asyncio.open_connection('127.0.0.1',self.port)
                writer.close(); await writer.wait_closed();break
            except ConnectionRefusedError: await asyncio.sleep(0.05)
        else: raise RuntimeError('Native web server did not become ready')
        self.projection_task=asyncio.create_task(self.projection_loop())
        return {**result, **self.status()}

    async def projection_loop(self):
        while True:
            await asyncio.sleep(30)
            try: await self.synchronize_projection()
            except Exception as error: print('Cortico memory projection sync pending: '+str(error),file=sys.stderr)

    async def synchronize_projection(self):
        async with self.projection_lock:
            snapshot={row['id']:row for row in self.base.service.store._conn.execute("SELECT id,review_status,lifecycle FROM memories WHERE source_plugin='cortico_weighted_memory'")}
            changes=[]
            for row in self.base.db.execute('SELECT id,fingerprint,body_hash,state FROM native_projection'):
                value=snapshot.get(row['id'])
                state='active' if value and value['review_status'] in ('confirmed','auto') and value['lifecycle'] not in ('forgotten','archived','deleted') else 'archived'
                if state!=row['state']: changes.append({'id':row['id'][8:],'state':state,'nativeId':row['id'],'fingerprint':row['fingerprint'],'bodyHash':row['body_hash']})
            if not changes:return
            for change in changes:
                if change['state']=='archived':self.base.db.execute('INSERT OR REPLACE INTO native_tombstones VALUES(?,?)',(change['nativeId'],change['fingerprint']))
                else:self.base.db.execute('DELETE FROM native_tombstones WHERE id=?',(change['nativeId'],))
            self.base.db.commit()
            result=await self.callback('legacy_projection',{'changes':changes})
            conflicts=set(result.get('conflicts',[])) if isinstance(result,dict) else set()
            for change in changes:
                if change['id'] in conflicts and change['state']=='active':
                    await self.base.service.store.update_review_status(change['nativeId'],'rejected')
                    change['state']='archived'
            for change in changes:self.base.db.execute('UPDATE native_projection SET state=? WHERE id=?',(change['state'],change['nativeId']))
            self.base.db.commit()

    async def import_memories(self,args):
        await self.synchronize_projection()
        async with self.projection_lock:
            rows=[];declined=0;updates=[]
            for row in args['rows']:
                identifier='cortico_'+row['id']
                fingerprint=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                body_hash=hashlib.sha256(json.dumps({k:v for k,v in row.items() if k not in ('state','hostRevision')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                tombstone=self.base.db.execute('SELECT fingerprint FROM native_tombstones WHERE id=?',(identifier,)).fetchone()
                if tombstone and tombstone['fingerprint']==fingerprint:declined+=1;continue
                if tombstone:self.base.db.execute('DELETE FROM native_tombstones WHERE id=?',(identifier,))
                previous=self.base.db.execute('SELECT body_hash FROM native_projection WHERE id=?',(identifier,)).fetchone()
                record=await self.base.service.store.get_memory(identifier)
                if previous and previous['body_hash']==body_hash and record and record.review_status in ('confirmed','auto') and record.metadata.get('cortico_import_hash')!=fingerprint:
                    metadata={**record.metadata,'cortico_import_hash':fingerprint}
                    await self.base.service.store.update_memory_payload(identifier,metadata=metadata)
                    # The legacy importer recognizes confirmed only; preserve native review and edits here.
                    updates.append((identifier,fingerprint,body_hash,'active'))
                    continue
                if previous and previous['body_hash']==body_hash and record and record.review_status=='auto':
                    updates.append((identifier,fingerprint,body_hash,'active'))
                    continue
                rows.append(row)
                updates.append((identifier,fingerprint,body_hash,'active'))
            result=await self.base.import_memories({**args,'rows':rows,'completeSnapshot':False})
            if args.get('completeSnapshot') is True:
                current={"cortico_"+row['id'] for row in args['rows']}
                for record in self.base.service.store._conn.execute("SELECT id FROM memories WHERE source_plugin='cortico_weighted_memory' AND review_status!='rejected'").fetchall():
                    if record['id'] not in current:
                        await self.base.service.store.update_review_status(record['id'],'rejected')
                        result['revoked']+=1
            self.base.db.executemany('INSERT OR REPLACE INTO native_projection VALUES(?,?,?,?)',updates)
            self.base.db.commit()
            return {**result,'nativeDeclined':declined,'eligible':len(args['rows'])}

    async def migrate_legacy(self,args):
        result=await self.base.dispatch('legacy',args)
        directory=Path(self.plugins[1].data_dir)
        marker=directory/'cortico-migration.json'
        if marker.exists():return {**result,'nativeAlreadyMigrated':True}
        rows=[dict(row) for row in self.base.db.execute('SELECT scope,kind,id,body,revision FROM documents ORDER BY scope,kind,id')]
        plugin=self.plugins[1]
        count=0
        async with plugin._data_lock:
            for row in rows:
                value=json.loads(row['body'])
                if row['kind']=='relationship' and row['scope'].startswith('private:') and row['id'].isdigit():
                    user=plugin._get_user(row['id'])
                    user['cortico_legacy']=value
                    for key,item in value.items():
                        if key.startswith(('chronotype_','relationship_')):user[key]=deepcopy(item)
                    if not user.get('umo'):user['umo']='cortico:FriendMessage:'+row['id']
                    count+=1
                if row['scope']=='self' and row['kind']=='state':
                    state=plugin.data.setdefault('daily_state',{})
                    if isinstance(value.get('energy'),(int,float)):state['energy']=min(100,max(0,value['energy']))
                    state['cortico_legacy']=value
            plugin._save_data_now_sync(sections={'users','daily_state'})
        (directory/'cortico-legacy-documents.jsonl').write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\n',encoding='utf-8')
        marker.write_text(json.dumps({'schema':1,'relationships':count,'documents':len(rows),'source':'Cortico companion.db; originals retained'},ensure_ascii=False,indent=2),encoding='utf-8')
        return {**result,'nativeRelationships':count,'nativeDocumentsArchived':len(rows)}

    def status(self):
        return {'ready':self.context is not None, 'mode':'native', 'routes':len(self.context.registered_web_apis) if self.context else 0,
            'tools':len(self.schemas()) if self.context else 0, 'port':self.port if self.context else None,
            'localEmbedding':bool(self.context and 'cortico-local-embedding' in self.context.provider_manager.inst_map),
            'addons':self.context.cortico_addons.status() if self.context and hasattr(self.context,'cortico_addons') else {}}

    def schemas(self):
        from astrbot.core.star.star_manager import PluginManager
        output = []
        for group in self.context.get_llm_tool_manager().func_list:
            for tool in PluginManager._iter_concrete_llm_tools(group):
                if getattr(tool, 'handler_module_path', '').startswith('data.plugins.'):
                    output.append(tool_schema(tool))
        return output

    async def event(self, value):
        if not isinstance(value,dict) or not all(isinstance(value.get(k),str) and value[k] for k in ('id','text','userId')):
            raise ValueError('Host-owned message identity required')
        event = self.events.get(value['id'])
        if event is None:
            platform=self.context.platform_manager.platform_insts[0]
            if not str(platform.client_self_id).isdigit():
                try:await platform.client.call_action('get_login_info')
                except Exception:pass
            event = self.context.create_cortico_event(value)
            self.events[value['id']] = event
            self.latest[event.unified_msg_origin] = event
            while len(self.events)>128: self.events.popitem(last=False)
            if not value.get('notice') and not value.get('internal') and not value.get('observedChannel'):
                await self.base.service.capture.incoming(event)
            from astrbot.core.star.star_handler import EventType
            if not value.get('observedChannel') and not value.get('internal'):
                await self.hooks(EventType.AdapterMessageEvent, event)
        return event

    async def hooks(self, event_type, event, *arguments):
        from astrbot.core.star.star_handler import EventType, star_handlers_registry
        from astrbot.core.platform.astr_message_event import event_context
        with event_context(event):
            handlers=star_handlers_registry.get_handlers_by_event_type(event_type)
            if event_type == EventType.AdapterMessageEvent:
                await self.context.cortico_stages[0].process(event)
                handlers=event.get_extra('activated_handlers',[])
            for handler in handlers:
                if not handler.handler_module_path.startswith('data.plugins.'): continue
                parameters=event.get_extra('handlers_parsed_params',{}).get(handler.handler_full_name,{}) if event_type==EventType.AdapterMessageEvent else {}
                result = handler.handler(event, *arguments, **parameters)
                if inspect.isasyncgen(result):
                    async for item in result:
                        if item is not None:
                            from astrbot.core.message.message_event_result import MessageEventResult
                            if event_type==EventType.AdapterMessageEvent and isinstance(item,MessageEventResult):
                                event.set_result(item)
                                for stage in self.context.cortico_stages[1:]:
                                    processed=stage.process(event)
                                    if inspect.isasyncgen(processed):
                                        async for _ in processed:pass
                                    elif inspect.isawaitable(processed):await processed
                            else:await event.send(item)
                elif inspect.isawaitable(result): await result
                if event_type==EventType.AdapterMessageEvent and handler.handler_full_name in event.get_extra('handlers_parsed_params',{}):event.stop_event()
                if event.is_stopped(): break

    async def dispatch(self, method, args):
        if method=='initialize': return await self.initialize(args)
        if method=='status': return {**await self.base.dispatch('status',{}), **self.status()}
        if method=='schemas': return self.schemas()
        if method=='companion_activation':
            from astrbot.core.star.star import star_map
            self.companion_enabled=bool(args['enabled'])
            self.plugins[1].enabled=self.companion_enabled and self.companion_original_enabled
            star_map['data.plugins.astrbot_plugin_private_companion.main'].activated=self.companion_enabled
            if hasattr(self.context,'cortico_addons'):await self.context.cortico_addons.activate_content(self.companion_enabled)
            return {'enabled':self.companion_enabled}
        if method=='addon_activation':return await self.context.cortico_addons.activate(args['plugin'],bool(args['enabled']))
        if method=='import':return await self.import_memories(args)
        if method=='legacy':return await self.migrate_legacy(args)
        if method=='launch':
            if args.get('plugin') not in ('companion','memory','content','memewiki'): raise ValueError('Unknown plugin')
            return {'url':f'http://127.0.0.1:{self.port}/_launch?key={self.launch_secret}&plugin={args["plugin"]}'+('&view=config' if args.get('view')=='config' else '')}
        if method=='context':
            if args['event'].get('observedChannel'): return await self.base.dispatch(method,args)
            event = await self.event(args['event'])
            if args['event'].get('notice'):return {'text':'平台通知已交由原版陪伴插件处理。','handled':True,'toolNames':[]}
            from astrbot.core.provider.entities import ProviderRequest
            from astrbot.core.star.star_handler import EventType
            from astrbot.core.agent.tool import ToolSet
            if event.is_stopped(): return {'text':'原版插件已处理或拦截本次输入；不重复回复。','handled':True,'toolNames':[]}
            from astrbot.core.star.star import star_map
            tools=ToolSet([t for t in self.context.get_llm_tool_manager().func_list if getattr(t,'handler_module_path','').startswith('data.plugins.') and star_map.get(t.handler_module_path) and star_map[t.handler_module_path].activated])
            history=deepcopy(args.get('history') or [])
            if not isinstance(history,list) or any(not isinstance(item,dict) or item.get('role') not in ('user','assistant') or not isinstance(item.get('content'),str) for item in history):raise ValueError('Invalid scoped Cortico history')
            manager=self.context.conversation_manager
            cid=await manager.get_curr_conversation_id(event.unified_msg_origin)
            if cid is None:cid=await manager.new_conversation(event.unified_msg_origin,platform_id='cortico',persona_id='cortico')
            await manager.update_conversation(event.unified_msg_origin,cid,history=history,persona_id='cortico')
            conversation=await manager.get_conversation(event.unified_msg_origin,cid)
            history_before=deepcopy(history)
            await self.hooks(EventType.OnWaitingLLMRequestEvent,event)
            request = ProviderRequest(prompt=event.message_str,system_prompt='',contexts=history,func_tool=tools,conversation=conversation)
            await self.hooks(EventType.OnLLMRequestEvent,event,request)
            injected=request.prompt[len(event.message_str):] if isinstance(request.prompt,str) and request.prompt.startswith(event.message_str) else '\n'+str(request.prompt or '')
            for part in request.extra_user_content_parts:
                item=part if isinstance(part,dict) else part.model_dump_for_context()
                if item.get('type')=='text': injected+='\n'+str(item.get('text',''))
            for item in request.contexts:
                if item not in history_before and isinstance(item.get('content'),str): injected+='\n'+item['content']
            legacy=self.base.read('private:'+event.get_sender_id(),'relationship',event.get_sender_id())['value'].get('legacyHumanlike')
            extra='\nCortico 既有关系格子（保留原有身份，不授予操作权限，不因新分数归零而重设）：'+json.dumps(legacy,ensure_ascii=False) if legacy and not event.get_group_id() else ''
            event.set_extra('cortico_allowed_tools',[t.name for t in request.func_tool or []])
            selected=event.get_extra('selected_provider')
            route={'endpoint':selected,**({'model':request.model} if request.model else {})} if selected else None
            return {'text':request.system_prompt+injected+extra, 'companion':{}, 'handled':event.is_stopped(),'toolNames':event.get_extra('cortico_allowed_tools'),'modelTarget':route}
        if method=='outbound':
            from astrbot.core.message import components as comp
            from astrbot.core.message.message_event_result import MessageEventResult, ResultContentType
            from astrbot.core.platform.astr_message_event import event_context
            from astrbot.core.provider.entities import LLMResponse
            from astrbot.core.star.star_handler import EventType
            event=self.events.get(args['eventId'])
            if event is None: raise ValueError('Outbound event has expired')
            if event.is_stopped(): return {'suppressed':True,'receipts':[]}
            event.set_extra('cortico_receipts',[])
            chain=[]
            for part in args['components']:
                cls=getattr(comp,part['type'],None)
                if cls not in (comp.Plain,comp.Image,comp.Record,comp.At,comp.Reply): raise ValueError('Invalid outbound component')
                chain.append(cls(**{k:v for k,v in part.items() if k!='type'}))
            response=LLMResponse(role='assistant',completion_text=''.join(p.text for p in chain if isinstance(p,comp.Plain)))
            with event_context(event):
                await self.hooks(EventType.OnLLMResponseEvent,event,response)
                for p in chain:
                    if isinstance(p,comp.Plain): p.text=response.completion_text;break
                event.set_result(MessageEventResult(chain=chain).set_result_content_type(ResultContentType.LLM_RESULT))
                for stage in self.context.cortico_stages[1:]:
                    processed=stage.process(event)
                    if inspect.isasyncgen(processed):
                        async for _ in processed: pass
                    elif inspect.isawaitable(processed): await processed
            event.set_extra('cortico_response_done',True)
            receipts=event.get_extra('cortico_receipts',[])
            return {'suppressed':not bool(receipts),'receipts':receipts}
        if method=='native_tool':
            event = await self.event(args['event'])
            if args['event'].get('observedChannel') and args['name'] in ('memory_companion_remember','memory_companion_core_memory'):
                raise ValueError('Use reviewed Cortico memory tools for non-chat sources')
            tool = self.context.get_llm_tool_manager().get_func(args['name'])
            from astrbot.core.star.star import star_map
            if tool and not star_map[tool.handler_module_path].activated:raise ValueError('Original plugin is disabled')
            if tool is None or not getattr(tool,'handler_module_path','').startswith('data.plugins.'):
                raise ValueError('Unknown plugin tool')
            if args['name'].startswith('pc_') and not self.companion_enabled:raise ValueError('Cortico companion extension is disabled')
            allowed=event.get_extra('cortico_allowed_tools')
            if allowed is not None and args['name'] not in allowed: raise ValueError('Plugin disabled this tool for the current conversation')
            from astrbot.core.platform.astr_message_event import event_context
            with event_context(event):
                result = tool.handler(event, **args.get('parameters',{}))
                if inspect.isasyncgen(result):
                    outputs=[]
                    async for item in result:
                        if isinstance(item,str): outputs.append(item)
                        elif item is not None: await event.send(item)
                    return '\n'.join(outputs)
                if inspect.isawaitable(result): result=await result
                return result
        if method=='provider_tool':
            entry=self.context.provider_calls.get(args.get('token'))
            if not entry or entry[0] is None or args.get('name') not in entry[1]: raise ValueError('Expired or unauthorized provider tool')
            if args.get('name','').startswith('pc_') and not self.companion_enabled:raise ValueError('Cortico companion extension is disabled')
            event,tools=entry
            from astrbot.core.star.star import star_map
            if not star_map[tools[args['name']].handler_module_path].activated:raise ValueError('Original plugin was disabled')
            from astrbot.core.platform.astr_message_event import event_context
            with event_context(event):
                result=tools[args['name']].handler(event,**args.get('parameters',{}))
                if inspect.isasyncgen(result):
                    outputs=[]
                    async for item in result:
                        if isinstance(item,str): outputs.append(item)
                        elif item is not None: await event.send(item)
                    return '\n'.join(outputs)
                return await result if inspect.isawaitable(result) else result
        if method=='response':
            result=await self.base.dispatch(method,args)
            session=f'cortico:{"GroupMessage" if args["target"].startswith("group:") else "FriendMessage"}:{args["target"].split(":",1)[1]}'
            event=self.latest.get(session)
            if event and not event.get_extra('cortico_response_done',False):
                from astrbot.core.provider.entities import LLMResponse
                from astrbot.core.star.star_handler import EventType
                await self.hooks(EventType.OnLLMResponseEvent,event,LLMResponse(role='assistant',completion_text=args['text']))
            return result
        if method=='close':
            if self.projection_task:
                self.projection_task.cancel()
                await asyncio.gather(self.projection_task,return_exceptions=True)
            self.web_stop.set()
            if self.web_task: await self.web_task
            for plugin in reversed(self.plugins): await plugin.terminate()
            from astrbot.core import db_helper
            await db_helper.engine.dispose()
            self.context=None
            if self.base is not None:
                if hasattr(self.base,'wiki'): self.base.wiki.close()
                if self.base.db is not None: self.base.db.close()
            return {'closed':True}
        return await self.base.dispatch(method,args)


def make_app(context, plugins, sources: Path, launch_secret: str, after_write=None):
    import hmac
    import secrets
    import time
    from urllib.parse import urlsplit
    from quart import Quart, request, redirect, send_from_directory, Response, jsonify
    from starlette.requests import Request
    from astrbot.api.web import PluginRequest, bind_request_context

    app = Quart(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 24 * 1024 * 1024
    sessions = {}
    plugin_roots = {
        'companion': sources / 'astrbot_plugin_private_companion_6_7_0' / 'pages' / '陪伴面板',
        'memory': sources / 'astrbot_plugin_memory_companion' / 'pages' / '记忆面板',
        'memewiki': sources / 'astrbot_plugin_memewiki' / 'views' / 'slang',
    }

    @app.before_request
    async def authenticate():
        if request.path == '/_launch': return None
        expires = sessions.get(request.cookies.get('cortico_astrbot_session', ''), 0)
        if expires < time.monotonic(): return jsonify({'success': False, 'error': '请从 Cortico 重新打开插件页面'}), 401
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            from astrbot.core.star.star import star_map
            if request.path.startswith('/astrbot_plugin_private_companion/') and not star_map['data.plugins.astrbot_plugin_private_companion.main'].activated:
                return jsonify({'success':False,'error':'陪伴扩展已在 Cortico 停用'}),503
            if request.headers.get('Origin') != request.host_url.rstrip('/'):
                return jsonify({'success': False, 'error': 'Invalid request origin'}), 403

    @app.after_request
    async def private_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/_launch')
    async def launch():
        if not hmac.compare_digest(request.args.get('key', ''), launch_secret):
            return jsonify({'success': False, 'error': 'Invalid launch key'}), 401
        plugin = request.args.get('plugin', 'companion')
        if plugin not in (*plugin_roots,'content'): return jsonify({'success': False, 'error': 'Unknown plugin'}), 404
        if plugin in ('content','memewiki') and (not hasattr(context,'cortico_addons') or plugin not in context.cortico_addons.schemas):return 'Plugin not installed',404
        session = secrets.token_urlsafe(32)
        sessions[session] = time.monotonic() + 12 * 60 * 60
        for key, expires in list(sessions.items()):
            if expires < time.monotonic(): sessions.pop(key, None)
        target='/_configuration/'+plugin if request.args.get('view')=='config' and plugin in ('content','memewiki') else '/plugins/companion/?cortico_tab=creative' if plugin=='content' else '/plugins/'+plugin+'/'
        response = redirect(target)
        response.set_cookie('cortico_astrbot_session', session, httponly=True, samesite='Strict', max_age=12*60*60)
        return response

    def html_page(plugin,filename):
        name = {'companion':'astrbot_plugin_private_companion','memory':'astrbot_plugin_memory_companion','memewiki':'astrbot_plugin_memewiki'}[plugin]
        bridge = '''<script>window.AstrBotPluginPage={ready:Promise.resolve(),apiGet:(p,q)=>fetch('/PLUGIN/'+p.replace(/^page\\/?/, 'page/')+(q?'?'+new URLSearchParams(q):''),{credentials:'same-origin'}).then(r=>r.json()),apiPost:(p,b)=>fetch('/PLUGIN/'+p.replace(/^page\\/?/,'page/'),{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(b)}).then(r=>r.json())};</script>'''.replace('PLUGIN', name)
        html = filename.read_text(encoding='utf-8')
        if plugin=='memewiki':html=html.replace('<script src="/api/plugin/page/bridge-sdk.js"></script>','')
        if plugin=='companion':
            html+='''<script>if(new URLSearchParams(location.search).get('cortico_tab')==='creative'){const open=()=>{const b=document.querySelector('button[data-tab="creative"]');if(b&&!b.hidden){b.click();observer.disconnect();}};const observer=new MutationObserver(open);observer.observe(document.body,{subtree:true,attributes:true,childList:true});open();setTimeout(()=>observer.disconnect(),15000);}</script>'''
        return Response(html.replace('<head>', '<head>' + bridge, 1), mimetype='text/html')

    @app.get('/_configuration/<plugin>')
    async def addon_config_page(plugin):
        if not hasattr(context,'cortico_addons') or plugin not in context.cortico_addons.schemas:return 'Plugin not installed',404
        return Response(Path(__file__).with_name('native-config.html').read_text(encoding='utf-8'),mimetype='text/html')

    @app.get('/_configuration/<plugin>/data')
    async def addon_config_read(plugin):
        if not hasattr(context,'cortico_addons') or plugin not in context.cortico_addons.schemas:return 'Plugin not installed',404
        return jsonify(context.cortico_addons.config(plugin))

    @app.post('/_configuration/<plugin>/data')
    async def addon_config_save(plugin):
        if not hasattr(context,'cortico_addons') or plugin not in context.cortico_addons.schemas:return 'Plugin not installed',404
        return await context.cortico_addons.save_config(plugin,await request.get_json())

    @app.get('/plugins/<plugin>/')
    async def page(plugin):
        if plugin not in plugin_roots: return 'Unknown plugin', 404
        return html_page(plugin,plugin_roots[plugin]/'index.html')

    @app.get('/plugins/<plugin>/<path:filename>')
    async def asset(plugin, filename):
        if plugin not in plugin_roots: return 'Unknown plugin', 404
        target=(plugin_roots[plugin]/filename).resolve()
        if not target.is_relative_to(plugin_roots[plugin].resolve()) or not target.is_file(): return 'Not found',404
        if target.suffix.lower()=='.html': return html_page(plugin,target)
        if plugin=='companion' and filename=='js/panels/provider-tree.js':
            text=target.read_text(encoding='utf-8')
            # The original badge checks only chat providers despite a separate embedding selector.
            text=text.replace('const availableProviders = Array.isArray(state.availableProviders) ? state.availableProviders : [];','const availableProviders = [...(state.availableProviders || []), ...(state.availableEmbeddingProviders || [])];',1)
            return Response(text,mimetype='application/javascript')
        return await send_from_directory(plugin_roots[plugin], filename)

    def wrapper(handler, path):
        async def invoke(**values):
            body = await request.get_data()
            async def receive(): return {'type':'http.request', 'body':body, 'more_body':False}
            scope = {'type':'http','method':request.method,'path':request.path,'query_string':request.query_string,
                'headers':[(key.lower().encode(), value.encode()) for key,value in request.headers.items()],
                'scheme':request.scheme,'server':('127.0.0.1',urlsplit(request.host_url).port or 80),
                'client':(request.remote_addr,0),'root_path':''}
            username = context.get_config().get('dashboard', {}).get('username')
            bound = PluginRequest(Request(scope, receive), plugin_name=path.split('/')[1], username=username)
            test_token=manual_provider_test.set(path=='/astrbot_plugin_private_companion/page/provider/test')
            try:
                with bind_request_context(bound):
                    result = handler(**values)
                    result=await result if inspect.isawaitable(result) else result
            finally:manual_provider_test.reset(test_token)
            if after_write and request.method not in ('GET','HEAD') and '/astrbot_plugin_memory_companion/' in path:
                await after_write()
            if hasattr(context,'cortico_addons') and request.method not in ('GET','HEAD'):await context.cortico_addons.after_write(path)
            return result
        return invoke
    for index,(path, handler, methods, _) in enumerate(context.registered_web_apis):
        app.add_url_rule(path, endpoint='native_'+str(index), view_func=wrapper(handler,path), methods=methods)
    return app


async def probe(args):
    async def blocked(kind, arguments):
        raise RuntimeError('Offline probe forbids model calls and external sends: ' + kind)
    context, plugins = await create_host(args.sources, args.state, blocked)
    try:
        report = {'plugins': [type(p).__name__ for p in plugins], 'routes': len(context.registered_web_apis),
            'routePaths': [p[0] for p in context.registered_web_apis]}
        app = make_app(context, plugins, args.sources, 'offline-test-key')
        client = app.test_client()
        assert (await client.get('/plugins/companion/')).status_code == 401
        assert (await client.get('/_launch?key=offline-test-key&plugin=companion')).status_code == 302
        results = {}
        for url in ['/plugins/companion/', '/plugins/memory/',
                    '/astrbot_plugin_private_companion/page/overview',
                    '/astrbot_plugin_memory_companion/page/stats',
                    '/astrbot_plugin_memory_companion/page/config/schema']:
            response = await client.get(url)
            result = await response.get_json() if response.mimetype == 'application/json' else None
            results[url] = {'status':response.status_code,'success':result.get('success') if isinstance(result,dict) else None}
            if response.status_code != 200: print(url, (await response.get_data(as_text=True))[:400])
        report['webProbe'] = results
        tools = context.get_llm_tool_manager().func_list
        report['tools'] = [tool_schema(t) for t in tools if getattr(t,'handler_module_path','').startswith('data.plugins.')]
        event = context.create_cortico_event({'id':'offline-probe-1','text':'测试资料，不是真实用户经历。','userId':'probe-user',
            'userName':'离线探针','at':time.time(),'target':'private:probe-user','internal':True})
        report['eventProbe'] = {'session':event.unified_msg_origin,'sender':event.get_sender_id(),'text':event.get_message_str()}
        (args.state / 'probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'plugins': report['plugins'], 'routes': report['routes']}))
    finally:
        for plugin in reversed(plugins):
            await plugin.terminate()


async def rpc():
    output = sys.stdout
    sys.stdout = sys.stderr
    # Windows numerical DLLs must load before the blocking stdin reader starts.
    if importlib.util.find_spec('fastembed') is not None:
        import fastembed
    waiters = {}
    sequence = 0
    def emit(value):
        output.write(json.dumps(value,ensure_ascii=False,default=str)+'\n')
        output.flush()
    async def callback(kind, arguments):
        nonlocal sequence
        sequence += 1
        key = 'native-'+str(sequence)
        future = asyncio.get_running_loop().create_future()
        waiters[key] = future
        emit({'callback':key,'kind':kind,'arguments':arguments})
        try: return await asyncio.wait_for(future,240)
        finally: waiters.pop(key,None)
    runtime = NativeRuntime(callback)
    running = set()
    async def execute(request):
        try:
            result = await runtime.dispatch(request['method'],request.get('arguments',{}))
            emit({'id':request['id'],'result':result})
        except Exception as error:
            import traceback
            traceback.print_exc(file=sys.stderr)
            emit({'id':request['id'],'error':str(error)})
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            if request.get('callback'):
                future = waiters.get(request['callback'])
                if future is not None and not future.done():
                    if 'error' in request: future.set_exception(RuntimeError(request['error']))
                    else: future.set_result(request.get('result'))
            else:
                task = asyncio.create_task(execute(request))
                running.add(task)
                task.add_done_callback(running.discard)
    finally:
        if runtime.context: await runtime.dispatch('close',{})
        for task in running: task.cancel()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--rpc',action='store_true')
    args = parser.parse_args()
    if args.rpc: asyncio.run(rpc())
    else:
        if args.state is None or args.sources is None: parser.error('--sources and --state are required for probe mode')
        args.state.mkdir(parents=True, exist_ok=True)
        asyncio.run(probe(args))
