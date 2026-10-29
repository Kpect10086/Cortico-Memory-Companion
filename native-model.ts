import type {Core} from 'cortico/core/core.ts';
import type {CoreConfig, ToolDef, Logger} from 'cortico/core/types.ts';
import {runForkLoop} from 'cortico/core/fork.ts';
import type {TokenMeters} from 'cortico/core/generation.ts';
import {message, type ContextRecord} from 'cortico/protocol/open-responses/context.ts';
import {readFile} from 'node:fs/promises';
import {extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {downloadImageBytes} from 'cortico/worlds/qq/image-download.ts';

export function nativeModelRunner(options:{core:()=>Pick<Core,'llm'|'providers'|'sessions'|'internBlobs'>;config:()=>CoreConfig;paused:()=>boolean}) {
  const running=new Set<AbortController>();
  return {
    abort(){for(const controller of running)controller.abort(Error('Cortico paused or stopped'));},
    async request(args:Record<string,any>,tools:ToolDef[],log:Logger){
      const manualTest=args.manualProviderTest===true;
      if(manualTest&&tools.length)throw Error('Manual provider tests cannot use tools');
      const requireRunning=()=>{if(!manualTest&&options.paused())throw Error('Cortico is paused');};
      requireRunning();
      const core=options.core(),config=options.config();
      const endpoint=!args.providerId || args.providerId==='cortico'?config.activeProvider:String(args.providerId);
      const configured=config.providers[endpoint]?.spec;
      if(!configured?.model)throw Error('Cortico model endpoint is not configured: '+endpoint);
      // Manual diagnostics use the provider registry while Core.llm follows the run pause.
      const client=manualTest?core.providers.bind(endpoint):core.llm;
      const spec=typeof args.model==='string'&&args.model&&args.model!==configured.model?{...configured,model:args.model,contextWindow:undefined}:configured;
      const controller=new AbortController();running.add(controller);
      const messages:ContextRecord[]=[];
      if(typeof args.system_prompt==='string'&&args.system_prompt)messages.push(message('system',args.system_prompt));
      for(const item of args.contexts??[]){
        if(!item||!['system','user','assistant'].includes(item.role))continue;
        const text=typeof item.content==='string'?item.content:Array.isArray(item.content)?item.content.filter((part:any)=>part?.type==='text').map((part:any)=>part.text??'').join('\n'):'';
        if(text)messages.push(message(item.role,text));
      }
      const prompt=message('user',String(args.prompt??''));
      try{
        const attachments=[];
        for(const source of [...args.image_urls??[],...args.audio_urls??[]]){
          if(typeof source!=='string')throw Error('Invalid model media reference');
          const data=source.match(/^data:((?:image|audio)\/[a-z0-9.+-]+);base64,([a-z0-9+/=\r\n]+)$/i);
          if(data){
            const bytes=Buffer.from(data[2],'base64');if(bytes.length>20*1024*1024)throw Error('Model media exceeds 20 MiB');
            attachments.push({bytes,mime:data[1],fallbackText:'原版陪伴任务附件'});
          }else if(/^https?:\/\//i.test(source)){
            const image=await downloadImageBytes(source,{timeoutMs:15000,maxImageBytes:20*1024*1024});
            attachments.push({bytes:image.buffer,mime:image.mime,fallbackText:'原版陪伴任务附件'});
          }else{
            const file=source.startsWith('file:')?fileURLToPath(source):source;
            const bytes=source.startsWith('base64://')?Buffer.from(source.slice(9),'base64'):await readFile(file);
            if(bytes.length>20*1024*1024)throw Error('Model media exceeds 20 MiB');
            const mime=({'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.wav':'audio/wav','.mp3':'audio/mpeg','.ogg':'audio/ogg'} as Record<string,string>)[extname(file).toLowerCase()];
            if(!mime)throw Error('Unsupported model media format');
            attachments.push({bytes,mime,fallbackText:'原版陪伴任务附件'});
          }
        }
        if(attachments.length)prompt.context.blobs=core.internBlobs(attachments);
        messages.push(prompt);
        const track=core.sessions.open('astrbot-native','AstrBot 原版陪伴任务',{messagesRef:()=>messages});
        const meters:TokenMeters[]=[];
        try{
          const text=await runForkLoop({id:'astrbot-native',messages,tools,signal:controller.signal,
            llm:{respond:async(request,settings)=>{requireRunning();return client.respond(request,{...settings,endpoint});}},
            spec:{...spec,...(typeof args.max_tokens==='number'?{maxTokens:args.max_tokens}:{})},
            maxRounds:8,softRounds:5,log,
            track:{...track,recordAttempts(attempts,records,extra){track.recordAttempts(attempts,records,extra);meters.push(...attempts.filter(a=>a.outcome==='completed').map(a=>a.meters));}},
          });
          requireRunning();
          const known=meters.length>0 && meters.every(m=>m.input!==null&&m.output!==null&&m.cachedInput!==null);
          return {text,providerId:endpoint,model:spec.model,usage:known?{
            input_other:meters.reduce((n,m)=>n+(m.input!-m.cachedInput!),0),input_cached:meters.reduce((n,m)=>n+m.cachedInput!,0),output:meters.reduce((n,m)=>n+m.output!,0),
          }:null};
        }finally{track.close();}
      }finally{running.delete(controller);}
    },
  };
}
