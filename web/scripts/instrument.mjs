/** Identical TS/TSX source maps for unit and Chromium coverage.
 * Instrument raw application source, before JSX/esbuild transformation.
 * Nonexecuted files are retained in the denominator by the report generator.
 */
import instrumentLib from 'istanbul-lib-instrument';
const {createInstrumenter}=instrumentLib;
import {relative,resolve,sep} from 'node:path';

export const root=resolve(import.meta.dirname,'..');
export const coverageEnabled=process.env.GEOFATHOM_WEB_COVERAGE==='1';
export function sourceName(file){
  const name=relative(root,file.split('?')[0]).split(sep).join('/');
  if(!/^src\/.+\.(ts|tsx)$/.test(name)||/\.(test|spec|d)\.(ts|tsx)$/.test(name))return null;
  return name;
}
export function instrument(code,name){
  const instrumenter=createInstrumenter({
    esModules:true,compact:false,preserveComments:true,produceSourceMap:true,
    parserPlugins:['typescript','jsx'],
    coverageGlobalScope:'globalThis',coverageGlobalScopeFunc:false,
  });
  const result=instrumenter.instrumentSync(code,name);
  return {code:result,map:instrumenter.lastSourceMap(),coverage:instrumenter.lastFileCoverage()};
}
export function coveragePlugin(){
  return {name:'geofathom-shared-coverage',enforce:'pre',transform(code,id){
    const name=sourceName(id);
    if(!name)return null;
    const {code:output,map}=instrument(code,name);
    return {code:output,map};
  }};
}
