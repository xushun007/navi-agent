from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("navi-agent")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"


__all__ = ["__version__", "app", "bootstrap", "config", "logging", "paths", "runtime"]
