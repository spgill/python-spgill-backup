# Stdlib imports
import dataclasses
import datetime
import json
import pathlib
import re
import shlex
import shutil
import sys
import typer
import typing

# Vendor imports
import apscheduler.executors.pool
import apscheduler.schedulers.blocking
import apscheduler.triggers.cron
import sh

# Local imports
from . import helper, command, config as app_config, model


@dataclasses.dataclass
class BackupContextObject:
    config: model.RootBackupConfiguration
    verbose: bool
    dry_run: bool


# Create a subclass of the context with correct typing of the backup config object
class BackupCLIContext(typer.Context):
    obj: BackupContextObject


# Initialize the typer app
app = typer.Typer()


# Main method that initializes the configuration and makes it available to all commands
@app.callback()
def app_main(
    ctx: BackupCLIContext,
    config: typing.Annotated[
        pathlib.Path,
        typer.Option(
            "--config",
            "-c",
            envvar="SPGILL_BACKUP_CONFIG",
            help="Path to backup configuration file.",
        ),
    ] = app_config.default_config_path,
    verbose: typing.Annotated[
        bool,
        typer.Option(
            "--verbose/",
            "-v/",
            envvar="SPGILL_BACKUP_VERBOSE",
            help="Print verbose information when executing commands.",
        ),
    ] = False,
    dry_run: typing.Annotated[
        bool,
        typer.Option(
            "--dry-run/",
            "-n/",
            envvar="SPGILL_BACKUP_DRY_RUN",
            help="Do not upload or write any data. Not supported by all commands.",
        ),
    ] = False,
):
    # Load the config options and insert it into the context object
    ctx.obj = BackupContextObject(
        config=app_config.load_config_values(config),
        verbose=verbose,
        dry_run=dry_run,
    )

    # Print warning message if this is a dry run
    if dry_run:
        helper.print_warning(
            "Executing as a dry-run. This may not be supported by all commands."
        )


@app.command(name="run", help="Execute a backup profile now.")
def app_run(
    ctx: BackupCLIContext,
    name: typing.Annotated[
        str, typer.Argument(help="Name of the backup profile to use.")
    ],
    groups: typing.Annotated[
        list[str],
        typer.Option(
            "--group",
            "-g",
            help="Specify a particular backup profile group to include in the backup run. The root group definitions will always be included. If no group is explicitly provided, all defined groups will be included.",
        ),
    ] = [],
    no_copy: typing.Annotated[
        bool,
        typer.Option(
            "--no-copy/",
            "-N/",
            help="Disable copying the resulting snapshot to secondary locations, if defined.",
        ),
    ] = False,
    locations_override: typing.Annotated[
        typing.Optional[list[str]],
        typer.Option(
            "--location",
            "-l",
            help="Manually specify backup location(s). You can specify this option multiple times. Locations do not have to be defined as a part of the backup profile. Implies the '--no-copy' option.",
        ),
    ] = None,
):
    config = ctx.obj.config
    dry_run = ctx.obj.dry_run

    profile = helper.get_profile(config, name)
    assert profile.policy
    policy = helper.get_policy(config, profile.policy)

    locations = helper.get_policy_locations(policy)
    primary_location_name = locations[0]

    # If location overrides were provided, infer the no copy option
    if locations_override:
        no_copy = True

    # Get the repo's data
    helper.print_line(f"Starting at {datetime.datetime.now()}")
    helper.print_line(f"Chosen profile: {name}")
    helper.print_line(f"Primary location: {primary_location_name}")
    if len(locations) > 1:
        helper.print_line("Secondary locations:", ", ".join(locations[1:]))

    # Construct the restic args
    args = [
        *helper.get_location_arguments(config, primary_location_name),
        "backup",
        *helper.get_hostname_arguments(profile),
        *helper.get_tag_arguments(config, name),
        *helper.get_inclusion_arguments(config, name, groups),
        *(profile.args or []),
    ]

    # Add dry run argument if necessary
    if dry_run:
        args.append("--dry-run")

    # If in verbose execution, print the command
    if ctx.obj.verbose:
        helper.print_line("Restic command:")
        print(shlex.join(["restic", *args]))

    # Execute the backup and parse out the saved snapshot ID
    helper.print_line("Executing backup...")
    primary_location_env = helper.get_execution_env(
        config, primary_location_name
    )
    backup_proc = helper.run_command_politely(
        command.restic, args, primary_location_env, [0, 3]
    )
    if backup_proc is None or isinstance(backup_proc, str):
        helper.print_error("Unknown error in execution of backup")

    # If this is a dry run, go ahead and exit
    if dry_run:
        helper.print_line("Dry run complete")
        exit()

    snapshot_match = re.search(
        r"snapshot (\w+) saved", backup_proc.stdout.decode()
    )
    if not snapshot_match:
        helper.print_error("Error: Unable to parse the saved snapshot.")
        exit(1)
    primary_snapshot = snapshot_match.group(1)

    # If there are secondary locations and copying is enabled, begin copying the snapshot
    if len(locations) > 1 and not no_copy:
        helper.print_line("Copying snapshot to secondary locations")
        copy_source_args = helper.get_location_arguments(
            config, primary_location_name, True
        )

        for secondary_location_name in locations[1:]:
            helper.print_nested_line(
                f"Copying to '{secondary_location_name}'..."
            )
            copy_dest_args = helper.get_location_arguments(
                config, secondary_location_name, False
            )
            copy_args = [
                *copy_dest_args,
                "copy",
                *copy_source_args,
                primary_snapshot,
            ]

            # Execute the copy
            copy_dest_env = helper.get_execution_env(
                config, secondary_location_name
            )
            helper.run_command_politely(
                command.restic,
                copy_args,
                {**primary_location_env, **copy_dest_env},
            )

    helper.print_line(f"Finished at {datetime.datetime.now()}")


