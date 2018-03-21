import logging
import re
import pkg_resources
import time

from netort.data_processing import Drain, get_nowait_from_queue
from netort.resource import manager as resource

from volta.common.interfaces import Phone
from volta.common.util import LogParser, Executioner


logger = logging.getLogger(__name__)


event_regexp = r"""
    ^
    (?P<date>\S+)
    \s+
    (?P<time>\S+)
    \s+
    (?P<tag>(\S+?)\s*\(\s*\d+\))
    :\s+
    (?P<message>.*)
    $
    """


class Abro(Phone):
    def __init__(self, config):
        Phone.__init__(self, config)
        self.logcat_stdout_reader = None
        self.logcat_stderr_reader = None
        self.source = config.get_option('phone', 'source')
        try:
            self.compiled_regexp = re.compile(
                config.get_option('phone', 'event_regexp', event_regexp), re.VERBOSE | re.IGNORECASE
            )
        except SyntaxError:
            logger.debug('Unable to parse specified regexp', exc_info=True)
            raise RuntimeError(
                "Unable to parse specified regexp: %s" % config.get_option('phone', 'event_regexp', event_regexp)
            )
        self.logcat_pipeline = None
        self.test_performer = None
        self.phone_q = None


    def adb_execution(self, cmd):
        def read_process_queues_and_report(outs_q, errs_q):
            outputs = get_nowait_from_queue(outs_q)
            for chunk in outputs:
                logger.debug('Command \'%s\' output: %s', cmd, chunk.strip('\n'))
            errors = get_nowait_from_queue(errs_q)
            if errors:
                worker.close()
                raise RuntimeError(
                    'There were errors executing \'%s\' on device %s. Errors :%s' % (cmd, self.source, errors)
                )
        worker = Executioner(cmd)
        outs_q, errs_q = worker.execute()
        while worker.is_finished() is None:
            read_process_queues_and_report(outs_q, errs_q)
            time.sleep(1)
        read_process_queues_and_report(outs_q, errs_q)
        while not outs_q.qsize() != 0 and errs_q.qsize() != 0:
            time.sleep(0.5)
        worker.close()
        logger.info('Command \'%s\' executed on device %s. Retcode: %s', cmd, self.source, worker.is_finished())
        if worker.is_finished() != 0:
            raise RuntimeError('Failed to execute adb command \'%s\'' % cmd)


    def prepare(self):
        self.adb_execution("adb -s {device_id} logcat -c".format(device_id=self.source))


    def start(self, results):
        self.phone_q = results
        self.__start_async_logcat()


    def __start_async_logcat(self):
        cmd = "adb -s {device_id} logcat -v time".format(device_id=self.source)
        self.worker = Executioner(cmd)
        out_q, err_q = self.worker.execute()

        self.logcat_pipeline = Drain(
            LogParser(
                out_q, self.compiled_regexp, self.config.get_option('phone', 'type')
            ),
            self.phone_q
        )
        self.logcat_pipeline.start()


    def run_test(self):
        logger.info('Infinite loop for volta because there are no tests specified, waiting for SIGINT')
        cmd = '/bin/bash -c \'while [ 1 ]; do sleep 1; done\''
        logger.info('Command \'%s\' executing...', cmd)
        self.test_performer = Executioner(cmd)
        self.test_performer.execute()


    def end(self):
        self.worker.close()
        if self.test_performer:
            self.test_performer.close()
        if self.logcat_pipeline:
            self.logcat_pipeline.close()


    def get_info(self):
        data = {}
        if self.phone_q:
            data['grabber_queue_size'] = self.phone_q.qsize()
        if self.test_performer:
            data['test_performer_is_finished'] = self.test_performer.is_finished()
        return data

    def close(self):
        pass
