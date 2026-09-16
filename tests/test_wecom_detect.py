import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

wecom = importlib.import_module("core-wecom.chat_platform")


class WeComDetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.wxwork = os.path.join(self.root, "WXWork")
        self.account_data = os.path.join(self.wxwork, "1688855370846072", "Data")
        os.makedirs(self.account_data)
        with open(os.path.join(self.account_data, "message.db"), "wb") as f:
            f.write(b"\xecencryptedheader")
        self.decrypted = os.path.join(self.root, "wxwork_decrypted")
        self.live_patch = patch.object(wecom, "load_live_manifest", return_value=None)
        self.live_patch.start()

    def tearDown(self):
        self.live_patch.stop()
        self.tmp.cleanup()

    def test_collect_data_dirs_finds_account_data(self):
        found = wecom._collect_data_dirs(self.wxwork)
        self.assertEqual(found, [self.account_data])

    def test_collect_data_dirs_skips_non_account_folders(self):
        os.makedirs(os.path.join(self.wxwork, "Global", "Data"))
        with open(os.path.join(self.wxwork, "Global", "Data", "message.db"), "wb") as f:
            f.write(b"SQLite format 3\x00")
        found = wecom._collect_data_dirs(self.wxwork)
        self.assertEqual(found, [self.account_data])

    def test_detect_data_dir_uses_custom_wxwork_root(self):
        with patch.object(wecom, "_get_wxwork_base_dirs", return_value=[self.wxwork]), \
             patch.object(wecom, "DECRYPTED_DIR", self.decrypted):
            plat = wecom.WeComPlatform()
            self.assertEqual(plat.detect_data_dir(), self.account_data)
            self.assertEqual(plat.data_dir, self.account_data)

    def test_detect_data_dir_prefers_plaintext_decrypted_dir(self):
        os.makedirs(self.decrypted)
        with open(os.path.join(self.decrypted, "message.db"), "wb") as f:
            f.write(b"SQLite format 3\x00")
        with patch.object(wecom, "_get_wxwork_base_dirs", return_value=[self.wxwork]), \
             patch.object(wecom, "DECRYPTED_DIR", self.decrypted):
            plat = wecom.WeComPlatform()
            self.assertEqual(plat.detect_data_dir(), self.decrypted)

    def test_detect_data_dir_picks_newer_account(self):
        older = os.path.join(self.wxwork, "1688855723749883", "Data")
        os.makedirs(older)
        with open(os.path.join(older, "message.db"), "wb") as f:
            f.write(b"\x04encrypted")
        os.utime(older, (1, 1))
        os.utime(self.account_data, (100, 100))
        with patch.object(wecom, "_get_wxwork_base_dirs", return_value=[self.wxwork]), \
             patch.object(wecom, "DECRYPTED_DIR", self.decrypted):
            plat = wecom.WeComPlatform()
            self.assertEqual(plat.detect_data_dir(), self.account_data)

    def test_append_wxwork_base_includes_nested_wxwork(self):
        parent = os.path.join(self.root, "chat_records")
        nested = os.path.join(parent, "WXWork")
        os.makedirs(nested)
        bases = []
        wecom._append_wxwork_base(parent, bases)
        self.assertEqual(bases, [os.path.abspath(parent), os.path.abspath(nested)])

    def test_detect_live_manifest_uses_remote_dir(self):
        live = {"mode": "live", "decrypted_dir": r"C:\wxwork_pull\decrypted"}
        with patch.object(wecom, "load_live_manifest", return_value=live), \
             patch.object(wecom, "DECRYPTED_DIR", self.decrypted):
            plat = wecom.WeComPlatform()
            self.assertEqual(plat.detect_data_dir(), r"C:\wxwork_pull\decrypted")
            self.assertTrue(plat._live)


if __name__ == "__main__":
    unittest.main()
