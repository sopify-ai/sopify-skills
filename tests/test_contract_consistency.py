from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.failure_recovery import (
    DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH,
    load_failure_recovery_schema,
)
from runtime.manifest import build_bundle_manifest


class ContractConsistencyTests(unittest.TestCase):
    def test_allowed_response_modes_match_manifest_limits(self) -> None:
        schema = load_failure_recovery_schema(DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH)
        manifest = build_bundle_manifest(bundle_root=REPO_ROOT, source_root=REPO_ROOT)
        self.assertEqual(
            schema["allowed_response_modes"],
            manifest.limits["runtime_gate_allowed_response_modes"],
        )

