import hashlib
import os
import tempfile
import unittest

from shared import agent_update


class AgentUpdateManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "agent"))
        os.makedirs(os.path.join(self.root, "dist"))
        with open(os.path.join(self.root, "agent", "VERSION"), "w", encoding="utf-8") as f:
            f.write("2026.09.16.1\n")
        self.exe = os.path.join(self.root, "dist", "WeComSyncAgent.exe")
        with open(self.exe, "wb") as f:
            f.write(b"fake-agent-bytes")
        agent_update._CACHE.update({"path": "", "mtime": 0.0, "size": 0, "sha256": ""})

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_manifest(self):
        info = agent_update.build_manifest(self.root)
        self.assertEqual(info["version"], "2026.09.16.1")
        self.assertEqual(info["size"], len(b"fake-agent-bytes"))
        self.assertEqual(info["url"], "/api/ingest/agent-exe")
        self.assertEqual(info["sha256"], hashlib.sha256(b"fake-agent-bytes").hexdigest())

    def test_missing_exe_returns_none(self):
        os.remove(self.exe)
        self.assertIsNone(agent_update.build_manifest(self.root))
