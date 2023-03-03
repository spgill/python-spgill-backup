import typing


class BackupLocation(typing.TypedDict, total=False):
    path: str
    passwordFile: str
    passwordCommand: str
    env: dict[str, str]
    cleanEnv: dict[str, str]


class BackupSourceDef(typing.TypedDict, total=False):
    # Basic include args don't have flags they're just added at the end of the restic command
    include: list[str]

    # Include arguments with flags
    includeFilesFrom: str
    includeFilesFromVerbatim: str

    # Exclude arguments with flags
    exclude: list[str]
    iexclude: list[str]
    excludeIfPresent: list[str]
    excludeFile: list[str]
    iexcludeFile: list[str]
    excludeCaches: bool
    excludeLargerThan: str


class BackupProfile(BackupSourceDef, total=False):
    hostname: str
    archiveName: str
    location: typing.Union[str, list[str]]
    retention: str
    tags: list[str]
    groups: dict[str, BackupSourceDef]
    args: list[str]

    # Private attributes
    _locations: list[str]


class ArchiveConfiguration(typing.TypedDict, total=False):
    cache: str
    passwordFile: str


class MasterBackupConfiguration(typing.TypedDict, total=False):
    v: int
    cache: str
    policies: dict[str, str]
    locations: dict[str, BackupLocation]
    profiles: dict[str, BackupProfile]
    globalProfile: BackupProfile
    archive: ArchiveConfiguration
