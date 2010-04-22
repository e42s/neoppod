#
# Copyright (C) 2006-2010  Nexedi SA
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

from time import time

from neo.epoll import Epoll
from neo.profiling import profiler_decorator

class EpollEventManager(object):
    """This class manages connections and events based on epoll(5)."""

    def __init__(self):
        self.connection_dict = {}
        self.reader_set = set([])
        self.writer_set = set([])
        self.prev_time = time()
        self.epoll = Epoll()
        self._pending_processing = []

    def getConnectionList(self):
        # XXX: use index
        return [x for x in self.connection_dict.values() if not x.isAborted()]

    def getClientList(self):
        # XXX: use index
        return [c for c in self.getConnectionList() if c.isClient()]

    def getServerList(self):
        # XXX: use index
        return [c for c in self.getConnectionList() if c.isServer()]

    def getConnectionListByUUID(self, uuid):
        """ Return the connection associated to the UUID, None if the UUID is
        None, invalid or not found"""
        # XXX: use index
        # XXX: consider remove UUID from connection and thus this method
        if uuid is None:
            return None
        result = []
        append = result.append
        for conn in self.getConnectionList():
            if conn.getUUID() == uuid:
                append(conn)
        return result

    def register(self, conn):
        fd = conn.getConnector().getDescriptor()
        self.connection_dict[fd] = conn
        self.epoll.register(fd)

    def unregister(self, conn):
        new_pending_processing = [x for x in self._pending_processing
                                  if x is not conn]
        # Check that we removed at most one entry from
        # self._pending_processing .
        assert len(new_pending_processing) > len(self._pending_processing) - 2
        self._pending_processing = new_pending_processing
        fd = conn.getConnector().getDescriptor()
        self.epoll.unregister(fd)
        del self.connection_dict[fd]

    def _getPendingConnection(self):
        if len(self._pending_processing):
            result = self._pending_processing.pop(0)
        else:
            result = None
        return result

    def _addPendingConnection(self, conn):
        self._pending_processing.append(conn)

    def poll(self, timeout=1):
        to_process = self._getPendingConnection()
        if to_process is None:
            # Fetch messages from polled file descriptors
            self._poll(timeout=timeout)
            # See if there is anything to process
            to_process = self._getPendingConnection()
        if to_process is not None:
            try:
                # Process
                to_process.process()
            finally:
                # ...and requeue if there are pending messages
                if to_process.hasPendingMessages():
                    self._addPendingConnection(to_process)

    def _poll(self, timeout=1):
        rlist, wlist, elist = self.epoll.poll(timeout)
        r_done_set = set()
        for fd in rlist:
            if fd in r_done_set:
                continue
            r_done_set.add(fd)
            conn = self.connection_dict[fd]
            conn.lock()
            try:
                conn.readable()
            finally:
                conn.unlock()
            if conn.hasPendingMessages():
                self._addPendingConnection(conn)

        w_done_set = set()
        for fd in wlist:
            if fd in w_done_set:
                continue
            w_done_set.add(fd)
            # This can fail, if a connection is closed in readable().
            try:
                conn = self.connection_dict[fd]
            except KeyError:
                pass
            else:
                conn.lock()
                try:
                    conn.writable()
                finally:
                    conn.unlock()

        e_done_set = set()
        for fd in elist:
            if fd in e_done_set:
                continue
            e_done_set.add(fd)
            # This can fail, if a connection is closed in previous calls to
            # readable() or writable().
            try:
                conn = self.connection_dict[fd]
            except KeyError:
                pass
            else:
                conn.lock()
                try:
                    conn.readable()
                finally:
                    conn.unlock()

        t = time()
        for conn in self.connection_dict.values():
            conn.lock()
            try:
                conn.checkTimeout(t)
            finally:
                conn.unlock()

    def addReader(self, conn):
        connector = conn.getConnector()
        assert connector is not None, conn.whoSetConnector()
        fd = connector.getDescriptor()
        if fd not in self.reader_set:
            self.reader_set.add(fd)
            self.epoll.modify(fd, 1, fd in self.writer_set)

    def removeReader(self, conn):
        connector = conn.getConnector()
        assert connector is not None, conn.whoSetConnector()
        fd = connector.getDescriptor()
        if fd in self.reader_set:
            self.reader_set.remove(fd)
            self.epoll.modify(fd, 0, fd in self.writer_set)

    @profiler_decorator
    def addWriter(self, conn):
        connector = conn.getConnector()
        assert connector is not None, conn.whoSetConnector()
        fd = connector.getDescriptor()
        if fd not in self.writer_set:
            self.writer_set.add(fd)
            self.epoll.modify(fd, fd in self.reader_set, 1)

    def removeWriter(self, conn):
        connector = conn.getConnector()
        assert connector is not None, conn.whoSetConnector()
        fd = connector.getDescriptor()
        if fd in self.writer_set:
            self.writer_set.remove(fd)
            self.epoll.modify(fd, fd in self.reader_set, 0)

# Default to EpollEventManager.
EventManager = EpollEventManager
