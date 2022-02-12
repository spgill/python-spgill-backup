# Stdlib imports
import datetime
import itertools
import json
import pathlib
import shlex
import shutil
import sys

# Vendor imports
import click
import colorama
from colorama import Fore, Style

# Local imports
from . import helper, command, config as applicationConfig, schema


@click.group()
@click.pass_context
@click.option(
    "--config",
    "-c",
    type=str,
    help="""Path to backup config file. Defaults to '~/.spgill.backup.yaml'.""",
)
def cli(ctx, config):
    # Initialize colorama (for windows)
    colorama.init()

    # Load the config options and insert it into the context object
    ctx.obj = applicationConfig.loadConfigValues(config)

    # If there are no backup locations defined, print error message and exit
    if not len(ctx.obj.get("locations", {}).keys()):
        helper.printError("Error: No backup locations defined in config")

    # If there are no backup profiles defined, print error message and exit
    if not len(ctx.obj.get("profiles", {}).keys()):
        helper.printError("Error: No backup profiles defined in config")


@cli.command(
    name="run", help="""Execute a backup profile with the name PROFILE."""
)
@click.pass_obj
@click.option(
    "--go",
    "-g",
    is_flag=True,
    help="""By default, this command runs in 'dry run' mode. This flag is necessary to actually execute the backup.""",
)
@click.argument("profile", type=str, required=True)
def cli_run(obj, go, profile):
    profileConf = helper.getProfileConfig(obj, profile)
    locationName = profileConf["location"]

    # Get the repo's data
    helper.printLine("Chosen profile:", profile)
    helper.printLine("Backup location:", locationName)

    # If in preview mode, print a warning
    if not go:
        helper.printWarning(
            "Warning: Running in dry-run mode. Run tool again with '--go' option to execute backup."
        )

    helper.printLine("Beginning backup...")

    # Add global include/exclude rules, then iterate through each group and add theirs
    include = profileConf.get("include", [])
    exclude = profileConf.get("exclude", [])
    groups = profileConf.get("groups", {})
    for _, groupDef in groups.items():
        include += groupDef.get("include", [])
        exclude += groupDef.get("exclude", [])

    # Construct the restic args
    args = [
        *helper.getBaseArgsForLocation(obj, locationName),
        "backup",
        *helper.getTagArgs(obj, profile),
        *itertools.chain(*[["--exclude", pattern] for pattern in exclude]),
        *include,
        *profileConf.get("args", []),
    ]

    # If this is the real deal, execute the backup
    if go:
        command.restic(
            args, _env=helper.getResticEnv(obj, locationName), _fg=True
        )

    # If in preview mode, just print the joined args
    else:
        print(shlex.join(args))


@cli.command(
    name="cli",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_interspersed_args=False,
    ),
    help="""Execute the restic command line directly. Repo, cache, and password args for PROFILE are automatically added before your own RESTIC_ARGS.""",
)
@click.pass_obj
@click.argument("location", type=str, required=True)
@click.argument("restic_args", nargs=-1, type=click.UNPROCESSED)
def cli_restic(obj, location, restic_args):
    # Collate everything, with unprocessed args, into a list
    args = [
        *helper.getBaseArgsForLocation(obj, location),
        *restic_args,
    ]

    # Execute the command
    command.restic(args, _env=helper.getResticEnv(obj, location), _fg=True)


@cli.command(
    name="command",
    help="""Write the basic restic command for a backup location to stdout. Helpful for using a repo in an external script.""",
)
@click.pass_obj
@click.argument("location", type=str, required=True)
def cli_command(obj: schema.MasterBackupConfiguration, location: str):
    locationConf = helper.getLocationConfig(obj, location)

    # We need to convert any environment vars to key=value pairs
    envArgs = []
    if locationEnv := locationConf.get("env", None):
        envArgs.append("env")
        for key, value in locationEnv.items():
            envArgs.append(f"{key}={value}")

    sys.stdout.write(
        shlex.join(
            [*envArgs, "restic", *helper.getBaseArgsForLocation(obj, location)]
        )
    )


