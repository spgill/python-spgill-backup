# On windows, sh will install but will be nonfunctional
try:
    import sh
except ImportError:
    sh = None

openSsl = sh.Command("openssl") if sh else None
zStd = sh.Command("zstd") if sh else None
