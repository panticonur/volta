import logging
import re
import pkg_resources
import time
import threading

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
    (?P<value>.*)
    $
    """


class Abro(Phone):
    def __init__(self, config, core):
        Phone.__init__(self, config, core)
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
        self.ADB_CMD =  config.get_option('phone', 'util', 'adb')
        self.worker = None
        self.closed = False
        self.shellexec_metrics = config.get_option('phone', 'shellexec_metrics')
        self.shellexec_executor = threading.Thread(target=self.__shell_executor)
        self.shellexec_executor.setDaemon(True)
        self.shellexec_executor.start()
        self.my_metrics = {}
        self.__create_my_metrics()


    def __create_my_metrics(self):
        self.my_metrics['events'] = self.core.data_session.new_metric(
            {
                'type': 'events',
                'name': 'events',
                'source': 'phone'
            }
        )
        for key, value in self.shellexec_metrics.items():
            self.my_metrics[key] = self.core.data_session.new_metric(
                {
                    'type': 'metrics',
                    'name': key,
                    'source': 'phone',
                    '_apply': value.get('apply') if value.get('apply') else '',
                }
            )


    def adb_execution(self, cmd):
        def read_process_queues_and_report(outs_q, errs_q):
            outputs = get_nowait_from_queue(outs_q)
            for chunk in outputs:
                logger.debug('Command \'%s\' output: %s', cmd, chunk.strip('\n'))
            errors = get_nowait_from_queue(errs_q)
            for err_chunk in errors:
                logger.warn('Errors in command \'%s\' output: %s', cmd, err_chunk.strip('\n'))
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
        self.adb_execution(self.ADB_CMD+' -s '+self.source+' logcat -c')


    def start(self, results):
        self.phone_q = results
        self.__start_async_logcat()


    def __start_async_logcat(self):
        cmd = self.ADB_CMD+' -s '+self.source+' logcat -v time'
        self.worker = Executioner(cmd)
        out_q, err_q = self.worker.execute()

        self.logcat_pipeline = Drain(
            LogParser(
                out_q, self.compiled_regexp, self.config.get_option('phone', 'type')
            ),
            self.my_metrics['events']
        )
        self.logcat_pipeline.start()


    def run_test(self):
        logger.info('Infinite loop for volta because there are no tests specified, waiting for SIGINT')
        cmd = '/bin/bash -c \'while [ 1 ]; do sleep 1; done\''
        logger.info('Command \'%s\' executing...', cmd)
        self.test_performer = Executioner(cmd)
        self.test_performer.execute()


    def end(self):
        self.closed = True
        if self.worker:
            self.worker.close()
        if self.test_performer:
            self.test_performer.close()
        if self.logcat_pipeline:
            self.logcat_pipeline.close()


    def close(self):
        pass


    def get_info(self):
        data = {}
        if self.phone_q:
            data['grabber_queue_size'] = self.phone_q.qsize()
        if self.test_performer:
            data['test_performer_is_finished'] = self.test_performer.is_finished()
        return data


    def __shell_executor(self):
        while not self.closed:
            for key, value in self.shellexec_metrics.items():
                try:
                    if not self.shellexec_metrics[key].get('last_ts') \
                            or self.shellexec_metrics[key]['last_ts'] < int(time.time()) * 10**6:
                        metric_value = self.__execute_shellexec_metric(value.get('cmd'))
                        ts = int(time.time()) * 10 ** 6
                        if not value.get('start_time'):
                            self.shellexec_metrics[key]['start_time'] = ts
                            ts = 0
                        else:
                            ts = ts - self.shellexec_metrics[key]['start_time']
                            self.shellexec_metrics[key]['last_ts'] = ts
                        self.my_metrics[key].put(
                            pd.DataFrame(
                                data={
                                    ts:
                                        {'ts': ts, 'value': metric_value}
                                },
                            ).T
                        )
                    else:
                        continue
                except Exception:
                    logger.warning('Failed to collect shellexec metric: %s', key)
                    logger.debug('Failed to collect shellexec metric: %s', key, exc_info=True)
            time.sleep(0.1)


    @staticmethod
    def __execute_shellexec_metric(cmd):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        (stdout, stderr) = proc.communicate()
        return stdout.strip('\n')
