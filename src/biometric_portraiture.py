#!/usr/bin/env python

import sys
import os
import threading
import inspect
from thinkgear import *
from lightstone import *
import json
import Queue
import time
import gzip

class BiometricDataPacket():
    PACKET_TEMPLATE = "[%(data_index)d, %(data_time).3f, %(data_type)d, %(data_value).6f]"
    def __init__(self, data_type, data_value):
        self.data_type = data_type
        self.data_value = data_value
        self.data_time = time.time()
        self.data_index = 0

    def set_index(self, index):
        self.data_index = index

    def __str__(self):
        members = inspect.getmembers(self)
        format_data = {}
        for key, value in members:
            format_data[key] = value
        return self.PACKET_TEMPLATE % (format_data)

class BiometricLogManager():
    _packet_queue = Queue.LifoQueue()
    _packet_index = 0
    def __init__(self, dump_file, size_limit = None):        
        if size_limit is not None:
            self._packet_queue = Queue.LifoQueue(size_limit)
        self.dump_file = gzip.open(dump_file, "w")
        self.dump_file.write("[")

    @classmethod
    def open(cls, dump_file, size_limit = None):
        return BiometricLogManager(dump_file, size_limit)

    @contextmanager
    def close(self):
        self.dump_file.write("]")
        self.dump_file.close()

    def add_packet(self, data_type, data_value):
        self._packet_queue.put(BiometricDataPacket(data_type, data_value))

    def dump_packets(self):
        try:            
            while 1:
                packet = self._packet_queue.get()
                packet.set_index(self._packet_index)
                self.dump_file.write("%s,\n" % packet)
                self._packet_index += 1
        except Queue.Empty, e:
            pass

class LoggingManager(threading.Thread):    
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self._logging_queue = queue
        self.stop_thread = False
    def stop(self):
        self.stop_thread = True

class LightstoneThread(LoggingManager):
    def __init__(self, queue):
        LoggingManager.__init__(self, queue)

    def run(self):
        self._lightstone = lightstone.open()
        while not self.stop_thread:
            self._lightstone.get_data()
            self._logging_queue.add_packet(2000, self._lightstone.hrv)
            self._logging_queue.add_packet(2001, self._lightstone.scl)
        self._lightstone.close()

class ThinkGearThread(LoggingManager):
    def __init__(self, queue, port):
        LoggingManager.__init__(self, queue)
        self.port = port

    def run(self):
        try:
            self._thinkgear = ThinkGearProtocol(self.port)
            for pkt in self._thinkgear.get_packets():
                for packet in pkt:
                    if packet.code in [0x02, 0x04, 0x05, 0x80]:
                        self._logging_queue.add_packet(1000 + packet.code, packet.value)
                if self.stop_thread:
                    break
        finally:
            self._thinkgear.serial.close()

def main(argv = None):
    print """
Biometric Portraiture Logger
By Kyle Machulis (kyle@nonpolynomial.com)
"""
    with closing(BiometricLogManager.open("./test.biolog.gz")) as q:
        l = LightstoneThread(q)
        t = ThinkGearThread(q, "/dev/tty.MindSet-DevB-1")

        l.start()
        t.start()                   
        try:
            while(1):
                l.join(.1)
                t.join(.1)
                q.dump_packets()
        except KeyboardInterrupt, e:
            print "Exiting"
            l.stop()
            t.stop()
            while l.is_alive():
                l.join()
            while t.is_alive():
                t.join()
if __name__ == '__main__':
    sys.exit(main())

