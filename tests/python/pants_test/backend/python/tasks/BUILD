target(
  name='tasks',
  dependencies=[
    ':pytest_run',
    ':python_eval',
    ':python_repl',
    ':python_task',
    ':setup_py',
  ]
)

python_library(
  name='python_task_test_base',
  sources=['python_task_test_base.py'],
  dependencies=[
    'src/python/pants/backend/python:plugin',
    'src/python/pants/base:address',
    'tests/python/pants_test/tasks:task_test_base'
  ]
)

python_tests(
  name='python_task',
  sources=['test_python_task.py'],
  dependencies=[
    ':python_task_test_base',
    'src/python/pants/backend/python/tasks:python',
  ]
)

python_tests(
  name='pytest_run',
  sources=['test_pytest_run.py'],
  dependencies=[
    '3rdparty/python:coverage',
    '3rdparty/python:pex',
    ':python_task_test_base',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/backend/python:python_setup',
    'src/python/pants/util:contextutil',
  ]
)


python_tests(
  name='python_eval',
  sources=['test_python_eval.py'],
  dependencies=[
    ':python_task_test_base',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:source_root',
  ]
)

python_tests(
  name='python_repl',
  sources=['test_python_repl.py'],
  dependencies=[
    ':python_task_test_base',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/backend/python:all_utils',
    'src/python/pants/base:address',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:source_root',
    'src/python/pants/base:target',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name='setup_py',
  sources=['test_setup_py.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:mock',
    ':python_task_test_base',

    # TODO(John Sirois): XXX this dep needs to be fixed.  All pants/java utility code needs to live
    # in pants java since non-jvm backends depend on it to run things.
    'src/python/pants/backend/jvm/subsystems:jvm',

    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/subsystem:subsystem_utils'
  ],
)
