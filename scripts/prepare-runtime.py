"""Prepare code-only sources and an isolated Python runtime; never edit a deployment."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--companion', type=Path, required=True, help='Cortico-Private-Companion checkout')
    parser.add_argument('--content', type=Path, help='optional Cortico-Content-Companion checkout')
    parser.add_argument('--memewiki', type=Path, help='optional Cortico-MemeWiki checkout')
    parser.add_argument('--output', type=Path, help='new isolated runtime directory')
    parser.add_argument('--sources-only', action='store_true', help='copy sources without creating a venv or installing dependencies')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error('Python 3.12 or newer is required')
    root = Path(__file__).resolve().parents[1]
    output = (args.output or root / '.runtime').resolve()
    if output.exists():
        parser.error('Refuse to overwrite an existing runtime; select a new --output directory')
    selected = {
        'astrbot_plugin_memory_companion': root / 'vendor/astrbot_plugin_memory_companion',
        'astrbot_plugin_private_companion_6_7_0': args.companion.resolve() / 'vendor/astrbot_plugin_private_companion_6_7_0',
    }
    for checkout, name in [(args.content, 'astrbot_plugin_content_companion'), (args.memewiki, 'astrbot_plugin_memewiki')]:
        if checkout:
            selected[name] = checkout.resolve() / 'vendor' / name
    for name, source in selected.items():
        if not (source / 'main.py').is_file():
            parser.error('Missing original source: ' + name)
    sdk = root / 'vendor/astrbot-runtime'
    if not (sdk / 'pyproject.toml').is_file():
        parser.error('Missing vendored AstrBot SDK')
    if any(output == source or output.is_relative_to(source) for source in [root / 'vendor', *selected.values()]):
        parser.error('Runtime output must be outside vendored sources')
    for name, source in selected.items():
        shutil.copytree(source, output / 'sources' / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))
    if args.sources_only:
        python = Path(sys.executable)
    else:
        subprocess.run([sys.executable, '-m', 'venv', str(output / 'python')], check=True)
        python = output / 'python' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        subprocess.run([str(python), '-m', 'pip', 'install', str(sdk)], check=True)
    print(json.dumps({'astrbotCompanion': {'enabled': False, 'nativeEnabled': True,
        'sourcesDir': str(output / 'sources'), 'pythonFile': str(python), 'nativePort': 7790,
        'localEmbeddingEnabled': False}, 'note': 'sources-only does not verify Python dependencies' if args.sources_only else 'Review this configuration and apply it only to your own test deployment.'}, indent=2))

if __name__ == '__main__':
    main()
