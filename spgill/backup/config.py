# Stdlib imports
import pathlib

# Vendor imports
import yaml

# Local imports
from . import helper, model

CURRENT_CONFIG_VERSION = 4

# Default configuration file path exists in the user's home dir
default_config_path = pathlib.Path("~/.spgill.backup.yaml")

# TODO: Flesh this out more with some examples
_default_config_contents = (
    f"""
v: {CURRENT_CONFIG_VERSION}

# List of backup storage locations (aka repos)
locations: {{}}

# List of backup policies, mapping locations and retention policies to re-usable names
policies: {{}}

# List of backup profiles, mapping include/exclude rules to policies defined above
profiles: {{}}

""".strip()
    + "\n"
)


# Return the config values in the config file
def load_config_values(
    config_path: pathlib.Path,
) -> model.RootBackupConfiguration:
    # Resolve the path string to a path object
    config_path = config_path.expanduser()

    # If the config file doesn't already exist, create it
    if not config_path.exists():
        with config_path.open("w") as handle:
            handle.write(_default_config_contents)

    # Open and decode the config file
    with config_path.open("r") as handle:
        parsed = yaml.load(handle, yaml.SafeLoader)
        instance = model.RootBackupConfiguration(**parsed)
        assert not isinstance(instance, list)

        if instance.v is not None and instance.v < CURRENT_CONFIG_VERSION:
            helper.print_warning(
                f'Warning: Config file located at "{config_path}" is possibly incompatible with the version of the backup tool you are using. Validate that the contents of the config file are compatible and update the "v" property to "v: {CURRENT_CONFIG_VERSION}", or delete the "v" property entirely to suppress this warning in the future.'
            )

        # Finally, return the values
        return instance
