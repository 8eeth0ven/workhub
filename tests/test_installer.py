"""Observable installation and template behavior, isolated from the real home."""

import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "scripts/install.py"
SERVICE = ROOT / "scripts/service.py"
START = "<!-- AGENT-WORKHUB:START -->"


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workhub 验收 空格 ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home 空格"
        self.home.mkdir()
        self.project = self.base / "项目 空格"
        self.project.mkdir()
        self.env = dict(os.environ)
        self.env.pop("AGENT_WORKHUB_HOME", None)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def command(self, script, *arguments, success=True, env=None):
        result = subprocess.run([sys.executable, str(script), *map(str, arguments)],
                                env=env or self.env, capture_output=True, text=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def install(self, *arguments, **kwargs):
        return self.command(INSTALLER, "--home", self.home, *arguments, **kwargs)

    def backend(self, *arguments):
        env = dict(self.env, AGENT_WORKHUB_HOME=str(self.home / ".local/share/agent-workhub"))
        return self.command(ROOT / "workhub.py", *arguments, env=env)


class InstallerTests(IsolatedCase):
    def test_original_bytes_mode_backup_and_shared_links(self):
        rule = self.home / ".codex/AGENTS.md"
        rule.parent.mkdir()
        original = "# 原有规则\r\n保留此行，没有末尾换行".encode()
        rule.write_bytes(original)
        rule.chmod(0o640)
        result = self.install("--global")
        self.assertTrue(rule.read_bytes().startswith(original))
        self.assertEqual(stat.S_IMODE(rule.stat().st_mode), 0o640)
        backup = Path(result["backup_dir"])
        manifest = json.loads((backup / "manifest.json").read_text())
        filename = next(name for name, target in manifest.items() if target == str(rule))
        self.assertEqual((backup / filename).read_bytes(), original)
        for client in (".codex", ".agents", ".zcode", ".claude"):
            link = self.home / client / "skills/agent-workhub"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), ROOT / "skill/agent-workhub")

    def test_repeat_global_and_project_install_is_idempotent(self):
        self.install("--global", "--project", self.project, "--name", "测试项目")
        before = {path: path.read_bytes() for path in (
            self.home / ".codex/AGENTS.md", self.home / ".zcode/AGENTS.md",
            self.home / ".claude/CLAUDE.md", self.project / "AGENTS.md", self.project / "CLAUDE.md")}
        repeat = self.install("--global", "--project", self.project, "--name", "测试项目")
        self.assertEqual(repeat["write_files"], [])
        self.assertEqual(repeat["skill_links"], [])
        self.assertIsNone(repeat["backup_dir"])
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual(path.read_text().count(START), 1)
        self.assertEqual(len(self.backend("projects")), 1)

    def test_foreign_skill_conflict_preflight_has_no_side_effects(self):
        conflict = self.home / ".claude/skills/agent-workhub"
        conflict.mkdir(parents=True)
        sentinel = conflict / "SKILL.md"
        sentinel.write_text("外来技能")
        rule = self.home / ".codex/AGENTS.md"
        rule.parent.mkdir()
        rule.write_text("已有规则")
        failure = self.install("--global", "--project", self.project, success=False)
        self.assertIn("同名技能", failure.stderr)
        self.assertEqual(rule.read_text(), "已有规则")
        self.assertEqual(sentinel.read_text(), "外来技能")
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_foreign_command_conflict_preflight_has_no_side_effects(self):
        command = self.home / ".local/bin/agent-workhub"
        command.parent.mkdir(parents=True)
        command.write_text("#!/bin/sh\n# unrelated\n")
        failure = self.install("--global", success=False)
        self.assertIn("同名命令", failure.stderr)
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".local/share").exists())

    def test_dry_run_site_plan_has_no_file_or_database_writes(self):
        site = self.project / "网页 空格"
        site.mkdir()
        (site / "index.html").write_text("<h1>项目网页</h1>")
        plan = self.install("--global", "--project", self.project, "--site-dir", site,
                            "--site-name", "测试网页", "--template", "library", "--dry-run")
        self.assertEqual(plan["register_site"]["directory"], str(site))
        self.assertEqual(plan["register_site"]["template"], "library")
        self.assertIn("site-add", plan["register_site"]["command"])
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_symlink_rule_does_not_mutate_target(self):
        target = self.base / "unrelated"
        target.write_text("必须保留")
        (self.project / "AGENTS.md").symlink_to(target)
        self.install("--project", self.project, success=False)
        self.assertEqual(target.read_text(), "必须保留")
        self.assertFalse((self.project / "CLAUDE.md").exists())
        self.assertFalse((self.home / ".local").exists())

    def test_static_directory_registration_is_real_and_idempotent(self):
        help_text = subprocess.check_output([sys.executable, str(ROOT / "workhub.py"), "--help"], text=True)
        if "site-add" not in help_text:
            self.skipTest("后端 site-add 尚未生成")
        site = self.project / "网页 空格"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html><title>真实页面</title>")
        result = self.install("--project", self.project, "--site-dir", site,
                              "--site-name", "真实页面", "--template", "radar")
        identifier = result["site_registration"]["id"]
        sites = self.backend("site-list")
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["directory"], str(site))
        self.assertEqual(sites[0]["kind"], "directory")
        self.assertEqual(sites[0]["template_id"], "radar")
        self.install("--project", self.project, "--site-dir", site, "--site-name", "真实页面", "--template", "radar")
        sites = self.backend("site-list")
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["id"], identifier)

    def test_invalid_site_metadata_is_rejected_before_writes(self):
        for extra in (("--template", "brief"), ("--site-url", "https://example.com"),
                      ("--site-url", "http://user:password@localhost:3000"),
                      ("--site-url", "http://localhost:0")):
            with self.subTest(arguments=extra):
                self.install("--project", self.project, *extra, success=False)
                self.assertFalse((self.project / "AGENTS.md").exists())
                self.assertFalse((self.home / ".local").exists())


