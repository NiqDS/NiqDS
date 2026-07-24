import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from skill.config import default_config


@pytest.fixture
def scratch_config(tmp_path):
    """A SkillConfig with every writable path redirected into tmp_path so

    tests never touch the checked-in sample_data/ or data/ directories.
    Metric scripts + demo reference data still point at the real bundled
    ones (read-only, safe to share across tests).
    """
    cfg = default_config()
    cfg.registry.involved_inns_path = tmp_path / "involved_inns.csv"
    cfg.registry.duplicates_path = tmp_path / "inn_duplicates.csv"
    cfg.registry.overlap_path = tmp_path / "metric_overlap.csv"
    cfg.registry.metric_requests_path = tmp_path / "metric_requests.csv"
    cfg.storage.pilots_root = tmp_path / "pilots"
    cfg.storage.navigator_dropzone = tmp_path / "navigator_dropzone"
    cfg.master_status.path = tmp_path / "inn_master_status.csv"
    return cfg
