# Stdlib imports
import os
import pathlib
import re
import sys
import typing

# Vendor imports
from colorama import Fore, Style
import humanize
import yaml

# Local imports
from . import schema


def fixTimestamp(t: str) -> str:
    return re.sub(
        r":(\d+)\.(\d+)",
        lambda match: f":{match.group(1)}.{match.group(2)[:6]}",
        t,
    )


def printLine(*args, file=sys.stdout):
    print("-" * 8, *args, file=file)


def printNestedLine(*args):
    print("-" * 12, *args)


def printWarning(message: str):
    printLine(f"{Fore.YELLOW}{message}{Style.RESET_ALL}", file=sys.stderr)


def printError(message: str):
    print("-" * 8, f"{Fore.RED}{message}{Style.RESET_ALL}", file=sys.stderr)
    exit(1)


def printKeyVal(key: str, value: str = ""):
    print(f"{Fore.YELLOW}{key}{Style.RESET_ALL}: {value}")


def printConfigData(data: typing.Any):
    serialized: str = yaml.dump(data)
    print("\n".join("|  " + line for line in serialized.splitlines()))


def humanReadable(num):
    return humanize.naturalsize(num, binary=True)


def getLocationConfig(
    config: schema.MasterBackupConfiguration, name: str
) -> schema.BackupLocation:
    locations = config.get("locations", {})

    if not (locationData := locations.get(name, None)):
        printError(f"Error: No backup location '{name}' defined in config")

    return locationData


def getProfileConfig(
    config: schema.MasterBackupConfiguration, name: str
) -> schema.BackupProfile:
    profiles = config.get("profiles", {})

    if not (profileData := profiles.get(name, None)):
        printError(f"Error: No backup profile '{name}' defined in config")

    # Ensure there is a location
    if "location" not in profileData:
        printError(f"Error: No location defined for profile '{name}'")

    return profileData


def getBaseArgsForLocation(
    config: schema.MasterBackupConfiguration, locationName: str
) -> list[str]:
    locationConf = getLocationConfig(config, locationName)

    # Generate cache dir args
    cacheArgs = []
    if cachePath := config.get("cache", None):
        cacheArgs = ["--cache-dir", cachePath]

    # Generate password args
    passwordArgs = []
    if "passwordFile" in locationConf:
        passwordArgs = ["--password-file", locationConf["passwordFile"]]
    elif "passwordCommand" in locationConf:
        passwordArgs = ["--password-command", locationConf["passwordCommand"]]
    else:
        printWarning(
            f"Warning: No 'passwordCommand' or 'passwordFile' defined for backup location '{locationName}'"
        )

    # Return the final list of args
    return [
        *cacheArgs,
        *passwordArgs,
        "--repo",
        locationConf["path"],
    ]


def getTagArgs(
    config: schema.MasterBackupConfiguration,
    profileName: str,
) -> list[str]:
    profile = getProfileConfig(config, profileName)
    if tags := profile.get("tags", []):
        return ["--tag", ",".join(tags)]
    return []


def getResticEnv(
    config: schema.MasterBackupConfiguration,
    locationName: str,
) -> dict:
    locationConf = getLocationConfig(config, locationName)

    env = os.environ.copy()

    # Inject any variables defined in the backup location's "env" attribute
    if locationEnv := locationConf.get("env", None):
        env.update(locationEnv)

    return env


def fullyQualifiedPath(pathStr: str, ensureExists: False) -> pathlib.Path:
    path = pathlib.Path(pathStr).expanduser().absolute()
    if ensureExists and not path.exists():
        printError(f"File path '{path}' (from '{pathStr}') does not exist")
    return path


def getIncludeExcludeArgs(
    config: schema.MasterBackupConfiguration,
    profileName: str,
    selectedGroupNames: typing.Sequence[str],
) -> typing.Generator[str, None, None]:
    profile = getProfileConfig(config, profileName)

    # Collate list of backup groups (including the base and global profiles)
    selectedGroups: list[schema.BackupSourceDef] = profile.get(
        "groups", {}
    ).values()
    if selectedGroupNames:
        selectedGroups = [
            group
            for groupName, group in profile.get("groups", {}).items()
            if groupName in selectedGroupNames
        ]

    finalGroups: list[schema.BackupSourceDef] = [
        config.get("globalProfile", {}),
        profile,
        *selectedGroups,
    ]

    # Basic include list must come last in the args, so they will be collected
    # and emitted last
    includeList: list[str] = []

    # Iterate through the groups and generate arguments
    for group in finalGroups:
        # Store basic include entries for emitting at the end
        for entry in group.get("include", []):
            includeList.append(entry)

        # Process various include files flags
        for entry in group.get("includeFilesFrom", []):
            yield "--files-from"
            yield fullyQualifiedPath(entry, True)

        for entry in group.get("includeFilesFromVerbatim", []):
            yield "--files-from-verbatim"
            yield fullyQualifiedPath(entry, True)

        # Process various exlude file flags
        for entry in group.get("exclude", []):
            yield "--exclude"
            yield entry

        for entry in group.get("iexclude", []):
            yield "--iexclude"
            yield entry

        for entry in group.get("excludeIfPresent", []):
            yield "--exclude-if-present"
            yield entry

        for entry in group.get("excludeFile", []):
            yield "--exclude-file"
            yield fullyQualifiedPath(entry, True)

        for entry in group.get("iexcludeFile", []):
            yield "--iexclude-file"
            yield fullyQualifiedPath(entry, True)

        if group.get("excludeCaches", False):
            yield "--exclude-caches"

        if excludeSize := group.get("excludeLargerThan", ""):
            # In case the user specifies a number with a suffix, this will probably be a number
            # and an error should be thrown
            if not isinstance(excludeSize, str):
                printError(
                    f"Option 'excludeLargerThan' should always be a string, not '{excludeSize}' ({type(excludeSize)})"
                )
            yield "--exclude-larger-than"
            yield excludeSize

    # Emit basic include lines
    for entry in includeList:
        yield entry


def getHostnameArgs(profile: schema.BackupProfile) -> list[str]:
    if hostname := profile.get("hostname", None):
        return ["--host", hostname]
    return []