@cli.command(
    name="archive",
    help=f"""
    Extract and archive snapshots from repo of PROFILE to a tar archive at DESTINATION. If no SNAPSHOTS are given, defaults to 'latest' snapshot. Includes AES256 encyption and Zstd compression.

    {Fore.RED}WARNING{Style.RESET_ALL}: Only designed to work in a Linux/macOS environment
    """,
)
@click.pass_obj
@click.argument("destination", type=str, required=True)
@click.argument("profile", type=str, required=True)
@click.argument("snapshots", nargs=-1, type=str, required=False)
def cli_archive(
    obj: schema.MasterBackupConfiguration, destination, profile: str, snapshots
):
    profileConf = helper.getProfileConfig(obj, profile)
    locationName = profileConf["location"]
    # locationConf = helper.getLocationConfig(locationName)

    # Pull archive configuration out of larger configuration structure
    archiveConf = obj.get("archive", {})

    # Reusable base args for following commands
    locationArgs = helper.getBaseArgsForLocation(obj, locationName)
    locationEnv = helper.getResticEnv(obj, locationName)

    dumpDestDir = pathlib.Path(destination).expanduser()
    if not dumpDestDir.exists():
        helper.printError(
            f"Destination directory '{dumpDestDir}' does not exist"
        )

    # Cache directory is optional
    cacheEnabled = "cache" in archiveConf
    dumpCacheDir = (
        pathlib.Path(
            archiveConf.get("cache", obj.get("cache", "~"))
        ).expanduser()
        if cacheEnabled
        else dumpDestDir
    )

    dumpPasswordFile = pathlib.Path(archiveConf.get("passwordFile", None))

    # If no snapshots have been selected, default to latest
    if not len(snapshots):
        snapshots = ["latest"]

    # Print some startup information
    helper.printLine("Selected profile:", profile)
    helper.printLine("Selected snapshots:", ", ".join(snapshots))

    # Iterate through each snapshot that's being dumped
    for snapshotName in snapshots:
        helper.printLine(f"Processing '{snapshotName}':")

        # Fetch information on the latest snapshot
        helper.printNestedLine(f"Querying snapshots for '{snapshotName}'...")
        snapsArgs = [
            *locationArgs,
            "--quiet",
            "snapshots",
            snapshotName,
            "--json",
        ]
        snapsCommand = command.restic(snapsArgs, _env=locationEnv)
        if b"null" in snapsCommand.stdout:
            helper.printError(f"Could not find snapshot: '{snapshotName}'")
        latest = json.loads(snapsCommand.stdout)[0]

        # Convert the timestamp to a datetime object
        # Requires the we first round off the milliseconds to three decimal places
        latest["time"] = datetime.datetime.fromisoformat(
            helper.fixTimestamp(latest["time"])
        )

        # Creat timestamp and unique filename for this repo
        timestamp = latest["time"].strftime(r"%Y%m%d%H%M%S")
        repoDirName = pathlib.Path(profileConf["repo"]).name
        filename = (
            f"{repoDirName}_{timestamp}_{latest['short_id']}.tar.zst.aes"
        )

        # Make sure the cache and destination files don't exist yet
        dumpCacheFile = dumpCacheDir / filename
        if dumpCacheFile.exists():
            helper.printError(f"Archive already exists at '{dumpCacheFile}'")
        dumpDestFile = dumpDestDir / filename
        if dumpDestFile.exists():
            helper.printError(
                f"Final archive already exists at '{dumpDestFile}'"
            )

        # Inform the user which snapshot is being used
        helper.printNestedLine(
            f"Using snapshot ID '{latest['id'][:8]}' with timestamp '{latest['time']}'"
        )

        # Fetch the size of the latest snapshot
        helper.printNestedLine("Querying snapshot size...")
        statsArgs = [*locationArgs, "--quiet", "stats", latest["id"], "--json"]
        statsCommand = command.restic(statsArgs, _env=locationEnv)
        latestSize = json.loads(statsCommand.stdout)["total_size"]
        helper.printNestedLine(
            f"Archive should be no larger than (approx.) {helper.humanReadable(latestSize)}"
        )

        # Ensure there's enough space in the cache dir and the destination
        dumpCacheUsage = shutil.disk_usage(dumpCacheDir)
        if dumpCacheUsage.free < latestSize:
            helper.printError(
                f"Error: Dump archive needs at least {helper.humanReadable(latestSize)}, "
                f"but directory only has {helper.humanReadable(dumpCacheUsage.free)} free"
            )
        dumpDestUsage = shutil.disk_usage(dumpDestDir)
        if dumpDestUsage.free < latestSize:
            helper.printError(
                f"Error: Dump archive needs at least {helper.humanReadable(latestSize)}, "
                f"but destination directory only has {helper.humanReadable(dumpDestUsage.free)} free"
            )

        # Begin dumping the repo to an archive
        helper.printNestedLine(
            "Creating archive... (compression and encryption enabled)"
        )
        print("Dumping to", dumpCacheFile)
        dumpCommand = command.openSsl(
            command.zStd(
                command.pv(
                    command.restic(
                        *[*locationArgs, "dump", latest["id"], "/"],
                        _env=locationEnv,
                        _piped=True,
                    ),
                    *["-pterbs", str(latestSize)],
                    _err=sys.stderr,
                    _piped=True,
                ),
                *["-c", "-T8"],
                _piped=True,
            ),
            *[
                "enc",
                "-aes-256-cbc",
                "-md",
                "sha512",
                "-pbkdf2",
                "-iter",
                "100000",
                "-pass",
                f"file:{dumpPasswordFile}",
                "-e",
            ],
            _out=str(dumpCacheFile),
        )

        # Detect dump errors
        if dumpCommand.exit_code != 0:
            helper.printError(
                f"Dump command returned with error code {dumpCommand.exit_code}. Aborting."
            )

        # Copy the dump archive to the destination, if cache was enabled
        if cacheEnabled:
            helper.printNestedLine("Moving archive to final destination...")
            dumpSize = dumpCacheFile.stat().st_size
            copyCommand = command.pv(
                *["-pterbs", dumpSize, dumpCacheFile],
                _out=str(dumpDestFile),
                _err=sys.stderr,
            )

            # After copying the dump to the destination, remove the cached dump file
            if copyCommand.exit_code != 0:
                helper.printError(
                    f"Copy command returned with error code {copyCommand.exit_code}. Aborting."
                )
            dumpCacheFile.unlink()

        # Print success message for this repo
        helper.printNestedLine(
            f"{Fore.GREEN}Success!{Style.RESET_ALL} Archive is now available at {dumpDestFile}"
        )


