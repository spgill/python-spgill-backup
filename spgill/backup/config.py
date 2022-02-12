# Stdlib imports
import os
import pathlib

# Vendor imports
import yaml

# Local imports
from . import helper, schema

_defaultConfig: schema.MasterBackupConfiguration = {
    "v": 2,
    "locations": {},
    "profiles": {},
}


def getDefaultConfigPath() -> str:
    return os.environ.get("SPGILL_BACKUP_CONFIG", "~/.spgill.backup.yaml")


# Return the config values in the config file
def loadConfigValues(
    configPath: str = None,
) -> schema.MasterBackupConfiguration:
    # Resolve the path string to a path object
    filePath = pathlib.Path(configPath or getDefaultConfigPath()).expanduser()

    # If the config file doesn't already exist, create it
    if not filePath.exists():
        with filePath.open("w") as handle:
            yaml.dump(_defaultConfig, handle)

    # Open and decode the config file
    values: schema.MasterBackupConfiguration = {}
    with filePath.open("r") as handle:
        values = yaml.load(handle, Loader=yaml.SafeLoader)
        if values["v"] < _defaultConfig["v"]:
            helper.printWarning(
                f'Warning: Config file located at "{filePath}" is possibly incompatible with the version of the backup tool you are using. Validate that the contents of the config file are compatible and update the "v" property to "v: {_defaultConfig["v"]}", or delete the "v" property entirely to suppress this warning in the future.'
            )

    # Finally, return the values
    return values
