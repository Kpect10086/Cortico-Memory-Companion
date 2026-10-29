import type {ToolDef} from 'cortico/core/types.ts';
import {createHash} from 'node:crypto';

export class NativeTtsProof {
  private proofs=new Map<string,{text:string;at:number}>();
  constructor(private now=()=>Date.now()){}
  remember(bytes:Uint8Array,text:string){
    this.proofs.set(createHash('sha256').update(bytes).digest('hex'),{text,at:this.now()});
    while(this.proofs.size>128)this.proofs.delete(this.proofs.keys().next().value!);
  }
  transcript(bytes:Uint8Array,role:string){
    if(role!=='astrbot-native-transport')return undefined;
    const found=this.proofs.get(createHash('sha256').update(bytes).digest('hex'));
    return found&&this.now()-found.at<15*60*1000?found.text:undefined;
  }
}

const actions=['get_login_info','get_status','get_version_info','get_friend_list','get_group_list','get_group_info','get_group_member_info','get_group_member_list','get_stranger_info','get_msg','get_forward_msg','get_group_msg_history','get_friend_msg_history','get_credentials','get_cookies','get_csrf_token','set_input_status'] as const;
export function companionTransport(options:{
  call:(action:string,args:Record<string,unknown>)=>Promise<unknown>;canRead:(conv:string)=>boolean;
  knownMessage:(id:string)=>string|undefined;qzoneEnabled:()=>boolean;paused:()=>boolean;
  qzoneBlockedReason?:()=>string|null;
  tts?:(text:string)=>Promise<string>;
  recallOwn?:(messageId:string)=>Promise<unknown>;
}):ToolDef {
  return {name:'qq_companion_transport',description:'原版陪伴插件的平台接口；仅内部适配器可调用。',tags:['read'],
    parameters:{type:'object',properties:{action:{type:'string',enum:[...actions]},parameters:{type:'object'}},required:['action'],additionalProperties:false},
    handler:async(args,ctx)=>{
      if(ctx.role!=='astrbot-native-transport')throw Error('Internal companion transport only');
      const action=String(args.action),params=(args.parameters??{}) as Record<string,unknown>;
      if(action==='cortico_qzone_authorize'){
        if(!options.qzoneEnabled()||options.paused())throw Error('Cortico QQ Zone is disabled or paused');
        const blocked=options.qzoneBlockedReason?.();if(blocked)throw Error(blocked);
        return JSON.stringify({allowed:true});
      }
      if(action==='cortico_tts'){
        if(options.paused()||!options.tts)throw Error('Cortico voice is unavailable');
        const text=String(params.text??'');if(!text.trim()||text.length>4000)throw Error('Invalid TTS text');
        return JSON.stringify({base64:await options.tts(text),mime:'audio/wav'});
      }
      if(action==='delete_msg'){
        if(options.paused()||!options.recallOwn)throw Error('Recall is unavailable');
        return JSON.stringify(await options.recallOwn(String(params.message_id??'')));
      }
      if(!actions.includes(action as typeof actions[number]))throw Error('Unsupported companion platform action');
      const id=(value:unknown)=>{const result=String(value??'');if(!/^\d{5,}$/.test(result))throw Error('Invalid QQ identity');return result;};
      if(action.startsWith('get_group_')){
        if(action!=='get_group_list'&&!options.canRead('group:'+id(params.group_id)))throw Error('Group is outside QQ read permissions');
      }else if(action==='get_friend_msg_history'||action==='get_stranger_info'){
        if(!options.canRead('private:'+id(params.user_id)))throw Error('Private conversation is outside QQ read permissions');
      }else if(action==='get_msg'){
        const conv=options.knownMessage(String(params.message_id));
        if(!conv||!options.canRead(conv))throw Error('Message is not known in an allowed conversation');
      }else if(action==='get_credentials'||action==='get_cookies'||action==='get_csrf_token'){
        if(!options.qzoneEnabled())throw Error('QQ Zone is disabled in Cortico');
        if(params.domain!==undefined&&!/^(?:[a-z0-9-]+\.)*qq\.com$/i.test(String(params.domain)))throw Error('QQ credential domain is not allowed');
      }else if(action==='set_input_status'){
        if(options.paused()||!options.canRead('private:'+id(params.user_id)))throw Error('Typing status is not allowed now');
      }
      const result=await options.call(action,params);
      if(action==='get_group_list'||action==='get_friend_list'){
        if(!Array.isArray(result))throw Error('Invalid OneBot directory response');
        return JSON.stringify(result.filter(row=>options.canRead((action==='get_group_list'?'group:':'private:')+String(row[action==='get_group_list'?'group_id':'user_id']))));
      }
      return JSON.stringify(result??null);
    },
  };
}
