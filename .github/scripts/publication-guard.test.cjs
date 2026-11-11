const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {selection, guard, revalidate} = require('./publication-guard.cjs');
const sha = 'a'.repeat(40);
const repo = {full_name:'goddenator/DeckPilot-TV'};
function context(label='deckpilot:preflight-preview') {
  return {repo:{owner:'goddenator',repo:'DeckPilot-TV'},eventName:'pull_request',issue:{number:3},payload:{label:{name:label},pull_request:{state:'open',head:{sha,ref:'feature/game-settings-research-v0.8',repo},base:{sha:'b'.repeat(40),ref:'main',repo}}}};
}
function github(pr=context().payload.pull_request, rules=[{type:'required_reviewers',reviewers:[{type:'User',reviewer:{login:'goddenator'}}]}]) {
  return {rest:{repos:{getEnvironment:async args=>{assert.equal(args.environment_name,'deckpilot-preview-publish');return {data:{protection_rules:rules}};}},pulls:{get:async args=>{assert.equal(args.pull_number,3);return {data:pr};}}}};
}
test('unmerged same-repo label freezes feature head, not main or merge SHA',()=>{
  assert.deepEqual(selection(context()),{sha,channel:'preview',mode:'preflight',recovery_id:''});
  assert.deepEqual(selection(context('deckpilot:publish-preview')),{sha,channel:'preview',mode:'publish',recovery_id:''});
});
test('forks, closed PRs, other targets, labels and push events fail closed',()=>{
  for(const change of [c=>c.payload.pull_request.head.repo={full_name:'attacker/DeckPilot-TV'},c=>c.payload.pull_request.state='closed',c=>c.payload.pull_request.base.ref='other',c=>c.payload.label.name='unrelated',c=>c.eventName='push']) {
    const c=context();change(c);assert.throws(()=>selection(c));
  }
});
test('dispatch defaults to non-publishing, validates full SHA/channel/mode',()=>{
  const c=context();c.eventName='workflow_dispatch';c.payload={inputs:{commit:sha,channel:'preview'}};
  assert.equal(selection(c).mode,'preflight');
  for(const inputs of [{commit:'main',channel:'preview'},{commit:sha,channel:'evil'},{commit:sha,channel:'preview',mode:'automatic'}])assert.throws(()=>selection({...c,payload:{inputs}}));
});
test('guard only emits approval inputs after verifying required owner reviewer',async()=>{
  const outputs={};await guard(github(),context(),{setOutput:(k,v)=>outputs[k]=v});assert.deepEqual(outputs,{sha,channel:'preview',mode:'preflight',recovery_id:''});
  for(const rules of [[],[{type:'wait_timer'}],[{type:'required_reviewers',reviewers:[{type:'User',reviewer:{login:'other'}}]}],[{type:'required_reviewers',reviewers:[{type:'User',reviewer:{login:'goddenator'}},{type:'User',reviewer:{login:'other'}}]}]]) {
    await assert.rejects(guard(github(undefined,rules),context(),{setOutput:()=>assert.fail('outputs before protection')}),/required environment reviewer/);
  }
});
test('environment API denial propagates; approval cannot bypass missing protection',async()=>{
  const g=github();g.rest.repos.getEnvironment=async()=>{throw Error('HTTP 403');};
  await assert.rejects(guard(g,context(),{setOutput:()=>assert.fail()}),/403/);
  await assert.rejects(revalidate(github(undefined,[]),context(),selection(context())),/required environment reviewer/);
});
test('after approval revalidate exact open same-repo feature head',async()=>{
  await revalidate(github(),context(),selection(context()));
  for(const change of [p=>p.head.sha='c'.repeat(40),p=>p.state='closed',p=>p.head.repo={full_name:'attacker/DeckPilot-TV'},p=>p.base.ref='other']) {
    const pr=structuredClone(context().payload.pull_request);change(pr);await assert.rejects(revalidate(github(pr),context(),selection(context())),/PR moved/);
  }
  await assert.rejects(revalidate(github(),context(),{...selection(context()),mode:'publish',recovery_id:''}),/selection changed/);
});
test('workflow scopes, same-repo labeled trigger and protected preflight cannot regress',()=>{
  const s=fs.readFileSync('.github/workflows/publish-approved.yml','utf8');
  const top=s.split('permissions:\n')[1].split('jobs:')[0];assert.match(top,/contents: read/);assert.match(top,/actions: read/);assert.doesNotMatch(top,/write/);
  const pub=s.split('  publish:\n')[1];const permissions=pub.split('    permissions:\n')[1].split('    concurrency:')[0];
  assert.match(permissions,/contents: write/);assert.match(permissions,/pull-requests: read/);assert.match(permissions,/actions: read/);assert.doesNotMatch(permissions,/write-all|admin/);
  assert.match(s,/types: \[labeled\]/);assert.match(s,/head.repo.full_name == github.repository/);assert.doesNotMatch(s,/pull_request_target|^  push:/m);
  assert.match(pub,/environment: deckpilot-\$\{\{ needs.guard.outputs.channel \}\}-publish/);
  assert.match(pub,/ref: \$\{\{ needs.guard.outputs.sha \}\}/);assert.match(pub,/persist-credentials: false/);
  assert.match(pub,/args=\(--preflight\)/);
  assert.ok(pub.indexOf('Revalidate approval immediately before publication') > pub.indexOf('Non-publishing publication preflight'));
  assert.ok(pub.indexOf('Revalidate approval immediately before publication') < pub.indexOf('name: Publish verified immutable pair'));
  assert.match(pub,/APPROVED_MODE: \$\{\{ needs.guard.outputs.mode \}\}/);
  assert.match(pub,/RECOVER_DRAFT_ID: \$\{\{ needs.guard.outputs.recovery_id \}\}/);
  assert.match(pub,/name: Publish verified immutable pair\n        if: needs.guard.outputs.mode == 'publish' \|\| needs.guard.outputs.mode == 'recover'/);
});

