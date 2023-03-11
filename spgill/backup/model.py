### stdlib imports
import dataclasses
import typing

### vendor imports
import dataclass_wizard


@dataclasses.dataclass
class BackupLocation:
    path: str
    password_file: typing.Optional[str] = None
    password_command: typing.Optional[str] = None
    env: typing.Optional[dict[str, str]] = None
    clean_env: typing.Optional[dict[str, str]] = None


@dataclasses.dataclass
class BackupSourceDef:
    # Basic include args don't have flags they're just added at the end of the restic command
    include: list[str] = dataclasses.field(default_factory=list)

    # Include arguments with flags
    include_files_from: str = ""
    include_files_from_verbatim: str = ""

    # Exclude arguments with flags
    exclude: list[str] = dataclasses.field(default_factory=list)
    iexclude: list[str] = dataclasses.field(default_factory=list)
    exclude_if_present: list[str] = dataclasses.field(default_factory=list)
    exclude_file: list[str] = dataclasses.field(default_factory=list)
    iexclude_file: list[str] = dataclasses.field(default_factory=list)
    exclude_caches: bool = False
    exclude_larger_than: str = ""


@dataclasses.dataclass
class BackupRetention:
    keep_last: typing.Optional[int] = None
    keep_within: typing.Optional[str] = None

    keep_hourly: typing.Optional[int] = None
    keep_daily: typing.Optional[int] = None
    keep_weekly: typing.Optional[int] = None
    keep_monthly: typing.Optional[int] = None
    keep_yearly: typing.Optional[int] = None


@dataclasses.dataclass
class BackupPolicy:
    location: typing.Optional[typing.Union[str, list[str]]]
    schedule: typing.Optional[str] = None
    retention: typing.Optional[BackupRetention] = None


@dataclasses.dataclass
class BackupProfile(BackupSourceDef):
    policy: typing.Optional[str] = None
    hostname: typing.Optional[str] = None
    archive_name: typing.Optional[str] = None
    tags: typing.Optional[list[str]] = None
    groups: typing.Optional[dict[str, BackupSourceDef]] = None
    args: typing.Optional[list[str]] = None


@dataclasses.dataclass
class ArchiveConfiguration:
    cache: str
    password_file: str


@dataclasses.dataclass
class RootBackupConfiguration(dataclass_wizard.YAMLWizard):
    locations: dict[str, BackupLocation]
    policies: dict[str, BackupPolicy]
    profiles: dict[str, BackupProfile]

    global_profile: typing.Optional[BackupProfile] = None
    archive: typing.Optional[ArchiveConfiguration] = None
    cache: typing.Optional[str] = None
    v: typing.Optional[int] = None
