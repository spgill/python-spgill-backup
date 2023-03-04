# Stdlib imports
import pathlib

# Vendor imports
import yaml

# Local imports
from . import helper, model

# Default configuration file path exists in the user's home dir
defaultConfigPath = pathlib.Path("~/.spgill.backup.yaml")

_defaultConfig: model.MasterBackupConfiguration = {
    "v": 2,
    "locations": {},
    "profiles": {},
}


# Return the config values in the config file
def loadConfigValues(
    configPath: pathlib.Path,
) -> model.MasterBackupConfiguration:
    # Resolve the path string to a path object
    configPath = configPath.expanduser()

    # If the config file doesn't already exist, create it
    if not configPath.exists():
        with configPath.open("w") as handle:
            yaml.dump(_defaultConfig, handle)

    # Open and decode the config file
    values: model.MasterBackupConfiguration = {}
    with configPath.open("r") as handle:
        values = yaml.load(handle, Loader=yaml.SafeLoader)
        if values["v"] < _defaultConfig["v"]:
            helper.printWarning(
                f'Warning: Config file located at "{configPath}" is possibly incompatible with the version of the backup tool you are using. Validate that the contents of the config file are compatible and update the "v" property to "v: {_defaultConfig["v"]}", or delete the "v" property entirely to suppress this warning in the future.'
            )

    # Finally, return the values
    return values
