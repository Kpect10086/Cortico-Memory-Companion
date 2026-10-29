import base from './base/webui/client.ts';
import type { WebUiClientBundle } from 'cortico/web/shared/client-panel.ts';
import type {SearchReceipt} from './store.mjs';

type Memory = { id: string; scope: string; text: string; kind: string; importance: number; reason: string; source: string; createdAt: number; state: string; revision: string; reviewError?: boolean; reviewPending?: boolean; metadata:string;trainingApproved?:boolean };
type Detail = Memory & { audit: Array<{ at: number; operation: string; detail: string }> };
type Evidence = {rows:Array<{id:string;scope:string;speaker:string;receivedAt:number;text:string;reviewPending?:boolean;reviewError?:boolean}>;matched:number;sourceIds:string[];missing:number;fragments:boolean};
type SearchResult = {rows:Array<{id:string;scope:string;text:string;kind:string;importance:number;createdAt:number;textTruncated:boolean;memoryIds:string[];linkedMemoryCount:number;linksTruncated:boolean}>;receipt:SearchReceipt};
type Snapshot = {
  total: number; chars: number; records: number; limit: number; matched: number;
  pendingSummary: number; oldestPendingAt: number | null;
  kinds: Array<{ kind: string; state: string; count: number }>;
  rows: Memory[];
};
const kinds: Record<string, string> = { core: '核心', archive: '旧档案', raw: '原始事件', fact: '事实', preference: '偏好', relation: '关系', commitment: '约定', recent: '近期', event:'事件', single:'高权重单句' };
const states: Record<string, string> = { active: '生效', pending: '待审核', rejected: '已停用', superseded: '已替代', archived:'已归档', rolled_back:'已回滚' };

