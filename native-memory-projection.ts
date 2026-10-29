import {MemoryStore,key} from './store.mjs';

export const NATIVE_SOURCE_COLUMNS='id,scope,text,kind,state,importance,createdAt,metadata,(SELECT MAX(rowid) FROM audit WHERE recordId=records.id) AS hostRevision';
export const canonicalSourceHash=(row:Record<string,unknown>)=>key('{'+Object.keys(row).sort().map(name=>JSON.stringify(name)+': '+JSON.stringify(row[name])).join(', ')+'}');
export const sourceBodyHash=(row:Record<string,unknown>)=>canonicalSourceHash(Object.fromEntries(Object.entries(row).filter(([name])=>!['state','hostRevision'].includes(name))));

export async function scopedNativeHistory(store:MemoryStore,target:string,safeMemory:(text:string)=>Promise<string>){
  const scopes=target==='private:operator'?['main','console','terminal']:[target];
  const rows=store.db.prepare(`SELECT text,speaker,receivedAt FROM raw_messages WHERE scope IN (${scopes.map(()=>'?').join(',')}) ORDER BY receivedAt DESC LIMIT 40`).all(...scopes).reverse() as Array<{text:string;speaker:string;receivedAt:number}>;
  const history=await Promise.all(rows.map(async row=>({role:row.speaker.endsWith(':self')?'assistant':'user',content:`[旧库原始记录；说话人标识 ${row.speaker||'未知'}；记录时间 ${new Date(row.receivedAt).toISOString()}，不据此推定事件发生时间]\n${await safeMemory(row.text)}`})));
  let budget=18000;return history.reverse().filter(item=>{budget-=item.content.length;return budget>=0;}).reverse();
}

export function synchronizeLegacyProjection(store:MemoryStore,changes:Array<{id:string;nativeId:string;state:string;fingerprint:string;bodyHash:string}>,threshold:number){
  const conflicts:string[]=[];let applied=0;
  for(const change of changes){
    if(!change||change.nativeId!=='cortico_'+change.id||!['active','archived'].includes(change.state))throw Error('Invalid native memory projection change');
    const row=store.db.prepare(`SELECT ${NATIVE_SOURCE_COLUMNS} FROM records WHERE id=?`).get(change.id) as Record<string,any>|undefined;
    if(!row||['raw','archive'].includes(row.kind))continue;
    if(row.state===change.state)continue;
    if(change.state==='archived'){
      if(row.state!=='active')continue;
      if(canonicalSourceHash(row)!==change.fingerprint){conflicts.push(change.id);continue;}
    }else{
      const last=store.db.prepare('SELECT detail FROM audit WHERE recordId=? ORDER BY rowid DESC LIMIT 1').get(change.id) as {detail:string}|undefined;
      if(row.state!=='archived'||!last||JSON.parse(last.detail).actor!=='astrbot-memory'||sourceBodyHash(row)!==change.bodyHash){conflicts.push(change.id);continue;}
    }
    store.review(change.id,change.state,'原版 MemoryCompanion 同步遗忘或恢复；原文与审计保留。',undefined,threshold,'astrbot-memory');applied++;
  }
  return {applied,conflicts};
}
