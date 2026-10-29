import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { MemoryStore, chars, eventScopes, key, isMemoryEvent } from './store.mjs';

const folder = mkdtempSync(join(tmpdir(), 'vanilla-memory-'));
let store,reopened;
try {
  const file = join(folder, 'test.db');
  store = new MemoryStore(file);
  assert.deepEqual(eventScopes({ source: 'qqbot', senderKey: 'private:1234', meta: { conv: { kind: 'private', id: 1234 } } }), ['private:1234', 'qq:1234']);
  assert.deepEqual(eventScopes({ source: 'qqbot', senderKey: 'group:5678', meta: { conv: { kind: 'group', id: 5678 }, user: 1234 } }), ['group:5678']);
  const id = store.put({ scope: 'private:A', text: '昨天喝了拿铁，今天已经改喝红茶', kind: 'raw', source: 'event:1', processed: 0 });
  assert.equal(store.put({ scope: 'private:A', text: '昨天喝了拿铁，今天已经改喝红茶', kind: 'raw', source: 'event:1', processed: 0 }), id);
  assert.equal(store.stats().total, 1);
  for(const n of [1,2]) {store.captureMessage({source:`fixture-${n}`,scope:'private:A',text:'来源补充',createdAt:Date.now()});store.db.prepare('INSERT INTO event_sources VALUES(?,?)').run(`fixture-${n}`,id);} 
  assert.equal(store.search('拿铁', ['private:A']).length, 0);
  assert.equal(store.search('拿铁', ['private:B']).length, 0);
  assert.throws(() => store.remember({ text: '喜欢拿铁', sourceId: id, importance: 5, reason: '偏好', kind: 'preference' }, ['private:B']));
  assert.throws(() => store.remember({ text: '喜欢拿铁', sourceId: id, importance: 5, reason: '', kind: 'preference' }, ['private:A']));
  const draft = store.remember({ text: '承诺2026-11-01完成任务', sourceId: id, sourceMessageIds: ['fixture-1','fixture-2'], importance: 9, reason: '遗漏会失约', kind: 'commitment' }, ['private:A']);
  assert.equal(store.get(draft).state, 'pending');
  assert(!store.pack(['private:A'], '').text.includes('承诺2026-11-01完成任务'));
  store.review(draft, 'active', '创作者确认');
  assert(store.pack(['private:A'], '').text.includes('承诺2026-11-01完成任务'));
  assert(!store.pack(['private:B'], '').text.includes('承诺2026-11-01完成任务'));
  const revision = key(JSON.stringify(store.get(draft)));
  const corrected = store.correct(draft, '香草承诺2026-11-08完成任务', 6, '纠正期限', revision);
  assert.equal(store.get(draft).state, 'superseded');
  assert.equal(store.get(corrected).source, draft);
  assert.equal(store.get(corrected).importance, 6);
  assert.equal(store.get(corrected).createdAt, store.get(draft).createdAt);
  assert.equal(store.get(corrected).state,'pending');store.review(corrected,'active','确认纠错',key(JSON.stringify(store.get(corrected))));
  assert(!store.search('2026-11-01完成任务', ['private:A']).some(row => row.id === draft));
  assert(store.pack(['private:A'], '').text.includes('2026-11-08完成任务'));
  const beforeConflict = store.stats().total;
  assert.throws(() => store.correct(draft, '不能覆盖新版本', 5, '旧页面', revision), /刷新/);
  assert.equal(store.stats().total, beforeConflict);
  assert.throws(() => store.correct(id, '不能改写证据', 5, '证据不可变', key(JSON.stringify(store.get(id)))), /原始资料/);
  const currentRevision = key(JSON.stringify(store.get(corrected)));
  store.db.exec("CREATE TEMP TRIGGER reject_audit BEFORE INSERT ON audit WHEN NEW.operation='operator-correct' BEGIN SELECT RAISE(ABORT,'audit failure'); END");
  assert.throws(() => store.correct(corrected, '应回滚', 5, '模拟写入失败', currentRevision), /audit failure/);
  assert.equal(store.stats().total, beforeConflict);
  assert.equal(store.get(corrected).state, 'active');
  store.db.exec('DROP TRIGGER reject_audit');
  store.review(corrected, 'rejected', '暂时停用', currentRevision);
  assert(!store.pack(['private:A'], '').text.includes('2026-11-08完成任务'));
  assert.throws(() => store.review(corrected, 'active', '过期页面', currentRevision), /刷新/);
  store.review(corrected, 'active', '恢复记忆', key(JSON.stringify(store.get(corrected))));
  assert(store.pack(['private:A'], '').text.includes('2026-11-08完成任务'));
  const status = store.put({scope:'private:A',text:'[演出状态] 安静',kind:'raw',source:'event:status',processed:0});
  assert(!store.pendingEvents().some(row => row.id === status));
  assert(!store.search('安静', ['private:A']).some(row => row.id === status));
  assert(store.get(status), '旧证据仍保留');
  assert.equal(isMemoryEvent({origin:'external',source:'vtuber',type:'vtuber.status',text:'[演出状态] 安静'}), false);
  assert.equal(isMemoryEvent({origin:'external',source:'streamdirector',text:'[导演状态]'}), false);
  assert.equal(isMemoryEvent({origin:'external',source:'asr',text:'我喜欢红茶'}), true);
  store.review(id, 'rejected', '无关原始资料');
  assert(!store.pendingEvents().some(row => row.id === id));
  assert.throws(() => store.remember({text:'无效来源',sourceId:id,importance:3,reason:'已停用',kind:'fact'},['private:A']));
  const now = Date.now();
  store.put({ scope: 'private:A', text: '过期近期细节', kind: 'recent', importance: 2, source: 'event:old', createdAt: now - 8 * 86400000 });
  assert(!store.pack(['private:A'], '', {}, now).text.includes('过期近期细节'));
  assert(store.search('过期', ['private:A']).length);
  store.put({ scope: 'main', text: '不要改变身份😀', kind: 'core', importance: 10, source: 'operator' });
  store.put({ scope: 'private:A', text: '私聊核心约定', kind: 'core', importance: 10, source: 'operator' });
  assert(!store.pack(['private:B'], '私聊核心约定').text.includes('私聊核心约定'));
  const old = store.put({ scope: 'private:A', text: '八天前的偏好', kind: 'raw', source: 'event:earlier', createdAt: now - 8 * 86400000 });
  const oldMemory = store.remember({ text: '旧偏好应保留事件日期', sourceId: old, importance: 8, reason: '日期依据原事件', kind: 'preference' }, ['private:A']);
  assert.equal(store.get(oldMemory).createdAt, store.get(old).createdAt);
  store.put({ scope: 'private:A', text: '拿铁'.repeat(1000), kind: 'archive', source: 'event:big' });
  const pack = store.pack(['private:A'], '拿铁', { maxChars: 1600, coreChars: 600, recentChars: 150, recallChars: 200 });
  assert(chars(pack.text) <= 1600);
  assert(pack.text.includes('不要改变身份😀'));
  assert.throws(() => store.pack(['private:A'], '', { coreChars: 1 }));
  store.close();
  reopened = new MemoryStore(file);
  assert.equal(reopened.get(id).source, 'event:1');
  assert.equal(reopened.get(corrected).text, '香草承诺2026-11-08完成任务');
  assert.equal(reopened.db.prepare("SELECT count(*) AS n FROM audit WHERE operation='operator-correct'").get().n, 1);
  assert.equal(reopened.db.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
  reopened.close();
  const tiers = new MemoryStore(join(folder, 'tiers.db'));
  try {
    const evidence = tiers.put({ scope: 'main', text: '有来源的记忆事件', kind: 'raw', source: 'event:tiers' });
    for(const n of [1,2])tiers.db.prepare('INSERT INTO event_sources VALUES(?,?)').run(`tier-source-${n}`,evidence);
    const candidate = importance => ({ text: `档位事件${importance}`, sourceId: evidence, sourceMessageIds: ['tier-source-1','tier-source-2'], importance, reason: '用户人生中影响重大且持续的事件候选', kind: 'fact' });
    for (let importance = 1; importance <= 9; importance++) {
      const regular = tiers.remember(candidate(importance), ['main']);
      assert.equal(tiers.get(regular).state, 'pending');tiers.review(regular,'active','人工确认',key(JSON.stringify(tiers.get(regular))));
    }
    for (let importance = 10; importance <= 12; importance++) {
      const high = tiers.remember(candidate(importance), ['main']);
      assert.equal(tiers.get(high).importance, importance);
      assert.equal(tiers.get(high).state, 'pending');
      assert(!tiers.pack(['main'], '档位事件').entries.some(row => row.id === high));
      assert(!tiers.search('档位事件', ['main'], 30).some(row => row.id === high));
      tiers.review(high, 'active', '用户确认重大影响及档位', key(JSON.stringify(tiers.get(high))));
      assert(tiers.pack(['main'], '档位事件').entries.some(row => row.id === high));
    }
    const regular = tiers.get(tiers.search('档位事件9', ['main'], 30).find(row => row.kind === 'fact' && row.importance === 9).id);
    const chosen = tiers.correct(regular.id, '用户选定的重大事件', 12, '用户主动选择12档', key(JSON.stringify(regular)));
    assert.equal(tiers.get(chosen).importance, 12);
    assert.equal(tiers.get(chosen).state, 'pending');tiers.review(chosen,'active','人工确认选档',key(JSON.stringify(tiers.get(chosen))));
    assert.equal(tiers.get(regular.id).state, 'superseded');
    for (const importance of [0, 13, 1.5, NaN, Infinity, '12', null]) {
      const count = tiers.stats().total;
      assert.throws(() => tiers.remember(candidate(importance), ['main']), /integer in 1\.\.12/);
      assert.throws(() => tiers.correct(chosen, '无效档位', importance, '应拒绝', key(JSON.stringify(tiers.get(chosen)))), /integer in 1\.\.12/);
      assert.equal(tiers.stats().total, count);
      assert.equal(tiers.get(chosen).state, 'active');
    }
  } finally { tiers.close(); }
  console.log('PASS: scope isolation, evidence, review/correction/restore, conflict protection, atomic rollback, technical-event exclusion, expiry, deduplication, Unicode budget and recovery');
  console.log('PASS: integer tiers 1..12, routine 1..9, exceptional candidates hidden until operator review, operator promotion and invalid-tier atomic rejection');
} finally {
  store?.close();reopened?.close();
  const target = resolve(folder);
  assert(target.startsWith(resolve(tmpdir()) + '\\') || target.startsWith(resolve(tmpdir()) + '/'));
  rmSync(target, { recursive: true, force: true });
}

await import('./event-self-check.mjs');
