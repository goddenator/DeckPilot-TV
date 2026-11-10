// Shared by the real workflow and its non-publishing contract tests.
const OWNER = 'goddenator';
const REPO = 'DeckPilot-TV';
const LABELS = {'deckpilot:publish-preview': 'publish', 'deckpilot:preflight-preview': 'preflight'};
function selection(context) {
  if (context.repo.owner !== OWNER || context.repo.repo !== REPO) throw Error('Unexpected repository');
  let sha, channel, mode;
  if (context.eventName === 'pull_request') {
    const pr = context.payload.pull_request;
    if (pr?.head?.repo?.full_name !== `${OWNER}/${REPO}` || pr?.base?.repo?.full_name !== `${OWNER}/${REPO}` || pr.base.ref !== 'main' || pr.state !== 'open') throw Error('Only an open same-repository PR targeting main is supported');
    mode = LABELS[context.payload.label?.name];
    if (!mode) throw Error('An explicit publication or preflight label is required');
    sha = pr.head.sha; channel = 'preview';
  } else if (context.eventName === 'workflow_dispatch') {
    ({commit: sha, channel, mode = 'preflight'} = context.payload.inputs);
  } else throw Error('Publication is never triggered by a push');
  if (!/^[a-f0-9]{40}$/.test(sha) || !['stable', 'preview'].includes(channel) || !['publish', 'preflight'].includes(mode)) throw Error('Exact reviewed SHA, channel and mode required');
  return {sha, channel, mode};
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
  if (selected.sha !== approved.sha || selected.channel !== approved.channel || selected.mode !== approved.mode) throw Error('Approved selection changed');
  // Recheck protection after the environment gate as well as before it.
  await ownerProtection(github, context, selected.channel);
  if (context.eventName === 'pull_request') {
    const pr = (await github.rest.pulls.get({...context.repo, pull_number: context.issue.number})).data;
    if (pr.state !== 'open' || pr.head.sha !== approved.sha || pr.head.repo.full_name !== `${OWNER}/${REPO}` || pr.base.ref !== 'main' || pr.base.repo.full_name !== `${OWNER}/${REPO}`) throw Error('PR moved, closed or changed source/target. Approve the new commit separately.');
  }
}
module.exports = {selection, ownerProtection, guard, revalidate};
