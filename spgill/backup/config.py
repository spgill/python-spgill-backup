# Stdlib imports
import pathlib

# Vendor imports
import yaml

# Local imports
from . import helper, model

# Default configuration file path exists in the user's home dir
defaultConfigPath = pathlib.Path("~/.spgill.backup.yaml")

_defaultConfig = {
    "v": 3,
    "locations": {},
    "policies": {},
    "profiles": {},
}


# Return the config values in the config file
def loadConfigValues(
    configPath: pathlib.Path,
) -> model.RootBackupConfiguration:
    # Resolve the path string to a path object
    configPath = configPath.expanduser()

    # If the config file doesn't already exist, create it
    if not configPath.exists():
        with configPath.open("w") as handle:
            yaml.dump(_defaultConfig, handle)

    # Open and decode the config file
    with configPath.open("r") as handle:
        parsed = model.RootBackupConfiguration.from_yaml(handle)
        assert not isinstance(parsed, list)
        values = parsed

        if values.v < _defaultConfig["v"]:
            helper.print_warning(
                f'Warning: Config file located at "{configPath}" is possibly incompatible with the version of the backup tool you are using. Validate that the contents of the config file are compatible and update the "v" property to "v: {_defaultConfig["v"]}", or delete the "v" property entirely to suppress this warning in the future.'
            )

        # Finally, return the values
        return values