class TemplateTests(IsolatedCase):
    def test_new_sites_are_real_empty_sites_without_demo_items(self):
        generator = ROOT / "scripts/site_templates.py"
        if not generator.exists() or any(not (ROOT / "templates" / name / "index.html").is_file()
                                         for name in ("radar", "library", "brief")):
            self.skipTest("模板生成器或模板尚未生成")
        for name in ("radar", "library", "brief"):
            with self.subTest(template=name):
                output = self.project / f"{name} 网站"
                result = self.command(generator, "create", "--template", name, "--output", output, "--name", "正式网站")
                data = json.loads((output / "data.json").read_text())
                self.assertIs(data["is_demo"], False)
                self.assertEqual(data["items"], [])
                self.assertIs(result["demo"], False)
                self.assertEqual(result["item_count"], 0)
                self.assertTrue((output / "index.html").is_file())
                manifest = json.loads((output / "workhub-site.json").read_text())
                self.assertEqual(manifest["template_id"], name)


class ServiceStagingTests(IsolatedCase):
    def service(self, *arguments, **kwargs):
        return self.command(SERVICE, *arguments, "--mode", "launchd", "--home", self.home, **kwargs)

    def test_staged_install_has_valid_plist_and_never_starts_service(self):
        result = self.service("install", "--port", "8912")
        self.assertTrue(result["staging_only"])
        self.assertFalse(result["loaded"])
        self.assertFalse(result["running"])
        with Path(result["plist"]).open("rb") as stream:
            config = plistlib.load(stream)
        self.assertEqual(config["Label"], "local.agent-workhub")
        runtime = self.home / ".local/share/agent-workhub/runtime"
        self.assertEqual(config["ProgramArguments"][1], str(runtime / "workhub.py"))
        self.assertEqual(config["WorkingDirectory"], str(runtime))
        self.assertEqual((runtime / "workhub.py").read_bytes(), (ROOT / "workhub.py").read_bytes())
        self.assertEqual((runtime / "assessments.py").read_bytes(), (ROOT / "assessments.py").read_bytes())
        self.assertTrue((runtime / "static/index.html").is_file())
        self.assertTrue((runtime / "templates/radar/index.html").is_file())
        self.assertEqual(config["ProgramArguments"][-2:], ["--port", "8912"])
        self.assertTrue(config["RunAtLoad"])
        self.assertTrue(config["KeepAlive"])
        self.assertGreaterEqual(config["ThrottleInterval"], 5)
        self.assertTrue(Path(config["ProgramArguments"][0]).is_absolute())
        self.assertTrue(Path(config["StandardErrorPath"]).parent.is_dir())
        status = self.service("status")
        self.assertEqual(status["url"], "http://127.0.0.1:8912")
        self.assertFalse(status["loaded"])
        self.service("stop")
        removed = self.service("uninstall")
        self.assertFalse(removed["installed"])

    def test_service_dry_run_and_foreign_config_protection(self):
        result = self.service("install", "--dry-run")
        self.assertTrue(result["dry_run"])
        self.assertFalse((self.home / "Library").exists())
        self.assertFalse((self.home / ".local").exists())
        plist = self.home / "Library/LaunchAgents/local.agent-workhub.plist"
        plist.parent.mkdir(parents=True)
        foreign = {"Label": "local.agent-workhub", "ProgramArguments": ["/bin/sh", "/somewhere/else"]}
        plist.write_bytes(plistlib.dumps(foreign))
        before = plist.read_bytes()
        self.service("install", success=False)
        self.assertEqual(plist.read_bytes(), before)
        self.assertFalse((self.home / ".local").exists())


