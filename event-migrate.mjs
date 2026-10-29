import { readFileSync, mkdirSync, writeFileSync, createReadStream } from 'node:fs';
import { resolve, join } from 'node:path';
import {createInterface} from 'node:readline';
import { fileURLToPath } from 'node:url';
import { MemoryStore, key } from './store.mjs';

export function stage(store, batch = 'events-v2', limit = 500) {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 5000 || !/^[\w-]{1,80}$/u.test(batch)) throw Error('Invalid migration batch or limit');
  store.db.exec('BEGIN IMMEDIATE');
  try {
    const rows = store.db.prepare("SELECT * FROM records WHERE state IN ('active','pending') AND metadata='{}' AND id NOT IN (SELECT recordId FROM migration_sources) ORDER BY createdAt,id LIMIT ?").all(limit);
    for (const row of rows) {
      store.db.prepare('INSERT INTO migration_sources VALUES(?,?,?)').run(row.id,batch,row.state);
      store.db.prepare("UPDATE records SET state='archived',processed=1 WHERE id=?").run(row.id);
      const chunks = [...row.text].join('').match(/[\s\S]{1,2500}/gu) ?? [];
      for (let i=0;i<chunks.length;i++) {
        const source=`migration:${batch}:${row.id}:${i}`;
        store.captureMessage({source,scope:row.scope,text:chunks[i],createdAt:row.createdAt,run:batch,speaker:'legacy'});
        const id=store.archiveEvent({source,scope:row.scope,text:chunks[i],createdAt:row.createdAt,run:`migration-${batch}`});
        const buffer=store.get(id), meta=JSON.parse(buffer.metadata);
        store.db.prepare('UPDATE records SET metadata=? WHERE id=?').run(JSON.stringify({...meta,migrationBatch:batch,legacyIds:[...new Set([...(meta.legacyIds ?? []),row.id])],timeConfidence:0}),id);
      }
      store.db.prepare('INSERT INTO audit VALUES(?,?,?,?)').run(Date.now(),'migration-stage',row.id,JSON.stringify({actor:'migration',batch,before:row,after:store.get(row.id)}));
    }
    store.db.exec('COMMIT');return {batch,staged:rows.length,pending:store.stats().pendingSummary};
  }catch(error){store.db.exec('ROLLBACK');throw error;}
}

export function rollbackMigration(store,batch) {
  store.db.exec('BEGIN IMMEDIATE');
  try {
    const rows=store.db.prepare('SELECT * FROM migration_sources WHERE batch=?').all(batch);
    if(rows.some(row=>store.get(row.recordId)?.state!=='archived')) throw Error('Migration originals have changed');
    for(const row of rows) {
      const entry=store.db.prepare("SELECT detail FROM audit WHERE recordId=? AND operation='migration-stage' ORDER BY rowid DESC LIMIT 1").get(row.recordId);
      const previous=JSON.parse(entry.detail).before;
      store.db.prepare('UPDATE records SET state=?,processed=? WHERE id=?').run(previous.state,previous.processed,row.recordId);
    }
    store.db.prepare("UPDATE records SET state='rolled_back' WHERE json_extract(metadata,'$.migrationBatch')=?").run(batch);
    store.db.prepare('INSERT INTO audit VALUES(?,?,?,?)').run(Date.now(),'migration-rollback',batch,JSON.stringify({actor:'migration',batch,count:rows.length}));
    store.db.exec('COMMIT');return {restored:rows.length};
  }catch(error){store.db.exec('ROLLBACK');throw error;}
}

export function applyCandidates(store,jsonl,threshold=8) {
  const rows=jsonl.split(/\r?\n/u).filter(Boolean).map(line=>JSON.parse(line));
  store.db.exec('SAVEPOINT migration_candidates');
  try {
    const ids=rows.map(row=>store.remember(row,[store.get((row.sourceIds ?? [row.sourceId])[0])?.scope],threshold));
    store.db.exec('RELEASE migration_candidates');return {ids};
  }catch(error){store.db.exec('ROLLBACK TO migration_candidates; RELEASE migration_candidates');throw error;}
}

if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const [command,file,...args]=process.argv.slice(2);
  if(!file || !['status','stage','rollback','export','apply','import'].includes(command)) throw Error('Usage: node event-migrate.mjs status|stage|rollback|export|apply|import DB [args]');
  const store=new MemoryStore(resolve(file));
  try {
    let result;
    if(command==='status') result=store.stats();
    if(command==='stage') result=stage(store,args[0] ?? 'events-v2',Number(args[1] ?? 500));
    if(command==='rollback') result=rollbackMigration(store,args[0] ?? 'events-v2');
    if(command==='import') {
      const lines=createInterface({input:createReadStream(resolve(args[0]),{encoding:'utf8'}),crlfDelay:Infinity});
      let count=0;store.db.exec('BEGIN IMMEDIATE');
      try {for await(const line of lines)if(line.trim())count+=store.importAll(line).count;store.db.exec('COMMIT');result={count};}
      catch(error){store.db.exec('ROLLBACK');throw error;}
      finally{lines.close();}
    }
    if(command==='apply') result=applyCandidates(store,readFileSync(resolve(args[0]),'utf8'),Number(args[1] ?? 8));
    if(command==='export') {
      const output=resolve(args[0] ?? join('D:/DownLoad','vanilla-memory'));
      mkdirSync(output,{recursive:true});
      const data=store.exportAll(args[1]==='approved');
      writeFileSync(join(output,'all.md'),data.md);writeFileSync(join(output,'all.jsonl'),data.jsonl);
      result={count:data.count,output};
    }
    console.log(JSON.stringify(result));
  }finally{store.close();}
}
