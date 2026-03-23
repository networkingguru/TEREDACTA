from teredacta.config import TeredactaConfig

def test_default_workers_is_1():
    cfg = TeredactaConfig()
    assert cfg.workers == 1

def test_workers_from_init():
    cfg = TeredactaConfig(workers=4)
    assert cfg.workers == 4
