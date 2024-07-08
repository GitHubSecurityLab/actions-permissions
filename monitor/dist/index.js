/******/ (() => { // webpackBootstrap
/******/ 	var __webpack_modules__ = ({

/***/ 668:
/***/ ((module) => {

module.exports = eval("require")("@actions/artifact");


/***/ }),

/***/ 376:
/***/ ((module) => {

module.exports = eval("require")("@actions/core");


/***/ }),

/***/ 81:
/***/ ((module) => {

"use strict";
module.exports = require("child_process");

/***/ }),

/***/ 113:
/***/ ((module) => {

"use strict";
module.exports = require("crypto");

/***/ }),

/***/ 147:
/***/ ((module) => {

"use strict";
module.exports = require("fs");

/***/ })

/******/ 	});
/************************************************************************/
/******/ 	// The module cache
/******/ 	var __webpack_module_cache__ = {};
/******/ 	
/******/ 	// The require function
/******/ 	function __nccwpck_require__(moduleId) {
/******/ 		// Check if module is in cache
/******/ 		var cachedModule = __webpack_module_cache__[moduleId];
/******/ 		if (cachedModule !== undefined) {
/******/ 			return cachedModule.exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = __webpack_module_cache__[moduleId] = {
/******/ 			// no module.id needed
/******/ 			// no module.loaded needed
/******/ 			exports: {}
/******/ 		};
/******/ 	
/******/ 		// Execute the module function
/******/ 		var threw = true;
/******/ 		try {
/******/ 			__webpack_modules__[moduleId](module, module.exports, __nccwpck_require__);
/******/ 			threw = false;
/******/ 		} finally {
/******/ 			if(threw) delete __webpack_module_cache__[moduleId];
/******/ 		}
/******/ 	
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/ 	
/************************************************************************/
/******/ 	/* webpack/runtime/compat */
/******/ 	
/******/ 	if (typeof __nccwpck_require__ !== 'undefined') __nccwpck_require__.ab = __dirname + "/";
/******/ 	
/************************************************************************/
var __webpack_exports__ = {};
// This entry need to be wrapped in an IIFE because it need to be isolated against other modules in the chunk.
(() => {
const core = __nccwpck_require__(376);
const {DefaultArtifactClient} = __nccwpck_require__(668)
const crypto = __nccwpck_require__(113);
const fs = __nccwpck_require__(147);

async function run() {
  try {
    const configString = core.getInput('config');
    let config = {};
    if (configString) {
      config = JSON.parse(configString);
    }
    if (!config.hasOwnProperty('create_artifact')) {
      config['create_artifact'] = true;
    }
    if (!config.hasOwnProperty('enabled')) {
      config['enabled'] = true;
    }
    if (!config.hasOwnProperty('debug')) {
      config['debug'] = false;
    }

    if (!config.enabled)
      return;

    const debug = core.getInput('debug').toUpperCase() === 'TRUE' || config.debug || process.env.RUNNER_DEBUG;
    if (debug) {
      // for the bash script
      core.exportVariable('RUNNER_DEBUG', 1);
    }

    const hosts = new Set();
    hosts.add(process.env.GITHUB_SERVER_URL.split('/')[2].toLowerCase());
    hosts.add(process.env.GITHUB_API_URL.split('/')[2].toLowerCase());
    if (process.env.ACTIONS_ID_TOKEN_REQUEST_URL) {
      hosts.add(process.env.ACTIONS_ID_TOKEN_REQUEST_URL.split('/')[2].toLowerCase());
    }

    if (!!core.getState('isPost')) {

      let rootDir = '';
      if (process.env.RUNNER_OS === 'Linux') {
        rootDir = '/home/mitmproxyuser';
      } else if (process.env.RUNNER_OS === 'macOS') {
        rootDir = '/Users/mitmproxyuser';
      }

      const debugLog = `${rootDir}/debug.log`;
      if (fs.existsSync(debugLog)) {
        // using core.info instead of core.debug to print even if the runner itself doesn't run in debug mode
        core.info(fs.readFileSync(debugLog, 'utf8'));
      }

      const data = fs.readFileSync(`${rootDir}/out.txt`, 'utf8');
      if (debug)
        console.log(`logged: ${data}`);

      const errorLog = `${rootDir}/error.log`;
      if (fs.existsSync(errorLog)) {
        core.setFailed(fs.readFileSync(errorLog, 'utf8'));
        process.exit(1);
      }

      const results = JSON.parse(`[${data.trim().replace(/\r?\n|\r/g, ',')}]`);

      let permissions = new Map();
      let wasUnknown = false;
      for (const result of results) {
        if (!hosts.has(result.host.toLowerCase()))
          continue;

        for (const p of result.permissions) {
          const kind = Object.keys(p)[0];
          const perm = p[kind];

          if (kind === 'unknown') {
            core.warning(`The github token was used to call ${result.method} ${result.host}${result.path} but the permission is unknown. Please report this to the action author.`);
            wasUnknown = true;
            continue;
          }

          if (permissions.has(kind)) {
            if (perm === "write") {
              permissions.set(kind, perm)
            }
          } else {
            permissions.set(kind, perm)
          }
        }
      }

      let summary = 'permissions:';
      if (permissions.size === 0) {
        summary += ' {}'
      } else {
        summary += '\n'
        for (const [kind, perm] of permissions) {
          summary += `  ${kind}: ${perm}\n`;
        }
      }

      if (wasUnknown) {
        summary += "\nAt least one call wasn't recognized. Please check the logs and report this to the action author.";
      }

      core.summary
        .addRaw('#### Minimal required permissions:\n')
        .addCodeBlock(summary, 'yaml')
        .write();

      if (config.create_artifact) {
        const tempDirectory = process.env['RUNNER_TEMP'];
        fs.writeFileSync(`${tempDirectory}/permissions`, JSON.stringify(Object.fromEntries(permissions)));
        await new DefaultArtifactClient().uploadArtifact(
          `${process.env['GITHUB_JOB']}-permissions-${crypto.randomBytes(16).toString("hex")}`,
          [`${tempDirectory}/permissions`],
          tempDirectory,
          { continueOnError: false }
        );
      }
    }
    else {
      core.saveState('isPost', true)
      const { spawn } = __nccwpck_require__(81);

      bashArgs = ['-e', 'setup.sh', Array.from(hosts).join(",")];
      if (debug)
        bashArgs.unshift('-v');

      const command = spawn('bash', bashArgs, { cwd: `${__dirname}/..` })

      command.stdout.on('data', output => {
        console.log(output.toString())
        if (output.toString().includes('--all done--')) {
          process.exit(0)
        }
      })
      command.stderr.on('data', output => {
        core.warning(output.toString())
      })
      command.on('exit', code => {
        if (code !== 0) {
          core.setFailed(`Exited with code ${code}`);
          process.exit(code);
        }
      })
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();

})();

module.exports = __webpack_exports__;
/******/ })()
;