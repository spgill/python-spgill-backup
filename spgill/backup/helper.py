# Stdlib imports
import os
import re
import sys

# Vendor imports
from colorama import Fore, Style
import humanize


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


def printKeyVal(key: str, value: str):
    print(f"{Fore.YELLOW}{key}{Style.RESET_ALL}: {value}")


def humanReadable(num):
    return humanize.naturalsize(num, binary=True)


def getProfileData(config: dict, profileName: str) -> dict:
    profiles = config.get("profiles", {})

    # Make sure the selected profile is defined
    if profileName not in profiles:
        printError(f"Error: No profile '{profileName}' defined in config")

    return profiles[profileName]


def getBaseResticsArgs(config: dict, profileData: dict) -> list[str]:
    # Generate cache dir args
    cacheArgs = []
    if cachePath := config.get("cache", None):
        cacheArgs = ["--cache-dir", cachePath]

    # Generate password args
    passwordArgs = []
    if "passwordFile" in profileData:
        passwordArgs = ["--password-file", profileData["passwordFile"]]
    elif "passwordCommand" in profileData:
        passwordArgs = ["--password-command", profileData["passwordCommand"]]
    else:
        printWarning(
            f"Warning: No 'passwordCommand' or 'passwordFile' defined for profile '{profileData}'"
        )

    # Return the final list of args
    return [
        *cacheArgs,
        *passwordArgs,
        "--repo",
        profileData["repo"],
    ]


def getResticEnv(config: dict, profileData: dict) -> dict:
    env = os.environ.copy()

    # If the repo is an S3 connection, return the s3 credentials as env variables
    if profileData["repo"].startswith("s3"):
        env["AWS_ACCESS_KEY_ID"] = profileData["s3"]["key"]
        env["AWS_SECRET_ACCESS_KEY"] = profileData["s3"]["secret"]

    return env
