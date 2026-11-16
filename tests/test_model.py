import enum
import json
from datetime import UTC, datetime

import msgspec
import pytest

from pyqbot._model import Model


class Role(enum.IntEnum):
    MEMBER = 1
    ADMIN = 2


class User(Model):
    id: str
    nickname: str | None = None
    union_openid: str | None = msgspec.field(default=None, name="unionOpenid")


class Member(User):
    # 必填字段排在父类的可选字段之后：只有字段全部按关键字传入才允许这样声明。
    role: Role
    joined_at: datetime


class Group(Model):
    openid: str
    members: tuple[Member, ...] = ()


MEMBER = Member(id="u1", role=Role.ADMIN, joined_at=datetime(2026, 7, 21, 2, 30, tzinfo=UTC))


def test_to_dict_returns_json_builtins_keyed_by_wire_names() -> None:
    group = Group(openid="g1", members=(MEMBER,))

    assert group.to_dict() == {
        "openid": "g1",
        "members": [
            {
                "id": "u1",
                "nickname": None,
                "unionOpenid": None,
                "role": 2,
                "joined_at": "2026-07-21T02:30:00Z",
            }
        ],
    }
    assert isinstance(group.to_dict()["members"], list)
    assert json.loads(json.dumps(group.to_dict())) == group.to_dict()


def test_fields_are_keyword_only_without_redeclaring_it() -> None:
    with pytest.raises(TypeError):
        User("u1")  # pyright: ignore[reportCallIssue]  故意按位置传参，验证运行时同样拒绝


def test_models_are_immutable_and_hashable() -> None:
    with pytest.raises(AttributeError):
        MEMBER.id = "u2"  # pyright: ignore[reportAttributeAccessIssue]  故意赋值，验证运行时只读

    assert hash(User(id="u1")) == hash(User(id="u1"))


def test_unknown_fields_are_ignored_when_decoding() -> None:
    user = msgspec.json.decode(b'{"id": "u1", "unionOpenid": "x", "added_later": 1}', type=User)

    assert user == User(id="u1", union_openid="x")
