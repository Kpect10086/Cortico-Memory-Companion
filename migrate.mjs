import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { MemoryStore, key } from './store.mjs';

/** @param {string} deployment */
export function migrate(deployment) {
  const data = join(deployment, 'data');
  const store = new MemoryStore(join(data, 'vanilla-memory.db'));
  /** @param {string} stem */
  const json = stem => { const file = join(data, stem + '.json'); return existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {}; };
  /** @param {unknown} n */
  const time = n => { const t = Number(n); return Number.isFinite(t) && t > 0 ? Math.round(t < 1e12 ? t * 1000 : t) : Date.now(); };
  const before = store.stats().total;
  store.db.exec('BEGIN IMMEDIATE');
  try {
    for (const [scope, rows] of Object.entries(json('fact-store').scopes ?? {})) for (const row of rows) {
      store.put({ id: key(`legacy:fact:${scope}:${row.hash ?? row.text}`), scope, text: row.text, source: `legacy:fact-store.json:${scope}:${row.hash}`, createdAt: time(row.createdAt) });
    }
    for (const [scope, rows] of Object.entries(json('vector-memory').vectors ?? {})) for (const row of rows) {
      store.put({ id: key(`legacy:vector:${scope}:${row.text}`), scope, text: row.text, source: `legacy:vector-memory.json:${scope}`, createdAt: time(row.timestamp) });
    }
    const short = json('memory-data');
    for (const [scope, rows] of Object.entries(short.notes ?? {})) for (const row of rows) {
      store.put({ id: key(`legacy:note:${scope}:${row.text}`), scope, text: row.text, kind: scope === 'main' ? 'core' : 'preference', state:'pending', importance: 9, reason: '原记忆插件中明确保留的笔记，迁移保留原文', source: `legacy:memory-data.json:notes:${scope}`, createdAt: time(row.ts) });
    }
    for (const section of ['summary', 'topic', 'store']) for (const [scope, content] of Object.entries(short[section] ?? {})) {
      store.put({ scope, text: typeof content === 'string' ? content : JSON.stringify(content), source: `legacy:memory-data.json:${section}:${scope}` });
    }
    const workspace = join(deployment, 'workspace');
    /** @param {string} directory */
    const walk = (directory, relative = '') => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        if (entry.name.startsWith('.') || entry.name === 'blobs' || entry.isSymbolicLink()) continue;
        const rel = relative ? relative + '/' + entry.name : entry.name;
        const file = join(directory, entry.name);
        if (entry.isDirectory()) walk(file, rel);
        else if (entry.name.endsWith('.md') && entry.name !== 'CONSTITUTION.md') {
          const text = readFileSync(file, 'utf8');
          let line = 1;
          for (const part of text.split(/\n\s*\n/)) {
            if (part.trim()) store.put({ id: key(`workspace:${rel}:${part}`), scope: 'workspace', text: part, source: `workspace:${rel}:line${line}`, createdAt: Math.round(statSync(file).mtimeMs) });
            line += part.split('\n').length + 1;
          }
        }
      }
    };
    if (existsSync(workspace)) walk(workspace);
    store.db.exec('COMMIT');
    const result = { added: store.stats().total - before, ...store.stats() };
    store.close();
    return result;
  } catch (error) { store.db.exec('ROLLBACK'); store.close(); throw error; }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log(JSON.stringify(migrate(resolve(process.argv[2])), null, 2));
