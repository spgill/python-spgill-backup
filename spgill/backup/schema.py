### stdlib imports
import re
import typing

### vendor imports
import pydantic


# A modification of RFC 1123 (used by k8s) substituting hyphen for underscore as that is more Pythonic
name_pattern = re.compile(r"^[a-z0-9]([_a-z0-9]*[a-z0-9])?$")
name_max_length = 63


def str_is_valid_name(value: str) -> str:
    if not name_pattern.match(value):
        raise ValueError(
            f"'{value}' does not confirm to regex '{name_pattern.pattern}'"
        )
    if len(value) > name_max_length:
        raise ValueError(
            f"'{value}' is more than {name_max_length} characters"
        )
    return value


def dict_keys_are_valid_names(
    value: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    for key in value:
        str_is_valid_name(key)
    return value


class BackupLocation(pydantic.BaseModel):
    path: str
    password_file: typing.Optional[str] = None
    password_command: typing.Optional[str] = None
    env: typing.Optional[dict[str, str]] = None


class BackupRetention(pydantic.BaseModel):
    keep_last: typing.Optional[int] = None
    keep_within: typing.Optional[str] = None

    keep_hourly: typing.Optional[int] = None
    keep_daily: typing.Optional[int] = None
    keep_weekly: typing.Optional[int] = None
    keep_monthly: typing.Optional[int] = None
    keep_yearly: typing.Optional[int] = None


class BackupPolicy(pydantic.BaseModel):
    location: typing.Optional[typing.Union[str, list[str]]]
    schedule: typing.Optional[str] = None
    retention: typing.Optional[BackupRetention] = None


class BackupProfile(pydantic.BaseModel):
    id: typing.Annotated[
        typing.Optional[str], pydantic.AfterValidator(str_is_valid_name)
    ] = None

    policy: typing.Optional[str] = None
    hostname: typing.Optional[str] = None
    archive_name: typing.Optional[str] = None
    tags: list[str] = []
    args: list[str] = []
    auto_apply: typing.Optional[bool] = False

    ### Include/exclude fields ###

    # Basic include args don't have flags they're just added at the end of the restic command
    include: list[str] = []

    # Include arguments with flags
    include_files_from: list[str] = []
    include_files_from_verbatim: list[str] = []

    # Exclude arguments with flags
    exclude: list[str] = []
    iexclude: list[str] = []
    exclude_if_present: list[str] = []
    exclude_file: list[str] = []
    iexclude_file: list[str] = []
    exclude_caches: typing.Optional[bool] = None
    exclude_larger_than: typing.Optional[str] = None


class ArchiveConfiguration(pydantic.BaseModel):
    cache: str
    password_file: str


class RootBackupConfiguration(pydantic.BaseModel):
    locations: typing.Annotated[
        dict[str, BackupLocation],
        pydantic.AfterValidator(dict_keys_are_valid_names),
    ]
    policies: typing.Annotated[
        dict[str, BackupPolicy],
        pydantic.AfterValidator(dict_keys_are_valid_names),
    ]
    profiles: typing.Annotated[
        dict[str, BackupProfile],
        pydantic.AfterValidator(dict_keys_are_valid_names),
    ]

    global_profile: typing.Optional[BackupProfile] = None
    archive: typing.Optional[ArchiveConfiguration] = None
    cache: typing.Optional[str] = None
    v: typing.Optional[int] = None
