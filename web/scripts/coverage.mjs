/** Run independent coverage suites and merge identical Istanbul source counters. */
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import coverageLib from 'istanbul-lib-coverage';
import reportLib from 'istanbul-lib-report';
import reports from 'istanbul-reports';
import {instrument,sourceName,root} from './instrument.mjs';

const {createCoverageMap}=coverageLib;
const {createContext}=reportLib;
const mode=process.argv[2];
const directory=path.join(root,'coverage');
const raw=path.join(directory,'raw');
function walk(dir){
  return fs.readdirSync(dir,{withFileTypes:true}).flatMap(entry=>{
    const file=path.join(dir,entry.name);
    return entry.isDirectory()?walk(file):[file];
  });
}
function run(script,args,kind){
  const dest=path.join(raw,kind);
  fs.rmSync(dest,{recursive:true,force:true});
  fs.mkdirSync(dest,{recursive:true});
  const result=spawnSync(process.execPath,[path.join(root,script),...args],{
    cwd:root,stdio:'inherit',env:{...process.env,GEOFATHOM_WEB_COVERAGE:'1',
      GEOFATHOM_WEB_COVERAGE_DIR:dest,
      ...(kind==='browser'?{GEOFATHOM_E2E_FRESH:'1'}:{})},
  });
  if(result.error)throw result.error;
  if(result.status!==0)process.exit(result.status??1);
}
function render(kinds,target){
  const map=createCoverageMap({});
  for(const file of walk(path.join(root,'src'))){
    const name=sourceName(file);
    if(name)map.addFileCoverage(instrument(fs.readFileSync(file,'utf8'),name).coverage);
  }
  const expected=new Set(map.files());
  for(const kind of kinds){
    const dest=path.join(raw,kind);
    if(!fs.existsSync(dest))throw new Error('Missing '+kind+' coverage.');
    const files=walk(dest).filter(x=>x.endsWith('.json'));
    if(!files.length)throw new Error('Empty '+kind+' coverage.');
    let observed=0;
    for(const file of files){
      const captured=JSON.parse(fs.readFileSync(file,'utf8'));
      for(const [name,entry] of Object.entries(captured)){
        if(!expected.has(name))throw new Error('Unknown source in coverage: '+name);
        const baseline=map.fileCoverageFor(name).data;
        for(const key of ['statementMap','fnMap','branchMap']){
          if(JSON.stringify(entry[key])!==JSON.stringify(baseline[key]))
            throw new Error('Incompatible source counters: '+name+' '+key);
        }
        map.addFileCoverage(entry);
        observed+=Object.values(entry.s).reduce((a,b)=>a+b,0);
      }
    }
    if(!observed)throw new Error('No executed statements in '+kind+' coverage.');
  }
  fs.mkdirSync(target,{recursive:true});
  const ctx=createContext({dir:target,coverageMap:map,sourceFinder:name=>fs.readFileSync(path.join(root,name),'utf8')});
  for(const reporter of ['json','json-summary','text','html'])reports.create(reporter).execute(ctx);
}
if(mode==='unit'){
  run('node_modules/vitest/vitest.mjs',['run','src'],'unit');
  render(['unit'],path.join(directory,'unit'));
}else if(mode==='browser'){
  run('node_modules/@playwright/test/cli.js',['test',...process.argv.slice(3)],'browser');
  render(['browser'],path.join(directory,'browser'));
}else if(mode==='merge'){
  render(['unit','browser'],directory);
}else throw new Error('Expected unit, browser or merge.');
