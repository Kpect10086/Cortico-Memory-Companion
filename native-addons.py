"""Cortico adapters for the original ContentCompanion and MemeWiki plugins."""
from __future__ import annotations
import asyncio,base64,hashlib,json,math,time
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit


class Addons:
    names={'content':'astrbot_plugin_content_companion','memewiki':'astrbot_plugin_memewiki'}
    def __init__(self,context,plugins,root,state,callback,settings):
        self.context=context;self.root=root;self.state=state;self.callback=callback;self.settings=settings
        self.plugins={p.__class__.__module__.split('.')[-2]:p for p in plugins}
        self.requested=dict(settings.get('addons',{}));self.companion_enabled=settings.get('companionEnabled',True)
        self.schemas={key:json.loads((root/name/'_conf_schema.json').read_text(encoding='utf-8')) for key,name in self.names.items() if name in self.plugins}
        self.content_original_enabled=True

    async def prepare(self):
        pc=self.plugins['astrbot_plugin_private_companion']
        original_request=pc._qzone_request
        async def guarded_request(event,method,url,**kwargs):
            host=urlsplit(url).hostname or ''
            if not (host=='qq.com' or host.endswith('.qq.com')) or not url.startswith('https://'):raise ValueError('Invalid original Qzone endpoint')
            await self.callback('qzone_permission',{})
            return await original_request(event,method,url,**kwargs)
        pc._qzone_request=guarded_request
        pc._qzone_platform_supported=lambda event=None:True
        async def publish(event=None,*,text='',images=None):
            from types import SimpleNamespace
            await self.callback('qzone_permission',{})
            encoded=[];seen=set()
            for source in list(images or [])[:12]:
                image,filename,mime=await pc._qzone_load_image_bytes(event,source,cookie_header='')
                pc._qzone_validate_image_bytes(image,filename=filename)
                digest=hashlib.sha256(image).hexdigest()
                if digest in seen:continue
                seen.add(digest);encoded.append('data:'+mime+';base64,'+base64.b64encode(image).decode())
                if len(encoded)>=9:break
            receipt=await self.callback('qzone_publish',{'text':str(text or '')[:300],'images':encoded})
            if not receipt.get('tid') or not str(receipt.get('uin','')).isdigit():raise RuntimeError('QQ did not confirm Qzone publication')
            return SimpleNamespace(tid=receipt['tid'],uin=int(receipt['uin']),name=receipt['uin'],text=receipt['text'],images=receipt['images'],create_time=int(time.time()),status='approved')
        pc._qzone_publish_post=publish
        for key,enabled in self.requested.items():
            name=self.names[key];plugin=self.plugins[name]
            from astrbot.core.star.star import star_map
            star_map[plugin.__class__.__module__].activated=bool(enabled)
            if key=='content':
                self.content_original_enabled=plugin.enabled
                plugin.enabled=bool(enabled and plugin.enabled and self.companion_enabled)
            else:
                async def search(event,query,_plugin=plugin):
                    text=await self.callback('web_search',{'query':query})
                    return _plugin._humanize_search(str(text or ''),900)
                plugin._astrbot_search=search
                plugin._astrbot_search_ready=lambda:(bool(self.settings.get('webSearchEnabled')),'Cortico WebSearch' if self.settings.get('webSearchEnabled') else 'Cortico WebSearch 未启用')

    def bind_content_storage(self):
        content=self.plugins.get(self.names['content'])
        if content is None:return
        pc=self.plugins['astrbot_plugin_private_companion'];host=content.host
        if pc.page_api is not None:pc._qzone_summary=pc.page_api._qzone_summary
        # Both original entrypoints share one project list; Content owns its durable copy.
        pc.data['creative_projects']=host.data['creative_projects']
        original_pc_save=pc._save_data_sync;original_content_save=host._save_data_sync
        def content_save(*args,**kwargs):
            original_content_save(*args,**kwargs)
            pc.data['creative_projects']=host.data['creative_projects']
        def pc_save(*args,**kwargs):
            projects=pc.data.get('creative_projects')
            if isinstance(projects,list):
                host.data['creative_projects']=projects
                original_content_save()
            if not args and not kwargs:kwargs={'sections':['creative_projects']}
            return original_pc_save(*args,**kwargs)
        host._save_data_sync=content_save;pc._save_data_sync=pc_save
        pc._save_creative_state_sync=lambda:pc._save_data_sync(sections=['creative_projects'])
        content.extension_api._owner=lambda owner:owner if owner is not None else pc
        self._sync_content_runtime()

    def _sync_content_runtime(self):
        content=self.plugins.get(self.names['content'])
        if content is None:return
        pc=self.plugins['astrbot_plugin_private_companion'];module=__import__(content.__class__.__module__,fromlist=['_CREATIVE_RUNTIME_ATTRIBUTES'])
        creative=content.config.get('creative',{})
        from data.plugins.astrbot_plugin_private_companion.helpers import _set_into_config
        for key,attribute in module._CREATIVE_RUNTIME_ATTRIBUTES.items():
            if key in creative:
                value=creative[key];setattr(pc,attribute,value);_set_into_config(pc.config,key,value)
        content._apply_qzone_config(pc)
        pc.config.save_config()

    async def after_write(self,path):
        content=self.plugins.get(self.names['content'])
        if content is None or not path.startswith('/astrbot_plugin_private_companion/'):return
        pc=self.plugins['astrbot_plugin_private_companion'];module=__import__(content.__class__.__module__,fromlist=['_CREATIVE_RUNTIME_ATTRIBUTES'])
        creative=content.config.setdefault('creative',{});changed=False
        for key,attribute in module._CREATIVE_RUNTIME_ATTRIBUTES.items():
            value=getattr(pc,attribute,creative.get(key))
            if value!=creative.get(key):creative[key]=value;changed=True
        qzone=content.config.setdefault('qzone',{})
        from data.plugins.astrbot_plugin_private_companion.helpers import _flat_get
        for key,attribute in module._QZONE_RUNTIME_ATTRIBUTES.items():
            # The settings response can refresh stale extension state before this hook.
            value=_flat_get(pc.config,'QZONE_COOKIE' if key=='cookie' else attribute,getattr(pc,attribute,qzone.get(key)))
            if value!=qzone.get(key):qzone[key]=value;changed=True
        if changed:
            content.config.save_config();content.host._sync_config();content._apply_qzone_config(pc)

    def status(self):
        return {key:{'installed':True,'enabled':bool(self.requested.get(key)),
            **({'service':self.plugins[name].extension_api.status()} if key=='content' else {'entries':self.plugins[name]._db_count(self.plugins[name]._readable_db_path())})}
            for key,name in self.names.items() if name in self.plugins}

    async def activate_content(self,enabled):
        self.companion_enabled=enabled
        content=self.plugins.get(self.names['content'])
        if content is not None:content.enabled=bool(enabled and self.requested.get('content') and self.content_original_enabled)

    async def activate(self,key,enabled):
        if key not in self.schemas:raise ValueError('Unknown original addon')
        from astrbot.core.star.star import star_map
        plugin=self.plugins[self.names[key]];was=bool(self.requested.get(key));self.requested[key]=enabled
        star_map[plugin.__class__.__module__].activated=enabled
        if key=='content':await self.activate_content(self.companion_enabled)
        elif was!=enabled:
            if enabled:await plugin.initialize()
            else:
                await plugin.terminate()
                if plugin._sync_task:await asyncio.gather(plugin._sync_task,return_exceptions=True)
                plugin._sync_task=None
        return {'enabled':enabled}

    def fields(self,key):
        def walk(schema,prefix=''):
            for name,item in schema.items():
                path=prefix+name
                if item.get('type')=='object':yield from walk(item.get('items',{}),path+'.')
                else:yield path,item
        return dict(walk(self.schemas[key]))

    def config(self,key):
        if key not in self.schemas:raise ValueError('Unknown original addon')
        cfg=self.context.cortico_configs[self.names[key]]
        encoded=json.dumps(cfg,sort_keys=True,ensure_ascii=False)
        values={}
        for path,item in self.fields(key).items():
            value=cfg
            for part in path.split('.'):
                value=value.get(part,item.get('default')) if isinstance(value,dict) else item.get('default')
            values[path]=value
        return {'schema':self.schemas[key],'values':values,'revision':hashlib.sha256(encoded.encode()).hexdigest()}

    async def save_config(self,key,payload):
        from quart import jsonify
        current=self.config(key)
        if payload.get('revision')!=current['revision']:return jsonify({'error':'配置已变化，请刷新后重试。'}),409
        values=payload.get('values');fields=self.fields(key)
        if not isinstance(values,dict) or set(values)-fields.keys():return jsonify({'error':'未知配置字段。'}),400
        cfg=self.context.cortico_configs[self.names[key]];updated=deepcopy(dict(cfg))
        for path,value in values.items():
            item=fields[path];kind=item['type']
            valid=(type(value) is bool if kind=='bool' else type(value) is int if kind=='int' else type(value) in (int,float) and math.isfinite(value) if kind=='float' else isinstance(value,str) and len(value)<=65536)
            if not valid or item.get('options') and value not in item['options']:return jsonify({'error':'配置类型或选项错误：'+path}),400
            target=updated;parts=path.split('.')
            for part in parts[:-1]:target=target.setdefault(part,{})
            target[parts[-1]]=value
        cfg.clear();cfg.update(updated);cfg.save_config()
        plugin=self.plugins[self.names[key]]
        if key=='memewiki':
            if self.requested.get(key):
                await plugin.terminate()
                if plugin._sync_task:await asyncio.gather(plugin._sync_task,return_exceptions=True)
            plugin._sync_task=None;plugin.config=dict(cfg)
            if self.requested.get(key):await plugin.initialize()
        else:
            self.content_original_enabled=bool(cfg.get('enabled',True));plugin.host._sync_config()
            self._sync_content_runtime();await self.activate_content(self.companion_enabled)
        return jsonify({'saved':True,**self.config(key)})
