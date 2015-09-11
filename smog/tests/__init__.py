__author__ = 'stoner'

import os
import yaml


def get_yaml_file(cfg_dir, cfg_file):
    """
    Reads in the configuration file for our parameters

    :param cls:
    :return:
    """
    curr_dir = os.path.abspath(cfg_dir)
    dirname = os.path.dirname(curr_dir)
    dirs = dirname.split("/")
    dirs.append("configs")
    dirs.append(cfg_file)
    config_dir = "/".join(dirs)

    with open(config_dir, "r") as cfg:
        txt = cfg.read()

    config = yaml.load(txt)

    # Get the deployment data
    return config


