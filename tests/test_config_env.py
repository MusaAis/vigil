from vigil.config import Config, load_env_file


def test_env_file_is_loaded_without_overriding_existing_values(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nLLM_API_KEY=sk-from-file   # inline\nLLM_MODEL=\"claude-sonnet-4.6\"\n"
                 "export VIGIL_MODE=replay\nEMPTY=\nNEATLOGS_API_KEY=already\nnot a pair\n")
    env = {"NEATLOGS_API_KEY": "shell-wins"}
    assert load_env_file(str(f), env) == 3
    assert env == {"NEATLOGS_API_KEY": "shell-wins", "LLM_API_KEY": "sk-from-file",
                   "LLM_MODEL": "claude-sonnet-4.6", "VIGIL_MODE": "replay"}


def test_missing_env_file_is_not_an_error(tmp_path):
    assert load_env_file(str(tmp_path / "nope"), {}) == 0


def test_config_from_env_reads_the_file_when_no_mapping_is_given(tmp_path, monkeypatch=None):
    import os
    f = tmp_path / ".env"
    f.write_text("LLM_API_KEY=sk-file-key\nLLM_BASE_URL=https://example.test/v1\n")
    cwd, saved = os.getcwd(), {k: os.environ.pop(k, None) for k in ("LLM_API_KEY", "LITELLM_API_KEY", "LLM_BASE_URL")}
    try:
        os.chdir(tmp_path)
        c = Config.from_env()
        assert c.llm_api_key == "sk-file-key" and c.llm_base_url == "https://example.test/v1"
        assert "sk-file-key" not in repr(c)
    finally:
        os.chdir(cwd)
        for k in ("LLM_API_KEY", "LLM_BASE_URL"):
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in saved.items() if v is not None})
