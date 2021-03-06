# Stdlib imports
import datetime
import json
import pathlib
import shlex
import shutil
import sys
import typer
import typing

# Vendor imports
import colorama
from colorama import Fore, Style

# Local imports
from . import helper, command, config as applicationConfig, schema


# Create a subclass of the context with correct typing of the backup config object
class BackupCLIContext(typer.Context):
    obj: schema.MasterBackupConfiguration


# Initialize the typer app
cli = typer.Typer()

# Default configuration file path
defaultConfigPath = pathlib.Path("~/.spgill.backup.yaml")


# Main method that initializes the configuration and makes it available to all commands
@cli.callback()
def cli_main(
    ctx: BackupCLIContext,
    config: pathlib.Path = typer.Option(
        defaultConfigPath,
        envvar="SPGILL_BACKUP_CONFIG",
        help="Path to backup configuration file.",
    ),
):
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


@cli.command(name="run", help="Execute a backup profile now.")
def cli_run(
    ctx: BackupCLIContext,
    profile: str = typer.Argument(
        ..., help="Name of the backup profile to use."
    ),
    groups: list[str] = typer.Option(
        [],
        "--group",
        "-g",
        help="Specify a particular backup profile group to include in the backup run. The root group definitions will always be included. If no group is explicitly provided, all defined groups will be included.",
    ),
    dry: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Execute this backup as a 'dry run'. The full restic command will be printed to the console, but restic application will not be invoked. Good for testing that your profile is configured correctly.",
    ),
):
    config = ctx.obj
    profileConf = helper.getProfileConfig(config, profile)
    locationName = profileConf["location"]

    # Get the repo's data
    helper.printLine("Chosen profile:", profile)
    helper.printLine("Backup location:", locationName)

    # If in preview mode, print a warning
    if dry:
        helper.printWarning(
            "Warning: Running in dry-run mode. Run tool again without '--dry-run' or '-d' option to execute backup."
        )

    # Construct the restic args
    args = [
        *helper.getBaseArgsForLocation(config, locationName),
        "backup",
        *helper.getHostnameArgs(profileConf),
        *helper.getTagArgs(config, profile),
        *helper.getIncludeExcludeArgs(config, profile, groups),
        *profileConf.get("args", []),
    ]

    # If this is the real deal, execute the backup
    if not dry:
        helper.printLine("Executing backup...")
        command.restic(
            args, _env=helper.getResticEnv(config, locationName), _fg=True
        )

    # If in preview mode, just print the joined args
    else:
        helper.printLine("Restic environment:")
        print(helper.getResticEnv(config, locationName))
        helper.printLine("Restic command:")
        print("restic " + shlex.join([str(arg) for arg in args]))


@cli.command(
    name="execute",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
    },
    help="Execute the restic command line application directly. All arguments pertaining to the backup location (repo, cache, password, etc.) are appended automatically. Every argument after LOCATION will be passed directly to the restic command.",
)
def cli_execute(
    ctx: BackupCLIContext,
    location: str = typer.Argument(
        ..., help="Name of the backup location to use when executing restic."
    ),
):
    config = ctx.obj

    # Collate everything, with unprocessed args, into a list
    args = [
        *helper.getBaseArgsForLocation(config, location),
        *ctx.args,
    ]

    # Execute the command
    command.restic(args, _env=helper.getResticEnv(config, location), _fg=True)


@cli.command(
    name="command",
    help="Write the basic restic command for a backup location to stdout. Includes all arguments pertaining to the backup location (repo, cache, password, etc), as well as any environment variables necessary. Helpful for using a repo in an external script.",
)
def cli_command(
    ctx: BackupCLIContext,
    location: str = typer.Argument(..., help="Name of the backup location."),
):
    config = ctx.obj
    locationConf = helper.getLocationConfig(config, location)

    # We need to convert any environment vars to key=value pairs
    envArgs = []
    if locationEnv := locationConf.get("env", None):
        envArgs.append("env")
        for key, value in locationEnv.items():
            envArgs.append(f"{key}={value}")

    sys.stdout.write(
        shlex.join(
            [
                *envArgs,
                "restic",
                *helper.getBaseArgsForLocation(config, location),
            ]
        )
    )