@app.command(
    name="init",
    help="""
        Initialize a new backup location preparing it for operation. Optionally,
        you may choose to inherit the restic chunker settings from an existing
        backup location. This ensures that (among other things) the
        de-duplication parameters are compatible and allows copying snapshots
        between the two.
    """,
)
def app_init_location(
    ctx: BackupCLIContext,
    location_name: typing.Annotated[
        str,
        typer.Argument(
            metavar="NAME", help="Name of the backup location to initialize."
        ),
    ],
    parent_location_name: typing.Annotated[
        typing.Optional[str],
        typer.Option(
            "--parent",
            "-p",
            help="Name of the existing (i.e. previously initialized) backup location to inherit chunker settings from.",
        ),
    ] = None,
):
    config = ctx.obj.config
    location_env = helper.get_execution_env(config, location_name)

    # Begin assembling arguments for the new backup location
    args: list[str] = [
        *helper.get_location_arguments(config, location_name),
        *ctx.args,
        "init",
    ]

    # If the parent location is provided, we need to validate that the operation
    # is possible and then insert the "from" args
    if parent_location_name:
        helper.validate_two_repo_operation(
            config, location_name, parent_location_name
        )
        location_env.update(
            helper.get_execution_env(config, parent_location_name)
        )
        args += helper.get_location_arguments(
            config, parent_location_name, from_repo=True
        )
        args.append("--copy-chunker-params")

    # Execute the restic command
    command.restic(
        args, _env=location_env, _fg=True, _ok_code=helper.foreground_ok_codes
    )


@app.command(
    name="execute",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
    },
    help="Execute the restic command line application directly. All arguments pertaining to the backup location (repo, cache, password, etc.) are appended automatically. Every argument after LOCATION will be passed directly to the restic command.",
)
def app_execute(
    ctx: BackupCLIContext,
    location_name: typing.Annotated[
        str,
        typer.Argument(
            help="Name of the backup location to use when executing restic."
        ),
    ],
):
    config = ctx.obj.config

    # Collate everything, with unprocessed args, into a list
    args = [
        *helper.get_location_arguments(config, location_name),
        *ctx.args,
    ]

    # Execute the command
    try:
        command.restic(
            args,
            _env=helper.get_execution_env(config, location_name),
            _fg=True,
            _ok_code=helper.foreground_ok_codes,
        )
    except sh.ErrorReturnCode as err:
        # Catch error codes and pass them through this tool's exit
        exit(err.exit_code)


