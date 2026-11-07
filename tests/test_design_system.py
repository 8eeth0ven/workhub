"""Generated project layouts stay independent while sharing one design system."""
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parent.parent


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "script" and "src" in values:
            self.urls.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet":
            self.urls.append(values["href"])


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class DesignSystemTests(unittest.TestCase):
    def generate(self, mode, output, *extra):
        return subprocess.run([sys.executable, str(ROOT / "scripts/site_templates.py"),
                               "create", "--template", mode, "--output", str(output),
                               "--name", "独立项目网站", *extra],
                              text=True, capture_output=True, timeout=10)

    def test_all_layouts_export_a_complete_standalone_site(self):
        with tempfile.TemporaryDirectory(prefix="workhub-theme-空格 ") as temporary:
            for mode in ("radar", "library", "brief"):
                with self.subTest(mode=mode):
                    output = Path(temporary) / mode
                    result = self.generate(mode, output)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    html = (output / "index.html").read_text()
                    parser = Assets()
                    parser.feed(html)
                    self.assertEqual(len(parser.ids), len(set(parser.ids)), "DOM identity must be unambiguous")
                    self.assertEqual(set(parser.urls), {"design-system.css", "runtime.js", "template-shell.css"})
                    for url in parser.urls:
                        self.assertFalse(url.startswith(("/", "http:", "https:", "..")))
                        self.assertTrue((output / url).is_file())
                    manifest = json.loads((output / "workhub-site.json").read_text())
                    self.assertEqual(manifest["design_system"], "workhub-v1")
                    self.assertEqual((output / "design-system.css").read_bytes(),
                                     (ROOT / "static/design-system.css").read_bytes())
                    self.assertEqual((output / "runtime.js").read_bytes(),
                                     (ROOT / "templates/runtime.js").read_bytes())
                    data = json.loads((output / "data.json").read_text())
                    self.assertFalse(data["is_demo"])
                    self.assertEqual(data["items"], [])
                    # An ordinary server, with no Workhub paths or proxy, must
                    # deliver the generated HTML, theme, runtime and data.
                    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(output)))
                    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
                    thread.start()
                    try:
                        opener = build_opener(ProxyHandler({}))
                        for path in ("index.html", *parser.urls, "data.json"):
                            with opener.open(f"http://127.0.0.1:{server.server_port}/{path}", timeout=3) as response:
                                self.assertEqual(response.status, 200)
                                self.assertEqual(response.read(), (output / path).read_bytes())
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=2)

    def test_generator_protects_existing_site_and_explicit_demo_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing"
            output.mkdir()
            original = b"<title>Existing user site</title>"
            (output / "index.html").write_bytes(original)
            result = self.generate("radar", output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((output / "index.html").read_bytes(), original)
            self.assertEqual(list(output.iterdir()), [output / "index.html"])
            preview = Path(temporary) / "demo"
            result = self.generate("brief", preview, "--demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((preview / "data.json").read_text())
            self.assertIs(data["is_demo"], True)
            self.assertGreater(len(data["items"]), 0)

    def test_common_small_text_and_buttons_meet_aa_contrast(self):
        css = (ROOT / "static/design-system.css").read_text()
        tokens = dict(re.findall(r"(--wh-[\w-]+):\s*(#[\da-fA-F]{3,6});", css))

        def luminance(hexcolor):
            hexcolor = hexcolor.lstrip("#")
            if len(hexcolor) == 3:
                hexcolor = "".join(c * 2 for c in hexcolor)
            channels = [int(hexcolor[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            rgb = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
            return sum(c * w for c, w in zip(rgb, (.2126, .7152, .0722)))

        for foreground, background in (("--wh-ink", "--wh-bg"), ("--wh-muted", "--wh-bg"),
                                       ("--wh-muted", "--wh-surface"), ("--wh-surface", "--wh-accent")):
            with self.subTest(foreground=foreground, background=background):
                light, dark = sorted((luminance(tokens[foreground]), luminance(tokens[background])), reverse=True)
                self.assertGreaterEqual((light + .05) / (dark + .05), 4.5)


if __name__ == "__main__":
    unittest.main()
