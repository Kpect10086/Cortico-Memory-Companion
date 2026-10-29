import type {World,CoreApi} from 'cortico/core/types.ts';
import {readFile} from 'node:fs/promises';
import {readFileSync,writeFileSync,renameSync,existsSync,mkdirSync} from 'node:fs';
import {extname,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

export function nativePlatform(options:{worlds:World[];core:()=>CoreApi;paused:()=>boolean;save:(bytes:Uint8Array,mime:string)=>string;
  timezone:string;dailyLedgerFile:string;legacyProactiveFile:string;maxProactivePerDay:()=>number;
}){
  const day=(at:number)=>new Intl.DateTimeFormat('en-CA',{timeZone:options.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(at));
  const reserve=()=>{
    const today=day(Date.now());let count=0;
    if(existsSync(options.dailyLedgerFile)){
      const saved=JSON.parse(readFileSync(options.dailyLedgerFile,'utf8'));if(saved.day===today){if(!Number.isSafeInteger(saved.attempts)||saved.attempts<0)throw Error('Invalid proactive ledger');count=saved.attempts;}
    }else if(existsSync(options.legacyProactiveFile)){
      const saved=JSON.parse(readFileSync(options.legacyProactiveFile,'utf8'));if(typeof saved.dayStart==='number'&&day(saved.dayStart)===today&&Number.isSafeInteger(saved.dailyCount)&&saved.dailyCount>=0)count=saved.dailyCount;
    }
    const limit=options.maxProactivePerDay();if(limit>0&&count>=limit)throw Error('Cortico proactive daily opportunity limit reached');
    mkdirSync(dirname(options.dailyLedgerFile),{recursive:true});
    writeFileSync(options.dailyLedgerFile+'.tmp',JSON.stringify({day:today,attempts:count+1}));renameSync(options.dailyLedgerFile+'.tmp',options.dailyLedgerFile);
  };
  const invoke=async(name:string,args:Record<string,unknown>,role='astrbot-native-transport')=>{
    const tool=options.worlds.find(world=>world.id==='qqbot')?.tools().find(tool=>tool.name===name);
    if(!tool)throw Error('Cortico QQ capability is unavailable: '+name);
    const outcome=await tool.handler(args,{role,log:options.core().log});
    if(typeof outcome!=='string'&&outcome.failed)throw Error(outcome.text);
    return typeof outcome==='string'?outcome:outcome.text;
  };
  const media=async(source:string,type:'image'|'audio')=>{
    if(/^(https?:\/\/|log:|mem:)/i.test(source))return source;
    const match=source.match(/^data:([^;,]+);base64,(.*)$/s);
    const file=source.startsWith('file:')?fileURLToPath(source):source;
    const bytes=match?Buffer.from(match[2],'base64'):source.startsWith('base64://')?Buffer.from(source.slice(9),'base64'):await readFile(file);
    if(bytes.length>20*1024*1024)throw Error('Outgoing companion media exceeds 20 MiB');
    const mime=match?.[1]??({'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.wav':'audio/wav','.mp3':'audio/mpeg'} as Record<string,string>)[extname(file).toLowerCase()]
      ??(bytes[0]===0x89&&bytes[1]===0x50?'image/png':bytes[0]===0xff&&bytes[1]===0xd8?'image/jpeg':undefined);
    if(!mime?.startsWith(type+'/'))throw Error('Outgoing companion media format is unknown');
    return options.save(bytes,mime);
  };
  const send=async(args:Record<string,any>)=>{
    if(options.paused())throw Error('Cortico is paused; message was not sent');
    const session=String(args.session??'');
    const parsed=session.match(/^(?:cortico|aiocqhttp):(FriendMessage|GroupMessage):(\d+)$/);
    if(!parsed)throw Error('Invalid companion delivery session');
    const to=(parsed[1]==='GroupMessage'?'group:':'private:')+parsed[2];
    const text:string[]=[],images:string[]=[],at:string[]=[];let audio:string|undefined,reply:number|undefined;
    for(const part of args.components??[]){
      const type=String(part.type??'').toLowerCase(),data=part.data??part;
      if(type==='plain'||type==='text')text.push(String(data.text??''));
      else if(type==='image')images.push(await media(String(data.file||data.url||''),'image'));
      else if(type==='record')audio=await media(String(data.file||data.url||''),'audio');
      else if(type==='at')at.push(String(data.qq));
      else if(type==='reply')reply=Number(data.id);
      else throw Error('Unsupported companion message component: '+type);
    }
    if(audio&&(text.length||images.length||at.length))throw Error('Send voice separately from text and images');
    if(args.proactive===true)reserve();
    const outcome=await invoke('qq_send',audio?{to,audio_handle:audio}:{to,text:text.join(''),images,...(at.length?{at}:{}),...(reply?{reply_message_id:reply}:{})});
    let receipt:any=null;try{receipt=JSON.parse(outcome);}catch{}
    if(receipt?.sent===true)return {confirmed:true,message_id:receipt.message_id,receipt:outcome};
    if(!outcome.startsWith('已发送（编号 '))throw Error(outcome);
    const ids=(outcome.match(/message_id:\s*([-\d, ]+)/)?.[1]??'').split(',').map(id=>id.trim()).filter(id=>/^-?\d+$/.test(id));
    return {confirmed:true,...(ids.length?{message_id:ids[ids.length-1],message_ids:ids}:{}),receipt:outcome};
  };
  return {send,async qzonePublish(args:Record<string,any>){
    if(options.paused())throw Error('Cortico is paused');
    await invoke('qq_companion_transport',{action:'cortico_qzone_authorize',parameters:{}});
    const identity=JSON.parse(await invoke('qq_companion_transport',{action:'get_login_info',parameters:{}}));
    if(!/^\d+$/.test(String(identity?.user_id)))throw Error('QQ identity is unavailable');
    if(!Array.isArray(args.images)||args.images.length>9)throw Error('Invalid original Qzone images');
    const images=await Promise.all(args.images.map((image:string)=>media(image,'image')));
    const result=await invoke('qq_qzone_post',{content:String(args.text??''),images});
    const tid=result.match(/^已发 QQ空间动态。tid=([^；\s]+)/)?.[1];
    if(!tid||tid==='(未知)')throw Error(result);
    return {tid,uin:String(identity.user_id),text:String(args.text??''),images,receipt:result};
  },async onebot(args:Record<string,any>){
    const action=String(args.action),parameters=args.parameters??{};
    if(['send_msg','send_private_msg','send_group_msg'].includes(action)){
      const group=action==='send_group_msg'||parameters.message_type==='group'||parameters.group_id!==undefined;
      const components=typeof parameters.message==='string'?[{type:'Plain',text:parameters.message}]:parameters.message;
      const result=await send({session:`cortico:${group?'GroupMessage':'FriendMessage'}:${group?parameters.group_id:parameters.user_id}`,components,proactive:args.proactive===true});
      return {status:'ok',retcode:0,...result};
    }
    if(action==='set_group_ban'||action==='set_group_kick'){
      if(options.paused())throw Error('Cortico is paused');
      const common={group:String(parameters.group_id??''),who:String(parameters.user_id??'')};
      const outcome=await invoke('qq_admin',action==='set_group_ban'?{...common,action:'ban',durationSec:parameters.duration??600}:{...common,action:'kick',rejectRejoin:parameters.reject_add_request??true},args.callerConv);
      if(!outcome.startsWith('OK (')&&!outcome.startsWith('已把 '))throw Error(outcome);
      return {status:'ok',retcode:0};
    }
    if(action==='send_poke'||action==='group_poke'||action==='friend_poke'){
      if(options.paused())throw Error('Cortico is paused');
      if(args.proactive===true)reserve();
      const outcome=await invoke('qq_poke',{target:parameters.group_id?'group:'+parameters.group_id:'private:'+parameters.user_id,user:String(parameters.user_id)});
      if(!outcome.startsWith('已戳一戳 '))throw Error(outcome);
      return {status:'ok',retcode:0};
    }
    const raw=await invoke('qq_companion_transport',{action,parameters});return JSON.parse(raw);
  }};
}
