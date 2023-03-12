### stdlib imports
import typing

### vendor imports
import sh

restic = sh.Command("restic")


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
