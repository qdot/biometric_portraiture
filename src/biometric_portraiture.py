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
    PACKET_TEMPLATE = "[%(data_index)d, %(data_time).3f, %(data_type)d, %(data_format)s]"
    def __init__(self, data_type, data_value, data_format = "\"%(data_value)s\""):
        self.data_type = data_type
        self.data_value = data_value
        self.data_time = time.time()
        self.data_index = 0
        self.data_format = data_format

    def set_index(self, index):
        self.data_index = index

    def __str__(self):
        members = inspect.getmembers(self)
        format_data = {}
        for key, value in members:
            format_data[key] = value
        return (self.PACKET_TEMPLATE % (format_data)) % (format_data)

class BiometricLogManager():
    _packet_queue = Queue.Queue()
    _packet_index = 0
    _update_time = 0
    _last_power = 0
    _last_scl = 0
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

    def add_packet(self, data_type, data_value, data_format = "\"%(data_value)s\""):
        self._packet_queue.put(BiometricDataPacket(data_type, data_value, data_format))

    def dump_packets(self):
        try:
            while not self._packet_queue.empty():
                packet = self._packet_queue.get()
                if packet.data_type == 2001:
                    self._last_scl = packet.data_value
                elif packet.data_type == 1002:
                    self._last_power = packet.data_value
                if packet.data_time - self._update_time > 1:
                    print "EEG Power: %d SCL Level: %f" % (self._last_power, self._last_scl)
                    self._update_time = packet.data_time
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
            self._logging_queue.add_packet(2000, self._lightstone.hrv, "%(data_value).3f")
            self._logging_queue.add_packet(2001, self._lightstone.scl, "%(data_value).3f")
        self._lightstone.close()

class ThinkGearThread(LoggingManager):
    def __init__(self, queue, port):
        LoggingManager.__init__(self, queue)
        self.port = port
        self.output_format = { 0x02 : "%(data_value)d",
                               0x04 : "%(data_value)d",
                               0x05 : "%(data_value)d",
                               0x80 : "%(data_value)d",
                               0x83 : "%(data_value)s",
                               }
    def run(self):
        try:
            self._thinkgear = ThinkGearProtocol(self.port)
            for pkt in self._thinkgear.get_packets():
                for packet in pkt:
                    if packet.code in self.output_format.keys():
                        if packet.code == 0x83:
                            value = packet.value._asdict().values()
                        else:
                            value = packet.value
                        self._logging_queue.add_packet(1000 + packet.code, value, self.output_format[packet.code])
                if self.stop_thread:
                    break
        finally:
            self._thinkgear.serial.close()

class MessageThread(LoggingManager):
    def __init__(self, queue):
        LoggingManager.__init__(self, queue)
    
    def run(self):
        try:
            while not self.stop_thread:                
                k = raw_input()
                if k[0] == " ":
                    self._logging_queue.add_packet(0, "Mark")
        except Exception, e:
            self.stop_thread = True
            pass

def main(argv = None):
    print """
Biometric Portraiture Logger
By Kyle Machulis (kyle@nonpolynomial.com)
"""
    with closing(BiometricLogManager.open("./test.biolog.gz")) as q:
        thread_list = []
        thread_list.append(LightstoneThread(q))
        thread_list.append(ThinkGearThread(q, "/dev/tty.MindSet-DevB-1"))
        thread_list.append(MessageThread(q))
        [x.start() for x in thread_list]
        try:
            while(1):
                [x.join(.1) for x in thread_list]
                q.dump_packets()
        except KeyboardInterrupt, e:
            print "Exiting"
        [x.stop() for x in thread_list]
        [x.join(1) if x.is_alive() else None for x in thread_list]
        q.dump_packets()

if __name__ == '__main__':
    sys.exit(main())

