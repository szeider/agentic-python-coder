"""Tests for model-config loading and api_params mapping in llm.py."""

import json

import pytest

from agentic_python_coder.llm import get_openrouter_llm, load_model_config


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
