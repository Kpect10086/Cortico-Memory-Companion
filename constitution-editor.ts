import {createHash} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,renameSync} from 'node:fs';
import {join} from 'node:path';
/** Exposed through the operator panel, never as model tools. */
export class ConstitutionEditor {
  constructor(private file:string,private versionsDir:string) {}
  snapshot(){
    const text=readFileSync(this.file,'utf8');
    return {text,revision:createHash('sha256').update(text).digest('hex'),versions:existsSync(this.versionsDir)?readdirSync(this.versionsDir).filter(name=>/^\d+-[a-f0-9]{64}\.md$/.test(name)).sort().reverse():[]};
  }
  save(text:string,revision:string){
    if(typeof text!=='string' || !text.trim() || text.length>24000)throw Error('宪法正文不能为空且须少于24000字符');
    const previous=this.snapshot();if(previous.revision!==revision)throw Error('宪法已变化，请重新读取后修改');
    mkdirSync(this.versionsDir,{recursive:true});
    const backup=join(this.versionsDir,`${Date.now()}-${previous.revision}.md`);
    if(!existsSync(backup))writeFileSync(backup,previous.text,{flag:'wx'});
    writeFileSync(this.file+'.tmp',text);renameSync(this.file+'.tmp',this.file);
    return this.snapshot();
  }
  restore(version:string,revision:string){
    if(!/^\d+-[a-f0-9]{64}\.md$/.test(version))throw Error('无效宪法版本');
    return this.save(readFileSync(join(this.versionsDir,version),'utf8'),revision);
  }
}
