#!/usr/bin/env python
#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.

from setuptools import setup, find_packages
import re

info = eval(file('__tryton__.py').read())

requires = []
for dep in info.get('depends', []):
    match = re.compile(
            '(ir|res|workflow|webdav)((\s|$|<|>|<=|>=|==|!=).*?$)').match(dep)
    if match:
        dep = 'trytond' + match.group(2)
    else:
        dep = 'trytond_' + dep
    requires.append(dep)

setup(name='trytond_' + info['name'].lower(),
    version=info.get('version', '0'),
    description=info.get('description', ''),
    author=info.get('author', ''),
    author_email=info.get('email', ''),
    url=info.get('website', ''),
    package_dir={'trytond.modules.' + info['name'].lower(): '.'},
    packages=[
        'trytond.modules.' + info['name'].lower(),
    ],
    package_data={
        'trytond.modules.' + info['name'].lower(): info.get('xml', []) \
                + info.get('translation', []) \
                + ['aged_balance.odt', 'general_journal.odt',
                'general_ledger.odt', 'third_party_balance.odt',
                'trial_balance.odt'],
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Plugins',
        'Intended Audience :: Developers',
        'Intended Audience :: Financial and Insurance Industry',
        'Intended Audience :: Legal Industry',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Natural Language :: English',
        'Natural Language :: French',
        'Natural Language :: German',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Office/Business',
        'Topic :: Office/Business :: Financial :: Accounting',
    ],
    license='GPL-3',
    install_requires=requires,
)
