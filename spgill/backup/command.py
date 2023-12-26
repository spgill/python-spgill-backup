### stdlib imports
import typing

### vendor imports
import sh

### local imports
from . import helper

try:
    restic = sh.Command("restic")
except sh.CommandNotFound:
    helper.print_error(
        "You must install restic and ensure its binary is in the terminal's PATH before running spgill-backup."
    )


# These three commands are only needed for working with archives
openssl: typing.Optional[sh.Command] = None
pv: typing.Optional[sh.Command] = None
zstd: typing.Optional[sh.Command] = None
try:
    openssl = sh.Command("openssl")
    pv = sh.Command("pv")
    zstd = sh.Command("zstd")
except sh.CommandNotFound:
    pass
