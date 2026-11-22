import {test as base,expect} from '@playwright/test';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

// Store previous document counters synchronously at navigation, then collect
// the live document at test teardown. This includes reloads without summing
// the same document twice. Each browser context is isolated by Playwright.
export const test=base.extend({
  page:async({page},use)=>{
    const dir=process.env.GEOFATHOM_WEB_COVERAGE_DIR;
    if(!dir){await use(page);return;}
    await page.addInitScript(()=>{
      const w=window as typeof window & {__coverage__?:unknown};
      window.addEventListener('pagehide',()=>{
        if(!w.__coverage__)return;
        const previous=JSON.parse(sessionStorage.getItem('__gf_coverage_documents')||'[]');
        previous.push(w.__coverage__);
        sessionStorage.setItem('__gf_coverage_documents',JSON.stringify(previous));
      });
    });
    try{await use(page);}
    finally{
      if(!page.isClosed()){
        const records=await page.evaluate(()=>{
          const current=(window as typeof window & {__coverage__?:unknown}).__coverage__;
          // A request-only failure may leave the page at about:blank.
          // Such a document has no application coverage and storage is denied.
          if (location.protocol !== 'http:' && location.protocol !== 'https:') return [];
          let old:unknown[]=[];
          try {
            old=JSON.parse(sessionStorage.getItem('__gf_coverage_documents')||'[]');
          } catch(error) {
            if (!(error instanceof DOMException) || error.name!=='SecurityError') throw error;
          }
          return current?[...old,current]:old;
        });
        mkdirSync(dir,{recursive:true});
        for(const record of records)writeFileSync(join(dir,randomUUID()+'.json'),JSON.stringify(record));
      }
    }
  },
});
export {expect};
