from __future__ import absolute_import
import os
import socket
import shutil
import uuid
import tempfile

import zmq

from dpark import util
import dpark.conf as conf

logger = util.get_logger(__name__)


class DparkEnv:
    environ = {}

    @classmethod
    def register(cls, name, value):
        cls.environ[name] = value

    @classmethod
    def get(cls, name, default=None):
        return cls.environ.get(name, default)

    def __init__(self):
        self.started = False
        roots = conf.DPARK_WORK_DIR
        if isinstance(roots, str):
            roots = roots.split(',')

        if not roots:
            logger.warning('Cannot get WORKDIR, use temp dir instead.')
            roots = [tempfile.gettempdir()]

        name = os.environ.get('DPARK_ID')
        if name is None:
            name = '%s-%s' % (socket.gethostname(), uuid.uuid4())
            os.environ['DPARK_ID'] = name

        self.workdir = [os.path.join(root, name) for root in roots]
        self.environ['WORKDIR'] = self.workdir

    def start(self, isMaster, environ={}):
        if self.started:
            return
        logger.debug("start env in %s: %s %s", os.getpid(), isMaster, environ)
        self.isMaster = isMaster
        if isMaster:
            try:
                for d in self.workdir:
                    util.mkdir_p(d)
            except OSError as e:
                if environ.get('is_local', False):
                    raise e

            self.environ['SERVER_URI'] = 'file://' + self.workdir[0]
            self.environ['COMPRESS'] = util.COMPRESS
        else:
            self.environ.update(environ)
            if self.environ['COMPRESS'] != util.COMPRESS:
                raise Exception("no %s available" % self.environ['COMPRESS'])

        self.ctx = zmq.Context()

        from dpark.tracker import TrackerServer, TrackerClient
        if isMaster:
            self.trackerServer = TrackerServer()
            self.trackerServer.start()
            addr = self.trackerServer.addr
            env.register('TrackerAddr', addr)
        else:
            addr = env.get('TrackerAddr')

        self.trackerClient = TrackerClient(addr)

        from dpark.cache import CacheTracker
        self.cacheTracker = CacheTracker()

        from dpark.shuffle import MapOutputTracker
        self.mapOutputTracker = MapOutputTracker()
        from dpark.shuffle import ParallelShuffleFetcher
        self.shuffleFetcher = ParallelShuffleFetcher(2)

        self.started = True
        logger.debug("env started")

    def stop(self):
        if not getattr(self, 'started', False):
            return
        logger.debug("stop env in %s", os.getpid())
        self.shuffleFetcher.stop()
        self.cacheTracker.stop()
        self.mapOutputTracker.stop()
        if self.isMaster:
            self.trackerServer.stop()
        from dpark.broadcast import stop_manager
        stop_manager()

        logger.debug("cleaning workdir ...")
        for d in self.workdir:
            shutil.rmtree(d, True)
        logger.debug("done.")

        self.started = False

env = DparkEnv()
