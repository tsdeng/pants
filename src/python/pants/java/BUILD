# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'executor',
  sources = ['executor.py'],
  dependencies = [
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name = 'nailgun_client',
  sources = ['nailgun_client.py'],
)

python_library(
  name = 'nailgun_executor',
  sources = ['nailgun_executor.py'],
  dependencies = [
    ':executor',
    ':nailgun_client',
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/pantsd:process_manager',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'util',
  sources = ['util.py'],
  dependencies = [
    ':executor',
    ':nailgun_executor',
    'src/python/pants/base:workunit',
  ],
)
