// Shared by the real workflow and its non-publishing contract tests.
const OWNER = 'goddenator';
const REPO = 'DeckPilot-TV';
const LABELS = {'deckpilot:publish-preview': 'publish', 'deckpilot:preflight-preview': 'preflight'};
function selection(context) {
  if (context.repo.owner !== OWNER || context.repo.repo !== REPO) throw Error('Unexpected repository');
  let sha, channel, mode, recovery_id = '';
  if (context.eventName === 'pull_request') {
    const pr = context.payload.pull_request;
    if (pr?.head?.repo?.full_name !== `${OWNER}/${REPO}` || pr?.base?.repo?.full_name !== `${OWNER}/${REPO}` || pr.base.ref !== 'main' || pr.state !== 'open') throw Error('Only an open same-repository PR targeting main is supported');
    const label=context.payload.label?.name || '';
    const recovery=/^deckpilot:(recover-preview|preflight-recovery):([1-9][0-9]*)$/.exec(label);
    mode = LABELS[label];
    if(recovery){mode=recovery[1]==='recover-preview'?'recover':'preflight';recovery_id=recovery[2];}
    if (!mode) throw Error('An explicit publication or preflight label is required');
    sha = pr.head.sha; channel = 'preview';
  } else if (context.eventName === 'workflow_dispatch') {
    ({commit: sha, channel, mode = 'preflight', recovery_id = ''} = context.payload.inputs);
  } else throw Error('Publication is never triggered by a push');
  if (!/^[a-f0-9]{40}$/.test(sha) || !['stable', 'preview'].includes(channel) || !['publish', 'preflight', 'recover'].includes(mode)) throw Error('Exact reviewed SHA, channel and mode required');
  if ((recovery_id && (!/^[1-9][0-9]*$/.test(recovery_id) || mode==='publish')) || (mode==='recover' && !recovery_id)) throw Error('Explicit exact recovery ID required; never recover implicitly');
  return {sha, channel, mode, recovery_id};
}
async function ownerProtection(github, context, channel) {
  const env = await github.rest.repos.getEnvironment({...context.repo, environment_name: `deckpilot-${channel}-publish`});
  const protectedByOwner = env.data.protection_rules?.some(r => r.type === 'required_reviewers' && r.reviewers?.length === 1 && r.reviewers[0].type === 'User' && r.reviewers[0].reviewer?.login === OWNER);
  if (!protectedByOwner) throw Error('Configure goddenator as sole required environment reviewer before publication or protected preflight');
}
async function guard(github, context, core) {
  const selected = selection(context);
  await ownerProtection(github, context, selected.channel);
  for (const [key, value] of Object.entries(selected)) core.setOutput(key, value);
}
async function revalidate(github, context, approved) {
  const selected = selection(context);
  if (selected.sha !== approved.sha || selected.channel !== approved.channel || selected.mode !== approved.mode || selected.recovery_id !== approved.recovery_id) throw Error('Approved selection changed');
  // Recheck protection after the environment gate as well as before it.
  await ownerProtection(github, context, selected.channel);
  if (context.eventName === 'pull_request') {
    const pr = (await github.rest.pulls.get({...context.repo, pull_number: context.issue.number})).data;
    if (pr.state !== 'open' || pr.head.sha !== approved.sha || pr.head.repo.full_name !== `${OWNER}/${REPO}` || pr.base.ref !== 'main' || pr.base.repo.full_name !== `${OWNER}/${REPO}`) throw Error('PR moved, closed or changed source/target. Approve the new commit separately.');
  }
}
module.exports = {selection, ownerProtection, guard, revalidate};
