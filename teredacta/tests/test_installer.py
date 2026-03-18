from click.testing import CliRunner
from teredacta.__main__ import cli


class TestInstaller:
    def test_install_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output.lower()
