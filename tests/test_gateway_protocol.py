import json

import pytest

import pyqbot
from pyqbot._gateway.close_codes import CloseAction, classify_close_code
from pyqbot._gateway.payload import (
    READY_EVENT,
    RESUMED_EVENT,
    Hello,
    OpCode,
    Ready,
    ReadyUser,
    decode_payload,
    encode_heartbeat,
    encode_identify,
    encode_resume,
)

# ---- OpCode 与 Intents：逐项对照 dev-prepare/event-emit/payload.md 的表格 ----


def test_opcodes_match_the_documented_table() -> None:
    assert {op.name: op.value for op in OpCode} == {
        "DISPATCH": 0,
        "HEARTBEAT": 1,
        "IDENTIFY": 2,
        "RESUME": 6,
        "RECONNECT": 7,
        "INVALID_SESSION": 9,
        "HELLO": 10,
        "HEARTBEAT_ACK": 11,
        "HTTP_CALLBACK_ACK": 12,
        "CALLBACK_VALIDATION": 13,
    }


def test_intents_match_the_documented_bits() -> None:
    assert {intent.name: intent.value for intent in pyqbot.Intents} == {
        "GUILDS": 1 << 0,
        "GUILD_MEMBERS": 1 << 1,
        "GUILD_MESSAGES": 1 << 9,
        "GUILD_MESSAGE_REACTIONS": 1 << 10,
        "DIRECT_MESSAGE": 1 << 12,
        "GROUP_MEMBER_EVENT": 1 << 24,
        "GROUP_AND_C2C_EVENT": 1 << 25,
        "INTERACTION": 1 << 26,
        "MESSAGE_AUDIT": 1 << 27,
        "FORUMS_EVENT": 1 << 28,
        "AUDIO_ACTION": 1 << 29,
        "PUBLIC_GUILD_MESSAGES": 1 << 30,
    }


def test_intents_combine_like_the_documented_example() -> None:
    # 文档举例：0|1<<30|1<<1 代表订阅 PUBLIC_GUILD_MESSAGES 和 GUILD_MEMBERS。
    intents = pyqbot.Intents.PUBLIC_GUILD_MESSAGES | pyqbot.Intents.GUILD_MEMBERS

    assert intents == 0 | 1 << 30 | 1 << 1
    assert pyqbot.Intents.GUILD_MEMBERS in intents


def test_unknown_intent_bits_are_kept() -> None:
    intents = pyqbot.Intents(1 << 31 | 1 << 25)

    assert int(intents) == 1 << 31 | 1 << 25
    assert pyqbot.Intents.GROUP_AND_C2C_EVENT in intents


# ---- 下行解码 ----


def test_hello_is_decoded_with_interval_in_both_units() -> None:
    payload = decode_payload('{"op": 10, "d": {"heartbeat_interval": 45000}}')

    assert payload.op is OpCode.HELLO
    assert (payload.s, payload.t, payload.id) == (None, None, None)
    hello = payload.decode_data(Hello)
    assert hello.heartbeat_interval == 45000
    assert hello.heartbeat_interval_seconds == 45


def test_ready_dispatch_is_decoded_from_bytes() -> None:
    frame = json.dumps(
        {
            "op": 0,
            "s": 1,
            "t": "READY",
            "d": {
                "version": 1,
                "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
                "user": {"id": "6158788878435714165", "username": "群pro测试机器人", "bot": True},
                "shard": [0, 0],
            },
        }
    ).encode()

    payload = decode_payload(frame)

    assert (payload.op, payload.s, payload.t) == (OpCode.DISPATCH, 1, READY_EVENT)
    assert payload.decode_data(Ready) == Ready(
        version=1,
        session_id="082ee18c-0be3-491b-9d8b-fbd95c51673a",
        user=ReadyUser(id="6158788878435714165", username="群pro测试机器人", bot=True),
        shard=(0, 0),
    )


def test_resumed_dispatch_carries_an_empty_string() -> None:
    payload = decode_payload('{"op": 0, "s": 2002, "t": "RESUMED", "d": ""}')

    assert (payload.t, payload.s) == (RESUMED_EVENT, 2002)
    assert payload.decode_data(str) == ""


