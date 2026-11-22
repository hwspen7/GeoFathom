import {afterAll} from 'vitest';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

afterAll(()=>{
  const dir=process.env.GEOFATHOM_WEB_COVERAGE_DIR;
  if(!dir)return;
  mkdirSync(dir,{recursive:true});
  const coverage=(globalThis as typeof globalThis & {__coverage__?:unknown}).__coverage__;
  if(coverage)writeFileSync(join(dir,randomUUID()+'.json'),JSON.stringify(coverage));
});
