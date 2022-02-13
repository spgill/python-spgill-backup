import typing


class BackupLocation(typing.TypedDict, total=False):
    path: str
    passwordFile: str
    passwordCommand: str
    env: dict[str, str]


class BackupSourceDef(typing.TypedDict, total=False):
    include: list[str]
    exclude: list[str]


class BackupProfile(BackupSourceDef, total=False):
    archiveName: str
    location: str
    tags: list[str]
    groups: dict[str, BackupSourceDef]
    args: list[str]


class ArchiveConfiguration(typing.TypedDict, total=False):
    cache: str
    passwordFile: str


class MasterBackupConfiguration(typing.TypedDict, total=False):
    v: int
    cache: str
    locations: dict[str, BackupLocation]
    profiles: dict[str, BackupProfile]
    archive: ArchiveConfiguration
