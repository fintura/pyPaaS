#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import os.path

import yaml

from .. import util


class BaseRunner(object):
    def __init__(self, name, branch, config):
        self._name = name
        self.branch = branch
        self.config = config

    @property
    def cls_name(self):
        return self.__class__.__name__

    @property
    def name(self):
        return '-'.join([
            self._name,
            self.branch.repo.name,
            self.branch.name
        ])

    def configure(self):
        raise NotImplemented

    def deconfigure(self):
        raise NotImplemented

    @property
    def in_maintenance(self):
        try:
            with open(os.path.expanduser('~/maintenance-state.yml')) as f:
                state = yaml.load(f)
                return self.name in state
        except FileNotFoundError:
            return False

    def enable_maintenance(self):
        try:
            with open(os.path.expanduser('~/maintenance-state.yml')) as f:
                state = yaml.load(f)
        except FileNotFoundError:
            state = dict()
        state[self.name] = {
            'started': datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        }
        util.replace_file(
            os.path.expanduser('~/maintenance-state.yml'),
            yaml.dump(state)
        )

    def disable_maintenance(self):
        try:
            with open(os.path.expanduser('~/maintenance-state.yml')) as f:
                state = yaml.load(f)
        except FileNotFoundError:
            state = dict()
        if self.name in state:
            del state[self.name]
        util.replace_file(
            os.path.expanduser('~/maintenance-state.yml'),
            yaml.dump(state)
        )

    def restart(self):
        enable_maintenance()
        disable_maintenance()


class NginxBase(BaseRunner):
    """
    A BaseRunner, which can be used as an upstream for nginx.

    upstream in this context means the contents of a location block
    in the nginx config.
    """
    @property
    def nginx_location(self):
        raise NotImplemented

    @property
    def nginx_conf(self):
        return ""
