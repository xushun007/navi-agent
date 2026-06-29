import unittest
import xml.etree.ElementTree as ET

from navi_agent.gateway.weixin import (
    WeixinGateway,
    WeixinReply,
    parse_weixin_message,
    render_text_reply,
    verify_weixin_signature,
)
from navi_agent.gateway.weixin.signature import make_weixin_signature
from navi_agent.gateway.weixin.xml import WeixinMessageParseError
from navi_agent.runtime import RuntimeResult


class FakeApp:
    def __init__(self) -> None:
        self.calls = []

    def handle(self, request):
        self.calls.append(request)
        return RuntimeResult(
            session_id=request.session_id or "generated",
            status="success",
            final_response="reply text",
        )


class WeixinGatewayTests(unittest.TestCase):
    def test_verify_signature_accepts_matching_values(self) -> None:
        signature = make_weixin_signature("token", "123", "nonce")

        verified = verify_weixin_signature(
            token="token",
            signature=signature,
            timestamp="123",
            nonce="nonce",
        )

        self.assertTrue(verified)

    def test_parse_text_message_extracts_core_fields(self) -> None:
        message = parse_weixin_message(_text_payload())

        self.assertEqual(message.to_user_name, "gh_agent")
        self.assertEqual(message.from_user_name, "openid-1")
        self.assertEqual(message.create_time, 1700000000)
        self.assertEqual(message.msg_type, "text")
        self.assertEqual(message.content, "hello")
        self.assertEqual(message.msg_id, "42")
        self.assertEqual(message.user_id, "openid-1")
        self.assertEqual(message.session_id, "weixin:openid-1:42")

    def test_parse_message_rejects_missing_required_field(self) -> None:
        with self.assertRaises(WeixinMessageParseError):
            parse_weixin_message("<xml><FromUserName>openid-1</FromUserName></xml>")

    def test_render_text_reply_swaps_sender_and_receiver(self) -> None:
        reply = WeixinReply(
            to_user_name="openid-1",
            from_user_name="gh_agent",
            content="hello back",
            create_time=1700000001,
        )

        rendered = render_text_reply(reply)
        root = ET.fromstring(rendered)

        self.assertEqual(root.findtext("ToUserName"), "openid-1")
        self.assertEqual(root.findtext("FromUserName"), "gh_agent")
        self.assertEqual(root.findtext("CreateTime"), "1700000001")
        self.assertEqual(root.findtext("MsgType"), "text")
        self.assertEqual(root.findtext("Content"), "hello back")

    def test_gateway_handles_text_message_with_app_service(self) -> None:
        app = FakeApp()
        gateway = WeixinGateway(token="token", app=app)

        rendered = gateway.handle_message(_text_payload())
        root = ET.fromstring(rendered)

        self.assertEqual(root.findtext("Content"), "reply text")
        self.assertEqual(app.calls[0].user_id, "openid-1")
        self.assertEqual(app.calls[0].session_id, "weixin:openid-1:42")
        self.assertEqual(app.calls[0].message, "hello")

    def test_gateway_rejects_invalid_signature(self) -> None:
        app = FakeApp()
        gateway = WeixinGateway(token="token", app=app)

        rendered = gateway.handle_message(
            _text_payload(),
            signature="bad",
            timestamp="123",
            nonce="nonce",
        )

        self.assertIsNone(rendered)
        self.assertEqual(app.calls, [])

    def test_gateway_verifies_echo(self) -> None:
        gateway = WeixinGateway(token="token", app=FakeApp())
        signature = make_weixin_signature("token", "123", "nonce")

        echo = gateway.verify_echo(
            signature=signature,
            timestamp="123",
            nonce="nonce",
            echostr="ok",
        )

        self.assertEqual(echo, "ok")

    def test_gateway_returns_text_fallback_for_non_text_message(self) -> None:
        gateway = WeixinGateway(token="token", app=FakeApp())

        rendered = gateway.handle_message(_image_payload())
        root = ET.fromstring(rendered)

        self.assertEqual(root.findtext("Content"), "暂时只支持文本消息。")


def _text_payload() -> str:
    return """
<xml>
  <ToUserName><![CDATA[gh_agent]]></ToUserName>
  <FromUserName><![CDATA[openid-1]]></FromUserName>
  <CreateTime>1700000000</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[hello]]></Content>
  <MsgId>42</MsgId>
</xml>
"""


def _image_payload() -> str:
    return """
<xml>
  <ToUserName><![CDATA[gh_agent]]></ToUserName>
  <FromUserName><![CDATA[openid-1]]></FromUserName>
  <CreateTime>1700000000</CreateTime>
  <MsgType><![CDATA[image]]></MsgType>
  <MsgId>43</MsgId>
</xml>
"""


if __name__ == "__main__":
    unittest.main()
