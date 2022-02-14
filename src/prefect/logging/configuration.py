import json
import logging
import logging.config
import os
import re
import warnings
from functools import partial
from pathlib import Path

import yaml

from prefect.settings import LoggingSettings
from prefect.utilities.collections import dict_to_flatdict, flatdict_to_dict

# This path will be used if `LoggingSettings.settings_path` does not exist
DEFAULT_LOGGING_SETTINGS_PATH = Path(__file__).parent / "logging.yml"

# Regex call to replace non-alphanumeric characters to '_' to create a valid env var
to_envvar = partial(re.sub, re.compile(r"[^0-9a-zA-Z]+"), "_")
# Regex for detecting interpolated global settings
interpolated_settings = re.compile(r"^{{([\w\d_]+)}}$")

PROCESS_LOGGING_CONFIG: dict = None


def load_logging_config(path: Path, settings: LoggingSettings) -> dict:
    """
    Loads logging configuration from a path allowing override from the environment
    """
    config = yaml.safe_load(path.read_text())

    # Load overrides from the environment
    flat_config = dict_to_flatdict(config)

    for key_tup, val in flat_config.items():

        # first check if the value was overriden via env var
        env_val = os.environ.get(
            # Generate a valid environment variable with nesting indicated with '_'
            to_envvar((settings.Config.env_prefix + "_".join(key_tup)).upper())
        )
        if env_val:
            val = env_val

        # next check if the value refers to a global setting
        # only perform this check if the value is a string beginning with '{{'
        if isinstance(val, str) and val.startswith(r"{{"):
            # this regex looks for `{{KEY}}`
            # and returns `KEY` as its first capture group
            matched_settings = interpolated_settings.match(val)
            if matched_settings:
                # retrieve the matched key
                matched_key = matched_settings.group(1)
                # retrieve the global logging setting corresponding to the key
                val = getattr(settings, matched_key, None)

        # reassign the updated value
        flat_config[key_tup] = val

    return flatdict_to_dict(flat_config)


def setup_logging(settings: LoggingSettings) -> None:
    global PROCESS_LOGGING_CONFIG, PROCESS_LOGGING_CONFIG_HASH

    # If the user has specified a logging path and it exists we will ignore the
    # default entirely rather than dealing with complex merging
    config = load_logging_config(
        (
            settings.settings_path
            if settings.settings_path.exists()
            else DEFAULT_LOGGING_SETTINGS_PATH
        ),
        settings,
    )

    if PROCESS_LOGGING_CONFIG:
        # Do not allow repeated configuration calls, only warn if the config differs
        config_diff = {
            key: value
            for key, value in config.items()
            if PROCESS_LOGGING_CONFIG[key] != value
        }
        if config_diff:
            warnings.warn(
                "Logging can only be setup once per process, the new logging config "
                f"will be ignored. The attempted changes were: {config_diff}",
                stacklevel=2,
            )
        return

    logging.config.dictConfig(config)

    # Copy configuration of the 'prefect.extra' logger to the extra loggers
    extra_config = logging.getLogger("prefect.extra")

    for logger_name in settings.get_extra_loggers():
        logger = logging.getLogger(logger_name)
        for handler in extra_config.handlers:
            logger.addHandler(handler)
            if logger.level == logging.NOTSET:
                logger.setLevel(extra_config.level)
            logger.propagate = extra_config.propagate

    PROCESS_LOGGING_CONFIG = config
