# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='tasks',
  dependencies=[
    ':node_task',
    ':npm_resolve',
  ]
)

python_tests(
  name='node_task',
  sources=['test_node_task.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/tasks:node_task',
    'src/python/pants/base:target',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name='npm_resolve',
  sources=['test_npm_resolve.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/tasks:npm_resolve',
    'src/python/pants/base:source_root',
    'src/python/pants/base:target',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)