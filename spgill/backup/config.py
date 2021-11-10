# Stdlib imports
import os
import pathlib

# Vendor imports
import yaml

# Local imports
from . import helper

_defaultConfig = {"v": 1, "profiles": {}}


def getDefaultConfigPath() -> str:
    return os.environ.get("SPGILL_BACKUP_CONFIG", "~/.spgill.backup.yaml")


# Return the config values in the config file
def loadConfigValues(configPath: str = None) -> dict:
    updateFile = False

    # Resolve the path string to a path object
    filePath = pathlib.Path(configPath or getDefaultConfigPath()).expanduser()

    # If the config file doesn't already exist, create it
    if not filePath.exists():
        with filePath.open("w") as handle:
            yaml.dump(_defaultConfig, handle)

    # Open and decode the config file
    values: dict = None
    with filePath.open("r") as handle:
        values = yaml.load(handle, Loader=yaml.SafeLoader)
        if values["v"] < _defaultConfig["v"]:
            helper.printWarning(
                f'Warning: Config file at "{filePath}" is possibly incompatible with this version of the backup tool. Validate the contents of the config file are compatible and update the "v" property to "{_defaultConfig["v"]}", or delete the "v" property entirely to suppress this warning.'
            )

    # If the config file needs to be updated, do it now
    if updateFile:
        with filePath.open("w") as handle:
            yaml.dump(values, handle)

    # Finally, return the values
    return values
