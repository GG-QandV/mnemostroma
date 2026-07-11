# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ProviderPlan


def build_dispatch_plan(config: GatewayConfig) -> ProviderPlan:
    if config.provider_mode == "disabled":
        return ProviderPlan(
            mode="disabled",
            would_dispatch=False,
            upstream_path=None,
        )

    return ProviderPlan(
        mode="configured",
        would_dispatch=True,
        upstream_path="/v1/chat/completions",
    )
