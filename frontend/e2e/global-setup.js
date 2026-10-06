const MCR = require('monocart-coverage-reports');
const { options } = require('./coverage');

module.exports = async () => {
  await MCR({ ...options }).cleanCache();
};
