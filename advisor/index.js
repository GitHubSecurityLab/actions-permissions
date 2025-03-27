const core = require('@actions/core');
const github = require('@actions/github');
const AdmZip = require('adm-zip');

let verbose = false;
let log = null;
let debug = (msg) => { if (verbose) { log(msg); } }

async function analyze(name, count, token, owner, repo, branch) {
  log(`Analyzing ${name} for the last ${count} successful runs.\n`);
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
  let wasUnknown = false;

  for (const run of runs.data.workflow_runs) {
    debug(`Analyzing run ${run.id}...`);

    const jobs = await octokit.rest.actions.listJobsForWorkflowRun({
      owner: owner,
      repo: repo,
      run_id: run.id,
    });

    debug(`Found ${jobs.data.jobs.length} jobs.`)

    const artifacts = await octokit.rest.actions.listWorkflowRunArtifacts({
      owner: owner,
      repo: repo,
      run_id: run.id,
    });

    debug(`${artifacts.data.artifacts.length} artifacts...`)

    for (const job of jobs.data.jobs) {
      if (job.conclusion !== 'success')
        continue;

      debug(`${job.name} ${job.id} was successful...`);
      debug(`Downloading logs for job id ${job.id}...`);

      let workflowRunLog = null;
      try {
        workflowRunLog = await octokit.rest.actions.downloadJobLogsForWorkflowRun({
          owner: owner,
          repo: repo,
          job_id: job.id,
        });
      } catch (e) {
        debug(`Logs for the job ${job.id} are not available.`);
        continue;
      }

      const logUploadMatch = workflowRunLog.data.match(/([^ "]+-permissions-[a-z0-9]{32})/m);
      if (!logUploadMatch) {
        debug(`Cannot find the magic string. Skipping.`);
        continue;
      }
      const artifactName = logUploadMatch[1];
      debug(`Looking for artifactName ${artifactName}`);
      const jobName = artifactName.split('-').slice(0, -2).join('-');

      for (const artifact of artifacts.data.artifacts) {
        if (artifact.name === artifactName) {
          debug(`Downloading artifact id ${artifact.id}`);
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
            if (kind === 'unknown') {
              wasUnknown = true;
              continue;
            }

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

  return [permissions, wasUnknown];
}

async function run(token, name, count, owner, repo, branch, format) {
  const [permissions, wasUnknown] = await analyze(name, count, token, owner, repo, branch);

  let summary = core.summary.addHeading(`Minimal required permissions for ${name}:`);
  log(`Minimal required permissions for ${name}:`);

  if (wasUnknown) {
    summary.addRaw("\nAt least one call wasn't recognized. Some permissions are unknown. Check the workflow runs.\n");
  }

  try {
    if (permissions.size === 0) {
      summary = summary.addRaw('No permissions logs were found.');
      throw new Error('No permissions logs were found.');
    } else {
      let additionalIndent = '';
      if (format)
        additionalIndent = '  ';

      for (const [jobName, jobPermissions] of permissions) {
        summary = summary.addHeading(`${jobName}:`, 2);
        log(`---------------------= ${jobName} =---------------------`);
        if (format)
          console.log(`${jobName}:`);

        let codeBlock = '';
        if (jobPermissions.size === 0) {
          codeBlock += `${additionalIndent}permissions: {}`;
        } else {
          codeBlock += `${additionalIndent}permissions:\n`;
          for (const [kind, perm] of jobPermissions) {
            codeBlock += `${additionalIndent}  ${kind}: ${perm}\n`;
          }
        }
  
        console.log(codeBlock); // write always
        summary = summary.addCodeBlock(codeBlock, 'yaml');
      }
    }
  } finally {
    if (process.env.GITHUB_ACTIONS) {
      await summary.write();
    }
  }
}

function printUsageAndExit() {
  console.log('Usage: node index.js <number_of_the_last_runs> <github_owner> <repo_name> <branch_name> [--format yaml] [--verbose]');
  console.log('For example: node index.js ci.yml 10 github actions-permissions main --format yaml --verbose');
  process.exit(1);
}

verbose = false;
log = console.log;

if (process.env.GITHUB_ACTIONS) {
  const name = core.getInput('name');
  const count = core.getInput('count');
  const token = core.getInput('token');
  verbose = process.env.RUNNER_DEBUG ? true : false;
  const branch = github.context.ref.split('/').slice(-1)[0];
  const format = null;

  run(token, name, count, github.context.repo.owner, github.context.repo.repo, branch, format).catch(error => {
    core.setFailed(error.message);
  });
} else {
  const args = process.argv.slice(2);
  const outputIndex = args.indexOf('--format');
  let format = null;

  if (outputIndex !== -1) {
    if (outputIndex + 1 >= args.length) {
      printUsageAndExit();
    }
    format = args[outputIndex + 1];
    if (!format || format !== 'yaml') {
      printUsageAndExit();
    }
    args.splice(outputIndex, 2); // Remove --output and its value from args
  }

  const debugIndex = args.indexOf('--verbose');
  if (debugIndex !== -1) {
    verbose = true;
    args.splice(debugIndex, 1); // Remove --verbose from args
  }

  if (args.length !== 5) {
    printUsageAndExit();
  }

  const [name, count, owner, repo, branch] = args;
  if (format !== null) {
    log = () => {};
  }

  run(process.env.GITHUB_TOKEN, name, count, owner, repo, branch, format).catch(error => {
    console.error(`Error: ${error.message}`);
    exit(2);
  });
}