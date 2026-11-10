"""Guarded local model configuration. Keys never appear in public responses."""
from __future__ import annotations

import contextlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from urllib.parse import urlsplit

from assessments import ProviderConfig, ReviewError, NoRedirects, clean_text, create_provider, normalize_result, _keys
from review_cli import discover_cli

KINDS = (("codex", "Codex"), ("claude", "Claude Code"), ("zcode", "Z Code"), ("custom", "自定义 CLI"))
FIELDS = {"mode", "provider", "base_url", "model", "cli_kind", "command", "cwd", "output_format", "timeout_seconds", "api_key", "api_keys", "clear_key"}
ENV_FIELDS = ("WORKHUB_LLM_PROVIDER", "WORKHUB_LLM_MODEL", "WORKHUB_LLM_BASE_URL", "WORKHUB_LLM_API_KEYS", "WORKHUB_LLM_API_KEY", "WORKHUB_LLM_REASONING_EFFORT", "WORKHUB_LLM_MAX_TOKENS")


class ModelAccess:
    def __init__(self, store, reviews):
        self.store, self.reviews = store, reviews
        self.directory = Path(store.directory)
        self._test_lock = threading.Lock()

    def _read(self):
        path = self.directory / "llm.json"
        legacy = not path.exists()
        if legacy:
            path = self.directory / "glm.json"
        if not path.exists():
            return {}
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077 or path.stat().st_size > 65536:
            raise ReviewError("模型配置须为本用户的 0600 普通文件", 503)
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError()
        except (OSError, ValueError, UnicodeError):
            raise ReviewError("模型配置无法读取，请在本机检查", 503) from None
        if legacy:
            config.setdefault("provider", "glm")
        return config

    def _busy(self):
        with self.store.connection() as db:
            return db.execute("SELECT 1 FROM review_job_items WHERE status IN ('queued','running') LIMIT 1").fetchone() is not None

    def state(self, saved=False):
        raw = self._read()
        effective = ProviderConfig(self.directory)
        provider = effective.public()
        kind = raw.get("cli_kind", "custom")
        if kind not in dict(KINDS):
            kind = "custom"
        custom = raw.get("command", []) if kind == "custom" else []
        safe_command = []
        hide_next = False
        for part in custom if isinstance(custom, list) else []:
            if not isinstance(part, str):
                continue
            safe_command.append("[凭据已隐藏]" if hide_next else clean_text(part, 4096, effective.secrets))
            hide_next = bool(re.fullmatch(r"(?i)--(?:api[-_]?key|key|token|password|secret)", part))
        base = effective.base if isinstance(effective.base, str) else ProviderConfig.BASES[effective.provider]
        cwd = raw.get("cwd", "") if isinstance(raw.get("cwd", ""), str) else ""
        timeout = getattr(effective, "timeout_seconds", 55)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= 60:
            timeout = 55
        response = {
            "config": {"mode": "cli" if effective.provider == "cli" else "api", "provider": effective.provider, "base_url": clean_text(base, 1000, effective.secrets), "model": provider.get("model", ""), "cli_kind": kind, "command": safe_command, "cwd": clean_text(cwd, 4096, effective.secrets), "output_format": raw.get("output_format", "json") if raw.get("output_format", "json") in ("json", "result") else "json", "timeout_seconds": timeout, "key_count": len(effective.keys), "has_key": bool(effective.keys)},
            "provider": provider,
            "providers": [{"id": key, "label": label, "base_url": ProviderConfig.BASES[key], "requires_key": key not in ("ollama", "cli")} for key, label in ProviderConfig.NAMES.items() if key != "cli"],
            "cli_options": [{"id": key, "label": label, "installed": key == "custom" or bool(discover_cli(key)), "model_editable": key != "zcode"} for key, label in KINDS],
            "busy": self._busy(),
            "environment_overrides": [name for name in ENV_FIELDS if name in os.environ],
        }
        if saved:
            response["saved"] = True
        return response

    def _draft(self, payload):
        if not isinstance(payload, dict) or set(payload) - FIELDS:
            raise ReviewError("模型接入参数无效")
        previous = self._read()
        provider = payload.get("provider", previous.get("provider", "openai"))
        mode = payload.get("mode", "cli" if provider == "cli" else "api")
        if mode not in ("api", "cli"):
            raise ReviewError("接入方式须为 API 或 CLI")
        if mode == "cli":
            provider = "cli"
        if provider not in ProviderConfig.NAMES or (mode == "api" and provider == "cli"):
            raise ReviewError("请选择支持的模型提供方")
        if type(payload.get("clear_key", False)) is not bool:
            raise ReviewError("移除密钥参数无效")
        timeout = payload.get("timeout_seconds", previous.get("timeout_seconds", 55))
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 1 <= timeout <= 60:
            raise ReviewError("超时须为 1 至 60 秒")
        same_provider = previous.get("provider") == provider
        config = {"provider": provider, "timeout_seconds": timeout, "max_retries": previous.get("max_retries", 2) if same_provider else 2, "concurrency": previous.get("concurrency", 1 if provider in ("cli", "ollama") else 3) if same_provider else (1 if provider in ("cli", "ollama") else 3)}
        if provider == "cli":
            kind = payload.get("cli_kind", previous.get("cli_kind", "codex"))
            if kind not in dict(KINDS):
                raise ReviewError("请选择本机 CLI")
            model = payload.get("model", "")
            if not isinstance(model, str) or len(model) > 100 or "\0" in model:
                raise ReviewError("模型名称无效")
            model = model.strip()
            if kind == "zcode" and model not in ("", "CLI"):
                raise ReviewError("Z Code CLI 使用客户端当前模型，请将模型留空")
            config.update(cli_kind=kind, model=model or "CLI", output_format="json", cwd=str(self.directory))
            if kind == "custom":
                command = payload.get("command")
                if command in (None, []) and previous.get("provider") == "cli" and previous.get("cli_kind", "custom") == "custom":
                    command = previous.get("command")
                if not isinstance(command, list) or not 1 <= len(command) <= 50 or any(not isinstance(part, str) or not part or len(part) > 4096 or "\0" in part for part in command):
                    raise ReviewError("CLI 命令须为非空 JSON 参数数组")
                if Path(command[0]).name.lower() in ("sh", "bash", "zsh", "fish", "cmd", "powershell", "pwsh"):
                    raise ReviewError("请指定 CLI 程序或包装器，不使用 shell 命令")
                if any(re.search(r"(?i)(?:--(?:api[-_]?key|key|token|password|secret)(?:=|$)|(?:API_KEY|ACCESS_TOKEN|PASSWORD|SECRET)\s*=|github_pat_|\bsk-[A-Za-z0-9_-]{20,})", part) for part in command):
                    raise ReviewError("不要在 CLI 参数中填写凭据，请使用客户端登录或环境配置")
                cwd = payload.get("cwd") or previous.get("cwd") or str(self.directory)
                output_format = payload.get("output_format", previous.get("output_format", "json"))
                config.update(command=list(command), cwd=cwd, output_format=output_format)
            else:
                if not discover_cli(kind):
                    raise ReviewError("未检测到所选 CLI，请先安装或使用高级自定义命令")
                command = [sys.executable, str(Path(__file__).with_name("review_cli.py")), "--agent", kind, "--timeout", str(max(.5, timeout - 2))]
                if model and model != "CLI" and kind != "zcode":
                    command += ["--model", model]
                config["command"] = command
        else:
            base = payload.get("base_url", previous.get("base_url", ProviderConfig.BASES[provider]) if previous.get("provider") == provider else ProviderConfig.BASES[provider])
            model = payload.get("model", previous.get("model", "") if previous.get("provider") == provider else ("glm-5.3-flash" if provider == "glm" else ""))
            if not isinstance(base, str) or not isinstance(model, str):
                raise ReviewError("接口地址和模型名称须为文字")
            base, model = base.strip().rstrip("/"), model.strip()
            try:
                parsed = urlsplit(base)
            except ValueError:
                raise ReviewError("接口地址无效") from None
            if provider == "openai" and parsed.scheme == "http":
                try:
                    if ipaddress.ip_address(parsed.hostname).is_loopback:
                        config["allow_local_http"] = True
                except (ValueError, TypeError):
                    pass
            same_destination = previous.get("provider", "openai") == provider and str(previous.get("base_url", ProviderConfig.BASES[provider])).rstrip("/") == base
            source = payload.get("api_keys", payload.get("api_key", ""))
            if not isinstance(source, (str, list)) or (isinstance(source, list) and any(not isinstance(key, str) for key in source)):
                raise ReviewError("API Key 格式无效")
            keys = _keys(source)
            if any(len(key) > 8192 for key in keys):
                raise ReviewError("API Key 超出允许长度")
            if payload.get("clear_key"):
                keys = []
            elif not keys and same_destination:
                keys = _keys(previous.get("api_keys", previous.get("api_key", [])))
            config.update(base_url=base, model=model, api_keys=keys)
            if same_destination:
                for name in ("reasoning_effort", "max_tokens", "token_parameter", "anthropic_version", "json_mode"):
                    if name in previous:
                        config[name] = previous[name]
        # Validate using the same backend parser without changing active config.
        with tempfile.TemporaryDirectory(prefix=".model-check-", dir=self.directory) as temporary:
            path = Path(temporary) / "llm.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            path.chmod(0o600)
            validated = ProviderConfig(temporary, environ={})
            if validated.error:
                raise ReviewError(validated.error)
        return config

    @contextlib.contextmanager
    def _idle(self):
        with self.reviews.lock:
            if self._busy():
                raise ReviewError("请等待当前评议完成后再修改或测试接入", 409)
            yield

    def save(self, payload):
        with self._idle():
            config = self._draft(payload)
            if any(name in os.environ for name in ENV_FIELDS):
                raise ReviewError("环境变量正在覆盖模型配置，请先移除对应覆盖后再保存", 409)
            if config["provider"] == "glm" and any(name in os.environ for name in ("GLM_MODEL", "GLM_BASE_URL", "GLM_API_KEYS", "GLM_API_KEY")):
                raise ReviewError("GLM 环境变量正在覆盖配置，请先移除对应覆盖后再保存", 409)
            encoded = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if len(encoded) > 65536:
                raise ReviewError("模型配置超出允许长度", 413)
            path = self.directory / "llm.json"
            if path.is_symlink():
                raise ReviewError("不覆盖模型配置符号链接", 409)
            if path.exists():
                backup = self.directory / "backups" / "model-access"
                backup.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination = backup / (str(time.time_ns()) + ".json")
                destination.write_bytes(path.read_bytes())
                destination.chmod(0o600)
            fd, temporary = tempfile.mkstemp(prefix=".llm-", dir=self.directory)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return self.state(saved=True)

    def test(self, payload):
        if not self._test_lock.acquire(blocking=False):
            raise ReviewError("连接测试正在进行，请稍候", 409)
        started = time.monotonic()
        try:
            with self._idle():
                draft = self._draft(payload)
            with tempfile.TemporaryDirectory(prefix=".model-probe-", dir=self.directory) as temporary:
                path = Path(temporary) / "llm.json"
                path.write_text(json.dumps(draft), encoding="utf-8");path.chmod(0o600)
                config = ProviderConfig(temporary, environ={})
                if not config.public()["configured"]:
                    raise ReviewError("请先填写模型和所需 API Key", 400)
                config.max_retries = 0
                if config.provider == "cli":
                    evidence = {"connectivity_test": True, "project_id": "connection-test", "project_name": "连接测试", "evidence": [], "sufficient_evidence": False, "source_fingerprint": "connection-test"}
                    result = create_provider(config).complete(evidence)
                    if not isinstance(result, dict) or result.get("error"):
                        raise ReviewError("CLI 未返回成功的连接响应", 502)
                    if result.get("ok") is not True:
                        # Existing user wrappers may return a complete review
                        # rather than the native adapters' tiny probe object.
                        normalize_result(result, evidence, config.model, config.secrets)
                else:
                    self._probe_http(config)
                return {"ok": True, "message": "连接成功", "provider": config.public(), "elapsed_ms": round((time.monotonic()-started)*1000)}
        finally:
            self._test_lock.release()

    @staticmethod
    def _probe_http(config):
        messages = [{"role": "user", "content": 'Connection test only. Return {"ok":true}. No project data or tools.'}]
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if config.provider == "anthropic":
            body = {"model": config.model, "messages": messages, "max_tokens": 128}
            headers.update({"x-api-key": config.keys[0], "anthropic-version": config.anthropic_version})
        else:
            body = {"model": config.model, "messages": messages, config.token_parameter: 256, "stream": False}
            if config.keys:
                headers["Authorization"] = "Bearer " + config.keys[0]
            if config.provider == "glm":
                body["reasoning_effort"] = "low"
        request = Request(config.endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with build_opener(NoRedirects()).open(request, timeout=min(config.timeout_seconds, 25)) as response:
                raw = response.read(131073)
            if len(raw) > 131072:
                raise ReviewError("连接测试响应超出允许长度", 502)
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("error"):
                raise ValueError()
            if config.provider == "anthropic":
                content = value.get("content")
                if not isinstance(content, list) or not any(isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip() for block in content):
                    raise ValueError()
            else:
                choices = value.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError()
                message = choices[0].get("message")
                if not isinstance(message, dict) or not any(isinstance(message.get(field), str) and message[field].strip() for field in ("content", "reasoning_content")):
                    raise ValueError()
        except HTTPError as error:
            status = error.code;error.close()
            raise ReviewError("连接测试失败（HTTP {}），请检查模型、地址或凭据".format(status), 502) from None
        except (URLError, TimeoutError, OSError):
            raise ReviewError("连接测试无法连接或超时", 502) from None
        except (ValueError, UnicodeError, TypeError):
            raise ReviewError("连接测试未收到兼容的模型响应", 502) from None
