"""Cortico host ports for the original companion domain modules; JSONL over stdio."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


def load_package(name, root):
    package = ModuleType(name)
    package.__path__ = [str(root)]
    sys.modules[name] = package


class Event:
    def __init__(self, value, bot_id):
        self.value = value
        self.persona_id = 'cortico'
        self.message_str = value['text']
        kind = 'GroupMessage' if value.get('groupId') else 'FriendMessage'
        self.unified_msg_origin = f"cortico:{kind}:{value.get('groupId') or value['userId']}"
        self.message_obj = SimpleNamespace(message_id=value['id'], timestamp=value['at'], message_str=value['text'], raw_message={})
        self.bot_id = bot_id
        self.private_companion_proactive_framework = bool(value.get('internal'))
        self._s4_source_capture_enabled = not value.get('internal') and not value.get('observedChannel')

    def get_platform_name(self): return 'cortico'
    def get_group_id(self): return self.value.get('groupId', '')
    def get_group_name(self): return self.value.get('groupName', '')
    def get_sender_id(self): return self.value['userId']
    def get_sender_name(self): return self.value.get('userName', '')
    def get_self_id(self): return self.bot_id
    def get_message_str(self): return self.message_str
    def get_messages(self): return []
    def get_extra(self, key, default=None): return getattr(self, '_extras', {}).get(key, default)
    def set_extra(self, key, value):
        if not hasattr(self, '_extras'): self._extras = {}
        self._extras[key] = value


class Provider:
    def __init__(self, runtime): self.runtime = runtime
    async def text_chat(self, **arguments):
        result = await self.runtime.model(arguments)
        return SimpleNamespace(completion_text=result, role='assistant', usage=None)


class HostContext:
    def __init__(self, runtime): self.provider = Provider(runtime)
    def get_using_provider(self, *args, **kwargs): return self.provider
    def get_provider_by_id(self, provider_id): return self.provider if provider_id == 'cortico' else None
    def get_all_stars(self): return []


class Runtime:
    def __init__(self):
        self.waiters = {}
        self.events = OrderedDict()
        self.service = None
        self.sequence = 0
        self.domain = None
        self.db = None

    async def model(self, arguments):
        self.sequence += 1
        key = f'model-{self.sequence}'
        future = asyncio.get_running_loop().create_future()
        self.waiters[key] = future
        emit({'callback': key, 'arguments': arguments})
        try: return await asyncio.wait_for(future, 180)
        finally: self.waiters.pop(key, None)

    async def initialize(self, args):
        self.root = Path(args['sources'])
        self.data_root = Path(args['dataDir'])
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.bot_id = args['botId']
        self.timezone = ZoneInfo(args['timezone'])
        load_package('stable_companion', self.root / 'astrbot_plugin_private_companion_6_7_0')
        load_package('memory_companion', self.root / 'astrbot_plugin_memory_companion')
        from stable_companion.helpers import _set_today_key_timezone
        _set_today_key_timezone(args['timezone'])
        from memory_companion.core.service import MemoryCompanionService
        self.service = MemoryCompanionService(context=HostContext(self), config=args.get('memoryConfig', {}),
            plugin_root=self.root / 'astrbot_plugin_memory_companion', data_dir=self.data_root / 'memory')
        self.service.capture.start()
        self.db = sqlite3.connect(self.data_root / 'companion.db')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS documents (scope TEXT, kind TEXT, id TEXT, body TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(scope,kind,id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS audit (at TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, before TEXT, after TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meme_cache (term TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)')
        self.db.commit()
        self.wiki = sqlite3.connect(f"{(self.root / 'astrbot_plugin_memewiki/data/memes.db').as_uri()}?mode=ro", uri=True)
        self.wiki.row_factory = sqlite3.Row
        self.persona = args['persona']
        self.settings = args.get('settings', {})
        from stable_companion.chronotype import ChronotypeMixin
        self.chronotype=ChronotypeMixin()
        self.chronotype._environment_fromtimestamp=lambda stamp:datetime.fromtimestamp(stamp,self.timezone)
        return {'ready': True, 'memeCount': self.wiki.execute('SELECT count(*) FROM memes').fetchone()[0], 'memoryIntegrity': self.service.store._conn.execute('PRAGMA integrity_check').fetchone()[0]}

    def read(self, scope, kind, identifier='current'):
        row = self.db.execute('SELECT body,revision FROM documents WHERE scope=? AND kind=? AND id=?', (scope, kind, identifier)).fetchone()
        return {'value': json.loads(row['body']), 'revision': row['revision']} if row else {'value': {}, 'revision': 0}

    def write(self, scope, kind, identifier, value, revision):
        if type(revision) is not int or revision<0: raise ValueError('revision must be a nonnegative integer')
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > 60000: raise ValueError('document exceeds 60000 characters')
        with self.db:
            before = self.read(scope, kind, identifier)
            if before['revision'] != revision: raise ValueError('revision conflict; reload before saving')
            self.db.execute('INSERT INTO documents VALUES(?,?,?,?,?) ON CONFLICT(scope,kind,id) DO UPDATE SET body=excluded.body,revision=excluded.revision', (scope, kind, identifier, text, revision + 1))
            self.db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (datetime.now(timezone.utc).isoformat(), scope, kind, identifier, json.dumps(before['value'], ensure_ascii=False), text))
        return {'value': value, 'revision': revision + 1}

    async def event(self, value):
        if not isinstance(value, dict) or not all(isinstance(value.get(key), str) and value[key] for key in ('id', 'text', 'userId')):
            raise ValueError('host-owned message identity required')
        event = self.events.get(value['id'])
        if event is None:
            event = Event(value, self.bot_id)
            self.events[value['id']] = event
            while len(self.events) > 64: self.events.popitem(last=False)
            if not value.get('internal') and not value.get('observedChannel'):
                scope=self.scope(event)
                item=self.read(scope,'relationship',event.get_sender_id())
                person=item['value'] or {'relationship_score_schema_version':2,'relationship_score':0}
                if person.get('chronotype_last_event')!=value['id']:
                    self.chronotype._note_user_chronotype_activity(person,value['at'])
                    self.chronotype._note_user_chronotype_tell(person,value['text'],now=value['at'])
                    person['chronotype_last_event']=value['id']
                    self.write(scope,'relationship',event.get_sender_id(),person,item['revision'])
        return event

    def scope(self, event):
        return ('group:' + event.get_group_id()) if event.get_group_id() else ('private:' + event.get_sender_id())

    async def dispatch(self, method, args):
        if method == 'initialize': return await self.initialize(args)
        if method == 'status':
            return {'ready': True, 'memory': self.service.store._conn.execute('SELECT count(*) FROM memories').fetchone()[0],
                'documents': self.db.execute('SELECT count(*) FROM documents').fetchone()[0], 'pendingModels': len(self.waiters), 'sources':self.service.capture.status()}
        if method == 'close':
            await self.service.aclose()
            self.wiki.close()
            self.db.close()
            return {'closed': True}
        if method == 'meme': return await self.meme(args)
        if method == 'operator': return await self.operator(args)
        if method == 'import': return await self.import_memories(args)
        if method == 'response':
            from memory_companion.core.models import SessionContext,utc_now
            target=args['target']
            if not isinstance(target,str) or not target.startswith(('private:','group:')) or args.get('delivery')!='confirmed' or not isinstance(args.get('text'),str):
                raise ValueError('confirmed host delivery required')
            kind,identifier=target.split(':',1)
            ctx=SessionContext(scope=kind,session_id=f'cortico:{"GroupMessage" if kind=="group" else "FriendMessage"}:{identifier}',
                platform='cortico',bot_id=self.bot_id,persona_id='cortico',user_id=identifier if kind=='private' else '',group_id=identifier if kind=='group' else '')
            identity=self.service.capture.identity(ctx,direction='outgoing',message=args['id'])
            return self.service.capture.submit(identity,{'body':args['text'],'source_message_at':args['at'],'observed_at':utc_now(),'evidence':'platform_accepted'})
        if method == 'legacy':
            directory = Path(args['directory'])
            migrated = {'state':0,'relationships':0}
            life = directory / 'life.json'
            if life.exists() and self.read('self','state')['revision']==0:
                value=json.loads(life.read_text(encoding='utf-8-sig'))
                state={'activity':value.get('activity',''),'mood_bias':value.get('mood',''),'energy':round(float(value.get('energy',0))*100),
                    'date':value.get('day',''),'legacyHumanlike':value,'reality':'role_state'}
                self.write('self','state','current',state,0)
                migrated['state']=1
            affinity=directory/'affinity.json'
            if affinity.exists():
                value=json.loads(affinity.read_text(encoding='utf-8-sig'))
                for identifier,person in value.get('people',{}).items():
                    if not str(identifier).isdigit() or not isinstance(person,dict): continue
                    scope='private:'+str(identifier)
                    if self.read(scope,'relationship',str(identifier))['revision']>0: continue
                    self.write(scope,'relationship',str(identifier),{'relationship_score_schema_version':2,'relationship_score':0,
                        'legacyHumanlike':person,'migrationNote':'旧交情分数与关系格子完整保留；两套分数没有等价换算，新结算单独起算，不能据此重置既有关系身份。'},0)
                    migrated['relationships']+=1
            return migrated
        event = await self.event(args['event'])
        if method == 'context':
            if args['event'].get('internal') or args['event'].get('observedChannel'):
                ctx=await self.service.identity.resolve_event_context(event)
                memory=await self.service.bridge_compose_context(query='与当前会话相关的近期对话、未完成话题和明确约定；旧话题不自动重开',session_context=ctx,max_chars=4000)
                return {'text':memory,'scope':self.scope(event),'companion':await self.companion(event,{'operation':'status'}),
                    **({'proactive':await self.companion(event,{'operation':'proactive'})} if args['event'].get('internal') else {})}
            req = SimpleNamespace(system_prompt='', prompt=event.message_str, contexts=[], func_tool=None)
            await self.service.handle_llm_request(event, req)
            injected = req.prompt[len(event.message_str):] if req.prompt.startswith(event.message_str) else req.prompt
            return {'text': req.system_prompt + '\n' + injected, 'scope': self.scope(event), 'companion':await self.companion(event, {'operation':'status'}), 'diagnostics':getattr(event,'memory_companion_injection_state',{})}
        if method == 'memory':
            operation = args.get('operation', 'recall')
            if args['event'].get('observedChannel') and operation in ('remember','core'):
                raise ValueError('Use Cortico source-reviewed memory tools for observed World material; it is not an authenticated human message')
            parameters = args.get('parameters', {})
            allowed = {'recall': self.service.tool_recall, 'navigate': self.service.tool_navigate,
                'sources': self.service.tool_sources, 'events': self.service.tool_events,
                'remember': self.service.tool_remember, 'core':self.service.tool_core_memory, 'notes': self.service.tool_note_read}
            if operation not in allowed: raise ValueError('unsupported memory operation')
            return await allowed[operation](event, **parameters)
        if method == 'companion': return await self.companion(event, args)
        raise ValueError('unknown bridge method')

    async def import_memories(self, args):
        from memory_companion.core.models import MemoryRecord, EntityRef
        count = unchanged = 0
        incoming_ids = set()
        for row in args['rows']:
            if row['state'] != 'active' or row['kind'] in ('raw', 'archive'): raise ValueError('only approved summaries can be imported')
            source_scope = row['scope']
            if source_scope in ('main', 'learning'):
                scope, target, session = 'private', 'operator', 'cortico:FriendMessage:operator'
            elif source_scope.startswith(('private:', 'qq:')):
                scope, target = 'private', source_scope.split(':', 1)[1]
                session = f'cortico:FriendMessage:{target}'
            elif source_scope.startswith('group:'):
                scope, target = 'group', source_scope.split(':', 1)[1]
                session = f'cortico:GroupMessage:{target}'
            else:
                scope,target='private','channel:'+source_scope
                session=f'cortico:FriendMessage:{target}'
            metadata = json.loads(row.get('metadata', '{}'))
            identifier = 'cortico_' + row['id']
            incoming_ids.add(identifier)
            fingerprint = hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            existing = self.service.store._conn.execute('SELECT metadata,review_status FROM memories WHERE id=?',(identifier,)).fetchone()
            if existing and json.loads(existing['metadata']).get('cortico_import_hash') == fingerprint and existing['review_status'] == 'confirmed':
                unchanged += 1
                continue
            content = row['text']
            if not metadata.get('occurredAt') or metadata.get('timeConfidence',1)<0.7:
                content = '[发生时间未知；记录日期不能当作事件日期] ' + content
            record = MemoryRecord(id=identifier, content=content, scope=scope, session_id=session,
                platform='cortico', owner_bot_id=self.bot_id, subject=EntityRef.bot_self(self.bot_id),
                object=EntityRef(kind='user' if scope == 'private' else 'group', id=target), group_id=target if scope == 'group' else '',
                visibility='private_pair' if scope == 'private' else 'group_public',
                memory_type={'commitment':'promise','core':'core_memory'}.get(row['kind'], 'conversation_event'),
                lifecycle='stable_memory', importance=min(1, row['importance'] / 12), salience=min(1, row['importance'] / 12),
                confidence=0.85, reality_level='imported_summary', review_status='confirmed', durability='durable',
                evidence=metadata.get('evidence', ''), metadata={**metadata, 'cortico_import_hash':fingerprint,'cortico_scope':source_scope, 'cortico_id':row['id'], 'cortico_weight':row['importance']},
                source_plugin='cortico_weighted_memory', occurred_at=metadata.get('occurredAt') or '',
                valid_from=metadata.get('effectiveAt') or '',
                canonical_key='cortico:'+row['id'],content_fingerprint=fingerprint,
                created_at=datetime.fromtimestamp(row['createdAt']/1000, timezone.utc).isoformat())
            await self.service.store.insert_memory(record)
            count += 1
        revoked = 0
        if args.get('completeSnapshot') is True:
            for row in self.service.store._conn.execute("SELECT id FROM memories WHERE source_plugin='cortico_weighted_memory' AND review_status!='rejected'").fetchall():
                if row['id'] not in incoming_ids:
                    await self.service.store.update_review_status(row['id'],'rejected')
                    revoked += 1
        return {'imported': count, 'unchanged':unchanged, 'revoked':revoked, 'eligible':len(incoming_ids), 'skippedScopes':len(args['rows'])-count-unchanged}

    async def meme(self, args):
        query = args.get('query', '').strip()
        if not query or len(query) > 300: raise ValueError('query must contain 1-300 characters')
        scope=args.get('scope')
        if isinstance(scope,str):
            custom=self.db.execute("SELECT id,body FROM documents WHERE scope=? AND kind='slang' AND (id=? OR (length(id)>=2 AND instr(?,id)>0)) ORDER BY length(id) DESC LIMIT 1",(scope,query,query)).fetchone()
            if custom:
                return {'title':custom['id'],'usage':json.loads(custom['body']).get('meaning',''),'source':'current_conversation','scope':scope}
        row = self.wiki.execute('SELECT * FROM memes WHERE title=?', (query,)).fetchone()
        if row is None:
            row = self.wiki.execute('SELECT * FROM memes WHERE length(title)>=2 AND instr(?,title)>0 ORDER BY length(title) DESC,title LIMIT 1', (query,)).fetchone()
        if row:
            data = dict(row)
            data['source'] = 'bundled'
            data['url'] = 'https://cnmeme.wiki/词条/' + quote(data['slug'])
            return data
        if not args.get('online', False): return {'found': False, 'query': query, 'source': 'bundled'}
        cached=self.db.execute('SELECT payload FROM meme_cache WHERE term=? AND expires_at>?',(query,datetime.now().timestamp())).fetchone()
        if cached: return {**json.loads(cached['payload']),'cached':True}
        def fetch():
            url = 'https://cnmeme.wiki/api/v1/public/memes?' + urlencode({'q':query,'limit':5})
            with urlopen(Request(url, headers={'User-Agent':'Cortico-memewiki/1.0'}), timeout=6) as response:
                raw = response.read(512001)
                if len(raw)>512000: raise ValueError('wiki response exceeds limit')
                return json.loads(raw)
        payload = await asyncio.to_thread(fetch)
        items = payload.get('items', [])
        matched = next((item for item in items if item.get('title') == query), None)
        result=({'found':False, 'candidates':[{'title':i.get('title'),'slug':i.get('slug')} for i in items[:5]], 'query':query} if matched is None else
            {'found':True, 'source':'online', 'title':matched['title'], 'summary':matched.get('summary','')[:2000], 'url':'https://cnmeme.wiki/词条/' + quote(matched['slug'])})
        with self.db:
            self.db.execute('INSERT INTO meme_cache VALUES(?,?,?) ON CONFLICT(term) DO UPDATE SET payload=excluded.payload,expires_at=excluded.expires_at',
                (query,json.dumps(result,ensure_ascii=False),datetime.now().timestamp()+(90*86400 if matched else 600)))
        return result

    async def operator(self, args):
        scope, kind, identifier = args.get('scope', 'self'), args.get('kind', 'state'), args.get('id', 'current')
        if not all(isinstance(v,str) and 0<len(v)<=180 for v in (scope,kind,identifier)): raise ValueError('invalid document key')
        if kind not in ('state','calendar','diary','relationship','anniversary','knowledge','goals','skills','open_items','slang','plan'):
            raise ValueError('invalid companion document kind')
        if args.get('action') == 'save':
            if not isinstance(args.get('value'), dict): raise ValueError('document must be an object')
            if kind=='slang':
                meaning=args['value'].get('meaning')
                if not 2<=len(identifier)<=16 or not isinstance(meaning,str) or not 1<=len(meaning)<=300: raise ValueError('slang requires a 2-16 character name and 1-300 character meaning')
            return self.write(scope, kind, identifier, args['value'], args['revision'])
        if args.get('action') == 'list':
            rows = self.db.execute('SELECT id,body,revision FROM documents WHERE scope=? AND kind=? ORDER BY id LIMIT 100', (scope,kind)).fetchall()
            total=self.db.execute('SELECT count(*) FROM documents WHERE scope=? AND kind=?',(scope,kind)).fetchone()[0]
            return {'items':[{'id':r['id'],'value':json.loads(r['body']),'revision':r['revision']} for r in rows], 'returned':len(rows),'total':total,'truncated':total>len(rows)}
        return self.read(scope,kind,identifier)

    async def companion(self, event, args):
        from stable_companion import relationship_ledger, relationship_policy, planning
        operation = args.get('operation', 'status')
        scope = self.scope(event)
        if operation == 'status':
            return {'state':self.read('self','state'), 'plan':self.read('self','plan'),
                'relationship':self.read(scope,'relationship',event.get_sender_id()),
                'calendar':await self.operator({'scope':scope,'kind':'calendar','action':'list'})}
        if operation == 'proactive':
            from stable_companion.proactive_routes import PROACTIVE_ROUTE_REGISTRY
            candidate=args.get('candidate',{})
            if not isinstance(candidate,dict): raise ValueError('candidate must be an object')
            route=PROACTIVE_ROUTE_REGISTRY.route_for(source=candidate.get('source','qq_proactive'),reason=candidate.get('reason',''),kind=candidate.get('kind',''))
            prepared=route.prepare_candidate(candidate,source='cortico',now=datetime.now().timestamp(),date_key=datetime.now(self.timezone).date().isoformat())
            person=self.read(scope,'relationship',event.get_sender_id())['value']
            return {'candidate':prepared,'preflight':asdict(route.preflight(person,prepared,now=datetime.now().timestamp())),
                'directive':route.render_directive(quota_tier=1),'review':route.review_directive(),
                'delivery':route.delivery_options(prepared),'chronotype':self.chronotype._user_chronotype(person,now=datetime.now().timestamp()),
                'authorization':'只评估当前Cortico渠道已经允许的联系机会，不新增收件人或发送权限。'}
        if operation == 'relationship':
            item = self.read(scope,'relationship',event.get_sender_id())
            user = item['value']
            relationship_ledger.migrate_relationship_score_schema(user, created=not user, now=event.value['at'])
            result = relationship_ledger.apply_relationship_event(user, args.get('delta'), reason_code=args.get('reason'),
                event_id=event.value['id'], now=event.value['at'], timezone_name=str(self.timezone))
            self.write(scope,'relationship',event.get_sender_id(),user,item['revision'])
            return {**result, 'stage':relationship_policy.relationship_stage_for_score(user.get('relationship_score',0))}
        if operation == 'plan_prompt':
            host = PlanningHost(self)
            return {'prompt':planning.build_daily_plan_prompt(host, datetime.now(self.timezone).isoformat(), args.get('memory',''))}
        if operation == 'plan_generate':
            host = PlanningHost(self, scope)
            raw = await self.model({'prompt':planning.build_daily_plan_prompt(host, datetime.now(self.timezone).isoformat(), args.get('memory','')), 'max_tokens':4096})
            value = host._extract_json_payload(raw)
            items = (value.get('schedule') or value.get('items') or value.get('plan')) if isinstance(value,dict) else value
            if not isinstance(items,list) or not 3 <= len(items) <= 32: raise ValueError('daily plan must have 3-32 items')
            previous_end = -1
            for item in items:
                if not isinstance(item,dict) or not isinstance(item.get('activity'),str) or not item['activity'].strip(): raise ValueError('plan activity missing')
                start, end = host._parse_hhmm_to_minutes(item.get('time')), host._parse_hhmm_to_minutes(item.get('end'))
                if start is None or end is None or start < previous_end: raise ValueError('plan overlaps or has invalid time')
                if end <= start: end += 1440
                if end-start < 15 or end-start > 720: raise ValueError('invalid plan duration')
                previous_end = end
            current = self.read('self','plan')
            return self.write('self','plan','current', {'date':datetime.now(self.timezone).date().isoformat(),'items':items,'source':'stable_6_7_0_planning','reality':'planned'},current['revision'])
        if operation == 'diary_generate':
            from stable_companion import dreaming
            host = PlanningHost(self, scope)
            result = await dreaming.generate_daily_diary(host)
            if not result.get('body'): raise ValueError('diary generation returned no content')
            result['source'] = 'stable_6_7_0_diary'
            result['reality'] = 'reflection'
            result.pop('raw',None)
            current = self.read(scope,'diary',result['date'])
            return self.write(scope,'diary',result['date'],result,current['revision'])
        if operation == 'save':
            kind = args.get('kind')
            if kind not in ('calendar','anniversary','knowledge','goals','skills','open_items','slang','state'):
                raise ValueError('unsupported companion write')
            value = args.get('value')
            if not isinstance(value,dict): raise ValueError('value must be an object')
            value = dict(value)
            if kind == 'calendar':
                for key in ('title','at'):
                    if not isinstance(value.get(key),str) or not value[key].strip(): raise ValueError('calendar title and at are required')
                at = datetime.fromisoformat(value['at'].replace('Z','+00:00'))
                if at.tzinfo is None: raise ValueError('calendar time must have timezone')
                value['state'] = 'proposed'
            if kind == 'anniversary':
                datetime.strptime(value.get('date',''),'%Y-%m-%d')
                if not value.get('title'): raise ValueError('anniversary title required')
            if kind=='slang':
                identifier=args.get('id','')
                meaning=value.get('meaning')
                if not 2<=len(identifier)<=16 or not isinstance(meaning,str) or not 1<=len(meaning)<=300: raise ValueError('slang requires a 2-16 character name and 1-300 character meaning')
            if kind == 'state':
                if set(value)-{'activity','mood','mood_bias','energy','location','status','note','date','sleep','dream','health','hunger','body_cycle','weather'}: raise ValueError('unknown state field')
                if 'energy' in value and (type(value['energy']) not in (int,float) or not 0 <= value['energy'] <= 100): raise ValueError('energy must be 0-100')
                value['reality'] = 'role_state'
            value['sourceEventId'] = event.value['id']
            target = 'self' if kind == 'state' else scope
            return self.write(target,kind,args.get('id','current'),value,args['revision'])
        if operation == 'list':
            return await self.operator({'scope':scope,'kind':args['kind'],'action':'list'})
        if operation == 'read':
            return await self.operator({'scope':scope,'kind':args['kind'],**({'id':args['id']} if args.get('id') else {'action':'list'})})
        raise ValueError('unsupported companion operation')


class PlanningHost:
    """Explicit stable-planning ports; absent observations remain absent."""
    def __init__(self, runtime, scope='self'):
        self.runtime = runtime
        self.scope = scope
        diaries = runtime.db.execute("SELECT body FROM documents WHERE scope=? AND kind='diary' ORDER BY id DESC LIMIT 10",(scope,)).fetchall()
        self.data = {'daily_state':runtime.read('self','state')['value'], 'daily_weather':{}, 'bot_diaries':[json.loads(r['body']) for r in diaries], 'daily_plan':runtime.read('self','plan')['value']}
    def persona_setting(self, name, default=None): return self.runtime.settings.get(name,default)
    def _get_default_persona_prompt(self): return self.runtime.persona
    def _format_can_do_for_prompt(self): return json.dumps(self.runtime.settings.get('capabilities',[]),ensure_ascii=False)
    def _format_state_for_prompt(self, state, **kwargs): return json.dumps(state,ensure_ascii=False)
    def _recent_diary_context(self):
        from stable_companion.dreaming import recent_diary_context
        return recent_diary_context(self)
    def _format_yesterday_conversation_summary_for_prompt(self): return '暂无已确认的昨日对话摘要。'
    def _format_yesterday_screen_diary_context_for_prompt(self): return '暂无已授权的屏幕日记。'
    def _weather_summary_text(self, weather): return '天气未接入，不可当作已知事实。'
    def _format_calendar_context_for_prompt(self): return datetime.now(self.runtime.timezone).isoformat()
    def _format_schedule_adjustments_for_prompt(self): return ''
    def _format_recent_daily_plan_history_for_prompt(self): return json.dumps(self.runtime.read('self','plan')['value'],ensure_ascii=False)
    def _format_skill_growth_schedule_context(self):
        return '\n'.join(r['body'] for r in self.runtime.db.execute("SELECT body FROM documents WHERE scope='self' AND kind='skills' LIMIT 10"))
    def _format_all_user_behavior_habits_for_schedule(self): return '未配置作息习惯，不推断用户何时在线。'
    def _format_important_dates_for_prompt(self): return '个人重要日期须按当前授权会话读取，不能混入全局计划。'
    def _environment_now(self): return datetime.now(self.runtime.timezone)
    async def _memory_companion_compose_feature_context(self,**kwargs):
        if self.scope=='self': return ''
        kind,target=self.scope.split(':',1)
        from memory_companion.core.models import SessionContext
        context=SessionContext(session_id=f'cortico:{"GroupMessage" if kind=="group" else "FriendMessage"}:{target}',scope=kind,
            platform='cortico',user_id=target if kind=='private' else '',group_id=target if kind=='group' else '',bot_id=self.runtime.bot_id,persona_id='cortico')
        return await self.runtime.service.bridge_compose_context(query=kwargs.get('query',''),session_context=context,
            top_k=kwargs.get('top_k',6),max_chars=kwargs.get('max_chars',1200))
    def _task_provider(self,*values): return 'cortico'
    async def _llm_call(self,prompt,**kwargs): return await self.runtime.model({'prompt':prompt,'max_tokens':kwargs.get('max_tokens',2048)})
    def _extract_json_payload(self,text):
        import re
        text = re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
        return json.loads(text)
    def _fallback_diary_payload(self,**kwargs):
        from stable_companion.dreaming import fallback_diary_payload
        return fallback_diary_payload(self,**kwargs)
    def _extract_weighted_dream_fragments(self,payload):
        fragments = payload.get('dream_fragments',[])
        return [x for x in fragments[:6] if isinstance(x,dict) and isinstance(x.get('text'),str)]
    def _normalize_story_plan(self,payload):
        return {'long_term_events':[x for x in payload.get('long_term_events',[])[:2] if isinstance(x,dict)],'today_events':[],'proactive_events':[]}
    def _parse_hhmm_to_minutes(self,value):
        import re
        if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d|24:00',value): return None
        hour,minute=map(int,value.split(':'))
        return hour*60+minute


async def main():
    runtime = Runtime()
    tasks = set()
    async def execute(request):
        try: emit({'id':request['id'],'result':await runtime.dispatch(request['method'],request.get('arguments',{}))})
        except Exception as error:
            logging.exception('companion bridge request failed')
            emit({'id':request['id'],'error':str(error)})
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            if 'callback' in request:
                future = runtime.waiters.get(request['callback'])
                if future and not future.done():
                    if 'error' in request: future.set_exception(RuntimeError(request['error']))
                    else: future.set_result(request['result'])
            else:
                task = asyncio.create_task(execute(request))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if runtime.service and not runtime.service._closed: await runtime.service.aclose()


if __name__ == '__main__':
    asyncio.run(main())