def test_payload_without_d_decodes_d_as_none() -> None:
    payload = decode_payload('{"op": 11}')

    assert payload.op is OpCode.HEARTBEAT_ACK
    assert payload.data == b"null"
    assert payload.decode_data(type(None)) is None


def test_dispatch_keeps_event_id_and_raw_data_for_the_event_layer() -> None:
    payload = decode_payload(
        '{"id": "ev-1", "op": 0, "s": 42, "t": "C2C_MESSAGE_CREATE", "d": {"content": "你好"}}'
    )

    assert payload.id == "ev-1"
    assert json.loads(payload.data) == {"content": "你好"}


def test_unknown_opcode_and_fields_do_not_break_decoding() -> None:
    payload = decode_payload('{"op": 99, "d": {"x": 1}, "added_later": true}')

    assert payload.op == 99
    assert isinstance(payload.op, OpCode)
    assert payload.op not in set(OpCode)


def test_payload_is_hashable_and_hides_the_raw_data_in_repr() -> None:
    payload = decode_payload('{"op": 0, "s": 3, "t": "X", "d": {"secret": "content"}}')

    assert hash(payload) == hash(
        decode_payload('{"op": 0, "s": 3, "t": "X", "d": {"secret": "content"}}')
    )
    assert "content" not in repr(payload)


DEEP = "[" * 100_000 + "]" * 100_000


@pytest.mark.parametrize(
    "frame",
    ["not json", "[]", '{"d": {}}', '{"op": "1"}', '{"op": 1, "s": "x"}', b"\xff", DEEP],
)
def test_malformed_frames_raise_payload_error(frame: str | bytes) -> None:
    with pytest.raises(pyqbot.PayloadError, match="无法解码网关 payload"):
        decode_payload(frame)


@pytest.mark.parametrize("d", ['{"interval": 45000}', DEEP])
def test_data_of_the_wrong_shape_raises_payload_error(d: str) -> None:
    payload = decode_payload(f'{{"op": 10, "d": {d}}}')

    with pytest.raises(pyqbot.PayloadError, match="无法解码"):
        payload.decode_data(Hello)


def test_ready_tolerates_missing_optional_fields() -> None:
    payload = decode_payload('{"op": 0, "s": 1, "t": "READY", "d": {"session_id": "s"}}')

    assert payload.decode_data(Ready) == Ready(session_id="s")


@pytest.mark.parametrize(
    ("d", "expected"),
    [
        (
            {"session_id": "s", "user": {"id": 6158788878435714165, "username": "bot"}},
            Ready(session_id="s", user=ReadyUser(username="bot")),
        ),
        (
            {"session_id": "s", "user": {"username": "bot"}},
            Ready(session_id="s", user=ReadyUser(username="bot")),
        ),
        ({"session_id": "s", "shard": None}, Ready(session_id="s")),
        ({"session_id": "s", "version": "1"}, Ready(session_id="s")),
        ({"session_id": "s", "user": "bot"}, Ready(session_id="s")),
    ],
)
def test_ready_tolerates_minor_fields_of_the_wrong_type(d: object, expected: Ready) -> None:
    payload = decode_payload(json.dumps({"op": 0, "s": 1, "t": "READY", "d": d}))

    assert payload.decode_data(Ready) == expected


@pytest.mark.parametrize("d", [{}, {"session_id": 1}, {"session_id": None}])
def test_ready_without_a_usable_session_id_fails(d: object) -> None:
    payload = decode_payload(json.dumps({"op": 0, "t": "READY", "d": d}))

    with pytest.raises(pyqbot.PayloadError):
        payload.decode_data(Ready)


# ---- 上行编码：与文档的示例结构逐字段对照 ----


def test_identify_matches_the_documented_shape() -> None:
    frame = encode_identify(
        "ACCESS_TOKEN",
        pyqbot.Intents.GUILDS | pyqbot.Intents.GUILD_MESSAGES,
        shard=(0, 4),
    )

    payload = json.loads(frame)
    assert payload["op"] == 2
    assert payload["d"]["token"] == "QQBot ACCESS_TOKEN"
    assert payload["d"]["intents"] == 513
    assert payload["d"]["shard"] == [0, 4]
    assert set(payload["d"]["properties"]) == {"$os", "$browser", "$device"}
    assert set(payload) == {"op", "d"}


