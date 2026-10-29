const chars = text => [...text].length;

const segmenter = new Intl.Segmenter('zh', {granularity:'word'});
const pattern = text => '%' + text.replace(/[\\%_]/g, '\\$&') + '%';

export function lookup(store, query, scopes, {view='memories',from=null,to=null,offset=0,limit=20,now=Date.now()}={}) {
  if(typeof query!=='string' || !query.trim() || chars(query)>300)throw Error('Query must contain 1..300 characters');
  if(!Array.isArray(scopes) || !scopes.length || scopes.length>128 || scopes.some(s=>typeof s!=='string' || !s.trim() || s.length>300))throw Error('Invalid search scopes');
  if(!['memories','sources'].includes(view) || !Number.isSafeInteger(offset) || offset<0 || !Number.isInteger(limit) || limit<1 || limit>30 || !Number.isFinite(now))throw Error('Invalid search bounds');
  for(const date of [from,to])if(date!==null && (typeof date!=='string' || !/T.*(?:Z|[+-]\d{2}:\d{2})$/u.test(date) || !Number.isFinite(Date.parse(date))))throw Error('Invalid search time');
  if(from && to && Date.parse(from)>Date.parse(to))throw Error('Invalid search time range');
  const allowed=view==='memories'?store.allowed(scopes):{sql:`scope IN (${scopes.map(()=>'?').join(',')})`,args:scopes};
  let eligible=`state='active' AND ${view==='memories'?"kind NOT IN ('raw','archive')":"kind='raw'"} AND ${allowed.sql} AND (json_extract(metadata,'$.effectiveAt') IS NULL OR julianday(json_extract(metadata,'$.effectiveAt'))<=julianday(?,'unixepoch'))`;
  const args=[...allowed.args,now/1000];
  if(from){eligible+=' AND createdAt>=?';args.push(Date.parse(from));}
  if(to){eligible+=' AND createdAt<=?';args.push(Date.parse(to));}
  const words=[...new Set([...segmenter.segment(query.toLowerCase())].filter(s=>s.isWordLike).map(s=>s.segment))].slice(0,16);
  const match=words.map(w=>`"${w.replaceAll('"','""')}"`).join(' OR ');
  const literals=view==='sources'?[query.trim()]:[...new Set([query.trim(),...words])];
  const literal=`(${literals.map(()=>"text LIKE ? ESCAPE '\\'").join(' OR ')})`,patterns=literals.map(pattern);
  const useFts=view==='memories' && words.length>0;
  const ftsCount=useFts?Number(store.db.prepare(`SELECT count(*) AS n FROM search JOIN records ON search.rowid=records.rowid WHERE search MATCH ? AND ${eligible}`).get(match,...args).n):0;
  const rows=useFts && offset<ftsCount?store.db.prepare(`SELECT records.*,bm25(search) AS relevance FROM search JOIN records ON search.rowid=records.rowid WHERE search MATCH ? AND ${eligible} ORDER BY relevance,importance DESC,createdAt DESC,id LIMIT ? OFFSET ?`).all(match,...args,limit,offset):[];
  const exclude=useFts?' AND rowid NOT IN (SELECT rowid FROM search WHERE search MATCH ?)':'';
  const fallbackArgs=[...args,...(useFts?[match]:[]),...patterns];
  const fallbackCount=Number(store.db.prepare(`SELECT count(*) AS n FROM records WHERE ${eligible}${exclude} AND ${literal}`).get(...fallbackArgs).n);
  if(rows.length<limit){
    const order=view==='memories'?'importance DESC,createdAt DESC,id':'createdAt DESC,id';
    rows.push(...store.db.prepare(`SELECT *,NULL AS relevance FROM records WHERE ${eligible}${exclude} AND ${literal} ORDER BY ${order} LIMIT ? OFFSET ?`).all(...fallbackArgs,limit-rows.length,Math.max(0,offset-ftsCount)));
  }
  for(const row of rows)if(view==='sources'){
    row.sourceMessageIds=store.db.prepare('SELECT source FROM event_sources WHERE recordId=? ORDER BY source').all(row.id).map(x=>x.source);
    const linked=`scope=? AND state='active' AND kind NOT IN ('raw','archive') AND (json_extract(metadata,'$.effectiveAt') IS NULL OR julianday(json_extract(metadata,'$.effectiveAt'))<=julianday(?,'unixepoch')) AND (EXISTS(SELECT 1 FROM json_each(coalesce(json_extract(metadata,'$.sourceIds'),'[]')) WHERE value=?) OR EXISTS(SELECT 1 FROM json_each(coalesce(json_extract(metadata,'$.sourceMessageIds'),'[]')) WHERE value IN (SELECT source FROM event_sources WHERE recordId=?)))`;
    row.linkedMemoryCount=Number(store.db.prepare(`SELECT count(*) AS n FROM records WHERE ${linked}`).get(row.scope,now/1000,row.id,row.id).n);
    row.memoryIds=store.db.prepare(`SELECT id FROM records WHERE ${linked} ORDER BY importance DESC,createdAt DESC,id LIMIT 30`).all(row.scope,now/1000,row.id,row.id).map(x=>x.id);
  }
  const matched=ftsCount+fallbackCount,nextOffset=offset+rows.length<matched?offset+rows.length:null;
  return {rows,receipt:{query,view,scopes:[...new Set(scopes)],includesSharedCore:view==='memories',from,to,
    eligibleRecords:Number(store.db.prepare(`SELECT count(*) AS n FROM records WHERE ${eligible}`).get(...args).n),matchedRecords:matched,returnedRecords:rows.length,nextOffset,
    queryComplete:true,outputComplete:nextOffset===null,historyCompleteness:'unknown',
    note:'只检查已保留、已生效的记忆或来源片段；记录时间不是发生时间。未归档输入、未采集和略过的历史不保证覆盖。词面匹配不是事实判断，未命中不能推断事情未发生。'}};
}
