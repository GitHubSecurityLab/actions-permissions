const core = require('@actions/core');
const github = require('@actions/github');
const AdmZip = require('adm-zip');

async function analyze(name, count, token, owner, repo, branch) {
  console.log(`Analyzing ${name} for the last ${count} successful runs.\n`);
  const octokit = github.getOctokit(token)

  const runs = await octokit.rest.actions.listWorkflowRuns({
    owner: owner,
    repo: repo,
    workflow_id: name,
    branch: branch,
    status: 'success',
    per_page: count,
    page: 1,
  });

  let permissions = new Map();

  for (const run of runs.data.workflow_runs) {
    if (process.env.RUNNER_DEBUG)
      console.log(`Analyzing run ${run.id}...`);

    const jobs = await octokit.rest.actions.listJobsForWorkflowRun({
      owner: owner,
      repo: repo,
      run_id: run.id,
    });

    if (process.env.RUNNER_DEBUG)
      console.log(`Found ${jobs.data.jobs.length} jobs.`)

    const artifacts = await octokit.rest.actions.listWorkflowRunArtifacts({
      owner: owner,
      repo: repo,
      run_id: run.id,
    });

    if (process.env.RUNNER_DEBUG)
      console.log(`${artifacts.data.artifacts.length} artifacts...`)

    for (const job of jobs.data.jobs) {
      if (job.conclusion !== 'success')
        continue;

      if (process.env.RUNNER_DEBUG) {
        console.log(`${job.name} ${job.id} was successful...`);
        console.log(`Downloading logs for job id ${job.id}...`);
      }

      let log = null;
      try {
        log = await octokit.rest.actions.downloadJobLogsForWorkflowRun({
          owner: owner,
          repo: repo,
          job_id: job.id,
        });
      } catch (e) {
        if (process.env.RUNNER_DEBUG)
          console.log(`Logs for the job ${job.id} are not available.`);
        continue;
      }

      const logUploadMatch = log.data.match(/^.* Container for artifact \"(.*-permissions-[a-z0-9]+)\" successfully created\. Starting upload of file\(s\)$/m);
      if (!logUploadMatch)
        continue;
      const artifactName = logUploadMatch[1];
      console.log(`Looking for artifactName ${artifactName}`);
      const jobName = artifactName.split('-').slice(0, -2).join('-');

      for (const artifact of artifacts.data.artifacts) {
        if (artifact.name === artifactName) {
          console.log(`Downloading artifact id ${artifact.id}`);
          const download = await octokit.rest.actions.downloadArtifact({
            owner: owner,
            repo: repo,
            artifact_id: artifact.id,
            archive_format: 'zip',
          });

          const zip = new AdmZip(Buffer.from(download.data));
          const zipEntries = zip.getEntries();
          const extracted = zip.readAsText(zipEntries[0]);
          const jobPermissions = new Map(Object.entries(JSON.parse(extracted)));

          if (!permissions.has(jobName)) {
            permissions.set(jobName, new Map());
          }

          const p = permissions.get(jobName);
          for (const [kind, perm] of jobPermissions) {
            if (p.has(kind)) {
              if (perm === "write") {
                p.set(kind, perm)
              }
            } else {
              p.set(kind, perm)
            }
          }
        }
      }
    }
  }

  return permissions;
}

async function run(name, count, token, owner, repo, branch) {
  const permissions = await analyze(name, count, token, owner, repo, branch);

  let summary = core.summary.addHeading(`Minimal required permissions for ${name}:`);
  console.log(`Minimal required permissions for ${name}:`);

  if (permissions.size === 0) {
    summary = summary.addRaw('No permissions logs were found.');
    console.log('No permissions logs were found.');
  } else {
    for (const [jobName, jobPermissions] of permissions) {
      summary = summary.addHeading(`${jobName}:`, 2);
      console.log(`---------------------= ${jobName} =---------------------`);

      let codeBlock = '';
      if (jobPermissions.size === 0) {
        codeBlock += 'permissions: {}';
        console.log('permissions: {}');
      } else {
        codeBlock += 'permissions:\n';
        console.log('permissions:');
        for (const [kind, perm] of jobPermissions) {
          codeBlock += `  ${kind}: ${perm}\n`;
          console.log(`  ${kind}: ${perm}`);
        }
      }

      summary = summary.addCodeBlock(codeBlock, 'yaml');
    }
  }

  if (process.env.GITHUB_ACTIONS) {
    await summary.write();
  }
}

if (!process.env.GITHUB_ACTIONS && process.argv.length !== 7) {
  console.log('Usage: node index.js <number_of_the_last_runs> <github_owner> <repo_name> <branch_name>');
  console.log('For example: node index.js ci.yml 10 github actions-permissions main');
  process.exit(1);
}

if (process.env.GITHUB_ACTIONS) {
  const name = core.getInput('name');
  const count = core.getInput('count');
  const token = core.getInput('token');

  run(name, count, token, github.context.repo.owner, github.context.repo.repo, github.context.ref.split('/').slice(-1)[0]).catch(error => {
    core.setFailed(error.message);
  });
} else {
  run(process.argv[2], process.argv[3], process.env.GITHUB_TOKEN, process.argv[4], process.argv[5], process.argv[6]).catch(error => {
    console.log(`Error: ${error.message}`);
  });
}