import enum
import json
from datetime import UTC, datetime

import msgspec
import pytest

from pyqbot._model import Model, OpenIntEnum, OpenStrEnum, RequestModel, decode


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


class Level(OpenIntEnum):
    LOW = 1
    HIGH = 2


class Message(Model):
    level: Level


def test_open_enum_decodes_known_values_to_members() -> None:
    assert msgspec.json.decode(b'{"level": 2}', type=Message).level is Level.HIGH


def test_open_enum_keeps_unknown_values_instead_of_failing() -> None:
    message = msgspec.json.decode(b'{"level": 9}', type=Message)

    assert isinstance(message.level, Level)
    assert (message.level.name, message.level.value) == ("UNKNOWN", 9)
    assert message.level == 9
    assert message.to_dict() == {"level": 9}


def test_unknown_values_are_not_registered_as_members() -> None:
    assert Level(9) == Level(9)
    assert repr(Level(9)) == "<Level.UNKNOWN: 9>"
    assert 9 not in Level
    assert list(Level) == [Level.LOW, Level.HIGH]
    assert 9 not in Level._value2member_map_  # pyright: ignore[reportPrivateUsage]  验证不缓存


# Level 没有取值 0；False == 0，若不排除 bool 会被当成未知整数收下。
@pytest.mark.parametrize("value", [False, "1", 1.5, None])
def test_open_int_enum_rejects_values_of_the_wrong_type(value: object) -> None:
    with pytest.raises(ValueError, match="is not a valid Level"):
        Level(value)


def test_values_equal_to_a_member_follow_the_standard_library() -> None:
    # 标准库先按值查表，_missing_ 管不到：True == 1、1.0 == 1 直接命中成员。
    assert Level(True) is Level.LOW
    assert Level(1.0) is Level.LOW


