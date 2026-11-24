import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import test from 'node:test';

import {resolveFrontendRevision} from './revision.mjs';

test('checked-out Git SHA is available without launcher environment variables',()=>{
  const actual=execFileSync('git',['rev-parse','HEAD'],{
    cwd:new URL('../../',import.meta.url),encoding:'utf8',
  }).trim().slice(0,12);
  assert.match(actual,/^[0-9a-f]{12}$/);
  assert.equal(resolveFrontendRevision({}),actual);
});

test('explicit valid revision wins and is normalized',()=>{
  assert.equal(resolveFrontendRevision({VITE_GEOFATHOM_REVISION:'ABCDEF1234567'}),'abcdef123456');
});

test('invalid injected revision never masquerades as a commit',()=>{
  const actual=resolveFrontendRevision({});
  assert.equal(resolveFrontendRevision({VITE_GEOFATHOM_REVISION:'unavailable'}),actual);
});
