# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import json
import time

from mnemostroma.gateway.provider import ProviderRequest, ProviderResponse


class FakeProviderTransport:
    async def send(self, request: ProviderRequest) -> ProviderResponse:
        body = json.dumps({
            "id": "chatcmpl_mnemo_fake_001",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Fake transport response",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        })
        return ProviderResponse(status=200, body=body)
