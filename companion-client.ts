import base from './client.ts';
import type {WebUiClientBundle} from 'cortico/web/shared/client-panel.ts';

const bundle:WebUiClientBundle={panels:{...base.panels,'native-memory':{mount(ctx){
  const status=ctx.ui.msgline();status.setAttribute('role','status');ctx.root.append(status);
  void ctx.invoke<{url?:string}>('launch').then(({url})=>{
    if(ctx.signal.aborted)return;if(!url){status.textContent='原版记忆面板尚未就绪，请查看运行诊断。';return;}
    const link=ctx.ui.h('a',null,'在独立窗口打开原版记忆面板');link.href=url;link.target='_blank';link.rel='noopener noreferrer';
    const frame=ctx.ui.h('iframe');frame.src=url;frame.title='我会牢牢记住你 · 原版记忆面板';
    frame.style.width='100%';frame.style.height='calc(100vh - 210px)';frame.style.minHeight='600px';frame.style.border='0';
    ctx.root.append(link,frame);
  }).catch(error=>{status.textContent=String(error);});
}},'astrbot-companion':{mount(ctx){
  const {ui,root}=ctx;
  const status=ui.msgline();status.setAttribute('role','status');
  const scope=ui.input({value:'self'});scope.setAttribute('aria-label','资料作用域');
  const kind=ui.select({value:'state',options:[
    ['state','角色状态'],['plan','生活计划'],['relationship','关系档案'],['calendar','日历与约定'],['anniversary','纪念日'],['diary','私人日记'],
    ['knowledge','知识'],['goals','目标'],['skills','技能'],['open_items','未完话题'],['slang','黑话'],
  ].map(([value,label])=>({value,label}))});kind.setAttribute('aria-label','资料类型');
  const identifier=ui.input({value:'current'});identifier.setAttribute('aria-label','资料编号');
  const editor=ui.h('textarea');editor.setAttribute('aria-label','资料 JSON');editor.rows=18;editor.style.width='100%';
  const result=ui.h('pre');result.style.whiteSpace='pre-wrap';
  let revision:number|null=null,identity='';
  const key=()=>JSON.stringify([scope.value,kind.value,identifier.value]);
  const load=async()=>{try{
    const data=await ctx.invoke<{value:unknown;revision:number}>('document',[{scope:scope.value,kind:kind.value,id:identifier.value}]);
    if(ctx.signal.aborted)return;revision=data.revision;identity=key();editor.value=JSON.stringify(data.value,null,2);status.textContent=`已读取 · 版本 ${revision}`;
  }catch(error){status.textContent=String(error);}};
  const controls=ui.rowbar();controls.append(ui.field('作用域（self、private:QQ、group:群号）',scope),ui.field('资料类型',kind),ui.field('编号',identifier),
    ui.button('读取',{onClick:()=>{void load();}}),ui.button('列出本类资料',{onClick:async()=>{try{
      const data=await ctx.invoke('document',[{scope:scope.value,kind:kind.value,action:'list'}]);if(!ctx.signal.aborted)result.textContent=JSON.stringify(data,null,2);
    }catch(error){status.textContent=String(error);}}}),
    ui.button('保存当前资料',{onClick:async()=>{try{
      if(revision===null||identity!==key())throw Error('请先读取所选资料，再保存。');
      const value=JSON.parse(editor.value);
      const saved=await ctx.invoke<{revision:number}>('document',[{action:'save',scope:scope.value,kind:kind.value,id:identifier.value,value,revision}]);
      if(!ctx.signal.aborted){revision=saved.revision;status.textContent=`已保存 · 版本 ${revision}`;}
    }catch(error){status.textContent=String(error);}}}));
  const query=ui.input({placeholder:'输入要查询的梗'});query.setAttribute('aria-label','梗百科查询');
  const search=ui.rowbar();search.append(query,ui.button('查梗百科',{onClick:async()=>{try{
    const data=await ctx.invoke('meme',[query.value]);if(!ctx.signal.aborted)result.textContent=JSON.stringify(data,null,2);
  }catch(error){status.textContent=String(error);}}}),ui.button('同步已审核旧记忆',{onClick:async()=>{try{
    const data=await ctx.invoke('sync');if(!ctx.signal.aborted)result.textContent=JSON.stringify(data,null,2);
  }catch(error){status.textContent=String(error);}}}));
  root.append(ui.h('p',null,'原版 MemoryCompanion 负责检索与注入；Cortico 保留权重审核、原文证据和现有 World。日历 state=proposed 为草稿，操作员核实后可改为 accepted。资料内容为 JSON，保存检查版本，防止覆盖其他修改。'),controls,status,editor,search,result);
  void ctx.invoke('status').then(data=>{if(!ctx.signal.aborted)result.textContent=JSON.stringify(data,null,2);}).catch(error=>{status.textContent=String(error);});
}}}};
export default bundle;
