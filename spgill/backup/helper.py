# Stdlib imports
import os
import re
import sys

# Vendor imports
from colorama import Fore, Style
import humanize

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
    config: schema.MasterBackupConfiguration, profileName: str
) -> list[str]:
    profileConf = getProfileConfig(config, profileName)

    if tags := profileConf.get("tags", []):
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