@cli.command(
    name="snapshots", help="List all snapshots found for the given profile."
)
def cli_snapshots(
    ctx: BackupCLIContext,
    profile: str = typer.Argument(..., help="Name of the backup profile."),
    json: bool = typer.Option(False, "--json/", help="Enable JSON output."),
):
    config = ctx.obj
    profileConf = helper.getProfileConfig(config, profile)
    locationName = profileConf["location"]

    # Assemble arguments for the command
    args = [
        *helper.getBaseArgsForLocation(config, locationName),
        "snapshots",
        *helper.getHostnameArgs(profileConf),
        *helper.getTagArgs(config, profile),
    ]

    # Enable JSON output if indicated
    if json:
        args.append("--json")

    # Execute the command
    command.restic(
        args, _env=helper.getResticEnv(config, locationName), _fg=True
    )


@cli.command(
    name="archive",
    help=f"""
    Extract and archive one or more snapshots from a backup location. Snapshots will be stored as ".tar" archives.

    {Fore.YELLOW}WARNING{Style.RESET_ALL}: Only designed to work in a Linux/macOS environment.
    """,
)
def cli_archive(
    ctx: BackupCLIContext,
    destination: pathlib.Path = typer.Argument(
        ..., help="Destination directory for the archive file."
    ),
    profile: str = typer.Argument(..., help="Name of the backup profile."),
    snapshots: list[str] = typer.Argument(
        ...,
        help="List of snapshot ID's to archive. 'latest' is valid and refers to the latest snapshot.",
    ),
    encrypt: bool = typer.Option(
        False,
        "--encrypt/",
        "-e/",
        help="Encrypt the archive using AES-256 encryption. Encrypted archives will have their extension changed to '.aes'. Make sure to specify a password file either with '--password' or in the configuration file.",
    ),
    password: typing.Optional[pathlib.Path] = typer.Option(
        None,
        "--password",
        "-p",
        help="Specify path to a file containing the password for archive encryption purposes.",
    ),
):
    config = ctx.obj
    profileConf = helper.getProfileConfig(config, profile)
    locationName = profileConf["location"]
    # locationConf = helper.getLocationConfig(locationName)

    # Pull archive configuration out of larger configuration structure
    archiveConf = config.get("archive", {})

    # Reusable base args for following commands
    locationArgs = helper.getBaseArgsForLocation(config, locationName)
    locationEnv = helper.getResticEnv(config, locationName)

    archiveDestDir = destination.expanduser()
    if not archiveDestDir.exists():
        helper.printError(
            f"Destination directory '{archiveDestDir}' does not exist"
        )

    # Cache directory is optional
    dumpCacheValue = archiveConf.get("cache", config.get("cache", None))
    cacheEnabled = bool(dumpCacheValue)
    archiveCacheDir = (
        pathlib.Path(dumpCacheValue).expanduser()
        if cacheEnabled
        else archiveDestDir
    )

    # Resolve the state of encryption and related variables
    encryptionPasswordPath: typing.Optional[pathlib.Path] = None
    encryptionEnabled = encrypt
    if encryptionEnabled:
        encryptionPasswordValue = password or archiveConf.get(
            "passwordFile", None
        )
        if not encryptionPasswordValue:
            helper.printError(
                "Archive encryption has been enabled, but a password has not been provided. Please do so via the '--password' option or the appropriate configuration file value."
            )
        encryptionPasswordPath = pathlib.Path(
            encryptionPasswordValue
        ).expanduser()

    # If no snapshots have been selected, default to latest
    if not len(snapshots):
        snapshots = ["latest"]

    # Print some startup information
    helper.printLine("Selected profile:", profile)
    helper.printLine("location name:", locationName)
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
        shortName = profileConf.get("archiveName", profile)
        filename = f"{shortName}_{timestamp}_{latest['short_id']}.tar.zst"
        if encryptionEnabled:
            filename += ".aes"

        # Make sure the cache and destination files don't exist yet
        archiveCacheFile = archiveCacheDir / filename
        if archiveCacheFile.exists():
            helper.printError(
                f"Archive already exists at '{archiveCacheFile}'"
            )
        archiveDestFile = archiveDestDir / filename
        if archiveDestFile.exists():
            helper.printError(
                f"Final archive already exists at '{archiveDestFile}'"
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
        archiveCacheUsage = shutil.disk_usage(archiveCacheDir)
        if archiveCacheUsage.free < latestSize:
            helper.printError(
                f"Error: Dump archive needs at least {helper.humanReadable(latestSize)}, "
                f"but directory only has {helper.humanReadable(archiveCacheUsage.free)} free"
            )
        archiveDestUsage = shutil.disk_usage(archiveDestDir)
        if archiveDestUsage.free < latestSize:
            helper.printError(
                f"Error: Dump archive needs at least {helper.humanReadable(latestSize)}, "
                f"but destination directory only has {helper.humanReadable(archiveDestUsage.free)} free"
            )

        # Begin dumping the repo to an archive
        helper.printNestedLine("Creating archive...")
        dumpCommand = None
        if encryptionEnabled:
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
                    f"file:{encryptionPasswordPath}",
                    "-e",
                ],
                _out=str(archiveCacheFile),
            )
        else:
            dumpCommand = command.zStd(
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
                _out=str(archiveCacheFile),
            )

        # Detect dump errors
        if dumpCommand.exit_code != 0:
            helper.printError(
                f"Restic dump command returned with error code {dumpCommand.exit_code}. Aborting."
            )

        # Copy the dump archive to the destination, if cache was enabled
        if cacheEnabled:
            helper.printNestedLine("Moving archive to final destination...")
            dumpSize = archiveCacheFile.stat().st_size
            copyCommand = command.pv(
                *["-pterbs", dumpSize, archiveCacheFile],
                _out=str(archiveDestFile),
                _err=sys.stderr,
            )

            # After copying the dump to the destination, remove the cached dump file
            if copyCommand.exit_code != 0:
                helper.printError(
                    f"Copy command returned with error code {copyCommand.exit_code}. Aborting."
                )
            archiveCacheFile.unlink()

        # Print success message for this repo
        helper.printNestedLine(
            f"{Fore.GREEN}Success!{Style.RESET_ALL} Archive is now available at {archiveDestFile}"
        )


