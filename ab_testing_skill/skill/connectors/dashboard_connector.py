"""Pluggable "Навигатор" (Navigator BI tool) upload -- spec step 6.

No public API contract was available for Navigator in this environment, so
the default connector just copies the financial-effect workbook into a
local dropzone folder and returns a placeholder link. Replace with a real
HTTP client once Navigator's upload API is known -- `pipeline.py` and
`monitoring.py` only depend on the `DashboardConnector` Protocol below.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class DashboardConnector(Protocol):
    def upload(self, pilot_name: str, workbook_path: Path) -> str:
        """Uploads/refreshes the dashboard source file, returns a dashboard URL (or a local reference)."""
        ...


class LocalDropzoneDashboardConnector:
    """Default connector: copies the workbook into `dropzone_dir` (mirroring

    what a human would currently do by hand) and returns a `file://` link.
    """

    def __init__(self, dropzone_dir: Path):
        self.dropzone_dir = Path(dropzone_dir)
        self.dropzone_dir.mkdir(parents=True, exist_ok=True)

    def upload(self, pilot_name: str, workbook_path: Path) -> str:
        dest = self.dropzone_dir / f"{pilot_name}{workbook_path.suffix}"
        shutil.copyfile(workbook_path, dest)
        return f"file://{dest.resolve()}"


class HttpNavigatorConnector:
    """Production connector -- fill in once Navigator's real upload API

    contract is known (endpoint, auth, multipart field name, response
    shape for the dashboard URL). Left as a documented stub rather than a
    guess, since inventing an API surface here would be worse than an
    explicit NotImplementedError.
    """

    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url
        self.api_token = api_token

    def upload(self, pilot_name: str, workbook_path: Path) -> str:
        raise NotImplementedError(
            "Wire this to Navigator's real upload endpoint once the API "
            "contract is available -- see docstring."
        )
