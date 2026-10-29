import assert from 'node:assert/strict';
import {readFileSync, readdirSync, existsSync, statSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join, relative, resolve} from 'node:path';
const root=resolve(import.meta.dirname,'..');
const json=path=>JSON.parse(readFileSync(join(root,path),'utf8').replace(/^\uFEFF/,''));
const pkg=json('package.json'), source=json('upstream-provenance.json');
assert.equal(source.official,false);
assert.equal(pkg.license,'SEE LICENSE IN LICENSE');
for(const file of ['README.md','LICENSE','UPSTREAM_PERMISSIONS.md','THIRD_PARTY_NOTICES.md','docs/INSTALL.md','docs/RELEASE_AUDIT.md',pkg.main,pkg.cortico.webUiClient,pkg.cortico.describe])assert(existsSync(join(root,file)),file);
for(const [name,record] of Object.entries({upstream:source.upstream,...(source.astrbotSdk?{astrbotSdk:source.astrbotSdk}:{})})){
  const subdir=name==='astrbotSdk'?'astrbot-runtime':Object.keys(record.files).includes('main.py')?readdirSync(join(root,'vendor')).find(d=>d!=='astrbot-runtime'):null;
  assert(subdir,'source directory');
  for(const [file,hash] of Object.entries(record.files))assert.equal(createHash('sha256').update(readFileSync(join(root,'vendor',subdir,file))).digest('hex'),hash,file);
}
const forbidden=/(?:D|C):[\\/]cortico|(?:D|C):[\\/]Users[\\/]/;
function visit(dir){for(const item of readdirSync(dir)){if(['node_modules','.git','.runtime','.audit-output','vendor'].includes(item))continue;const path=join(dir,item);if(statSync(path).isDirectory()){visit(path);continue;}assert(!/\.(?:sqlite|sqlite3|db|exe|dll|pth|onnx|wav|mp3)$/.test(item),relative(root,path));if(/\.(?:ts|mts|mjs|js|css|json|html|md|py)$/.test(item))assert(!forbidden.test(readFileSync(path,'utf8')),`private deployment text in ${relative(root,path)}`);}}
visit(root);
const desc=json(pkg.cortico.describe);const names=(desc.tools??[]).map(t=>t.name);assert.equal(names.length,new Set(names).size);
console.log(JSON.stringify({package:pkg.name,version:pkg.version,originalAuthor:source.originalAuthor,upstreamCommit:source.upstream.commit,upstreamHashesVerified:Object.keys(source.upstream.files).length,tools:names.length,privateDataScan:'pass',certification:'not claimed'}));