@app.command(
    name="command",
    help="Write the basic restic command for a backup location to stdout. Includes all arguments pertaining to the backup location (repo, cache, password, etc), as well as any environment variables necessary. Helpful for using a repo in an external script.",
)
def app_command(
    ctx: BackupCLIContext,
    location_name: typing.Annotated[
        str, typer.Argument(help="Name of the backup location.")
    ],
):
    config = ctx.obj.config
    location = helper.get_location(config, location_name)

    # We need to convert any environment vars to key=value pairs
    env_args = []
    if location_env := (location.env or location.clean_env):
        env_args.append("env")
        for key, value in location_env.items():
            env_args.append(f"{key}={value}")

    sys.stdout.write(
        shlex.join(
            str(arg)
            for arg in [
                *env_args,
                "restic",
                *helper.get_location_arguments(config, location_name),
            ]
        )
    )


@app.command(
    name="snapshots", help="List all snapshots found for the given profile."
)
def app_snapshots(
    ctx: BackupCLIContext,
    profile_name: typing.Annotated[
        str,
        typer.Argument(
            help="Name of the backup profile. Executes on the first location defined in the backup profile.",
        ),
    ],
    json: typing.Annotated[
        bool, typer.Option("--json/", help="Enable JSON output.")
    ] = False,
    location_override: typing.Annotated[
        typing.Optional[str],
        typer.Option(
            "--location",
            "-l",
            help="Manually specify a backup location. Location does not have to be defined as a part of the backup profile.",
        ),
    ] = None,
):
    config = ctx.obj.config
    profile = helper.get_profile(config, profile_name)
    assert profile.policy
    policy = helper.get_policy(config, profile.policy)
    locations = helper.get_policy_locations(policy)
    location_name = location_override or locations[0]

    # Assemble arguments for the command
    args = [
        *helper.get_location_arguments(config, location_name),
        "snapshots",
        *helper.get_tag_arguments(config, profile_name),
    ]

    # Enable JSON output if indicated
    if json:
        args.append("--json")

    # Execute the command
    command.restic(
        args,
        _env=helper.get_execution_env(config, location_name),
        _fg=True,
        _ok_code=helper.foreground_ok_codes,
    )


@app.command(
    name="apply",
    help="Apply a retention policy to selectively remove snapshots from a backup location. By default, will be applied to all location defined in the backup profile.",
)
def app_apply(
    ctx: BackupCLIContext,
    profile_name: typing.Annotated[
        str, typer.Argument(help="Name of the backup profile.")
    ],
    prune: typing.Annotated[
        bool,
        typer.Option(
            "--prune/",
            "-p/",
            help="After forgetting the snapshots, prune the storage location to clean up unused data. Generally a time consuming process.",
        ),
    ] = False,
    locations_override: typing.Annotated[
        typing.Optional[list[str]],
        typer.Option(
            "--location",
            "-l",
            help="Manually specify a backup location to apply retention policy to. You can specify this option multiple times. Locations do not have to be defined as a part of the backup profile.",
        ),
    ] = None,
):
    config = ctx.obj.config
    dry_run = ctx.obj.dry_run

    profile = helper.get_profile(config, profile_name)
    assert profile.policy
    policy = helper.get_policy(config, profile.policy)
    locations = locations_override or helper.get_policy_locations(policy)

    for location_name in locations:
        helper.print_line(f"Applying policy to '{location_name}'...")
        # Assemble arguments for the command
        args = [
            *helper.get_location_arguments(config, location_name),
            "forget",
            # We need to disable grouping or else adding paths/tags/etc. will mess up the policy
            "--group-by",
            "",
            *helper.get_tag_arguments(config, profile_name),
            *helper.get_retention_arguments(config, policy),
        ]

        # Add extra args
        if dry_run:
            args.append("--dry-run")
        if prune:
            args.append("--prune")

        # Execute the forget command
        helper.run_command_politely(
            command.restic,
            args,
            helper.get_execution_env(config, location_name),
        )


