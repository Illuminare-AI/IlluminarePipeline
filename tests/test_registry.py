import pytest

from factcheck.config import Settings
from factcheck.llm.providers.anthropic import AnthropicChat
from factcheck.llm.providers.openai_compat import OpenAICompatChat
from factcheck.llm.registry import ModelRegistry, parse_spec


def _settings(**kw):
    return Settings(_env_file=None, **kw)


def test_parse_spec():
    assert parse_spec("anthropic:claude-opus-5") == ("anthropic", "claude-opus-5")
    assert parse_spec("ollama:gemma3:12b") == ("ollama", "gemma3:12b")
    assert parse_spec("claude-haiku-4-5") == ("anthropic", "claude-haiku-4-5")
    with pytest.raises(ValueError, match="provider prefix"):
        parse_spec("gpt-5")
    with pytest.raises(ValueError, match="no model"):
        parse_spec("openai:")


def test_anthropic_models_share_one_client():
    reg = ModelRegistry(_settings(anthropic_api_key="k"))
    a, b = reg.build("anthropic:claude-opus-5"), reg.build("claude-haiku-4-5")
    assert isinstance(a, AnthropicChat) and a.client is b.client
    assert a.capabilities.supports_effort and not b.capabilities.supports_effort


def test_openai_reasoning_model_knobs():
    chat = ModelRegistry(_settings(openai_api_key="k")).build("openai:gpt-5")
    assert isinstance(chat, OpenAICompatChat)
    assert chat.effort_param == "reasoning_effort" and chat.temperature is None
    assert chat.max_tokens_param == "max_completion_tokens" and chat.schema_mode == "strict"
    plain = ModelRegistry(_settings(openai_api_key="k")).build("openai:gpt-4.1")
    assert plain.effort_param is None and plain.temperature == 0.0


def test_ollama_needs_no_key_and_uses_the_local_url():
    chat = ModelRegistry(_settings(ollama_url="http://box:11434/")).build("ollama:gemma3:12b")
    assert str(chat.client.base_url).startswith("http://box:11434/v1")
    assert chat.schema_mode == "json_schema" and chat.capabilities.supports_images
    assert chat.provider == "ollama" and chat.max_tokens_param == "max_tokens"


def test_kimi_is_text_only_with_prompt_json():
    chat = ModelRegistry(_settings(moonshot_api_key="k")).build("kimi:kimi-k2")
    assert not chat.capabilities.supports_images and chat.schema_mode == "none"
    assert "moonshot" in str(chat.client.base_url)


def test_text_only_override_and_missing_key():
    reg = ModelRegistry(_settings(openai_api_key="k", llm_text_only_models="gpt-4.1-nano"))
    assert not reg.build("openai:gpt-4.1-nano").capabilities.supports_images
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        ModelRegistry(_settings()).build("gemini:gemini-2.5-flash")


def test_build_llm_wires_the_three_roles(monkeypatch):
    from factcheck.deps import build_llm

    llm = build_llm(_settings(llm_backend="live", anthropic_api_key="k", openai_api_key="k",
                              llm_model="openai:gpt-5", llm_search_model="anthropic:claude-sonnet-5-5"))
    assert llm.judge.provider == "openai" and llm.search.provider == "anthropic"
    with pytest.raises(ValueError, match="server-side search"):
        build_llm(_settings(llm_backend="live", openai_api_key="k", llm_model="openai:gpt-5",
                            llm_fast_model="openai:gpt-5", llm_search_model="openai:gpt-5"))
