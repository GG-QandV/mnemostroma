# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import pytest

from mnemostroma.gateway.errors import GatewayParseError
from mnemostroma.gateway.openai import parse_chat_completions


class TestPayloadValidation:
    def test_requires_object_payload(self):
        with pytest.raises(GatewayParseError, match="object"):
            parse_chat_completions("not a dict")

    def test_rejects_non_object_json(self):
        with pytest.raises(GatewayParseError, match="object"):
            parse_chat_completions([])

    def test_rejects_none(self):
        with pytest.raises(GatewayParseError, match="object"):
            parse_chat_completions(None)


class TestModel:
    def test_requires_model(self):
        with pytest.raises(GatewayParseError, match="model"):
            parse_chat_completions({"messages": [{"role": "user", "content": "hi"}]})

    def test_rejects_empty_model(self):
        with pytest.raises(GatewayParseError, match="model"):
            payload = {"model": "", "messages": [{"role": "user", "content": "hi"}]}
            parse_chat_completions(payload)

    def test_rejects_non_string_model(self):
        with pytest.raises(GatewayParseError, match="model"):
            payload = {"model": 123, "messages": [{"role": "user", "content": "hi"}]}
            parse_chat_completions(payload)


class TestMessages:
    def test_requires_nonempty_messages(self):
        with pytest.raises(GatewayParseError, match="messages"):
            parse_chat_completions({"model": "gpt-4"})

    def test_rejects_empty_messages_list(self):
        with pytest.raises(GatewayParseError, match="messages"):
            parse_chat_completions({"model": "gpt-4", "messages": []})

    def test_rejects_non_list_messages(self):
        with pytest.raises(GatewayParseError, match="messages"):
            parse_chat_completions({"model": "gpt-4", "messages": "hi"})

    def test_validates_message_roles(self):
        with pytest.raises(GatewayParseError, match="role"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "invalid", "content": "hi"}]
            })

    def test_rejects_non_string_content(self):
        with pytest.raises(GatewayParseError, match="content"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": ["array"]}]
            })

    def test_rejects_multimodal_content(self):
        with pytest.raises(GatewayParseError, match="content"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": "hi"}]
                }]
            })

    def test_rejects_missing_content(self):
        with pytest.raises(GatewayParseError, match="content"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user"}]
            })


class TestUnsupportedFields:
    def test_rejects_tools(self):
        with pytest.raises(GatewayParseError, match="tools"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"type": "function"}],
            })

    def test_rejects_tool_choice(self):
        with pytest.raises(GatewayParseError, match="tool_choice"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "tool_choice": "auto",
            })

    def test_rejects_functions(self):
        with pytest.raises(GatewayParseError, match="functions"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "functions": [],
            })

    def test_rejects_function_call(self):
        with pytest.raises(GatewayParseError, match="function_call"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "function_call": "none",
            })

    def test_rejects_response_format(self):
        with pytest.raises(GatewayParseError, match="response_format"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {"type": "json_object"},
            })

    def test_rejects_unknown_top_level_field(self):
        with pytest.raises(GatewayParseError, match="unknown_field"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "unknown_field": "value",
            })

    def test_rejects_extra_field_in_message(self):
        with pytest.raises(GatewayParseError, match="extra_field"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi", "extra_field": "v"}],
            })

    def test_rejects_seed(self):
        with pytest.raises(GatewayParseError, match="seed"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "seed": 42,
            })

    def test_rejects_n(self):
        with pytest.raises(GatewayParseError, match="n"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "n": 2,
            })


class TestValidPayloads:
    def test_accepts_minimal_payload(self):
        req = parse_chat_completions({
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hello"}],
        })
        assert req.model == "gpt-4"
        assert len(req.messages) == 1
        assert req.messages[0].role == "user"
        assert req.messages[0].content == "hello"
        assert req.stream is False
        assert req.temperature is None
        assert req.max_tokens is None

    def test_accepts_full_allowed_payload(self):
        req = parse_chat_completions({
            "model": "claude-3",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ],
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 1024,
        })
        assert req.model == "claude-3"
        assert len(req.messages) == 3
        assert req.stream is True
        assert req.temperature == 0.7
        assert req.max_tokens == 1024

    def test_accepts_stream_false(self):
        req = parse_chat_completions({
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        assert req.stream is False


class TestTypeValidation:
    def test_rejects_non_numeric_temperature(self):
        with pytest.raises(GatewayParseError, match="temperature"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": "hot",
            })

    def test_rejects_out_of_range_temperature(self):
        with pytest.raises(GatewayParseError, match="temperature"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 5.0,
            })

    def test_rejects_negative_max_tokens(self):
        with pytest.raises(GatewayParseError, match="max_tokens"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": -1,
            })

    def test_rejects_non_int_max_tokens(self):
        with pytest.raises(GatewayParseError, match="max_tokens"):
            parse_chat_completions({
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": "lots",
            })


class TestAllowedRoles:
    @pytest.mark.parametrize("role", ["system", "user", "assistant"])
    def test_accepts_allowed_roles(self, role):
        req = parse_chat_completions({
            "model": "gpt-4",
            "messages": [{"role": role, "content": "test"}],
        })
        assert req.messages[0].role == role
