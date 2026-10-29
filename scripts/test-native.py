"""Offline original-plugin acceptance using a fresh temporary data root."""
import argparse
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile

async def verify(sources):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('cortico_native_acceptance', root / 'native-host.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    async def blocked(kind, arguments):
        calls.append(kind)
        raise RuntimeError('External operations are blocked in offline acceptance')
    with tempfile.TemporaryDirectory(prefix='cortico-port-test-') as temporary:
        context, plugins = await module.create_host(sources, Path(temporary), blocked,
            {'addons': {'content': True, 'memewiki': True}, 'privateTargets': [], 'groupTargets': [],
             'localEmbeddingEnabled': False, 'activeProvider': 'fixture',
             'providers': [{'id': 'fixture', 'model': 'fixture-model', 'modalities': ['text']}]})
        try:
            app = module.make_app(context, plugins, sources, 'offline-test-key')
            client = app.test_client()
            assert (await client.get('/plugins/companion/')).status_code == 401
            assert (await client.get('/_launch?key=offline-test-key&plugin=companion')).status_code == 302
            pages = ['/plugins/companion/', '/plugins/memory/', '/plugins/memewiki/',
                     '/_configuration/content', '/_configuration/memewiki',
                     '/astrbot_plugin_private_companion/page/overview']
            for page in pages:
                response = await client.get(page)
                assert response.status_code == 200, (page, response.status_code)
            denied = await client.post('/_configuration/content', json={'enabled': False})
            assert denied.status_code == 403
            pc = next(plugin for plugin in plugins if plugin.__class__.__name__ == 'PrivateCompanionPlugin')
            content = next(plugin for plugin in plugins if plugin.__class__.__name__ == 'ContentCompanionPlugin')
            for enabled in [True, False]:
                response = await client.post('/astrbot_plugin_private_companion/page/settings/update',
                    json={'settings': {'enable_qzone_life_publish': enabled}},
                    headers={'Origin': 'http://localhost'})
                result = await response.get_json()
                assert response.status_code == 200 and result.get('success'), result
                assert content.config['qzone']['life_publish_enabled'] is enabled
                assert pc.enable_qzone_life_publish is enabled
            assert len(plugins) == 4
            tools = context.get_llm_tool_manager().func_list
            names = [tool.name for tool in tools if getattr(tool, 'handler_module_path', '').startswith('data.plugins.')]
            assert len(names) == len(set(names))
            assert 'search_meme_wiki' in names and 'content_companion_view_work' in names
            print({'originalPlugins': len(plugins), 'registeredRoutes': len(context.registered_web_apis),
                   'nativeTools': len(names), 'authenticatedPages': len(pages),
                   'unauthenticatedDenied': True, 'crossOriginWriteDenied': True,
                   'lifeSettingRoundTrip': True,
                   'externalOperationsExecuted': 0, 'blockedCallbackAttempts': len(calls)})
        finally:
            for plugin in reversed(plugins):
                await plugin.terminate()
            from astrbot.core import db_helper
            await db_helper.engine.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(verify(arguments.sources.resolve()))
