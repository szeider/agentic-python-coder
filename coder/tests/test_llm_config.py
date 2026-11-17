"""Tests for model-config loading and api_params mapping in llm.py."""

import json
import subprocess
import types
from pathlib import Path

import pytest

from agentic_python_coder.llm import (
    get_openrouter_llm,
    list_available_models,
    load_model_config,
)


def write_config(tmp_path, name, cfg):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(cfg))
    return str(path)


class TestLoadModelConfig:
    def test_invalid_json_raises_value_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_model_config(str(path))

    def test_missing_path_key_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, "nopath", {"temperature": 0.0})
        with pytest.raises(ValueError, match="'path'"):
            load_model_config(cfg_path)

    def test_unknown_model_lists_available(self):
        with pytest.raises(FileNotFoundError, match="sonnet45"):
            load_model_config("definitely-not-a-model")


class TestApiParamsMapping:
    def test_standard_sampling_params(self, tmp_path):
        cfg = write_config(
            tmp_path,
            "std",
            {"path": "x/y", "temperature": 0.3, "max_tokens": 100, "top_p": 0.9},
        )
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert llm.api_params["temperature"] == 0.3
        assert llm.api_params["max_tokens"] == 100
        assert llm.api_params["top_p"] == 0.9

    def test_no_sampling_params_drops_temperature(self, tmp_path):
        cfg = write_config(
            tmp_path,
            "nsp",
            {
                "path": "x/y",
                "temperature": 0.0,
                "max_tokens": 100,
                "no_sampling_params": True,
            },
        )
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert "temperature" not in llm.api_params
        assert llm.api_params["max_tokens"] == 100

    def test_top_k_provider_reasoning_go_to_extra_body(self, tmp_path):
        cfg = write_config(
            tmp_path,
            "extra",
            {
                "path": "x/y",
                "top_k": 40,
                "provider": {"order": ["anthropic"]},
                "reasoning": {"effort": "low"},
            },
        )
        llm = get_openrouter_llm(model=cfg, api_key="k")
        extra = llm.api_params["extra_body"]
        assert extra["top_k"] == 40
        assert extra["provider"] == {"order": ["anthropic"]}
        assert extra["reasoning"] == {"effort": "low"}

    def test_request_timeout_configures_client(self, tmp_path):
        cfg = write_config(tmp_path, "timeout", {"path": "x/y", "request_timeout": 77})
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert llm.client.timeout == 77

    def test_default_endpoint_is_openrouter_with_headers(self, tmp_path):
        cfg = write_config(tmp_path, "plain", {"path": "x/y"})
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert "openrouter.ai" in str(llm.client.base_url)
        assert "HTTP-Referer" in llm.client.default_headers


class TestReasoningEffort:
    def test_reasoning_effort_is_top_level_param(self, tmp_path):
        cfg = write_config(
            tmp_path,
            "re",
            {"path": "x/y", "temperature": 0.2, "reasoning_effort": "low"},
        )
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert llm.api_params["reasoning_effort"] == "low"
        assert llm.api_params["temperature"] == 0.2
        assert "reasoning_effort" not in llm.api_params.get("extra_body", {})

    def test_reasoning_effort_with_no_sampling_params(self, tmp_path):
        cfg = write_config(
            tmp_path,
            "re_nsp",
            {
                "path": "x/y",
                "temperature": 0.0,
                "no_sampling_params": True,
                "reasoning_effort": "none",
            },
        )
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert llm.api_params == {"reasoning_effort": "none"}

    def test_no_reasoning_effort_without_field(self, tmp_path):
        cfg = write_config(tmp_path, "plain", {"path": "x/y", "temperature": 0.0})
        llm = get_openrouter_llm(model=cfg, api_key="k")
        assert "reasoning_effort" not in llm.api_params

    def test_readme_openai_example(self, tmp_path, monkeypatch):
        # The OpenAI example of README.md, section "Custom Models and Endpoints"
        cfg = write_config(
            tmp_path,
            "openai",
            {
                "path": "gpt-6-luna",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "reasoning_effort": "none",
            },
        )
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        llm = get_openrouter_llm(model=cfg)
        assert str(llm.client.base_url).rstrip("/") == "https://api.openai.com/v1"
        assert llm.client.api_key == "sk-fake"
        assert llm.model == "gpt-6-luna"
        assert llm.api_params == {"reasoning_effort": "none"}
        for key in ("temperature", "top_p", "max_tokens"):
            assert key not in llm.api_params


def _head_llm_module():
    """llm.py as committed at HEAD, imported as a separate module."""
    repo = Path(__file__).resolve().parents[2]
    try:
        src = subprocess.run(
            ["git", "show", "HEAD:coder/src/agentic_python_coder/llm.py"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git or the committed llm.py is not available")
    module = types.ModuleType("llm_at_head")
    module.__file__ = str(repo / "coder/src/agentic_python_coder/llm.py")
    exec(compile(src, "llm_at_head.py", "exec"), module.__dict__)
    return module


@pytest.mark.parametrize("model", list_available_models())
def test_bundled_models_unchanged_against_head(model):
    """Request parameters of every bundled model equal those built by HEAD."""
    head = _head_llm_module()
    old = head.get_openrouter_llm(model=model, api_key="k")
    new = get_openrouter_llm(model=model, api_key="k")
    assert new.model == old.model
    assert new.api_params == old.api_params
    assert str(new.client.base_url) == str(old.client.base_url)
    assert new.client.timeout == old.client.timeout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
