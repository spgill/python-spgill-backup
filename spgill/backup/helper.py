# Stdlib imports
import os
import pathlib
import re
import sys
import typing

# Vendor imports
import humanize
import mergedeep
import rich
import rich.console
import sh
import yaml

# Local imports
from . import model


foreground_ok_codes: list[int] = [0, 1, 2, 3, 10, 11, 130]
"""List of expected restic error codes that can be safely ignore if running in `_fg` mode."""


def fix_timestamp(t: str) -> str:
    return re.sub(
        r":(\d+)\.(\d+)",
        lambda match: f":{match.group(1)}.{match.group(2)[:6]}",
        t,
    )


console = rich.console.Console(highlight=False)
error_console = rich.console.Console(highlight=False, stderr=True)


def print(*args, stderr=False):
    if stderr:
        error_console.print(*args)
    else:
        console.print(*args)


def print_line(*args, stderr=False):
    print("-" * 8, *args, stderr=stderr)


def print_nested_line(*args):
    print("-" * 12, *args)


def print_warning(message: str):
    print_line(f"[yellow]{message}", stderr=True)


def print_error(message: str):
    print("-" * 8, f"[red]{message}", stderr=True)
    exit(1)


def print_kv(key: str, value: str = ""):
    print(f"[yellow]{key}[/]: {value}")


def print_config_data(data: typing.Any):
    serialized: str = yaml.dump(data)
    print("\n".join("|  " + line for line in serialized.splitlines()))


def human_readable(num):
    return humanize.naturalsize(num, binary=True)


def get_location(
    config: model.RootBackupConfiguration, name: str
) -> model.BackupLocation:
    if not (location := config.locations.get(name, None)):
        print_error(f"Error: No backup location found by name '{name}'")

    assert location is not None
    return location


def merge_with_global_profile(
    config: model.RootBackupConfiguration, profile: model.BackupProfile
) -> model.BackupProfile:
    """This function returns the given profile with the global profile defaults applied."""
    # Serialize the global profile and selected profile to dictionaries
    global_dict = (
        {}
        if config.global_profile is None
        else config.global_profile.dict(exclude_defaults=True)
    )
    profile_dict = profile.dict(exclude_defaults=True)

    # Perform an additive merge of the two profiles
    merged_dict = mergedeep.merge(
        {}, global_dict, profile_dict, strategy=mergedeep.Strategy.ADDITIVE
    )

    # Return a new backup profile representing the merger
    return model.BackupProfile(**merged_dict)


def get_profile(
    config: model.RootBackupConfiguration, name: str
) -> model.BackupProfile:
    if not (profile := config.profiles.get(name, None)):
        print_error(f"Error: No backup profile found by name '{name}'")

    assert profile is not None

    # Ensure there is a policy defined for the profile
    if not profile.policy:
        print_error(f"Error: Backup profile '{name}' has no policy defined")

    return merge_with_global_profile(config, profile)


def get_policy(
    config: model.RootBackupConfiguration, name: str
) -> model.BackupPolicy:
    if not (policy := config.policies.get(name, None)):
        print_error(f"Error: No backup policy found by name '{name}'")

    assert policy is not None

    # Ensure location is defined
    if not policy.location:
        print_error(f"Error: Policy '{name}' has no location defined")

    return policy


def get_policy_locations(policy: model.BackupPolicy) -> list[str]:
    assert policy.location is not None
    if isinstance(policy.location, str):
        return [policy.location]
    return policy.location


# List of location option flags for both local and remote locations
location_option_names = {
    "repo": {"from": "--from-repo", "to": "--repo"},
    "password_file": {"from": "--from-password-file", "to": "--password-file"},
    "password_command": {
        "from": "--from-password-command",
        "to": "--password-command",
    },
}


def get_location_arguments(
    config: model.RootBackupConfiguration,
    location_name: str,
    from_repo: bool = False,
) -> list[str]:
    location = get_location(config, location_name)
    option_key = "from" if from_repo else "to"

    # Generate cache dir args (only for destination repos)
    cache_args = []
    if not from_repo:
        if config.cache:
            cache_args = ["--cache-dir", config.cache]
        else:
            cache_args = ["--no-cache"]

    # Generate password args
    password_args = []
    if location.password_file:
        password_file_path = fully_qualified_path(location.password_file, True)
        password_args = [
            location_option_names["password_file"][option_key],
            str(password_file_path),
        ]
    elif location.password_command:
        password_args = [
            location_option_names["password_command"][option_key],
            location.password_command,
        ]
    else:
        print_warning(
            f"Warning: No 'password_command' or 'password_file' defined for backup location '{location_name}'"
        )

    # Return the final list of args
    return [
        *cache_args,
        *password_args,
        location_option_names["repo"][option_key],
        location.path,
    ]


def get_tag_arguments(
    config: model.RootBackupConfiguration,
    profile_name: str,
) -> list[str]:
    profile = get_profile(config, profile_name)
    if profile.tags:
        return ["--tag", ",".join(profile.tags)]
    return []


