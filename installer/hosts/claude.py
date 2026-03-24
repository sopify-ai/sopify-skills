"""Claude host adapter."""

from __future__ import annotations

from installer.models import EntryMode, FeatureId, HostCapability, SupportTier

from .base import HostAdapter, HostRegistration

CLAUDE_ADAPTER = HostAdapter(
    host_name="claude",
    source_dirname="Claude",
    destination_dirname=".claude",
    header_filename="CLAUDE.md",
)

CLAUDE_CAPABILITY = HostCapability(
    host_id="claude",
    support_tier=SupportTier.DEEP_VERIFIED,
    install_enabled=True,
    declared_features=(
        FeatureId.PROMPT_INSTALL,
        FeatureId.PAYLOAD_INSTALL,
        FeatureId.WORKSPACE_BOOTSTRAP,
        FeatureId.RUNTIME_GATE,
        FeatureId.PREFERENCES_PRELOAD,
        FeatureId.HANDOFF_FIRST,
        FeatureId.HOST_BRIDGE,
    ),
    verified_features=(
        FeatureId.PROMPT_INSTALL,
        FeatureId.PAYLOAD_INSTALL,
        FeatureId.WORKSPACE_BOOTSTRAP,
        FeatureId.RUNTIME_GATE,
        FeatureId.PREFERENCES_PRELOAD,
        FeatureId.HANDOFF_FIRST,
        FeatureId.HOST_BRIDGE,
        FeatureId.SMOKE_VERIFIED,
    ),
    entry_modes=(EntryMode.PROMPT_ONLY,),
    doctor_checks=(
        "host_prompt_present",
        "payload_present",
        "workspace_bundle_manifest",
        "workspace_handoff_first",
        "workspace_preferences_preload",
        "bundle_smoke",
    ),
    smoke_targets=("bundle_runtime_smoke",),
)

CLAUDE_HOST = HostRegistration(adapter=CLAUDE_ADAPTER, capability=CLAUDE_CAPABILITY)
