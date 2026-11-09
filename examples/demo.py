#!/usr/bin/env python3
"""Read-only Workhub demonstration with fictional data and an isolated database.

Run ``python3 examples/demo.py --port 8899``. This entry point never constructs a
real assessment provider, reads user configuration, or performs model requests.
All temporary databases and generated websites are removed when it exits.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import signal
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import workhub

DEMO_NOTE = "演示结果，未调用模型"
PROJECTS = (
    ("radar", "示例 · 开放信息雷达", "虚构演示项目：按来源整理信息，保留可核查线索与待验证假设。", "信息雷达"),
    ("library", "示例 · 知识资料库", "虚构演示项目：把参考资料、方法笔记与证据条目分类归档。", "项目资料"),
    ("brief", "示例 · 周度研究简报", "虚构演示项目：汇总阶段发现、反例、验证限制与优先行动。", "阶段简报"),
    ("plan", "示例 · 待启动计划", "虚构演示项目：尚未提交工作记录，用于展示未评议状态。", None),
)
DIMENSIONS = (
    ("goal", "目标清晰度"), ("evidence", "证据质量"),
    ("verification", "验证充分度"), ("risks", "覆盖与风险"),
    ("next_steps", "下一步行动"),
)


def stamp(minutes=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def prepare_site(mode, destination):
    """Build only from repository-owned, explicitly fictional demo assets."""
    source = ROOT / "templates" / mode
    destination.mkdir(parents=True)
    page = (source / "index.html").read_text(encoding="utf-8")
    page = page.replace('href="/design-system.css"', 'href="design-system.css"')
    page = page.replace('src="/templates/runtime.js"', 'src="runtime.js"')
    page = page.replace('href="/templates/template-shell.css"', 'href="template-shell.css"')
    (destination / "index.html").write_text(page, encoding="utf-8")
    shutil.copyfile(ROOT / "static" / "design-system.css", destination / "design-system.css")
    shutil.copyfile(ROOT / "templates" / "runtime.js", destination / "runtime.js")
    shutil.copyfile(ROOT / "templates" / "template-shell.css", destination / "template-shell.css")
    shutil.copyfile(ROOT / "examples" / "demo-content" / mode / "data.json", destination / "data.json")


class DemoReviews:
    """Preset illustrative review results; no LLM/configuration code is used."""

    def __init__(self, store, fixtures):
        self.store = store
        self.fixtures = fixtures
        self.results = {}
        for index, (mode, project) in enumerate(fixtures.items()):
            if mode == "plan":
                continue
            evidence = self.evidence(project)
            reference = next((item["id"] for item in evidence if item["kind"] == "event"), evidence[0]["id"])
            insufficient = mode == "brief"
            headline = {"radar": "来源已整理，下一步需要检验覆盖盲点", "library": "资料结构清晰，补充维护规则会更完整", "brief": "目前资料不足，先补充反例与复核步骤"}[mode]
            questions = [
                ("clarification", "这个项目具体支持哪一种决策？", "边界明确后，才能判断现有资料是否切题。", "补充一条可检验的项目目标。"),
                ("assumptions", "是否把条目数量当作覆盖充分的依据？", "来源数量和资料质量并不自动等同。", "标注独立来源与转载关系。"),
                ("evidence", "哪些记录能够被其他人独立复核？", "登记的陈述仍需与原始证据对应。", "为关键结论提供来源与复核步骤。"),
                ("perspectives", "换一个立场，会优先补充哪些反例？", "当前分类可能掩盖不同来源的观察。", "增加一份反例和替代解释清单。"),
                ("consequences", "如果当前假设不成立，会影响哪个下一步？", "需要区分可逆尝试和依赖该假设的决定。", "在行动项旁写清前提与回退办法。"),
                ("reflection", "现在最值得回答的，还是最初那个问题吗？", "项目在推进中可能改变了真正需要解决的问题。", "对照原目标复核当前优先事项。"),
            ]
            self.results[project["id"]] = {
                "id": "demo-review-" + mode, "project_id": project["id"], "project_name": project["name"],
                "created_at": stamp(7 + index), "model": "预置演示 / 未调用模型", "is_demo": True,
                "verdict": "insufficient_evidence" if insufficient else "needs_attention" if mode == "radar" else "ready",
                "headline": headline, "summary": DEMO_NOTE + "。这份预置示例展示如何区分已有依据、未证实假设与下一步补证；不代表对任何真实项目的评价。",
                "strengths": [] if insufficient else ["演示依据：已有清晰的栏目与来源登记。", "演示依据：阶段记录保留了任务、产物和验证范围。"],
                "assumptions": ["示例假设：现有来源能够覆盖目标主题，仍需反例验证。"],
                "questions": [{"id": "q" + str(i + 1), "kind": kind, "question": question, "why": why, "suggested_check": check, "evidence_ids": [reference]} for i, (kind, question, why, check) in enumerate(questions)],
                "blind_spots": ["演示盲点：尚未说明来源失效和异常资料的处理方式。"],
                "next_actions": [{"priority": "high", "action": "补充可以推翻现有判断的反例", "reason": "演示行动：检验覆盖范围，而不是继续增加同类条目。"}, {"priority": "medium", "action": "把关键结论与复核步骤建立对应关系", "reason": "演示行动：让另一位协作者能够独立复查。"}],
                "dimensions": [{"key": key, "label": label, "score": None if insufficient else (2 if mode == "radar" and i in (1, 2, 3) else 3), "reason": "演示理由：资料不足，保留判断。" if insufficient else "演示理由：已有登记信息可说明当前进展，但尚需独立复核与边界说明。", "evidence_ids": [reference]} for i, (key, label) in enumerate(DIMENSIONS)],
                "confidence": "low" if insufficient else "medium", "evidence_count": len(evidence),
                "source_fingerprint": "demo-fixture-not-model-output", "is_stale": mode == "radar",
            }

    def evidence(self, project):
        items = [{"id": "project:" + project["id"], "kind": "project", "text": project["name"] + "：" + project["description"]}]
        items.extend({"id": "event:" + str(event["id"]), "kind": "event", "text": event["summary"] + "\n" + event["details"], "created_at": event["created_at"]} for event in self.store.events(identifier=project["id"], limit=20))
        return items

    def public_state(self):
        return {"is_demo": True, "reviews": list(self.results.values()), "jobs": [], "provider": {"configured": False, "provider": "演示模式", "provider_id": "demo", "model": DEMO_NOTE, "key_count": 0, "requires_key": False, "mode": "demo", "is_demo": True}, "rubric": [{"key": key, "label": label} for key, label in DIMENSIONS]}

    def project(self, identifier):
        project = next((p for p in self.fixtures.values() if p["id"] == identifier), None)
        if project is None:
            raise ValueError("演示项目不存在")
        review = self.results.get(identifier)
        return {"review": review, "history": [review] if review else [], "answers": [{"id": 1, "project_id": identifier, "text": "演示补充：当前目标与来源清单均为虚构，后续需要增加反例和可复核步骤。", "created_at": stamp(20)}] if review else [], "evidence": self.evidence(project), "is_demo": True}

    def job(self, identifier):
        raise ValueError("演示模式不会创建模型任务")

    def close(self, wait=False):
        return None


def seed(store, directory):
    fixtures = {}
    public_paths = {}
    for mode, name, description, site_name in PROJECTS:
        project_path = directory / "projects" / mode
        project_path.mkdir(parents=True)
        project = store.register(str(project_path), name, description)
        fixtures[mode] = project
        public_paths[str(project_path)] = "examples/" + mode
        if site_name:
            site_path = directory / "sites" / mode
            prepare_site(mode, site_path)
            public_paths[str(site_path)] = "examples/demo-content/" + mode
            store.site_add(str(project_path), site_name, directory=str(site_path), template=mode, description="虚构演示网站 · " + site_name)
        if mode == "plan":
            continue
        agent = {"radar": "codex", "library": "claude", "brief": "zcode"}[mode]
        events = [
            ("running", "演示记录：整理项目目标与信息结构", "演示步骤：确认栏目、来源和验证范围。"),
            ("completed", "演示记录：完成网站排版与示例内容检查", "演示产物：data.json 与静态页面；未执行真实项目工作。"),
        ]
        if mode == "radar":
            events.append(("running", "演示记录：开始补充来源交叉核验", "演示待办：标注重复转述和缺失来源。"))
        if mode == "brief":
            events.append(("blocked", "演示记录：等待补充反例与复核步骤", "演示阻塞：现有虚构资料不足以支持完整判断。"))
        for index, (status, summary, details) in enumerate(events):
            event = store.record(str(project_path), agent, status, summary, details, "虚构示例项目推进", "demo-" + mode)
            created = stamp(30 - index * 6 + len(fixtures))
            with store.connection() as db:
                db.execute("UPDATE events SET created_at=? WHERE id=?", (created, event["id"]))
        created = stamp(2 + len(fixtures))
        with store.connection() as db:
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (created, project["id"]))
            db.execute("UPDATE runs SET updated_at=? WHERE project_id=?", (created, project["id"]))
    seed_archives(store, fixtures, directory)
    # A visibly fictional coding lesson, with an actual file in its temporary
    # demo project. It never borrows source or understanding state from the user.
    lesson_path = directory / "projects" / "radar" / "view.js"
    lesson_path.write_text("function showTitle(node, item) { node.textContent = item.title; }\n", encoding="utf-8")
    workhub.LearningStore(store).add_card({
        "project_id": fixtures["radar"]["id"], "card_key": "demo-literal-text",
        "title": "示例：为什么把标题当作文字展示？", "concept": "textContent 将内容作为普通文本写入页面。",
        "explanation": "这是一张虚构演示学习卡。信息条目的标题可能包含尖括号；把它当文字显示，可以让页面忠实呈现标题。",
        "implementation": "演示项目的 showTitle 接收节点和条目，把 item.title 赋给 node.textContent。它不解析 HTML，也不创建标题中的标签。",
        "terms": [{"term": "DOM", "definition": "浏览器在内存中表示页面结构的对象。"}, {"term": "textContent", "definition": "读取或设置节点的文本，不把文本解析成 HTML。"}],
        "steps": ["读取条目的标题。", "找到标题节点。", "通过 textContent 写入文本。"],
        "example": 'item.title = "<b>示例标题</b>"；页面会显示这些字面字符。',
        "self_check": "如果标题里有 <b>，为什么这里不会自动变成粗体？",
        "sources": [{"path": "view.js", "line": 1, "symbol": "showTitle", "note": "仅位于本次临时演示项目。"}],
        "agent": "demo", "run_id": "fictional-learning-example",
    })
    return fixtures, public_paths


def seed_archives(store, fixtures, directory):
    """Only fictional prompts, sessions and a small read-only article fixture."""
    archive = workhub.ArchiveStore(store)
    for mode, project in fixtures.items():
        if mode == "plan":
            continue
        agent = {"radar": "codex", "library": "claude", "brief": "zcode"}[mode]
        archive.add_session({"project_id": project["id"], "agent": agent,
                             "session_id": "fictional-session-" + mode,
                             "title": "示例 · 项目研究会话", "source": "fictional_demo",
                             "source_ref": "examples/demo.py · 虚构会话，未读取真实聊天"})
        original = archive.add_prompt({"project_id": project["id"], "agent": agent,
                                      "session_id": "fictional-session-" + mode,
                                      "title": "示例 · 资料整理要求", "prompt_key": "demo-original-" + mode,
                                      "content": "请整理示例资料的来源，说明目标、当前依据和仍待核查的问题。此提示词完全虚构，仅供演示。",
                                      "record_type": "original", "source": "fictional_demo"})
        if mode != "radar":
            continue
        archive.add_prompt({"project_id": project["id"], "agent": agent,
                            "session_id": "fictional-session-radar", "title": "示例 · 整理后的复用提示词",
                            "prompt_key": "demo-derived-radar", "record_type": "derived", "derived_from": original["id"],
                            "content": "用一句话解释示例项目，再列出来源、关键反例和可复核的下一步。此文本是虚构的整理版。",
                            "source": "fictional_demo"})
        article = directory / "publications" / mode
        article.mkdir(parents=True)
        (article / "cover.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="340"><rect width="800" height="340" fill="#253c33"/><text x="48" y="180" font-family="sans-serif" font-size="42" fill="#e1edda">WORKHUB · FICTIONAL DEMO</text></svg>', encoding="utf-8")
        (article / "article.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>示例 · 项目更新草稿</title><body style="font:16px/1.9 sans-serif;margin:24px;max-width:760px"><h1>示例 · 项目更新草稿</h1><p>这是只读的虚构公众号图文，用于展示项目档案内的阅读体验。没有发布到任何平台。</p><img src="cover.svg" alt="虚构演示封面" style="width:100%"><p>示例步骤：接入项目、保存提示词、留存配图和生成版本。</p></body></html>', encoding="utf-8")
        archive.add_artifact({"project_id": project["id"], "title": "示例 · 项目更新草稿", "directory": str(article),
                              "entry": "article.html", "kind": "publication", "status": "draft", "version": "fictional-demo",
                              "prompt_ids": [original["id"]], "source": "fictional_demo"})


def public_payload(value, paths):
    """Strip internal fixture paths from every JSON field, including sites."""
    if isinstance(value, dict):
        return {key: public_payload(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [public_payload(item, paths) for item in value]
    if isinstance(value, str):
        for actual, logical in sorted(paths.items(), key=lambda item: len(item[0]), reverse=True):
            value = value.replace(actual, logical)
        return value
    return value


@contextmanager
def demo_server(port=8899):
    """Yield a stopped loopback server; the caller owns its serve_forever thread."""
    with tempfile.TemporaryDirectory(prefix="workhub-demo-") as temporary:
        directory = Path(temporary).resolve()
        store = workhub.Store(directory / "database")
        fixtures, paths = seed(store, directory)
        paths[str(directory)] = "examples/.demo-runtime"
        paths[str(ROOT)] = "workhub"
        reviews = DemoReviews(store, fixtures)
        sites = workhub.SiteManager(store)
        base = workhub.handler_for(store, manager=sites, reviews=reviews)

        class DemoHandler(base):
            def json_response(self, code, payload):
                if isinstance(payload, dict):
                    payload = dict(payload, is_demo=True)
                super().json_response(code, public_payload(payload, paths))

            def transform_html(self, body):
                text = body.decode("utf-8")
                text = text.replace('id="demo-banner" class="demo-banner" role="note" hidden', 'id="demo-banner" class="demo-banner" role="note"')
                return text.encode("utf-8")

            def do_GET(self):
                if urlsplit(self.path).path == "/api/integrations":
                    if not self.check_access():
                        return
                    self.json_response(200, {"integrations": [{"agent": agent, "name": name, "ready": False, "is_demo": True} for agent, name in (("codex", "Codex"), ("zcode", "Z Code"), ("claude", "Claude Code"))]})
                    return
                super().do_GET()

            def do_POST(self):
                if not self.check_access():
                    return
                self.json_response(405, {"error": "演示模式仅供查看，未调用模型；请启动正常工作台以使用真实评议。"})

        server = workhub.WorkhubServer(("127.0.0.1", port), DemoHandler)
        try:
            yield server
        finally:
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口范围为 1 至 65535")

    def stop(signum, frame):
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    with demo_server(args.port) as server:
        print("Workhub 只读演示：http://127.0.0.1:{} — 虚构项目与预置评议，未调用模型。".format(server.server_port), flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
