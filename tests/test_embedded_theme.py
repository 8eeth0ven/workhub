"""HTTP checks for fixed local theme resources; no user configuration or data."""
from contextlib import contextmanager
import http.client
from pathlib import Path
import tempfile
import threading
import unittest

import workhub

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def serving(directory=None):
    handler = workhub.directory_handler_for(directory) if directory is not None else workhub.handler_for(None)
    server = workhub.WorkhubServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def get(port, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request("GET", path)
    response = connection.getresponse()
    data = response.read()
    result = response.status, response.getheader("Content-Type"), data
    connection.close()
    return result


class EmbeddedThemeHTTPTests(unittest.TestCase):
    def test_directory_injection_is_idempotent_case_insensitive_and_opt_out_preserving(self):
        original = b'<HTML><HeAd><title>Fixture</title></HeAd><body data-workhub-native="reader"><h1>Original</h1></body></HTML>'
        with tempfile.TemporaryDirectory(prefix="theme-http-") as temporary:
            directory = Path(temporary)
            source = directory / "index.html"
            source.write_bytes(original)
            with serving(directory) as port:
                status, _, page = get(port, "/")
                self.assertEqual(status, 200)
                self.assertEqual(page.count(b"/__workhub/theme.css"), 1)
                self.assertEqual(page.count(b"/__workhub/theme.js"), 1)
                self.assertLess(page.index(b"/__workhub/theme.js"), page.index(b"</HeAd>"))
                self.assertNotIn(str(directory).encode(), page)
                self.assertEqual(source.read_bytes(), original, "injection must not rewrite project files")
                self.assertEqual(get(port, "/?workhub_theme=original")[2], original)
                source.write_bytes(page)
                self.assertEqual(get(port, "/")[2], page, "already-injected pages must remain stable")
                source.write_bytes(b'<head><link rel="stylesheet" href="/__workhub/theme.css"></head><body>Fixture</body>')
                upgraded = get(port, "/")[2]
                self.assertEqual(upgraded.count(b"/__workhub/theme.css"), 1)
                self.assertEqual(upgraded.count(b"/__workhub/theme.js"), 1, "legacy CSS-only injection needs the runtime")

    def test_fixed_routes_and_direct_static_assets(self):
        with tempfile.TemporaryDirectory(prefix="theme-resources-") as temporary:
            directory = Path(temporary)
            (directory / "index.html").write_text("<body>Fixture</body>")
            with serving(directory) as port:
                status, mime, javascript = get(port, "/__workhub/theme.js")
                self.assertEqual(status, 200)
                self.assertIn("javascript", mime)
                self.assertEqual(javascript, (ROOT / "static/embedded-theme.js").read_bytes())
                self.assertEqual(get(port, "/__workhub/theme.js?file=unrelated")[2], javascript)
                self.assertEqual(get(port, "/__workhub/unknown.js")[0], 404)
                status, mime, stylesheet = get(port, "/__workhub/theme.css")
                self.assertEqual(status, 200)
                self.assertIn("text/css", mime)
                self.assertEqual(stylesheet, b"\n".join((ROOT / "static" / name).read_bytes() for name in ("design-system.css", "embedded-theme.css")))
        with serving() as port:
            for name in ("design-system.css", "embedded-theme.css", "embedded-theme.js"):
                with self.subTest(resource=name):
                    status, _, content = get(port, "/" + name)
                    self.assertEqual(status, 200)
                    self.assertEqual(content, (ROOT / "static" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
