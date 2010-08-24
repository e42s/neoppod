
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

from neo import logging

from neo.handler import EventHandler
from neo.protocol import Packets, ZERO_TID, ZERO_OID
from neo import util

def checkConnectionIsReplicatorConnection(func):
    def decorator(self, conn, *args, **kw):
        if self.app.replicator.current_connection is conn:
            result = func(self, conn, *args, **kw)
        else:
            # Should probably raise & close connection...
            result = None
        return result
    return decorator

def add64(packed, offset):
    """Add a python number to a 64-bits packed value"""
    return util.p64(util.u64(packed) + offset)

class ReplicationHandler(EventHandler):
    """This class handles events for replications."""

    def connectionLost(self, conn, new_state):
        logging.error('replication is stopped due to a connection lost')
        self.app.replicator.reset()

    def connectionFailed(self, conn):
        logging.error('replication is stopped due to connection failure')
        self.app.replicator.reset()

    def acceptIdentification(self, conn, node_type,
                       uuid, num_partitions, num_replicas, your_uuid):
        # set the UUID on the connection
        conn.setUUID(uuid)

    @checkConnectionIsReplicatorConnection
    def answerTIDsFrom(self, conn, tid_list):
        app = self.app
        if tid_list:
            # If I have pending TIDs, check which TIDs I don't have, and
            # request the data.
            present_tid_list = app.dm.getTIDListPresent(tid_list)
            tid_set = set(tid_list) - set(present_tid_list)
            for tid in tid_set:
                conn.ask(Packets.AskTransactionInformation(tid), timeout=300)

            # And, ask more TIDs.
            p = Packets.AskTIDsFrom(add64(tid_list[-1], 1), 1000,
                      app.replicator.current_partition.getRID())
            conn.ask(p, timeout=300)
        else:
            # If no more TID, a replication of transactions is finished.
            # So start to replicate objects now.
            p = Packets.AskOIDs(ZERO_OID, 1000,
                      app.replicator.current_partition.getRID())
            conn.ask(p, timeout=300)

    @checkConnectionIsReplicatorConnection
    def answerTransactionInformation(self, conn, tid,
                                           user, desc, ext, packed, oid_list):
        app = self.app
        # Directly store the transaction.
        app.dm.storeTransaction(tid, (), (oid_list, user, desc, ext, packed),
            False)

    @checkConnectionIsReplicatorConnection
    def answerOIDs(self, conn, oid_list):
        app = self.app
        if oid_list:
            app.replicator.next_oid = add64(oid_list[-1], 1)
            # Pick one up, and ask the history.
            oid = oid_list.pop()
            conn.ask(Packets.AskObjectHistoryFrom(oid, ZERO_TID, 1000),
                timeout=300)
            app.replicator.oid_list = oid_list
        else:
            # Nothing remains, so the replication for this partition is
            # finished.
            app.replicator.replication_done = True

    @checkConnectionIsReplicatorConnection
    def answerObjectHistoryFrom(self, conn, oid, serial_list):
        app = self.app
        if serial_list:
            # Check if I have objects, request those which I don't have.
            present_serial_list = app.dm.getSerialListPresent(oid, serial_list)
            serial_set = set(serial_list) - set(present_serial_list)
            for serial in serial_set:
                conn.ask(Packets.AskObject(oid, serial, None), timeout=300)

            # And, ask more serials.
            conn.ask(Packets.AskObjectHistoryFrom(oid,
                add64(serial_list[-1], 1), 1000), timeout=300)
        else:
            # This OID is finished. So advance to next.
            oid_list = app.replicator.oid_list
            if oid_list:
                # If I have more pending OIDs, pick one up.
                oid = oid_list.pop()
                conn.ask(Packets.AskObjectHistoryFrom(oid, ZERO_TID, 1000),
                    timeout=300)
            else:
                # Otherwise, acquire more OIDs.
                p = Packets.AskOIDs(app.replicator.next_oid, 1000,
                          app.replicator.current_partition.getRID())
                conn.ask(p, timeout=300)

    @checkConnectionIsReplicatorConnection
    def answerObject(self, conn, oid, serial_start,
            serial_end, compression, checksum, data, data_serial):
        app = self.app
        # Directly store the transaction.
        obj = (oid, compression, checksum, data, data_serial)
        app.dm.storeTransaction(serial_start, [obj], None, False)
        del obj
        del data