@pytest.mark.parametrize("raw", [b'{"level": true}', b'{"level": 1.0}', b'{"level": "1"}'])
def test_decoding_checks_the_json_type_strictly(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(raw, type=Message)


class Scope(OpenStrEnum):
    C2C = "c2c"
    GROUP = "group"


class Operation(Model):
    scope: Scope


def test_open_str_enum_decodes_known_values_to_members() -> None:
    assert msgspec.json.decode(b'{"scope": "group"}', type=Operation).scope is Scope.GROUP


def test_open_str_enum_keeps_unknown_values_instead_of_failing() -> None:
    operation = msgspec.json.decode(b'{"scope": "guild"}', type=Operation)

    assert isinstance(operation.scope, Scope)
    assert (operation.scope.name, operation.scope.value) == ("UNKNOWN", "guild")
    assert operation.scope == "guild"
    assert operation.scope != Scope.C2C
    assert f"{operation.scope}" == "guild"
    assert operation.to_dict() == {"scope": "guild"}
    assert decode(b'{"scope": "guild"}', Operation) == operation


def test_unknown_str_values_are_not_registered_as_members() -> None:
    assert Scope("guild") == Scope("guild")
    assert repr(Scope("guild")) == "<Scope.UNKNOWN: 'guild'>"
    assert "guild" not in Scope
    assert list(Scope) == [Scope.C2C, Scope.GROUP]
    assert "guild" not in Scope._value2member_map_  # pyright: ignore[reportPrivateUsage]  验证不缓存


@pytest.mark.parametrize("value", [1, None, b"c2c"])
def test_open_str_enum_rejects_values_of_the_wrong_type(value: object) -> None:
    with pytest.raises(ValueError, match="is not a valid Scope"):
        Scope(value)


@pytest.mark.parametrize("raw", [b'{"scope": 1}', b'{"scope": null}'])
def test_str_decoding_checks_the_json_type_strictly(raw: bytes) -> None:
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(raw, type=Operation)


# ---- 请求模型 ----


class Body(RequestModel):
    name: str
    note: str | None = None
    tags: tuple[str, ...] = ()
    flag: bool | None = None


class Wrapper(RequestModel):
    body: Body


def test_request_models_leave_out_fields_at_their_defaults() -> None:
    wrapper = Wrapper(body=Body(name="n", flag=False))

    assert msgspec.json.encode(wrapper) == b'{"body":{"name":"n","flag":false}}'
    assert wrapper.to_dict() == {"body": {"name": "n", "flag": False}}
    assert Body(name="n", tags=("a",)).to_dict() == {"name": "n", "tags": ["a"]}


# ---- 凭证字段 ----


class Credential(Model):
    _secret_fields = frozenset({"token"})

    name: str
    token: str


class Holder(Model):
    credential: Credential


def test_secret_fields_are_hidden_in_both_representations() -> None:
    holder = Holder(credential=Credential(name="n", token="tok-123"))

    assert repr(holder) == "Holder(credential=Credential(name='n', token='***'))"
    assert dict(holder.credential.__rich_repr__()) == {"name": "n", "token": "***"}
    assert holder.to_dict() == {"credential": {"name": "n", "token": "tok-123"}}


def test_models_without_secrets_keep_the_default_repr() -> None:
    assert repr(User(id="u1")) == "User(id='u1', nickname=None, union_openid=None)"


def test_misspelled_secret_field_is_rejected_at_class_creation() -> None:
    with pytest.raises(TypeError, match="tokne"):

        class Broken(Model):  # pyright: ignore[reportUnusedClass]  只验证类创建时报错
            _secret_fields = frozenset({"tokne"})

            token: str


# ---- 宽容解码：只有必填字段会让整条数据失败 ----


class Profile(Model):
    id: str
    age: int | None = None
    tags: tuple[str, ...] = ()
    owner: User | None = None


def test_decode_takes_the_fast_path_for_valid_data() -> None:
    assert decode(b'{"id": "p", "age": 3}', Profile) == Profile(id="p", age=3)


def test_optional_fields_of_the_wrong_type_fall_back_to_defaults() -> None:
    raw = b'{"id": "p", "age": "3", "tags": null, "owner": {"id": 1, "nickname": "n"}}'

    # owner.id 是必填字段，类型不符让 owner 整体退回默认值；Profile 本身照常解出。
    assert decode(raw, Profile) == Profile(id="p")


def test_nested_models_are_cleaned_field_by_field() -> None:
    raw = b'{"id": "p", "owner": {"id": "u", "nickname": 5, "unionOpenid": "x"}}'

    assert decode(raw, Profile).owner == User(id="u", union_openid="x")


def test_models_inside_tuples_are_cleaned_one_by_one() -> None:
    raw = json.dumps(
        {
            "openid": "g",
            "members": [
                {"id": "u1", "role": 2, "joined_at": "2026-07-21T02:30:00Z", "nickname": 5},
                {"id": 1, "role": 2, "joined_at": "2026-07-21T02:30:00Z"},  # 必填字段不符
                "不是对象",
                {"id": "u2", "role": 2, "joined_at": "2026-07-21T02:30:00Z", "unionOpenid": "x"},
            ],
        }
    )

    # 坏的次要字段退回默认值，仍不合法的元素只丢掉自己。
    assert decode(raw, Group).members == (
        MEMBER,
        Member(
            id="u2",
            role=Role.ADMIN,
            joined_at=datetime(2026, 7, 21, 2, 30, tzinfo=UTC),
            union_openid="x",
        ),
    )


def test_tuples_of_non_models_and_non_lists_are_left_to_the_field_rule() -> None:
    assert decode(b'{"id": "p", "tags": ["a", 1]}', Profile) == Profile(id="p")
    assert decode(b'{"openid": "g", "members": {}}', Group) == Group(openid="g")


@pytest.mark.parametrize("raw", [b'{"age": 3}', b'{"id": 1}', b"[]", b"not json"])
def test_required_fields_still_fail(raw: bytes) -> None:
    with pytest.raises(msgspec.DecodeError):
        decode(raw, Profile)


def test_non_model_types_are_decoded_strictly() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'"x"', int)
