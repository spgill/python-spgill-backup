### stdlib imports
import typing

### vendor imports
import pydantic


class BackupLocation(pydantic.BaseModel):
    path: str
    password_file: typing.Optional[str] = None
    password_command: typing.Optional[str] = None
    env: typing.Optional[dict[str, str]] = None
    clean_env: typing.Optional[dict[str, str]] = None


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
    locations: dict[str, BackupLocation]
    policies: dict[str, BackupPolicy]
    profiles: dict[str, BackupProfile]

    global_profile: typing.Optional[BackupProfile] = None
    archive: typing.Optional[ArchiveConfiguration] = None
    cache: typing.Optional[str] = None
    v: typing.Optional[int] = None
