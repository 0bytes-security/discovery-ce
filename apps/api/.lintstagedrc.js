const buildRuffCheckCommand = (filenames) => {
  return `poetry run ruff check ${filenames.join(' ')}`;
};

const buildRuffFormatCommand = (filenames) => {
  return `poetry run ruff format ${filenames.join(' ')}`;
};

module.exports = {
  '*.py': [buildRuffCheckCommand, buildRuffFormatCommand]
};
