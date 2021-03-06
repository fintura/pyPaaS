#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import os.path
import subprocess
from contextlib import suppress

from . import options, util
from .repo import Repo


nginx_ssl_config = """
{conf}
server {{
    listen 80 {extra_listen_options};
    listen [::]:80 {extra_listen_options};
    server_name {domain};
    rewrite ^ https://$http_host$request_uri? permanent;
    {http_extra_config}
}}
server {{
    # TODO: drop spdy in favor of http2 as soon as nginx supports it
    listen 443 ssl http2 {extra_listen_options};
    listen [::]:443 ssl http2 {extra_listen_options};
    server_name {domain};
    ssl_certificate {ssl_certificate};
    ssl_certificate_key {ssl_certificate_key};
    ssl_session_timeout 5m;
    ssl_dhparam /etc/ssl/private/httpd/dhparam.pem;
    ssl_protocols TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers 'ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-DSS-AES128-GCM-SHA256:kEDH+AESGCM:ECDHE-RSA-AES128-SHA256:ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA:ECDHE-ECDSA-AES128-SHA:ECDHE-RSA-AES256-SHA384:ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA:ECDHE-ECDSA-AES256-SHA:DHE-RSA-AES128-SHA256:DHE-RSA-AES128-SHA:DHE-DSS-AES128-SHA256:DHE-RSA-AES256-SHA256:DHE-DSS-AES256-SHA:DHE-RSA-AES256-SHA:AES128-GCM-SHA256:AES256-GCM-SHA384:AES128-SHA256:AES256-SHA256:AES128-SHA:AES256-SHA:AES:CAMELLIA:DES-CBC3-SHA:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!aECDH:!EDH-DSS-DES-CBC3-SHA:!EDH-RSA-DES-CBC3-SHA:!KRB5-DES-CBC3-SHA';
    ssl_prefer_server_ciphers on;
    add_header Strict-Transport-Security max-age=15768000;
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate {ssl_certificate_chain};
    resolver 8.8.8.8 8.8.4.4;
    {https_extra_config}
    {locations}
}}
"""  # nopep8 (silence pep8 warning about long lines)

nginx_config = """
{conf}
server {{
    listen 80 {extra_listen_options};
    listen [::]:80 {extra_listen_options};
    server_name {domain};
    {locations}
    {http_extra_config}
}}
"""  # nopep8 (silence pep8 warning about long lines)

location = """
location {path} {{
    {contents}
    {extra_config}
}}
"""


class Domain(object):
    def __init__(self, name):
        self.name = name
        try:
            self.config = options.domains[name]
        except KeyError:
            raise ValueError('This domain is not configured')

    @classmethod
    def all(cls):
        for key in options.domains:
            yield cls(key)

    @classmethod
    def configure_all(cls):
        for d in cls.all():
            d.configure(nginx_reload=False)
        cls.nginx_reload()

    @staticmethod
    def nginx_configtest():
        try:
            subprocess.check_call(['sudo', '/usr/sbin/nginx', '-t'])
        except subprocess.CalledProcessError:
            return False
        return True

    @staticmethod
    def nginx_reload():
        subprocess.check_call(['sudo', '/usr/sbin/nginx', '-s', 'reload'])

    @property
    def nginx_config_path(self):
        return os.path.join(
            os.path.expanduser('~/nginx.d/'),
            self.name + ".conf"
        )

    @property
    def runners(self):
        res = dict()
        for path, config in self.config['locations'].items():
            c = config['upstream']
            try:
                branch = Repo(c['repo']).branches[c['branch']]
                runner = branch.runners[c['runner']]
                if (runner.in_maintenance or
                        branch.current_checkout is None) and \
                        'maintenance_upstream' in config:
                    c = config['maintenance_upstream']
                    branch = Repo(c['repo']).branches[c['branch']]
                    runner = branch.runners[c['runner']]
                if branch.current_checkout is not None:
                    res[path] = runner
            except KeyError:
                raise ValueError('Repo, branch or runner not found for {}'
                                 .format(repr(c)))
        return res

    def configure(self, nginx_reload=True):
        util.mkdir_p(os.path.expanduser('~/nginx.d/'))
        with suppress(FileNotFoundError):
            # Remove old broken config
            os.unlink(self.nginx_config_path + '.broken')

        args = dict(
            domain=self.name,
            extra_listen_options=self.config.get(
                'extra_listen_options', ''
            ),
            conf='\n'.join(
                runner.nginx_conf for runner in self.runners.values()
            ),
            locations='\n'.join(
                location.format(
                    path=path,
                    contents=runner.nginx_location,
                    extra_config=self.config['locations'][path]
                        .get('nginx_extra_config', '')
                ) for path, runner in self.runners.items()
            ),
            http_extra_config=self.config.get(
                'nginx_http_extra_config', ''
            ),
            https_extra_config=self.config.get(
                'nginx_https_extra_config', ''
            ),
            ssl_certificate=self.config.get(
                'ssl_certificate',
                '/etc/ssl/private/httpd/{domain}/{domain}.crt'.format(
                    domain=self.name
                )
            ),
            ssl_certificate_key=self.config.get(
                'ssl_certificate_key',
                '/etc/ssl/private/httpd/{domain}/{domain}.key'.format(
                    domain=self.name
                )
            ),
            ssl_certificate_chain=self.config.get(
                'ssl_certificate_chain',
                '/etc/ssl/private/httpd/{domain}/trusted_chain.crt'.format(
                    domain=self.name
                )
            )
        )
        if self.config.get('ssl', True):
            util.replace_file(
                self.nginx_config_path,
                nginx_ssl_config.format(**args)
            )
        else:
            util.replace_file(
                self.nginx_config_path,
                nginx_config.format(**args)
            )
        if not self.nginx_configtest():
            # That file is probably broken => rename it
            os.rename(
                self.nginx_config_path,
                self.nginx_config_path + '.broken'
            )
            raise RuntimeError('nginx configuration failed')
        if nginx_reload:
            self.nginx_reload()

    @classmethod
    def cleanup(cls):
        config_files = {d.nginx_config_path for d in cls.all()}
        to_remove = []
        for f in os.listdir((os.path.expanduser('~/nginx.d'))):
            f = os.path.join(os.path.expanduser('~/nginx.d'), f)
            if f not in config_files:
                to_remove.append(f)
        [os.unlink(f) for f in to_remove]
