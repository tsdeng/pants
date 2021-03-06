# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import zipfile
from collections import OrderedDict, defaultdict
from hashlib import sha1

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_compile.compile_context import IsolatedCompileContext
from pants.backend.jvm.tasks.jvm_compile.execution_graph import (ExecutionFailure, ExecutionGraph,
                                                                 Job)
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_strategy import JvmCompileStrategy
from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.worker_pool import Work, WorkerPool
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_mkdir, safe_walk
from pants.util.fileutil import atomic_copy


class JvmCompileIsolatedStrategy(JvmCompileStrategy):
  """A strategy for JVM compilation that uses per-target classpaths and analysis."""

  @classmethod
  def register_options(cls, register, compile_task_name, supports_concurrent_execution):
    if supports_concurrent_execution:
      register('--worker-count', advanced=True, type=int, default=1,
               help='The number of concurrent workers to use compiling with {task} with the '
                    'isolated strategy.'.format(task=compile_task_name))
    register('--capture-log', advanced=True, action='store_true', default=False,
             fingerprint=True,
             help='Capture compilation output to per-target logs.')

  def __init__(self, context, options, workdir, analysis_tools, compile_task_name,
               sources_predicate):
    super(JvmCompileIsolatedStrategy, self).__init__(context, options, workdir, analysis_tools,
                                                     compile_task_name, sources_predicate)

    # Various working directories.
    self._analysis_dir = os.path.join(workdir, 'isolated-analysis')
    self._classes_dir = os.path.join(workdir, 'isolated-classes')
    self._logs_dir = os.path.join(workdir, 'isolated-logs')
    self._jars_dir = os.path.join(workdir, 'jars')

    self._capture_log = options.capture_log

    try:
      worker_count = options.worker_count
    except AttributeError:
      # tasks that don't support concurrent execution have no worker_count registered
      worker_count = 1
    self._worker_count = worker_count

    self._worker_pool = None

  def name(self):
    return 'isolated'

  def compile_context(self, target):
    analysis_file = JvmCompileStrategy._analysis_for_target(self._analysis_dir, target)
    classes_dir = os.path.join(self._classes_dir, target.id)
    # Generate a short unique path for the jar to allow for shorter classpaths.
    #   TODO: likely unnecessary after https://github.com/pantsbuild/pants/issues/1988
    jar_file = os.path.join(self._jars_dir, '{}.jar'.format(sha1(target.id).hexdigest()[:12]))
    return IsolatedCompileContext(target,
                                  analysis_file,
                                  classes_dir,
                                  jar_file,
                                  self._sources_for_target(target))

  def _create_compile_contexts_for_targets(self, targets):
    compile_contexts = OrderedDict()
    for target in targets:
      compile_context = self.compile_context(target)
      compile_contexts[target] = compile_context
    return compile_contexts

  def pre_compile(self):
    super(JvmCompileIsolatedStrategy, self).pre_compile()
    safe_mkdir(self._analysis_dir)
    safe_mkdir(self._classes_dir)
    safe_mkdir(self._logs_dir)
    safe_mkdir(self._jars_dir)

  def prepare_compile(self, cache_manager, all_targets, relevant_targets):
    super(JvmCompileIsolatedStrategy, self).prepare_compile(cache_manager, all_targets,
                                                            relevant_targets)

    # Update the classpath by adding relevant target's classes directories to its classpath.
    compile_classpaths = self.context.products.get_data('compile_classpath')

    with self.context.new_workunit('validate-{}-analysis'.format(self._compile_task_name)):
      for target in relevant_targets:
        cc = self.compile_context(target)
        safe_mkdir(cc.classes_dir)
        compile_classpaths.add_for_target(target, [(conf, cc.classes_dir) for conf in self._confs])
        self.validate_analysis(cc.analysis_file)

    # This ensures the workunit for the worker pool is set
    with self.context.new_workunit('isolation-{}-pool-bootstrap'.format(self._compile_task_name)) \
            as workunit:
      # This uses workunit.parent as the WorkerPool's parent so that child workunits
      # of different pools will show up in order in the html output. This way the current running
      # workunit is on the bottom of the page rather than possibly in the middle.
      self._worker_pool = WorkerPool(workunit.parent,
                                     self.context.run_tracker,
                                     self._worker_count)

  def finalize_compile(self, targets):
    # Replace the classpath entry for each target with its jar'd representation.
    compile_classpaths = self.context.products.get_data('compile_classpath')
    for target in targets:
      cc = self.compile_context(target)
      for conf in self._confs:
        compile_classpaths.remove_for_target(target, [(conf, cc.classes_dir)])
        compile_classpaths.add_for_target(target, [(conf, cc.jar_file)])

  def invalidation_hints(self, relevant_targets):
    # No partitioning.
    return (0, None)

  def compute_classes_by_source(self, compile_contexts):
    buildroot = get_buildroot()
    # Build a mapping of srcs to classes for each context.
    classes_by_src_by_context = defaultdict(dict)
    for compile_context in compile_contexts:
      # Walk the context's jar to build a set of unclaimed classfiles.
      unclaimed_classes = set()
      with compile_context.open_jar(mode='r') as jar:
        for name in jar.namelist():
          unclaimed_classes.add(os.path.join(compile_context.classes_dir, name))

      # Grab the analysis' view of which classfiles were generated.
      classes_by_src = classes_by_src_by_context[compile_context]
      if os.path.exists(compile_context.analysis_file):
        products = self._analysis_parser.parse_products_from_path(compile_context.analysis_file,
                                                                  compile_context.classes_dir)
        for src, classes in products.items():
          relsrc = os.path.relpath(src, buildroot)
          classes_by_src[relsrc] = classes
          unclaimed_classes.difference_update(classes)

      # Any remaining classfiles were unclaimed by sources/analysis.
      classes_by_src[None] = list(unclaimed_classes)
    return classes_by_src_by_context

  def _compute_classpath_entries(self, compile_classpaths,
                                 target_closure,
                                 compile_context,
                                 extra_compile_time_classpath):
    # Generate a classpath specific to this compile and target.
    return ClasspathUtil.compute_classpath_for_target(compile_context.target, compile_classpaths,
                                                      extra_compile_time_classpath, self._confs,
                                                      target_closure)

  def _upstream_analysis(self, compile_contexts, classpath_entries):
    """Returns tuples of classes_dir->analysis_file for the closure of the target."""
    # Reorganize the compile_contexts by class directory.
    compile_contexts_by_directory = {}
    for compile_context in compile_contexts.values():
      compile_contexts_by_directory[compile_context.classes_dir] = compile_context
    # If we have a compile context for the target, include it.
    for entry in classpath_entries:
      if not entry.endswith('.jar'):
        compile_context = compile_contexts_by_directory.get(entry)
        if not compile_context:
          self.context.log.debug('Missing upstream analysis for {}'.format(entry))
        else:
          yield compile_context.classes_dir, compile_context.analysis_file

  def _capture_log_file(self, target):
    if self._capture_log:
      return os.path.join(self._logs_dir, "{}.log".format(target.id))
    return None

  def exec_graph_key_for_target(self, compile_target):
    return "compile({})".format(compile_target.address.spec)

  def _create_compile_jobs(self, compile_classpaths, compile_contexts, extra_compile_time_classpath,
                           invalid_targets, invalid_vts_partitioned, compile_vts, register_vts,
                           update_artifact_cache_vts_work):
    def create_work_for_vts(vts, compile_context, target_closure):
      def work():
        progress_message = compile_context.target.address.spec
        cp_entries = self._compute_classpath_entries(compile_classpaths,
                                                     target_closure,
                                                     compile_context,
                                                     extra_compile_time_classpath)

        upstream_analysis = dict(self._upstream_analysis(compile_contexts, cp_entries))

        # Capture a compilation log if requested.
        log_file = self._capture_log_file(compile_context.target)

        # Mutate analysis within a temporary directory, and move it to the final location
        # on success.
        tmpdir = os.path.join(self.analysis_tmpdir, compile_context.target.id)
        safe_mkdir(tmpdir)
        tmp_analysis_file = JvmCompileStrategy._analysis_for_target(
            tmpdir, compile_context.target)
        if os.path.exists(compile_context.analysis_file):
           shutil.copy(compile_context.analysis_file, tmp_analysis_file)
        target, = vts.targets
        compile_vts(vts,
                    compile_context.sources,
                    tmp_analysis_file,
                    upstream_analysis,
                    cp_entries,
                    compile_context.classes_dir,
                    log_file,
                    progress_message,
                    target.platform)
        atomic_copy(tmp_analysis_file, compile_context.analysis_file)

        # Jar the compiled output.
        self._create_context_jar(compile_context)

        # Update the products with the latest classes.
        register_vts([compile_context])

        # Kick off the background artifact cache write.
        if update_artifact_cache_vts_work:
          self._write_to_artifact_cache(vts, compile_context, update_artifact_cache_vts_work)

      return work

    jobs = []
    invalid_target_set = set(invalid_targets)
    for vts in invalid_vts_partitioned:
      assert len(vts.targets) == 1, ("Requested one target per partition, got {}".format(vts))

      # Invalidated targets are a subset of relevant targets: get the context for this one.
      compile_target = vts.targets[0]
      compile_context = compile_contexts[compile_target]
      compile_target_closure = compile_target.closure()

      # dependencies of the current target which are invalid for this chunk
      invalid_dependencies = (compile_target_closure & invalid_target_set) - [compile_target]

      jobs.append(Job(self.exec_graph_key_for_target(compile_target),
                      create_work_for_vts(vts, compile_context, compile_target_closure),
                      [self.exec_graph_key_for_target(target) for target in invalid_dependencies],
                      # If compilation and analysis work succeeds, validate the vts.
                      # Otherwise, fail it.
                      on_success=vts.update,
                      on_failure=vts.force_invalidate))
    return jobs

  def compile_chunk(self,
                    invalidation_check,
                    all_targets,
                    relevant_targets,
                    invalid_targets,
                    extra_compile_time_classpath_elements,
                    compile_vts,
                    register_vts,
                    update_artifact_cache_vts_work):
    """Executes compilations for the invalid targets contained in a single chunk."""
    assert invalid_targets, "compile_chunk should only be invoked if there are invalid targets."
    # Get the classpath generated by upstream JVM tasks and our own prepare_compile().
    compile_classpaths = self.context.products.get_data('compile_classpath')

    extra_compile_time_classpath = self._compute_extra_classpath(
        extra_compile_time_classpath_elements)

    compile_contexts = self._create_compile_contexts_for_targets(all_targets)

    # Now create compile jobs for each invalid target one by one.
    jobs = self._create_compile_jobs(compile_classpaths,
                                     compile_contexts,
                                     extra_compile_time_classpath,
                                     invalid_targets,
                                     invalidation_check.invalid_vts_partitioned,
                                     compile_vts,
                                     register_vts,
                                     update_artifact_cache_vts_work)

    exec_graph = ExecutionGraph(jobs)
    try:
      exec_graph.execute(self._worker_pool, self.context.log)
    except ExecutionFailure as e:
      raise TaskError("Compilation failure: {}".format(e))

  def compute_resource_mapping(self, compile_contexts):
    return ResourceMapping(self._classes_dir)

  def post_process_cached_vts(self, cached_vts):
    """Localizes the fetched analysis for targets we found in the cache.

    This is the complement of `_write_to_artifact_cache`.
    """
    compile_contexts = []
    for vt in cached_vts:
      for target in vt.targets:
        compile_contexts.append(self.compile_context(target))

    for compile_context in compile_contexts:
      portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(
          self._analysis_dir, compile_context.target)
      if os.path.exists(portable_analysis_file):
        self._analysis_tools.localize(portable_analysis_file, compile_context.analysis_file)

  def _create_context_jar(self, compile_context):
    """Jar up the compile_context to its output jar location.

    TODO(stuhood): In the medium term, we hope to add compiler support for this step, which would
    allow the jars to be used as compile _inputs_ as well. Currently using jar'd compile outputs as
    compile inputs would make the compiler's analysis useless.
      see https://github.com/twitter-forks/sbt/tree/stuhood/output-jars
    """
    root = compile_context.classes_dir
    with compile_context.open_jar(mode='w') as jar:
      for abs_sub_dir, dirnames, filenames in safe_walk(root):
        for name in dirnames + filenames:
          abs_filename = os.path.join(abs_sub_dir, name)
          arcname = os.path.relpath(abs_filename, root)
          jar.write(abs_filename, arcname)

  def _write_to_artifact_cache(self, vts, compile_context, get_update_artifact_cache_work):
    assert len(vts.targets) == 1
    assert vts.targets[0] == compile_context.target

    # Noop if the target is uncacheable.
    if (compile_context.target.has_label('no_cache')):
      return
    vt = vts.versioned_targets[0]

    # Set up args to relativize analysis in the background.
    portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(
        self._analysis_dir, compile_context.target)
    relativize_args_tuple = (compile_context.analysis_file, portable_analysis_file)

    # Collect the artifacts for this target.
    artifacts = []

    def add_abs_products(p):
      if p:
        for _, paths in p.abs_paths():
          artifacts.extend(paths)
    # Resources.
    resources_by_target = self.context.products.get_data('resources_by_target')
    add_abs_products(resources_by_target.get(compile_context.target))
    # Classes.
    classes_by_target = self.context.products.get_data('classes_by_target')
    add_abs_products(classes_by_target.get(compile_context.target))
    # Log file.
    log_file = self._capture_log_file(compile_context.target)
    if log_file and os.path.exists(log_file):
      artifacts.append(log_file)
    # Jar.
    artifacts.append(compile_context.jar_file)

    # Get the 'work' that will publish these artifacts to the cache.
    # NB: the portable analysis_file won't exist until we finish.
    vts_artifactfiles_pair = (vt, artifacts + [portable_analysis_file])
    update_artifact_cache_work = get_update_artifact_cache_work([vts_artifactfiles_pair])

    # And execute it.
    if update_artifact_cache_work:
      work_chain = [
          Work(self._analysis_tools.relativize, [relativize_args_tuple], 'relativize'),
          update_artifact_cache_work
      ]
      self.context.submit_background_work_chain(work_chain, parent_workunit_name='cache')

  def parse_deps(self, classpath, compile_context):
    # We intentionally pass in an empty string for classes_dir in order to receive
    # relative paths, because we currently don't know (and don't need to know) what target
    # provided the file.
    return self._analysis_parser.parse_deps_from_path(compile_context.analysis_file, dict, '')