class SessionStagingTests(IsolatedCase):
    def test_default_session_stages_and_remembers_mode_without_spawning(self):
        installed = self.command(SERVICE, "install", "--home", self.home, "--port", "8913")
        self.assertEqual(installed["mode"], "session")
        self.assertTrue(installed["staging_only"])
        self.assertFalse(installed["running"])
        status = self.command(SERVICE, "status", "--home", self.home)
        self.assertEqual(status["mode"], "session")
        self.assertEqual(status["url"], "http://127.0.0.1:8913")
        self.assertFalse((self.home / "Library").exists())
        removed = self.command(SERVICE, "uninstall", "--home", self.home)
        self.assertFalse(removed["installed"])

    def test_session_dry_run_has_no_writes(self):
        planned = self.command(SERVICE, "install", "--home", self.home, "--dry-run", "--port", "8914")
        self.assertEqual(planned["mode"], "session")
        self.assertIn(str(ROOT / "workhub.py"), planned["process_plan"])
        self.assertFalse((self.home / ".local").exists())


class ReleaseAuditTests(IsolatedCase):
    def test_placeholder_examples_and_public_keys_pass(self):
        release = self.base / "release"
        examples = release / "examples"
        examples.mkdir(parents=True)
        (examples / "provider-example.json").write_text(json.dumps({"api_key": "YOUR_API_KEY", "model": "MODEL"}))
        (release / "public.pem").write_text("-----BEGIN PUBLIC KEY-----\nPUBLIC-EXAMPLE-BODY\n-----END PUBLIC KEY-----")
        result = self.command(ROOT / "scripts/audit_release.py", "--root", release)
        self.assertTrue(result["ok"])
        self.assertEqual(result["findings"], [])

    def test_secret_findings_do_not_echo_values(self):
        release = self.base / "release"
        release.mkdir()
        secret = "ghp_" + "AbCdEf0123456789" * 3
        home_path = "/" + "Users" + "/" + "example-person" + "/project"
        (release / "settings.json").write_text(json.dumps(dict(api_key=secret, path=home_path)))
        result = self.command(ROOT / "scripts/audit_release.py", "--root", release, success=False)
        findings = json.loads(result.stdout)["findings"]
        self.assertTrue(any(row["kind"] == "provider-token" for row in findings))
        self.assertTrue(any(row["kind"] == "personal-home-path" for row in findings))
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertNotIn(home_path, result.stdout + result.stderr)

    def test_runtime_and_private_configuration_block_without_reading(self):
        release = self.base / "release"
        release.mkdir()
        (release / ".env").write_bytes(b"\xff\xfe")
        (release / "state.sqlite3").write_bytes(b"SQLite format 3\x00")
        (release / "runtime").mkdir()
        result = self.command(ROOT / "scripts/audit_release.py", "--root", release, success=False)
        kinds = {row["kind"] for row in json.loads(result.stdout)["findings"]}
        self.assertTrue({"private-configuration", "database-artifact", "runtime-artifact"}.issubset(kinds))
        self.assertNotIn("unreadable-source", kinds)

    def test_private_key_and_real_shaped_test_token_are_not_exempt(self):
        release = self.base / "release"
        (release / "tests").mkdir(parents=True)
        token = "ghp_" + "AbCdEf0123456789" * 3
        (release / "tests/test_fixture.py").write_text(repr(token))
        private = "-----BEGIN " + "RSA PRIVATE KEY-----\n" + "M" + "A" * 120 + "\n-----END " + "RSA PRIVATE KEY-----"
        (release / "private.pem").write_text(private)
        result = self.command(ROOT / "scripts/audit_release.py", "--root", release, success=False)
        kinds = {row["kind"] for row in json.loads(result.stdout)["findings"]}
        self.assertTrue({"private-key", "provider-token"}.issubset(kinds))
        self.assertNotIn(token, result.stdout + result.stderr)
        self.assertNotIn(private, result.stdout + result.stderr)

    def test_git_tracked_private_file_still_blocks_when_ignored(self):
        release = self.base / "release"
        release.mkdir()
        subprocess.run(["git", "init", "--quiet", str(release)], check=True, capture_output=True)
        (release / "llm.json").write_text("{}")
        subprocess.run(["git", "-C", str(release), "add", "llm.json"], check=True, capture_output=True)
        (release / ".gitignore").write_text("llm.json\n")
        result = self.command(ROOT / "scripts/audit_release.py", "--root", release, success=False)
        self.assertEqual(json.loads(result.stdout)["scope"], "git-candidates")
        self.assertIn({"path": "llm.json", "kind": "private-configuration"}, json.loads(result.stdout)["findings"])


if __name__ == "__main__":
    unittest.main()
