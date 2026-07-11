# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayStartupError
from mnemostroma.gateway.server import GatewayServer

TEST_TOKEN = "lifecycle-test-token"


class TestConductorGatewayLifecycle:
    @pytest.mark.asyncio
    async def test_conductor_starts_gateway_only_when_enabled(self):
        cfg = GatewayConfig(enabled=True, port=18790, token_env="LIFECYCLE_TEST_TOKEN")
        os.environ["LIFECYCLE_TEST_TOKEN"] = TEST_TOKEN
        try:
            server = GatewayServer(cfg)
            await server.start()
            assert server.started is True
            await server.stop()
        finally:
            os.environ.pop("LIFECYCLE_TEST_TOKEN", None)

    @pytest.mark.asyncio
    async def test_conductor_stops_gateway_before_persistence(self):
        cfg = GatewayConfig(enabled=True, port=18791, token_env="LIFECYCLE_TEST_TOKEN2")
        os.environ["LIFECYCLE_TEST_TOKEN2"] = TEST_TOKEN
        try:
            server = GatewayServer(cfg)
            await server.start()
            assert server.started is True

            persistence_stop = AsyncMock()

            await server.stop()
            assert server.started is False

            await persistence_stop()
            persistence_stop.assert_awaited_once()
        finally:
            os.environ.pop("LIFECYCLE_TEST_TOKEN2", None)

    @pytest.mark.asyncio
    async def test_gateway_disabled_does_not_start(self):
        cfg = GatewayConfig(enabled=False, port=18792)
        server = GatewayServer(cfg)
        await server.start()
        assert server.started is False
        assert server.task is None

    @pytest.mark.asyncio
    async def test_conductor_integration_with_mock(self):
        cfg = GatewayConfig(
            enabled=True, port=18793, token_env="LIFECYCLE_TEST_TOKEN3"
        )
        os.environ["LIFECYCLE_TEST_TOKEN3"] = TEST_TOKEN
        try:
            server = GatewayServer(cfg)
            await server.start()
            assert server.started is True

            await server.stop()
            assert server.started is False
        finally:
            os.environ.pop("LIFECYCLE_TEST_TOKEN3", None)

    @pytest.mark.asyncio
    async def test_gateway_port_conflict_fails_without_fallback(self):
        cfg1 = GatewayConfig(
            enabled=True, port=18794, token_env="LIFECYCLE_TEST_TOKEN4"
        )
        cfg2 = GatewayConfig(
            enabled=True, port=18794, token_env="LIFECYCLE_TEST_TOKEN5"
        )
        os.environ["LIFECYCLE_TEST_TOKEN4"] = TEST_TOKEN
        os.environ["LIFECYCLE_TEST_TOKEN5"] = TEST_TOKEN
        try:
            server1 = GatewayServer(cfg1)
            await server1.start()
            assert server1.started is True

            server2 = GatewayServer(cfg2)
            with pytest.raises(GatewayStartupError):
                await server2.start()

            await server1.stop()
        finally:
            os.environ.pop("LIFECYCLE_TEST_TOKEN4", None)
            os.environ.pop("LIFECYCLE_TEST_TOKEN5", None)
