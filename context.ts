/** Append changes to the delivered history so existing request prefixes remain reusable. */
export class MemoryContext {
  private records: Map<string,string> | null = null;
  private seen = new Map<string,string>();
  private intro = '';
  private scope = '';
  private hosting = '';
  reset(): void {this.records = null; this.seen.clear(); this.intro = ''; this.scope = ''; this.hosting = '';}
  update(pack: {intro:string;entries:{id:string;text:string}[]}, scopes:string[], hosting:string): string[] {
    const next = new Map(pack.entries.map(row=>[row.id,row.text]));
    const scope = JSON.stringify([...new Set(scopes)].sort());
    const prefixes = new Map<string,number>();
    for (const id of new Set([...this.seen.keys(), ...next.keys()])) {
      const prefix = id.slice(0,12);
      prefixes.set(prefix, (prefixes.get(prefix) ?? 0) + 1);
    }
    const reference = (id:string):string => prefixes.get(id.slice(0,12)) === 1 ? id.slice(0,12) : id;
    const added = pack.entries.filter(row=>this.seen.get(row.id)!==row.text);
    const removed = [...(this.records?.keys()??[])].filter(id=>!next.has(id));
    const texts:string[] = [];
    const entered = [...next.keys()].filter(id=>!this.records?.has(id));
    const fullView = !this.records || scope!==this.scope || added.some(row => reference(row.id) === row.id && row.id.length > 12);
    if (fullView || entered.length || added.length || removed.length || pack.intro!==this.intro) {
      const lines = ['[记忆资料更新]'];
      if (pack.intro!==this.intro) lines.push(pack.intro);
      if (fullView) lines.push('作用域 '+scope, '当前检索条目ID：'+JSON.stringify([...next.keys()].map(reference)));
      else if (entered.length) lines.push('加入检索视图ID：'+JSON.stringify(entered.map(reference)));
      if (added.length) lines.push('新增或更新条目：', ...added.map(row=>row.text));
      if (removed.length) lines.push('移出检索视图ID：'+JSON.stringify(removed.map(reference)));
      if (!this.records || pack.intro!==this.intro) lines.push('检索视图ID用唯一前12位，碰撞时保留完整ID；工具所需完整来源ID用 memory_recall 或 memory_sources 查询。未重列正文沿用本上下文同ID的最新版本；移出检索视图不否定历史事实。停用或纠正以最新有效版本和来源为准。');
      texts.push(lines.join('\n'));
    }
    if (hosting!==this.hosting) texts.push(hosting);
    for (const row of pack.entries) this.seen.set(row.id,row.text);
    this.records=next;this.intro=pack.intro;this.scope=scope;this.hosting=hosting;
    return texts;
  }
}