@cli.command(
    name="decrypt",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_interspersed_args=False,
    ),
    help=f"""
    Take an archive at FILE_INPUT, that was previously generated by the dump command, and write the decrypted and decompressed archive to FILE_OUTPUT.

    {Fore.RED}WARNING{Style.RESET_ALL}: Only works on Linux/macOS
    """,
)
@click.pass_obj
@click.argument("file_input", type=click.File("rb"))
@click.argument("file_output", type=click.File("wb"))
def cli_decrypt(obj, file_input, file_output):
    # Ensure output is NOT a terminal
    if hasattr(file_output, "isatty") and file_output.isatty():
        helper.printError("Stdout is a TTY. Try piping this command instead.")

    # Construct arguments for the command chain
    dumpPasswordPath = obj.get("dump", {}).get("passwordFile", "")

    # Pipe openssl to zstd and then stdout
    command.zStd(
        command.openSsl(
            *[
                "enc",
                "-aes-256-cbc",
                "-md",
                "sha512",
                "-pbkdf2",
                "-iter",
                "100000",
                "-pass",
                f"file:{dumpPasswordPath}",
                "-d",
            ],
            _piped=True,
            _in=file_input,
        ),
        *["-dc", "-T8"],
        _out=file_output,
    )


@cli.command(
    name="list",
    help="""List all backup locations and profiles defined in config file.""",
)
@click.pass_obj
def cli_list(obj: schema.MasterBackupConfiguration):
    # Locations
    helper.printLine("Locations:")
    for locationName, locationConf in obj["locations"].items():
        helper.printKeyVal("Name", locationName)
        helper.printKeyVal("  path", locationConf.get("path"))
        helper.printKeyVal("  passwordFile", locationConf.get("passwordFile"))
        helper.printKeyVal(
            "  passwordCommand", locationConf.get("passwordCommand")
        )

        helper.printKeyVal("  env")
        for key, value in locationConf.get("env", {}).items():
            helper.printKeyVal(f"    {key}", value)

        print()

    # Profiles
    helper.printLine("Profiles:")
    for profileName, profileConf in obj["profiles"].items():
        helper.printKeyVal("Name", profileName)
        helper.printKeyVal("  location", profileConf["location"])
        helper.printKeyVal("  tags", ", ".join(profileConf.get("tags", [])))

        helper.printKeyVal("  include")
        for line in profileConf.get("include", []):
            print(f"    {line}")

        helper.printKeyVal("  exclude")
        for line in profileConf.get("exclude", []):
            print(f"    {line}")

        helper.printKeyVal("  groups")
        for groupName, groupConf in profileConf.get("groups", {}).items():
            helper.printKeyVal(f"    {groupName}")
            helper.printKeyVal("      include")
            for line in groupConf.get("include", []):
                print(f"        {line}")
            helper.printKeyVal("      exclude")
            for line in groupConf.get("exclude", []):
                print(f"        {line}")

        helper.printKeyVal("  args")
        for line in profileConf.get("args", []):
            print(f"    {line}")

        print()


if __name__ == "__main__":
    cli()
