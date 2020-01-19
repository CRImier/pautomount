#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pautomount
version = pautomount.__version__

try:
    import fastentrypoints
except ImportError:
    from setuptools.command import easy_install
    import pkg_resources
    easy_install.main(['fastentrypoints'])
    pkg_resources.require('fastentrypoints')
    import fastentrypoints

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

# from https://stackoverflow.com/questions/25192794/no-module-named-pip-req
def parse_requirements(filename):
    lineiter = (line.strip() for line in open(filename))
    return [line for line in lineiter if line and not line.startswith("#")]

setup(
  name = 'pautomount',
  py_modules = ['pautomount'],
  version = version,
  description = 'A daemon for automounting and/or executing actions on hotplug of removable drives',
  author = 'Arsenijs Picugins',
  author_email = 'crimier@yandex.ru',
  url = 'https://github.com/CRImier/pautomount',
  download_url = 'https://github.com/CRImier/pautomount/archive/{}.tar.gz'.format(version),
  keywords = ['linux', 'partitions', 'automount', 'usb', 'flash drives'],
  install_requires = parse_requirements("requirements.txt"),
  entry_points={"console_scripts": ["pautomount = pautomount:main"]}
)