def test_identify_defaults_to_a_single_shard() -> None:
    payload = json.loads(encode_identify("t", pyqbot.Intents.GROUP_AND_C2C_EVENT))

    assert payload["d"]["shard"] == [0, 1]
    assert payload["d"]["intents"] == 1 << 25


@pytest.mark.parametrize("shard", [(1, 1), (-1, 4), (0, 0), (4, 4)])
def test_identify_rejects_impossible_shards(shard: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="shard"):
        encode_identify("t", pyqbot.Intents.GUILDS, shard=shard)


def test_identify_rejects_an_empty_token() -> None:
    with pytest.raises(ValueError, match="access_token"):
        encode_identify("", pyqbot.Intents.GUILDS)


def test_resume_matches_the_documented_shape() -> None:
    payload = json.loads(encode_resume("my_token", "session_id_i_stored", 1337))

    assert payload == {
        "op": 6,
        "d": {"token": "QQBot my_token", "session_id": "session_id_i_stored", "seq": 1337},
    }


@pytest.mark.parametrize(("token", "session_id"), [("", "s"), ("t", "")])
def test_resume_rejects_empty_arguments(token: str, session_id: str) -> None:
    with pytest.raises(ValueError, match="不能为空"):
        encode_resume(token, session_id, 1)


def test_identify_and_resume_frames_are_built_from_hidden_structures() -> None:
    # 编码结果必须带 token；隐藏只作用于 repr，见 test_credentials 的结构测试。
    assert "QQBot secret-tok" in encode_identify("secret-tok", pyqbot.Intents.GUILDS)
    assert "QQBot secret-tok" in encode_resume("secret-tok", "s", 1)


@pytest.mark.parametrize(
    ("seq", "expected"), [(251, {"op": 1, "d": 251}), (None, {"op": 1, "d": None})]
)
def test_heartbeat_carries_the_latest_seq_or_null(seq: int | None, expected: object) -> None:
    assert json.loads(encode_heartbeat(seq)) == expected


def test_encoded_frames_are_text() -> None:
    assert isinstance(encode_heartbeat(None), str)


# ---- 关闭码分类：对照 dev-prepare/error-trace/websocket.md ----


@pytest.mark.parametrize(
    ("code", "action"),
    [
        (4001, CloseAction.GIVE_UP),
        (4002, CloseAction.GIVE_UP),
        (4006, CloseAction.IDENTIFY),
        (4007, CloseAction.IDENTIFY),
        (4008, CloseAction.RESUME),
        (4009, CloseAction.RESUME),
        (4010, CloseAction.GIVE_UP),
        (4011, CloseAction.GIVE_UP),
        (4012, CloseAction.GIVE_UP),
        (4013, CloseAction.GIVE_UP),
        (4014, CloseAction.GIVE_UP),
        (4900, CloseAction.IDENTIFY),
        (4907, CloseAction.IDENTIFY),
        (4913, CloseAction.IDENTIFY),
        (4914, CloseAction.GIVE_UP),
        (4915, CloseAction.GIVE_UP),
    ],
)
def test_documented_close_codes(code: int, action: CloseAction) -> None:
    info = classify_close_code(code)

    assert (info.code, info.action) == (code, action)
    assert info.reason


def test_undocumented_platform_codes_fall_back_to_identify() -> None:
    # 文档：「其他错误，请重新发起 identify」。
    assert classify_close_code(4000).action is CloseAction.IDENTIFY
    assert classify_close_code(4999).action is CloseAction.IDENTIFY


@pytest.mark.parametrize("code", [None, 1000, 1001, 1006, 1011, 3000])
def test_disconnects_without_a_platform_code_try_to_resume(code: int | None) -> None:
    info = classify_close_code(code)

    assert info.action is CloseAction.RESUME
    assert info.code == code