@cli.command(
    name="decrypt",
    help="Helper command for decrypting a snapshot archive that has been encrypted by this tool on export.",
)
def cli_decrypt(
    ctx: BackupCLIContext,
    stream_input: typer.FileBinaryRead = typer.Argument(..., metavar="INPUT"),
    stream_output: typer.FileBinaryWrite = typer.Argument(
        ..., metavar="OUTPUT"
    ),
    password: typing.Optional[pathlib.Path] = typer.Option(
        None,
        "--password",
        "-p",
        help="Specify path to a file containing the password for archive decryption.",
    ),
):
    config = ctx.obj

    # Ensure output is NOT a terminal
    if hasattr(stream_output, "isatty") and stream_output.isatty():
        helper.printError("Stdout is a TTY. Try piping this command instead.")

    # Construct arguments for the command chain
    archivePasswordValue = password or config.get("archive", {}).get(
        "passwordFile", None
    )
    if not archivePasswordValue:
        helper.printError(
            "You are trying to decrypt an archive, but a password has not been provided. Please do so via the '--password' option or the appropriate configuration file value."
        )
    archivePasswordPath = pathlib.Path(archivePasswordValue).expanduser()

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
                f"file:{archivePasswordPath}",
                "-d",
            ],
            _piped=True,
            _in=stream_input,
        ),
        *["-dc", "-T8"],
        _out=stream_output,
    )


@cli.command(
    name="list",
    help="List all backup locations and backup profiles defined in the configuration file.",
)
def cli_list(ctx: BackupCLIContext):
    config = ctx.obj

    # Locations
    helper.printLine(f"Locations: {', '.join(config['locations'].keys())}")
    for locationName, locationConf in config["locations"].items():
        helper.printKeyVal("Name", locationName)
        helper.printConfigData(locationConf)
        print()

    # Profiles
    helper.printLine(f"Profiles: {', '.join(config['profiles'].keys())}")
    for profileName, profileConf in [
        (
            f"{Fore.RED}globalProfile{Style.RESET_ALL}",
            config.get("globalProfile", {}),
        ),
        *config["profiles"].items(),
    ]:
        helper.printKeyVal("Name", profileName)
        helper.printConfigData(profileConf)
        print()
