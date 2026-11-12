const { spawnSync } = require('node:child_process');
const path = require('node:path');

module.exports = async function setupV2() {
  const root = path.resolve(__dirname, '../..');
  const python = process.env.FV_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const result = spawnSync(python, ['-B', 'tests/prepare_v2_browser.py'], { cwd: root, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`V2 fixture generation failed (${result.status})`);
};
