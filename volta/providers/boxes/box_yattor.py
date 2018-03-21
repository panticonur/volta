import logging
import Queue as queue
import time
import numpy as np
import json

from volta.common.interfaces import VoltaBox
from volta.common.util import TimeChopper, string_to_np

from netort.data_processing import Drain
from netort.resource import manager as resource

from ctypes import *
# https://docs.python.org/2/library/ctypes.html


logger = logging.getLogger(__name__)


class YattorBox(VoltaBox):
    """
    Attributes:
        chop_ratio (int): chop ratio for incoming data, 1 means 1 second (500 for sample_rate 500)
        grab_timeout (int): timeout for grabber
    """
    def __init__(self, config):
        VoltaBox.__init__(self, config)
        self.lib = CDLL("libyattor.so")
        self.serialNumber = int(config.get_option('volta', 'source'))
        self.sample_rate = 10000 # config.get_option('volta', 'sample_rate', 10000)
        self.chop_ratio = config.get_option('volta', 'chop_ratio', 1)
        self.grab_timeout = config.get_option('volta', 'grab_timeout', 1)
        if self.lib.yattor_open(self.serialNumber, 1)!=0:
            RuntimeError("Unable to open yattor")
        self.grabber_q = None


    def start_test(self, results):
        self.grabber_q = results
        """if self.lib.yattor_purge()!=0:
            RuntimeError("Unable to purge yattor")"""
        if self.lib.yattor_start(0)!=0:
            RuntimeError("Unable to start yattor")

        self.reader = YattorReader(self.lib, self.sample_rate)
        self.pipeline = Drain(
            TimeChopper(
                self.reader, self.sample_rate, self.chop_ratio
            ),
            self.grabber_q
        )
        logger.info('Starting grab thread...')
        self.pipeline.start()
        logger.debug('Waiting grabber thread finish...')


    def end_test(self):
        self.lib.yattor_stop()
        try:
            self.reader.close()
        except AttributeError:
            logger.warn('VoltaBox has no Reader. Seems like VoltaBox initialization failed')
            logger.debug('VoltaBox has no Reader. Seems like VoltaBox initialization failed', exc_info=True)
        try:
            self.pipeline.close()
        except AttributeError:
            logger.warn('VoltaBox has no Pipeline. Seems like VoltaBox initialization failed')
        else:
            self.pipeline.join(10)
        self.lib.yattor_close()
        del self.lib


    def get_info(self):
        data = {}
        if self.pipeline:
            data['grabber_alive'] = self.pipeline.isAlive()
        if self.grabber_q:
            data['grabber_queue_size'] = self.grabber_q.qsize()
        return data



class YattorReader(object):
    def __init__(self, lib, sample_rate):
        self.closed = False
        self.lib = lib
        self.sample_rate = sample_rate
        FloatArray_t = c_float * (sample_rate*2)
        self.floatBuffer = FloatArray_t()
        #WordArray_t = c_ushort * (sample_rate*2)
        #self.wordBuffer = WordArray_t()


    def _read_chunk(self):
        amount = self.lib.yattor_read_ampere(-1, self.sample_rate*2, self.floatBuffer)
        #amount = self.lib.yattor_read_milliampere(-1, self.sample_rate, self.wordBuffer)
        if amount>0:
            chunk = np.frombuffer(buffer=self.floatBuffer, dtype=np.float32, count=amount)
            #chunk = np.frombuffer(buffer=self.wordBuffer, dtype=np.uint16, count=amount)#.astype(np.float32)
            chunk = chunk * 1000
            return chunk
        if amount==0:
            work = self.lib.yattor_working();
            if work!=0:
                raise RuntimeError('yattor not working "'+str(work)+'"')
            time.sleep(0.5)
        else:
            raise RuntimeError('yattor error: yattor_read_ampere "'+str(amount)+'"')


    def __iter__(self):
        while not self.closed:
            yield self._read_chunk()
        yield self._read_chunk()


    def close(self):
        self.closed = True