def get_execution_env(
    config: model.RootBackupConfiguration,
    location_name: str,
) -> dict[str, str]:
    location = get_location(config, location_name)

    # Else, we will augment the execution environment with the "env" property (if defined)
    return {**dict(os.environ), **(location.env or {})}


def validate_two_repo_operation(
    config: model.RootBackupConfiguration,
    location_a_name: str,
    location_b_name: str,
) -> None:
    """Validate that two user-provided locations names are compatible for a cross-repo operation."""
    # First, just make sure they aren't the same location
    if location_a_name == location_b_name:
        print_error(
            "Error: You can't perform this operation on the same backup location. Exiting..."
        )

    # Next we check that the two location's environment vars don't overlap.
    # This is a limitation of restic's implementation of S3/B2/etc.
    location_a = get_location(config, location_a_name)
    location_a_env = location_a.env or {}

    location_b = get_location(config, location_b_name)
    location_b_env = location_b.env or {}

    intersection = [k for k in location_a_env if k in location_b_env]
    if len(intersection) > 0:
        print_error(
            "Error: These backup locations are incompatible because they have conflicting environment variables. Consider working with a separate local backup location as a middle man, or using rclone. Exiting..."
        )


def fully_qualified_path(
    path: typing.Union[str, pathlib.Path], ensure_exists: bool = False
) -> pathlib.Path:
    normalized = pathlib.Path(path).expanduser().absolute()
    if ensure_exists and not normalized.exists():
        print_error(f"File path '{normalized}' (from '{path}') does not exist")
    return normalized


def get_inclusion_arguments(
    config: model.RootBackupConfiguration,
    profile_name: str,
    group_names: list[str],
) -> typing.Generator[str, None, None]:
    profile = get_profile(config, profile_name)

    # List of includes must come last as positional args, so they will be collected
    # and emitted last
    include_list: list[str] = []

    # Store basic include entries for emitting at the end
    for entry in profile.include:
        include_list.append(entry)

    # Process various include files flags
    for entry in profile.include_files_from:
        yield "--files-from"
        yield str(fully_qualified_path(entry, True))

    for entry in profile.include_files_from_verbatim:
        yield "--files-from-verbatim"
        yield str(fully_qualified_path(entry, True))

    # Process various exlude file flags
    for entry in profile.exclude:
        yield "--exclude"
        yield entry

    for entry in profile.iexclude:
        yield "--iexclude"
        yield entry

    for entry in profile.exclude_if_present:
        yield "--exclude-if-present"
        yield entry

    for entry in profile.exclude_file:
        yield "--exclude-file"
        yield str(fully_qualified_path(entry, True))

    for entry in profile.iexclude_file:
        yield "--iexclude-file"
        yield str(fully_qualified_path(entry, True))

    if profile.exclude_caches:
        yield "--exclude-caches"

    if exclude_size := profile.exclude_larger_than:
        # In case the user specifies a number with a suffix, this will probably be a number
        # and an error should be thrown
        if not isinstance(exclude_size, str):
            print_error(
                f"Option 'exclude_larger_than' should always be a string, not '{exclude_size}' ({type(exclude_size)})"
            )
        yield "--exclude-larger-than"
        yield exclude_size

    # Emit basic include lines
    for entry in include_list:
        yield entry


def get_hostname_arguments(profile: model.BackupProfile) -> list[str]:
    if profile.hostname:
        return ["--host", profile.hostname]
    return []


def get_retention_arguments(
    config: model.RootBackupConfiguration,
    policy: model.BackupPolicy,
) -> list[str]:
    # If there are no retention args, return empty list
    if not policy.retention:
        print_warning("Warning: No retention defined for policy")
        return []

    # Build out the args for retention
    retention = policy.retention
    args: list[str] = []

    if retention.keep_last:
        args += ["--keep-last", retention.keep_last]

    if retention.keep_within:
        args += ["--keep-within", retention.keep_within]

    if retention.keep_hourly:
        args += ["--keep-hourly", retention.keep_hourly]

    if retention.keep_daily:
        args += ["--keep-daily", retention.keep_daily]

    if retention.keep_weekly:
        args += ["--keep-weekly", retention.keep_weekly]

    if retention.keep_monthly:
        args += ["--keep-monthly", retention.keep_monthly]

    if retention.keep_yearly:
        args += ["--keep-yearly", retention.keep_yearly]

    return args


def maximize_niceness():
    os.nice(20)


def run_command_politely(
    command: sh.Command,
    args: list[typing.Any],
    env: dict = {},
    ok_codes: list[int] = [0],
):
    # Start the command
    running_proc = command(
        *args,
        _preexec_fn=maximize_niceness,
        _bg=True,
        _env=env,
        _out=sys.stdout,
        _err=sys.stderr,
        _tee=True,
        _ok_code=ok_codes,
    )

    # The running process should not be a string
    assert isinstance(running_proc, sh.RunningCommand)

    # Wait for it to finish and catch any keyboard interrupts
    try:
        running_proc.wait()
    except KeyboardInterrupt:
        print("---------- Keyboard interrupt detected")
        if running_proc.is_alive():
            print("---------- Killing the running process...")
            running_proc.kill()
        exit()

    return running_proc
