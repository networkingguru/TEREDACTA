from click.testing import CliRunner
from teredacta.__main__ import cli


class TestStartMultiWorker:
    def test_start_accepts_workers_config(self, tmp_path):
        """start no longer rejects workers > 1."""
        cfg = tmp_path / "teredacta.yaml"
        cfg.write_text("workers: 4\nhost: 127.0.0.1\nport: 19999\ndb_path: /nonexistent\n")
        pid_file = str(tmp_path / "teredacta.pid")
        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--config", str(cfg), "--pid-file", pid_file])
        assert "Multi-worker mode is not supported" not in result.output