@app.command(
    name="prune",
    help="Prune a storage location of unused data packs.",
)
def app_prune(
    ctx: BackupCLIContext,
    location_name: typing.Annotated[
        str,
        typer.Argument(
            help="Name of the backup location to use when executing restic."
        ),
    ],
):
    config = ctx.obj.config

    # Assemble arguments for the command
    args = [*helper.get_location_arguments(config, location_name), "prune"]

    # Execute the command
    helper.run_command_politely(
        command.restic, args, helper.get_execution_env(config, location_name)
    )


@app.command(
    name="archive",
    help="""
    Extract and archive one or more snapshots from a backup location. Snapshots will be stored as ".tar" archives.

    WARNING: Only designed to work in a Linux/macOS environment.
    """,
)
def app_archive(  # noqa: C901
    ctx: BackupCLIContext,
    destination: typing.Annotated[
        pathlib.Path,
        typer.Argument(help="Destination directory for the archive file."),
    ],
    profile_name: typing.Annotated[
        str, typer.Argument(help="Name of the backup profile.")
    ],
    snapshots: typing.Annotated[
        list[str],
        typer.Argument(
            help="List of snapshot ID's to archive. 'latest' is valid and refers to the latest snapshot.",
        ),
    ],
    location_override: typing.Annotated[
        typing.Optional[str],
        typer.Option(
            "--location",
            "-l",
            help="Name of location to query for the snapshot. Defaults to the primary location defined in the backup profile.",
        ),
    ] = None,
    encrypt: typing.Annotated[
        bool,
        typer.Option(
            "--encrypt/",
            "-e/",
            help="Encrypt the archive using AES-256 encryption. Encrypted archives will have their extension changed to '.aes'. Make sure to specify a password file either with '--password' or in the configuration file.",
        ),
    ] = False,
    password: typing.Annotated[
        typing.Optional[pathlib.Path],
        typer.Option(
            "--password",
            "-p",
            help="Specify path to a file containing the password for archive encryption purposes.",
        ),
    ] = None,
):
    # Must have all the required commands available to use
    if not command.openssl or not command.pv or not command.zstd:
        helper.print_error(
            "Error: Cannot find commands required for archive operation. Ensure 'openssl', 'pv', and 'zstd' are installed and available on PATH."
        )
        exit(1)

    config = ctx.obj.config
    profile = helper.get_profile(config, profile_name)
    assert profile.policy
    policy = helper.get_policy(config, profile.policy)
    locations = helper.get_policy_locations(policy)
    location_name = location_override or locations[0]

    # Pull archive configuration out of larger configuration structure
    archive_config = config.archive

    # Reusable base args for following commands
    location_args = helper.get_location_arguments(config, location_name)
    location_env = helper.get_execution_env(config, location_name)

    archive_dest_dir = destination.expanduser()
    if not archive_dest_dir.exists():
        helper.print_error(
            f"Destination directory '{archive_dest_dir}' does not exist"
        )

    # Cache directory is optional
    dump_cache_value = archive_config.cache if archive_config else config.cache
    cache_enabled = bool(dump_cache_value)
    archive_cache_dir = (
        pathlib.Path(dump_cache_value).expanduser()
        if cache_enabled
        else archive_dest_dir
    )

    # Resolve the state of encryption and related variables
    encryption_password_path: typing.Optional[pathlib.Path] = None
    encryption_enabled = encrypt
    if encryption_enabled:
        encryption_password_value = password or (
            archive_config.password_file if archive_config else None
        )
        if not encryption_password_value:
            helper.print_error(
                "Archive encryption has been enabled, but a password has not been provided. Please do so via the '--password' option or the appropriate configuration file value."
            )
            exit(1)
        encryption_password_path = pathlib.Path(
            encryption_password_value
        ).expanduser()

    # If no snapshots have been selected, default to latest
    if not len(snapshots):
        snapshots = ["latest"]

    # Print some startup information
    helper.print_line("Selected profile:", profile_name)
    helper.print_line("location name:", location_name)
    helper.print_line("Selected snapshots:", ", ".join(snapshots))

    # Iterate through each snapshot that's being dumped
    for snapshot_name in snapshots:
        helper.print_line(f"Processing '{snapshot_name}':")

        # Fetch information on the latest snapshot
        helper.print_nested_line(
            f"Querying snapshots for '{snapshot_name}'..."
        )
        snaps_args = [
            *location_args,
            "--quiet",
            "snapshots",
            snapshot_name,
            "--json",
        ]
        snaps_proc = command.restic(snaps_args, _env=location_env)
        if snaps_proc is None:
            helper.print_error("Error querying snaphots. Exiting.")
        assert isinstance(snaps_proc, str)
        if "null" in snaps_proc:
            helper.print_error(f"Could not find snapshot: '{snapshot_name}'")
        latest = json.loads(snaps_proc)[0]

        # Convert the timestamp to a datetime object
        # Requires the we first round off the milliseconds to three decimal places
        latest["time"] = datetime.datetime.fromisoformat(
            helper.fix_timestamp(latest["time"])
        )

        # Creat timestamp and unique filename for this repo
        timestamp = latest["time"].strftime(r"%Y%m%d%H%M%S")
        short_name = profile.archive_name or profile_name
        file_name = f"{short_name}_{timestamp}_{latest['short_id']}.tar.zst"
        if encryption_enabled:
            file_name += ".aes"

        # Make sure the cache and destination files don't exist yet
        archive_cache_file = archive_cache_dir / file_name
        if archive_cache_file.exists():
            helper.print_error(
                f"Archive already exists at '{archive_cache_file}'"
            )
        archive_dest_file = archive_dest_dir / file_name
        if archive_dest_file.exists():
            helper.print_error(
                f"Final archive already exists at '{archive_dest_file}'"
            )

        # Inform the user which snapshot is being used
        helper.print_nested_line(
            f"Using snapshot ID '{latest['id'][:8]}' with timestamp '{latest['time']}'"
        )

        # Fetch the size of the latest snapshot
        helper.print_nested_line("Querying snapshot size...")
        stats_args = [
            *location_args,
            "--quiet",
            "stats",
            latest["id"],
            "--json",
        ]
        stats_proc = command.restic(stats_args, _env=location_env)
        if stats_proc is None:
            helper.print_error("Error querying snaphot statistics. Exiting.")
        assert isinstance(stats_proc, str)
        latest_size = json.loads(stats_proc)["total_size"]
        helper.print_nested_line(
            f"Archive should be no larger than (approx.) {helper.human_readable(latest_size)}"
        )

        # Ensure there's enough space in the cache dir and the destination
        archive_cache_usage = shutil.disk_usage(archive_cache_dir)
        if archive_cache_usage.free < latest_size:
            helper.print_error(
                f"Error: Dump archive needs at least {helper.human_readable(latest_size)}, "
                f"but directory only has {helper.human_readable(archive_cache_usage.free)} free"
            )
        archive_dest_usage = shutil.disk_usage(archive_dest_dir)
        if archive_dest_usage.free < latest_size:
            helper.print_error(
                f"Error: Dump archive needs at least {helper.human_readable(latest_size)}, "
                f"but destination directory only has {helper.human_readable(archive_dest_usage.free)} free"
            )

        # Begin dumping the repo to an archive
        helper.print_nested_line("Creating archive...")
        dump_proc = None
        if encryption_enabled:
            dump_proc = command.openssl(
                command.zstd(
                    command.pv(
                        command.restic(
                            *[*location_args, "dump", latest["id"], "/"],
                            _env=location_env,
                            _piped=True,
                        ),
                        *["-pterbs", str(latest_size)],
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
                    f"file:{encryption_password_path}",
                    "-e",
                ],
                _out=str(archive_cache_file),
            )
        else:
            dump_proc = command.zstd(
                command.pv(
                    command.restic(
                        *[*location_args, "dump", latest["id"], "/"],
                        _env=location_env,
                        _piped=True,
                    ),
                    *["-pterbs", str(latest_size)],
                    _err=sys.stderr,
                    _piped=True,
                ),
                *["-c", "-T8"],
                _out=str(archive_cache_file),
            )

        if dump_proc is None:
            helper.print_error("Error creating archive. Exiting.")

        # Copy the dump archive to the destination, if cache was enabled
        if cache_enabled:
            helper.print_nested_line("Moving archive to final destination...")
            dump_size = archive_cache_file.stat().st_size
            copy_proc = command.pv(
                *["-pterbs", dump_size, archive_cache_file],
                _out=str(archive_dest_file),
                _err=sys.stderr,
            )

            if copy_proc is None:
                helper.print_error(
                    "Error copying archive to final destination. Exiting."
                )

            archive_cache_file.unlink()

        # Print success message for this repo
        helper.print_nested_line(
            f"[green]Success![/] Archive is now available at {archive_dest_file}"
        )


@app.command(
    name="decrypt",
    help="Helper command for decrypting a snapshot archive that has been encrypted by this tool on export.",
)
def app_decrypt(
    ctx: BackupCLIContext,
    stream_input: typing.Annotated[
        typer.FileBinaryRead, typer.Argument(metavar="INPUT")
    ],
    stream_output: typing.Annotated[
        typer.FileBinaryWrite, typer.Argument(metavar="OUTPUT")
    ],
    password: typing.Annotated[
        typing.Optional[pathlib.Path],
        typer.Option(
            "--password",
            "-p",
            help="Specify path to a file containing the password for archive decryption.",
        ),
    ] = None,
):
    # Must have all the required commands available to use
    if not command.openssl or not command.pv or not command.zstd:
        helper.print_error(
            "Error: Cannot find commands required for archive operation. Ensure 'openssl', 'pv', and 'zstd' are installed and available on PATH."
        )
        exit(1)

    config = ctx.obj.config

    # Ensure output is NOT a terminal
    if hasattr(stream_output, "isatty") and stream_output.isatty():
        helper.print_error("Stdout is a TTY. Try piping this command instead.")

    # Construct arguments for the command chain
    archive_password_value = (
        config.archive.password_file if config.archive else password
    )
    archive_password_value = password or (
        config.archive.password_file if config.archive else None
    )
    if not archive_password_value:
        helper.print_error(
            "You are trying to decrypt an archive, but a password has not been provided. Please do so via the '--password' option or the appropriate configuration file value."
        )
        exit(1)
    archive_password_path = pathlib.Path(archive_password_value).expanduser()

    # Pipe openssl to zstd and then stdout
    command.zstd(
        command.openssl(
            *[
                "enc",
                "-aes-256-cbc",
                "-md",
                "sha512",
                "-pbkdf2",
                "-iter",
                "100000",
                "-pass",
                f"file:{archive_password_path}",
                "-d",
            ],
            _piped=True,
            _in=stream_input,
        ),
        *["-dc", "-T8"],
        _out=stream_output,
    )


@app.command(
    name="list",
    help="List all backup locations and backup profiles defined in the configuration file.",
)
def app_list(ctx: BackupCLIContext):
    config = ctx.obj.config

    # Locations
    locations = config.locations
    helper.print("Locations:")
    for location_name in locations:
        helper.print(f"  - {location_name}")

    helper.print()

    # Policies
    policies = config.policies
    helper.print_line("Policies:")
    for policy_name in policies:
        helper.print(f"  - {policy_name}")

    helper.print()

    # Profiles
    profiles = config.profiles
    helper.print_line("Profiles:")
    for profile_name in [
        "[red]global_profile",
        *profiles.keys(),
    ]:
        helper.print(f"  - {profile_name}")

    helper.print()


@app.command(name="copy", help="Copy a snapshot from one location to another.")
def app_copy(
    ctx: BackupCLIContext,
    source: typing.Annotated[
        str,
        typer.Argument(
            help="Source location; where the snapshot will be copied FROM."
        ),
    ],
    destination: typing.Annotated[
        str,
        typer.Argument(
            help="Destination location; where the snapshot will be copied TO."
        ),
    ],
    snapshots: typing.Annotated[
        list[str],
        typer.Argument(
            min=1,
            help="IDs of one or more snapshots to copy from the source to the destination.",
        ),
    ],
):
    config = ctx.obj.config

    # Quickly validate that both locations can be used together
    helper.validate_two_repo_operation(config, source, destination)

    # Assemble arguments for the command
    source_args = helper.get_location_arguments(config, source, True)
    destination_args = helper.get_location_arguments(
        config, destination, False
    )
    args = [*destination_args, "copy", *source_args, *snapshots]

    # Get env vars for the source and destination, and make sure there's no overlap
    source_env = helper.get_execution_env(config, source)
    destination_env = helper.get_execution_env(config, destination)

    # Execute the restic command
    command.restic(
        args,
        _env={**source_env, **destination_env},
        _fg=True,
        _ok_code=helper.foreground_ok_codes,
    )


@app.command(
    name="mount",
    help="Mount to the filesystem all snapshots belonging to a backup profile.",
)
def app_mount(
    ctx: BackupCLIContext,
    profile_name: typing.Annotated[
        str,
        typer.Argument(
            metavar="PROFILE", help="Name of the backup profile to use."
        ),
    ],
    mount_point: typing.Annotated[
        pathlib.Path,
        typer.Argument(metavar="MOUNT", help="Filesystem mount point."),
    ],
    location_name: typing.Annotated[
        typing.Optional[str],
        typer.Option(
            "--location",
            "-l",
            help="Name of backup location to mount. Defaults to the primary backup location defined in the backup policy.",
        ),
    ] = None,
):
    config = ctx.obj.config

    # Ensure that the mount point exists
    if not mount_point.exists():
        helper.print_error("Error: Mount point does not exist")
        exit(1)

    profile = helper.get_profile(config, profile_name)
    helper.print_line(f"Backup profile: {profile_name}")

    assert profile.policy
    policy = helper.get_policy(config, profile.policy)
    helper.print_line(f"Backup policy: {profile.policy}")

    locations = helper.get_policy_locations(policy)
    location_name = location_name or locations[0]
    location_env = helper.get_execution_env(config, location_name)
    helper.print_line(f"Backup location: {location_name}")

    # Construct the restic args
    args = [
        *helper.get_location_arguments(config, location_name),
        "mount",
        *helper.get_tag_arguments(config, profile_name),
        str(mount_point),
    ]

    helper.print_line("Mounting...")

    command.restic(
        *args, _env=location_env, _fg=True, _ok_code=helper.foreground_ok_codes
    )


# region Daemon implementation
@app.command(
    name="daemon",
    help="""
        Run the backup orchestrator daemon (service) in blocking mode.
        Will execute backup profiles according to their policy schedule.
    """,
)
def app_daemon(
    ctx: BackupCLIContext,
):
    """
    This command implements the scheduling logic for the backup orchestrator
    daemon (service). This essentially schedules exclusive workers to proxy
    the backup execution to the existing "run" command.
    """
    config = ctx.obj.config

    helper.print_line("Scheduling jobs for applicable profiles...")
    scheduler = apscheduler.schedulers.blocking.BlockingScheduler(
        executors={
            "default": apscheduler.executors.pool.ThreadPoolExecutor(1)
        },
        job_defaults={
            "misfire_grace_time": None,
            "coalesce": True,
            "max_instances": 1,
        },
    )
    jobs_added = False

    # Iterate through every defined profile
    for profile_name, profile in config.profiles.items():
        policy = (
            helper.get_policy(config, profile.policy)
            if profile.policy
            else None
        )
        if policy and policy.schedule:
            helper.print_nested_line(f"{profile_name}: {policy.schedule}")
            trigger = apscheduler.triggers.cron.CronTrigger.from_crontab(
                policy.schedule
            )

            scheduler.add_job(
                id=profile_name,
                trigger=trigger,
                func=app_run,
                args=[ctx],
                kwargs={
                    "name": profile_name,
                    "groups": [],
                    "no_copy": False,
                    "locations_override": None,
                },
            )
            jobs_added = True

    if not jobs_added:
        helper.print_warning(
            "No jobs scheduled. Check your configuration and try again. Exiting..."
        )
        exit()

    try:
        helper.print_warning("Starting scheduler...")
        scheduler.start()
    except KeyboardInterrupt:
        helper.print_warning("Scheduler stopping...")
        exit()


# endregion
