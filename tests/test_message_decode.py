import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "message_decode", os.path.join(ROOT, "core-wecom", "message_decode.py")
)
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)


class MessageDecodeTests(unittest.TestCase):
    def test_recovers_type2_ssh_command(self):
        raw = '/\x08\x00\x12+\n)ssh -i "私钥路径" root@43.160.235.132'
        text = md.recover_display_text(2, raw)
        self.assertIn("ssh -i", text)
        self.assertNotIn("\x08", text)

    def test_recovers_toml_blob(self):
        raw = '\x06\x08\x00\x12\x06\n\x06[cli]\ninstaller = "internal"\n'
        text = md.recover_display_text(2, raw)
        self.assertIn("installer", text)

    def test_image_falls_back_to_url(self):
        raw = "\x07\x08x\x03BChttps://wework.qpic.cn/wwpic3az/demo/0"
        text = md.recover_display_text(4, raw)
        self.assertIn("wework.qpic.cn", text)
        self.assertIn("[图片]", text)

    def test_image_fields_split_url_from_caption(self):
        raw = "[图片] https://wework.qpic.cn/wwpic3az/163172_demo_1767679929/0P"
        text, url = md.recover_display_fields(4, raw)[:2]
        self.assertEqual(text, "[图片]")
        self.assertEqual(url, "https://wework.qpic.cn/wwpic3az/163172_demo_1767679929/0")

    def test_ignores_doc_icon_png(self):
        raw = "https://wwcdn.weixin.qq.com/node/wework/images/sheet_tsp@3x.png"
        self.assertEqual(md.extract_image_urls(raw), [])

    def test_plain_chinese_stays(self):
        self.assertEqual(md.recover_display_text(2, "你好世界"), "你好世界")

    def test_extracts_zip_from_garbled_file_text(self):
        raw = "[图片/文件] 文件] 文件] 文件] AiSession-client-win.zip"
        text, url, name = md.recover_display_fields(15, raw)
        self.assertEqual(name, "AiSession-client-win.zip")
        self.assertIn("AiSession-client-win.zip", text)
        self.assertEqual(url, "")

    def test_extracts_hash_named_jpg(self):
        raw = "[文件] ] ] ] ] ] -045c4806893b4f79b2736d9491b28aa5_compress.jpg"
        self.assertEqual(
            md.extract_attachment_name(raw),
            "-045c4806893b4f79b2736d9491b28aa5_compress.jpg",
        )

    def test_plain_text_does_not_become_file(self):
        text, url, name = md.recover_display_fields(2, "请看 prompt_content.txt")
        self.assertEqual(name, "")
        self.assertIn("prompt_content.txt", text)

    def test_strips_protobuf_prefix_from_synced_text(self):
        text = md.recover_display_text(2, "M I\nG试用期全部用这个 过了试用期公司会分配账号使用grok")
        self.assertTrue(text.startswith("试用期"))
        self.assertIn("grok", text)

    def test_drops_random_id_tokens(self):
        self.assertTrue(md._is_id_token("dt2nbZncRN6ajH8"))
        self.assertFalse(md._is_id_token("qodercli"))
        self.assertEqual(md.recover_display_text(2, "dt2nbZncRN6ajH8"), "[文本]")

    def test_strips_leading_junk_before_chinese(self):
        self.assertEqual(md.recover_display_text(2, "'肯定是王伦那边同意了才能接"), "肯定是王伦那边同意了才能接")
        self.assertIn("汪伦", md.recover_display_text(2, "6你有汪伦同意吗？还是自己直接接入进去"))

    def test_drops_wecom_app_version(self):
        self.assertEqual(md.recover_display_text(2, "2.8.18"), "[文本]")
        text = md.recover_display_text(2, "目前缺失信息：无\n2.8.18")
        self.assertEqual(text, "目前缺失信息：无")
        self.assertNotIn("2.8.18", md.recover_display_text(
            2, "群聊的聊天记录\n2.8.18\n518 经开区"
        ))
        parts = [
            "【工作进度播报】\n汇报人：吴贤腾",
            "节点：下午进度",
            "人才库修改模板系统80%：针对用户反馈，生成 _修改后.docx",
        ]
        text = md._pick_best_text(parts, ["_修改后.docx"])
        self.assertIn("汇报人：吴贤腾", text)
        self.assertNotEqual(text, "_修改后.docx")


if __name__ == "__main__":
    unittest.main()