test('live CI preflight requests matching scopes without checking out PR code or sending writes',()=>{
  const s=fs.readFileSync('.github/workflows/release.yml','utf8').split('  publication-permissions-preflight:\n')[1];
  assert.match(s,/contents: write/);assert.match(s,/pull-requests: read/);assert.match(s,/actions: read/);
  assert.match(s,/head.repo.full_name == github.repository/);assert.match(s,/github.rest.repos.getEnvironment/);assert.match(s,/github.rest.pulls.get/);
  assert.doesNotMatch(s,/actions\/checkout|environment:|run:|github.rest.\w+\.(create|update|delete)/);
});

test('recovery is explicit, ID-pinned and shares the fresh owner approval barrier',async()=>{
  const c=context('deckpilot:recover-preview:440744496');
  assert.deepEqual(selection(c),{sha,channel:'preview',mode:'recover',recovery_id:'440744496'});
  assert.equal(selection(context('deckpilot:preflight-recovery:440744496')).mode,'preflight');
  for(const label of ['deckpilot:recover-preview:0','deckpilot:recover-preview:main','deckpilot:recover-preview:'])assert.throws(()=>selection(context(label)));
  await assert.rejects(guard(github(undefined,[]),c,{setOutput:()=>assert.fail()}),/required environment reviewer/);
  await assert.rejects(revalidate(github(),c,{...selection(c),recovery_id:'1'}),/selection changed/);
  const dispatch={...c,eventName:'workflow_dispatch',payload:{inputs:{commit:sha,channel:'preview',mode:'recover'}}};
  assert.throws(()=>selection(dispatch),/recovery ID/);
  assert.throws(()=>selection({...dispatch,payload:{inputs:{commit:sha,channel:'preview',mode:'publish',recovery_id:'1'}}}),/never recover implicitly/);
});