const bundle: WebUiClientBundle = { panels: { ...base.panels,
  'weighted-memory': { mount(ctx) {
    const { ui, root } = ctx;
    const controls = ui.rowbar();
    const lookup=ui.sheet({title:'权重检索 · 记忆与原文',desc:'先查已通过记忆，再查来源并核对原话。管理操作与检索使用同一份资料。'});
    const lookupQuery=ui.input({placeholder:'关键词、原文片段或编号'});lookupQuery.maxLength=300;lookupQuery.setAttribute('aria-label','权重检索关键词');
    const lookupScope=ui.input({value:'main'});lookupScope.setAttribute('aria-label','检索会话');
    const lookupView=ui.select({value:'memories',options:[{value:'memories',label:'已通过记忆'},{value:'sources',label:'原始来源片段'}]});lookupView.setAttribute('aria-label','检索资料类型');
    const lookupFrom=ui.input({type:'date'}),lookupTo=ui.input({type:'date'});
    const lookupControls=ui.rowbar(),lookupResults=ui.h('div'),lookupReceipt=ui.msgline();
    lookupReceipt.setAttribute('role','status');
    let lookupRequest=0,lookupOffset=0,lookupStarted=false;
    const runLookup=async(start=0)=>{
      const ticket=++lookupRequest;lookupStarted=true;lookupOffset=start;
      try{
        const data=await ctx.invoke<SearchResult>('search',[{query:lookupQuery.value,scope:lookupScope.value,view:lookupView.value,offset:start,
          from:lookupFrom.value?new Date(lookupFrom.value+'T00:00:00').toISOString():null,to:lookupTo.value?new Date(lookupTo.value+'T23:59:59.999').toISOString():null}]);
        if(ctx.signal.aborted || ticket!==lookupRequest)return;
        const receipt=data.receipt;
        lookupReceipt.textContent=`会话 ${receipt.scopes.join('、')}${receipt.includesSharedCore?'（含共享核心摘要）':''}；记录时间 ${receipt.from ?? '不限'} ～ ${receipt.to ?? '不限'}；可检索 ${receipt.eligibleRecords} 条，匹配 ${receipt.matchedRecords} 条，本页 ${receipt.returnedRecords} 条。查询${receipt.queryComplete?'完成':'未完成'}；结果${receipt.outputComplete?'已完整显示':'有分页或截断'}；历史采集完整性未知。${receipt.note}`;
        const cards=data.rows.map(row=>{
          const card=ui.sheet({title:`${row.kind==='raw'?'来源片段':'记忆'} · 权重 ${row.importance}`,desc:`${row.scope} · 记录时间 ${new Date(row.createdAt).toLocaleString()} · ${row.id}`});
          const text=ui.h('pre',null,row.text+(row.textTruncated?'\n[正文已截断，请查看原话]':''));text.style.whiteSpace='pre-wrap';
          const actions=ui.actions(),proof=ui.h('div');
          actions.append(ui.button('核对原话',{onClick:async()=>{
            try{const evidence=await ctx.invoke<Evidence>('evidence',[row.id,0]);if(ctx.signal.aborted || ticket!==lookupRequest)return;
              const render=(e:Evidence)=>{proof.replaceChildren(ui.h('p',null,`${e.fragments?'来源片段，未定位完整原消息':'原始发言'} · 共 ${e.matched} 条 · 缺失 ${e.missing} 条`),...e.rows.map(message=>ui.h('pre',null,`${message.speaker || '说话人未知'} · ${new Date(message.receivedAt).toLocaleString()}\n${message.text}`)));
                const next=startEvidence+e.rows.length;
                if(next<e.matched)proof.append(ui.button('下一页原话',{onClick:async()=>{try{const following=await ctx.invoke<Evidence>('evidence',[row.id,next]);if(ctx.signal.aborted || ticket!==lookupRequest)return;startEvidence=next;render(following);}catch(e){lookupReceipt.textContent=String(e);}}}));
                if(e.rows.some(message=>message.reviewPending))proof.append(ui.button('刷新原话审核',{onClick:async()=>{try{const following=await ctx.invoke<Evidence>('evidence',[row.id,startEvidence,true]);if(!ctx.signal.aborted && ticket===lookupRequest)render(following);}catch(e){lookupReceipt.textContent=String(e);}}}));};
              let startEvidence=0;render(evidence);
            }catch(e){lookupReceipt.textContent=String(e);}
          }}),ui.button(row.kind==='raw'?'管理来源片段':'管理这条记忆',{onClick:()=>{filter.value=row.kind==='raw'?'raw':'memories';search.value=row.id;offset=0;void reload();}}));
          for(const id of row.memoryIds)actions.append(ui.button('查看关联记忆 '+id.slice(0,12),{onClick:()=>{filter.value='memories';search.value=id;offset=0;void reload();}}));
          card.body.append(text,actions,proof);
          if(row.kind==='raw')card.body.append(ui.h('p',null,`关联已通过记忆 ${row.linkedMemoryCount} 条${row.linksTruncated?'；引用未全部展示':''}。`));
          return card.el;
        });
        lookupResults.replaceChildren(...cards);
        if(!cards.length)lookupResults.append(ui.h('p',null,'本次词面条件未命中，可换关键词或查来源；不能据此断言事情没有发生。'));
        const pages=ui.actions();
        if(start>0)pages.append(ui.button('上一页检索结果',{onClick:()=>{void runLookup(Math.max(0,start-20));}}));
        if(receipt.nextOffset!==null)pages.append(ui.button('下一页检索结果',{onClick:()=>{void runLookup(receipt.nextOffset!);}}));
        lookupResults.append(pages);
      }catch(e){if(!ctx.signal.aborted && ticket===lookupRequest){lookupResults.replaceChildren();lookupReceipt.textContent=`检索未完成：${String(e)}`;}}
    };
    lookupControls.append(ui.field('查找内容',lookupQuery),ui.field('会话',lookupScope),ui.field('资料',lookupView),ui.field('记录日期起',lookupFrom),ui.field('记录日期止',lookupTo),ui.button('检索记忆与原文',{onClick:()=>{void runLookup();}}));
    lookup.body.append(lookupControls,lookupReceipt,lookupResults);
    lookupQuery.addEventListener('keydown',event=>{if(event.key==='Enter')void runLookup();},{signal:ctx.signal});
    const filter = ui.select({ value: 'memories', options: [
      { value: 'memories', label: '提炼后的记忆' }, { value: 'pending', label: '待审核' },
      { value: 'core', label: '核心' }, { value: 'rejected', label: '已停用 / 旧版本' },
      {value:'archived',label:'已归档'}, { value: 'raw', label: '原始事件' }, { value: 'archive', label: '旧档案' }, { value: 'all', label: '全部资料' },
    ] });
    const search=ui.input({placeholder:'搜索摘要或 ID'});
    const kind=ui.select({value:'',options:[{value:'',label:'所有类型'},...Object.entries(kinds).map(([value,label])=>({value,label}))]});
    const sort=ui.select({value:'time',options:[{value:'time',label:'记录时间：新 → 旧'},{value:'time-asc',label:'记录时间：旧 → 新'},{value:'weight',label:'重要性：高 → 低'},{value:'weight-asc',label:'重要性：低 → 高'},{value:'confidence',label:'时间置信度排序'},{value:'category',label:'事件分组'}]});
    sort.setAttribute('aria-label','记忆排序');
    const selected=new Map<string,string>();
    const bulkReason=ui.input({placeholder:'批量操作理由'});bulkReason.maxLength=500;
    const bulk=ui.actions();
    const manage=ui.sheet({title:'快速添加与导出'});
    const manualText=ui.textarea({rows:3});manualText.maxLength=1500;
    const scope=ui.input({value:'main'});
    const manualKind=ui.select({value:'event',options:Object.entries(kinds).filter(([value])=>['event','single','preference','relation','commitment','core'].includes(value)).map(([value,label])=>({value,label}))});
    const sourceType=ui.select({value:'manual',options:[{value:'manual',label:'手工录入'},{value:'fabricated',label:'捏造记忆'}]});
    const at=ui.input({placeholder:'发生时间 ISO，例如 2026-10-13T20:10:00+08:00；留空表示未知'});
    const effective=ui.input({placeholder:'生效时间 ISO；留空为审核后生效'});
    const weight=ui.input({type:'number',value:'8'});weight.min='1';weight.max='12';weight.step='1';
    const manualReason=ui.input({placeholder:'添加理由'});manualReason.maxLength=500;
    const tags=ui.input({placeholder:'标签，用逗号分隔'});
    const transfer=ui.textarea({rows:3});transfer.placeholder='导入 all.jsonl 或合并/拆分后的 JSON 数组';
    const manageActions=ui.actions();
    const exportFormat=ui.select({value:'json',options:[{value:'json',label:'JSON'},{value:'md',label:'Markdown (.md)'},{value:'sqlite',label:'SQLite (.sqlite)'},{value:'training',label:'训练素材（仅单独授权的当前版本，JSONL）'}]});
    const exportScope=ui.select({value:'all',options:[{value:'all',label:'全部资料'},{value:'approved',label:'仅已通过记忆'}]});
    const exportButton=ui.button('一键导出',{variant:'primary',onClick:()=>{void exportMemory();}});
    const exportActions=ui.actions();exportActions.append(exportButton);
    manage.body.append(ui.field('记忆摘要或自然语言内容',manualText),ui.field('作用域',scope),ui.field('类型',manualKind),ui.field('来源',sourceType),ui.field('发生时间',at),ui.field('生效时间',effective),ui.field('权重',weight),ui.field('标签',tags),ui.field('添加理由',manualReason),manageActions,ui.field('导入或批量合并拆分内容',transfer));
    manage.body.append(ui.field('导出格式',exportFormat),ui.field('导出范围',exportScope),exportActions);
    const download=(name:string,blob:Blob)=>{const url=URL.createObjectURL(blob);const link=ui.h('a') as HTMLAnchorElement;link.href=url;link.download=name;link.click();setTimeout(URL.revokeObjectURL.bind(URL,url),1000);};
    const body = ui.h('div');
    const error = ui.msgline();
    const exportMemory=async()=>{
      exportButton.disabled=true;exportFormat.disabled=true;exportScope.disabled=true;error.textContent='正在生成导出文件…';
      try {
        const format=exportFormat.value,approved=exportScope.value==='approved';
        const blob=await ctx.invokeBinary('exportFile',[format,approved]);
        if(ctx.signal.aborted)return;
        download(`memory-${format==='training'?'training-approved':approved?'approved':'all'}-${new Date().toISOString().replace(/[:.]/g,'-')}.${format==='training'?'jsonl':format}`,blob);
        error.textContent='导出文件已生成，已发起下载。';
      }catch(failure){if(!ctx.signal.aborted)error.textContent=`导出失败：${String(failure)}`;}
      finally{exportButton.disabled=false;exportFormat.disabled=false;exportScope.disabled=false;}
    };
    const page = ui.msgline();
    let request = 0, offset = 0;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    ctx.signal.addEventListener('abort', () => clearTimeout(refreshTimer), { once: true });
    body.addEventListener('input', () => clearTimeout(refreshTimer), { signal: ctx.signal });
    body.addEventListener('click', () => clearTimeout(refreshTimer), { signal: ctx.signal });
    const previous = ui.button('上一页', { onClick: () => { offset = Math.max(0, offset - 30); void reload(); } });
    const next = ui.button('下一页', { onClick: () => { offset += 30; void reload(); } });
    const reload = async (retry = false) => {
      clearTimeout(refreshTimer);
      if (ctx.signal.aborted) return;
      const current = ++request;
      try {
        const data = await ctx.invoke<Snapshot>('snapshot', [filter.value, offset, retry,search.value,kind.value,sort.value]);
        if (ctx.signal.aborted || current !== request) return;
        if (offset > 0 && offset >= data.matched) { offset = Math.max(0, offset - 30); return void reload(); }
        error.textContent = '';selected.clear();
        previous.disabled = offset === 0;
        next.disabled = offset + 30 >= data.matched;
        page.textContent = `${data.matched ? offset + 1 : 0}–${Math.min(offset + 30, data.matched)} / ${data.matched} 条`;
        const overview = ui.sheet({ title: '权重检索', desc: '长期检索只读取已通过记忆。普通候选按配置自动通过或待审，单句权重须达到配置门槛。每页30条。原始资料保留用于追溯。' });
        overview.body.append(ui.kv([
          { k: '资料总数', v: String(data.total) },
          { k: '待整理原始事件', v: String(data.pendingSummary) },
          { k: '最早待整理来源时间', v: data.oldestPendingAt === null ? '无积压' : new Date(data.oldestPendingAt).toLocaleString() },
          { k: '本次注入', v: `${data.records} 条 / ${data.chars} 字符，上限 ${data.limit}` },
          ...data.kinds.map(row => ({ k: `${kinds[row.kind] ?? row.kind} · ${states[row.state] ?? row.state}`, v: String(row.count) })),
        ]));
        const cards = data.rows.map(row => {
          const meta=JSON.parse(row.metadata || '{}');
          const select=ui.checkbox('选择记忆',{disabled:row.reviewPending || row.reviewError,onChange:checked=>{if(checked)selected.set(row.id,row.revision);else selected.delete(row.id);}});
          const card = ui.sheet({ title: `${meta.category ?? ''} · ${kinds[row.kind] ?? row.kind} · ${states[row.state] ?? row.state} · ${row.importance >= 10 ? '非常规' : '常规'}档 ${row.importance}`, desc: `发生时间 ${meta.occurredAt ?? '时间不确定'} · 记录时间 ${new Date(row.createdAt).toLocaleString()} · ${meta.sourceType ?? '旧资料'} · ${row.scope}` });
          const preview = ui.h('pre', null, row.text);
          preview.style.whiteSpace = 'pre-wrap';
          const actions = ui.actions(), editor = ui.h('div'), notice = ui.msgline();
          const evidence=ui.h('div');let evidenceRequest=0,evidenceTimer:ReturnType<typeof setTimeout>|undefined;
          ctx.signal.addEventListener('abort',()=>clearTimeout(evidenceTimer),{once:true});
          const showEvidence=async(start=0,retry=false)=>{
            clearTimeout(evidenceTimer);const ticket=++evidenceRequest;
            try{
              const data=await ctx.invoke<Evidence>('evidence',[row.id,start,retry]);
              if(ctx.signal.aborted || current!==request || ticket!==evidenceRequest)return;
              const entries=data.rows.map(source=>{
                const text=ui.h('pre',null,source.text);text.style.whiteSpace='pre-wrap';
                const entry=ui.sheet({title:source.speaker || '发言者未知',desc:`${new Date(source.receivedAt).toLocaleString()} · ${source.scope} · ${source.id}`});entry.body.append(text);return entry.el;
              });
              const buttons=ui.actions();
              if(start>0)buttons.append(ui.button('上一组来源',{onClick:()=>{void showEvidence(Math.max(0,start-10));}}));
              if(start+10<data.matched)buttons.append(ui.button('下一组来源',{onClick:()=>{void showEvidence(start+10);}}));
              buttons.append(ui.button('重试来源审核',{onClick:()=>{void showEvidence(start,true);}}),ui.button('关闭来源',{onClick:()=>{evidenceRequest++;clearTimeout(evidenceTimer);evidence.replaceChildren();}}));
              evidence.replaceChildren(ui.h('p',null,`${data.fragments?'来源片段（未定位原消息）':'来源消息'} ${data.matched} 条${data.missing ? `；${data.missing} 条未找到原消息，片段 ID：${data.sourceIds.join(', ')}` : ''}`),...entries,buttons);
              if(data.rows.some(source=>source.reviewPending))evidenceTimer=setTimeout(()=>{void showEvidence(start);},1500);
            }catch(failure){if(!ctx.signal.aborted && current===request)notice.textContent=`读取来源失败：${String(failure)}`;}
          };
          const reason = ui.input({ placeholder: row.importance >= 10 ? '重大影响及选档理由（必填）' : '审核或纠错理由（必填）' });
          reason.maxLength = 500;
          reason.required = true;
          const run = async (method: string, args: unknown[]) => {
            if (!reason.value.trim()) { notice.textContent = '请填写操作理由（1–500字符）'; reason.focus(); return; }
            const buttons = [...actions.querySelectorAll('button'), ...editor.querySelectorAll('button')];
            buttons.forEach(button => { button.disabled = true; });
            try { await ctx.invoke(method, args); if (!ctx.signal.aborted) await reload(); }
            catch (failure) { if (!ctx.signal.aborted) notice.textContent = `操作失败：${String(failure)}`; }
            finally { buttons.forEach(button => { button.disabled = false; }); }
          };
          const show = async (editing: boolean) => {
            try {
              const detail = await ctx.invoke<Detail>('detail', [row.id]);
              if (ctx.signal.aborted || current !== request) return;
              editor.replaceChildren();
              const text = ui.textarea({ value: detail.text, rows: 6 });
              text.readOnly = !editing;
              const weight = ui.input({ value: String(detail.importance), type: 'number' });
              weight.min = '1'; weight.max = '12'; weight.step = '1'; weight.required = true;
              const detailMeta=JSON.parse(detail.metadata || '{}');
              const occurred=ui.input({value:detailMeta.occurredAt ?? '',placeholder:'带时区 ISO；留空为未知'});
              const editTags=ui.input({value:(detailMeta.tags ?? []).join(',')});
              const buttons = ui.actions();
              if (editing) {
                text.maxLength = 1500;
                buttons.append(ui.button('保存纠错', { variant: 'primary', onClick: () => {
                  if (!weight.reportValidity()) return;
                  void run('correct', [detail.id, detail.revision, text.value, Number(weight.value), reason.value,{occurredAt:occurred.value.trim() || null,tags:editTags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean)}]);
                } }));
              }
              buttons.append(ui.button('关闭', { onClick: () => { editor.replaceChildren(); } }));
              editor.append(ui.field(editing ? '纠正后的正文' : '完整原文', text));
              if (editing) editor.append(ui.field('发生时间',occurred),ui.field('标签',editTags),ui.field('权重（1–12；1–9 常规，10–12 仅重大事情）', weight));
              editor.append(ui.kv((detail as Detail & {conflicts?:Array<{id:string;state:string}>}).conflicts?.map(r=>({k:'相同摘要候选',v:r.id+' · '+r.state})) ?? []));
              editor.append(ui.kv(detail.audit.map(entry => ({ k: `${new Date(entry.at).toLocaleString()} · ${entry.operation}`, v: entry.detail }))), buttons);
            } catch (failure) { if (!ctx.signal.aborted && current === request) notice.textContent = `读取详情失败：${String(failure)}`; }
          };
          actions.append(ui.button('回滚最近操作',{onClick:()=>{void run('rollback',[row.id,row.revision,reason.value]);}}));
          actions.append(ui.button('原文 / 操作记录', { onClick: () => { void show(false); } }));
          actions.append(ui.button('查看来源证据',{onClick:()=>{void showEvidence();}}));
          if (row.state === 'active' && !['raw','archive'].includes(row.kind)) actions.append(
            ui.button('单独允许用于训练',{onClick:()=>{void run('reviewTraining',[row.id,row.revision,true,reason.value]);}}),
            ui.button('撤回训练授权',{onClick:()=>{void run('reviewTraining',[row.id,row.revision,false,reason.value]);}}));
          if (row.state !== 'superseded') {
            if (!['raw', 'archive'].includes(row.kind)) actions.append(ui.button('纠错 / 调整权重', { onClick: () => { void show(true); } }));
            if (row.state !== 'active' && !['raw','archive'].includes(row.kind)) actions.append(ui.button(row.state === 'pending' ? (row.importance >= 10 ? '通过非常规档位' : '通过') : '恢复', { onClick: () => { void run('review', [row.id, row.revision, 'active', reason.value]); } }));
            if (row.state !== 'rejected') actions.append(ui.button(row.state === 'pending' ? '拒绝' : '停用', { variant: 'danger', onClick: () => { void run('review', [row.id, row.revision, 'rejected', reason.value]); } }));
          }
          card.body.append(select.el,preview, ui.kv([{ k: '训练授权', v: row.trainingApproved?'当前版本已单独授权':'未授权' },{ k: '保留理由', v: row.reason }, { k: '来源 / 前一版本', v: row.source }, { k: '记录 ID', v: row.id }]), ui.field('操作理由', reason), actions, notice, editor,evidence);
          return card.el;
        });
        body.replaceChildren(overview.el, ...cards);
        if(lookupStarted)void runLookup(lookupOffset);
        if (data.rows.some(row => row.reviewPending)) refreshTimer = setTimeout(() => { void reload(); }, 1500);
      } catch (failure) {
        if (!ctx.signal.aborted && current === request) error.textContent = `读取记忆失败：${String(failure)}`;
      }
    };
    let performing=false;
    const perform=async(method:string,args:unknown[])=>{if(performing)return;performing=true;const buttons=[...bulk.querySelectorAll('button'),...manageActions.querySelectorAll('button')];buttons.forEach(button=>{button.disabled=true;});try{await ctx.invoke(method,args);if(!ctx.signal.aborted)await reload();}catch(failure){error.textContent=String(failure);}finally{performing=false;buttons.forEach(button=>{button.disabled=false;});}};
    const items=()=>[...selected].map(([id,revision])=>({id,revision}));
    for(const [state,label] of [['active','批量通过'],['rejected','批量拒绝'],['archived','批量归档']]) bulk.append(ui.button(label,{onClick:()=>{void perform('batchReview',[items(),state,bulkReason.value]);}}));
    bulk.append(ui.button('全选当前页',{onClick:()=>{body.querySelectorAll<HTMLInputElement>('input[type=checkbox]:not(:disabled)').forEach(input=>{input.checked=true;input.dispatchEvent(new Event('change'));});}}),ui.button('提交合并 / 拆分',{onClick:()=>{try{void perform('restructure',[items(),JSON.parse(transfer.value),bulkReason.value]);}catch(failure){error.textContent=String(failure);}}}));
    manageActions.append(ui.button('添加为待审',{onClick:()=>{if(!weight.reportValidity())return;void perform('manual',[{text:manualText.value,scope:scope.value,kind:manualKind.value,sourceType:sourceType.value,occurredAt:at.value.trim() || null,effectiveAt:effective.value.trim() || null,importance:Number(weight.value),reason:manualReason.value,tags:tags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean)}]);}}),ui.button('导入为待审',{onClick:()=>{void perform('importAll',[transfer.value]);}}));
    controls.append(search,kind,sort,filter, ui.button('刷新', { onClick: () => { void reload(true); } }), previous, next, page);
    filter.addEventListener('change', () => { offset = 0; void reload(); }, { signal: ctx.signal });
    for(const input of [kind,sort]) input.addEventListener('change',()=>{offset=0;void reload();},{signal:ctx.signal});
    search.addEventListener('change',()=>{offset=0;void reload();},{signal:ctx.signal});
    root.append(lookup.el,controls,bulkReason,bulk,manage.el,error,body);
    void reload();
  } },
  'constitution':{mount(ctx){
    const {ui,root}=ctx,editor=ui.textarea({rows:20}),notice=ui.msgline(),actions=ui.actions();
    const versions=ui.select({value:'',options:[]});let revision='';
    const load=async(data?:{text:string;revision:string;versions:string[]})=>{
      try{const state=data??await ctx.invoke<{text:string;revision:string;versions:string[]}>('snapshot');
        if(ctx.signal.aborted)return;editor.value=state.text;revision=state.revision;
        versions.replaceChildren(...state.versions.map(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;return option;}));
        notice.textContent='只有控制台操作员能保存；保存后点击重载系统提示词生效。';
      }catch(error){notice.textContent=String(error);}
    };
    const update=async(method:string,args:unknown[])=>{try{await load(await ctx.invoke(method,args));}catch(error){notice.textContent=String(error);}};
    actions.append(ui.button('重新读取',{onClick:()=>{void load();}}),ui.button('保存固定宪法',{variant:'primary',onClick:()=>{void update('save',[editor.value,revision]);}}),
      ui.button('恢复所选版本',{onClick:()=>{if(versions.value)void update('restore',[versions.value,revision]);}}));
    root.append(ui.field('固定身份和底线',editor),ui.field('历史版本',versions),actions,notice);void load();
  }},
} };
export default bundle;
