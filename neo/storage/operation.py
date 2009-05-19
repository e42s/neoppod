#
# Copyright (C) 2006-2009  Nexedi SA
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import logging

from neo import protocol
from neo.storage.handler import StorageEventHandler
from neo.protocol import INVALID_UUID, INVALID_SERIAL, INVALID_TID, \
        INVALID_PARTITION, \
        RUNNING_STATE, BROKEN_STATE, TEMPORARILY_DOWN_STATE, \
        MASTER_NODE_TYPE, STORAGE_NODE_TYPE, CLIENT_NODE_TYPE, \
        DISCARDED_STATE, OUT_OF_DATE_STATE
from neo.util import dump
from neo.node import MasterNode, StorageNode, ClientNode
from neo.connection import ClientConnection
from neo.protocol import Packet
from neo.exception import PrimaryFailure, OperationFailure

class TransactionInformation(object):
    """This class represents information on a transaction."""
    def __init__(self, uuid):
        self._uuid = uuid
        self._object_dict = {}
        self._transaction = None

    def getUUID(self):
        return self._uuid

    def addObject(self, oid, compression, checksum, data):
        self._object_dict[oid] = (oid, compression, checksum, data)

    def addTransaction(self, oid_list, user, desc, ext):
        self._transaction = (oid_list, user, desc, ext)

    def getObjectList(self):
        return self._object_dict.values()

    def getTransaction(self):
        return self._transaction

class OperationEventHandler(StorageEventHandler):
    """This class deals with events for a operation phase."""

    def connectionCompleted(self, conn):
        # FIXME this must be implemented for replications.
        raise NotImplementedError

    def connectionFailed(self, conn):
        # FIXME this must be implemented for replications.
        raise NotImplementedError

    def connectionAccepted(self, conn, s, addr):
        """Called when a connection is accepted."""
        # Client nodes and other storage nodes may connect. Also,
        # master nodes may connect, only if they misunderstand that
        # I am a master node.
        StorageEventHandler.connectionAccepted(self, conn, s, addr)

    def dealWithClientFailure(self, uuid):
        if uuid is not None:
            app = self.app
            node = app.nm.getNodeByUUID(uuid)
            if node is not None and node.getNodeType() == CLIENT_NODE_TYPE:
                for tid, t in app.transaction_dict.items():
                    if t.getUUID() == uuid:
                        for o in t.getObjectList():
                            oid = o[0]
                            try:
                                del app.store_lock_dict[oid]
                                del app.load_lock_dict[oid]
                            except KeyError:
                                pass
                        del app.transaction_dict[tid]

                # Now it may be possible to execute some events.
                app.executeQueuedEvents()

    def timeoutExpired(self, conn):
        if not conn.isServerConnection():
            if conn.getUUID() == self.app.primary_master_node.getUUID():
                # If a primary master node timeouts, I cannot continue.
                logging.critical('the primary master node times out')
                raise PrimaryFailure('the primary master node times out')
            else:
                # Otherwise, this connection is to another storage node.
                raise NotImplementedError
        else:
            self.dealWithClientFailure(conn.getUUID())

        StorageEventHandler.timeoutExpired(self, conn)

    def connectionClosed(self, conn):
        if not conn.isServerConnection():
            if conn.getUUID() == self.app.primary_master_node.getUUID():
                # If a primary master node closes, I cannot continue.
                logging.critical('the primary master node is dead')
                raise PrimaryFailure('the primary master node is dead')
            else:
                # Otherwise, this connection is to another storage node.
                raise NotImplementedError
        else:
            self.dealWithClientFailure(conn.getUUID())

        StorageEventHandler.connectionClosed(self, conn)

    def peerBroken(self, conn):
        if not conn.isServerConnection():
            if conn.getUUID() == self.app.primary_master_node.getUUID():
                # If a primary master node gets broken, I cannot continue.
                logging.critical('the primary master node is broken')
                raise PrimaryFailure('the primary master node is broken')
            else:
                # Otherwise, this connection is to another storage node.
                raise NotImplementedError
        else:
            self.dealWithClientFailure(conn.getUUID())

        StorageEventHandler.peerBroken(self, conn)

    def handleRequestNodeIdentification(self, conn, packet, node_type,
                                        uuid, ip_address, port, name):
        if not conn.isServerConnection():
            self.handleUnexpectedPacket(conn, packet)
        else:
            app = self.app
            if name != app.name:
                logging.error('reject an alien cluster')
                p = protocol.protocolError('invalid cluster name')
                conn.answer(p, packet)
                conn.abort()
                return

            addr = (ip_address, port)
            node = app.nm.getNodeByUUID(uuid)
            if node is None:
                if node_type == MASTER_NODE_TYPE:
                    node = app.nm.getNodeByServer(addr)
                    if node is None:
                        node = MasterNode(server = addr, uuid = uuid)
                        app.nm.add(node)
                else:
                    # If I do not know such a node, and it is not even a master
                    # node, simply reject it.
                    logging.error('reject an unknown node %s', dump(uuid))
                    conn.answer(protocol.notReady('unknown node'), packet)
                    conn.abort()
                    return
            else:
                # If this node is broken, reject it.
                if node.getUUID() == uuid:
                    if node.getState() == BROKEN_STATE:
                        p = protocol.brokenNodeDisallowedError('go away')
                        conn.answer(p, packet)
                        conn.abort()
                        return

            # Trust the UUID sent by the peer.
            node.setUUID(uuid)
            conn.setUUID(uuid)

            p = protocol.acceptNodeIdentification(STORAGE_NODE_TYPE, app.uuid, 
                        app.server[0], app.server[1], app.num_partitions, 
                        app.num_replicas, uuid)
            conn.answer(p, packet)

            if node_type == MASTER_NODE_TYPE:
                conn.abort()

    def handleAcceptNodeIdentification(self, conn, packet, node_type,
                                       uuid, ip_address, port,
                                       num_partitions, num_replicas, your_uuid):
        if not conn.isServerConnection():
            raise NotImplementedError
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleAnswerPrimaryMaster(self, conn, packet, primary_uuid,
                                  known_master_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskLastIDs(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskPartitionTable(self, conn, packet, offset_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleSendPartitionTable(self, conn, packet, ptid, row_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleNotifyPartitionChanges(self, conn, packet, ptid, cell_list):
        """This is very similar to Send Partition Table, except that
        the information is only about changes from the previous."""
        if not conn.isServerConnection():
            app = self.app
            nm = app.nm
            pt = app.pt
            if app.ptid >= ptid:
                # Ignore this packet.
                logging.info('ignoring older partition changes')
                return

            # First, change the table on memory.
            app.ptid = ptid
            for offset, uuid, state in cell_list:
                node = nm.getNodeByUUID(uuid)
                if node is None:
                    node = StorageNode(uuid = uuid)
                    if uuid != app.uuid:
                        node.setState(TEMPORARILY_DOWN_STATE)
                    nm.add(node)

                pt.setCell(offset, node, state)

                if uuid == app.uuid:
                    # If this is for myself, this can affect replications.
                    if state == DISCARDED_STATE:
                        app.replicator.removePartition(offset)
                    elif state == OUT_OF_DATE_STATE:
                        app.replicator.addPartition(offset)

            # Then, the database.
            app.dm.changePartitionTable(ptid, cell_list)
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleStartOperation(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleStopOperation(self, conn, packet):
        if not conn.isServerConnection():
            raise OperationFailure('operation stopped')
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleAskUnfinishedTransactions(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskTransactionInformation(self, conn, packet, tid):
        app = self.app
        t = app.dm.getTransaction(tid)

        if t is None:
            p = protocol.tidNotFound('%s does not exist' % dump(tid))
        else:
            p = protocol.answerTransactionInformation(tid, t[1], t[2], t[3], t[0])
        conn.answer(p, packet)

    def handleAskObjectPresent(self, conn, packet, oid, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleDeleteTransaction(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleCommitTransaction(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleLockInformation(self, conn, packet, tid):
        if not conn.isServerConnection():
            app = self.app
            try:
                t = app.transaction_dict[tid]
                object_list = t.getObjectList()
                for o in object_list:
                    app.load_lock_dict[o[0]] = tid

                app.dm.storeTransaction(tid, object_list, t.getTransaction())
            except KeyError:
                pass

            conn.answer(protocol.notifyInformationLocked(tid), packet)
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleUnlockInformation(self, conn, packet, tid):
        if not conn.isServerConnection():
            app = self.app
            try:
                t = app.transaction_dict[tid]
                object_list = t.getObjectList()
                for o in object_list:
                    oid = o[0]
                    del app.load_lock_dict[oid]
                    del app.store_lock_dict[oid]

                app.dm.finishTransaction(tid)
                del app.transaction_dict[tid]

                # Now it may be possible to execute some events.
                app.executeQueuedEvents()
            except KeyError:
                pass
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleAskObject(self, conn, packet, oid, serial, tid):
        app = self.app
        if oid in app.load_lock_dict:
            # Delay the response.
            app.queueEvent(self.handleAskObject, conn, packet, oid,
                           serial, tid)
            return

        if serial == INVALID_SERIAL:
            serial = None
        if tid == INVALID_TID:
            tid = None
        o = app.dm.getObject(oid, serial, tid)
        if o is not None:
            serial, next_serial, compression, checksum, data = o
            if next_serial is None:
                next_serial = INVALID_SERIAL
            logging.debug('oid = %s, serial = %s, next_serial = %s',
                          dump(oid), dump(serial), dump(next_serial))
            p = protocol.answerObject(oid, serial, next_serial,
                           compression, checksum, data)
        else:
            logging.debug('oid = %s not found', dump(oid))
            p = protocol.oidNotFound('%s does not exist' % dump(oid))
        conn.answer(p, packet)

    def handleAskTIDs(self, conn, packet, first, last, partition):
        # This method is complicated, because I must return TIDs only
        # about usable partitions assigned to me.
        if first >= last:
            conn.answer(protocol.protocolError( 'invalid offsets'), packet)
            return

        app = self.app

        if partition == INVALID_PARTITION:
            # Collect all usable partitions for me.
            getCellList = app.pt.getCellList
            partition_list = []
            for offset in xrange(app.num_partitions):
                for cell in getCellList(offset, readable=True):
                    if cell.getUUID() == app.uuid:
                        partition_list.append(offset)
                        break
        else:
            partition_list = [partition]

        tid_list = app.dm.getTIDList(first, last - first,
                                     app.num_partitions, partition_list)
        conn.answer(protocol.answerTIDs(tid_list), packet)

    def handleAskObjectHistory(self, conn, packet, oid, first, last):
        if first >= last:
            conn.answer(protocol.protocolError( 'invalid offsets'), packet)
            return

        app = self.app
        history_list = app.dm.getObjectHistory(oid, first, last - first)
        if history_list is None:
            history_list = []
        p = protocol.answerObjectHistory(oid, history_list)
        conn.answer(p, packet)

    def handleAskStoreTransaction(self, conn, packet, tid, user, desc,
                                  ext, oid_list):
        uuid = conn.getUUID()
        if uuid is None:
            self.handleUnexpectedPacket(conn, packet)
            return

        app = self.app

        t = app.transaction_dict.setdefault(tid, TransactionInformation(uuid))
        t.addTransaction(oid_list, user, desc, ext)
        conn.answer(protocol.answerStoreTransaction(tid), packet)

    def handleAskStoreObject(self, conn, packet, oid, serial,
                             compression, checksum, data, tid):
        uuid = conn.getUUID()
        if uuid is None:
            self.handleUnexpectedPacket(conn, packet)
            return
        # First, check for the locking state.
        app = self.app
        locking_tid = app.store_lock_dict.get(oid)
        if locking_tid is not None:
            if locking_tid < tid:
                # Delay the response.
                app.queueEvent(self.handleAskStoreObject, conn, packet,
                               oid, serial, compression, checksum,
                               data, tid)
            else:
                # If a newer transaction already locks this object,
                # do not try to resolve a conflict, so return immediately.
                logging.info('unresolvable conflict in %s', dump(oid))
                p = protocol.answerStoreObject(1, oid, locking_tid)
                conn.answer(p, packet)
            return

        # Next, check if this is generated from the latest revision.
        history_list = app.dm.getObjectHistory(oid)
        if history_list:
            last_serial = history_list[0][0]
            if last_serial != serial:
                logging.info('resolvable conflict in %s', dump(oid))
                p = protocol.answerStoreObject(1, oid, last_serial)
                conn.answer(p, packet)
                return
        # Now store the object.
        t = app.transaction_dict.setdefault(tid, TransactionInformation(uuid))
        t.addObject(oid, compression, checksum, data)
        p = protocol.answerStoreObject(0, oid, serial)
        conn.answer(p, packet)
        app.store_lock_dict[oid] = tid

    def handleAbortTransaction(self, conn, packet, tid):
        uuid = conn.getUUID()
        if uuid is None:
            self.handleUnexpectedPacket(conn, packet)
            return

        app = self.app
        try:
            t = app.transaction_dict[tid]
            object_list = t.getObjectList()
            for o in object_list:
                oid = o[0]
                try:
                    del app.load_lock_dict[oid]
                except KeyError:
                    pass
                del app.store_lock_dict[oid]

            del app.transaction_dict[tid]

            # Now it may be possible to execute some events.
            app.executeQueuedEvents()
        except KeyError:
            pass

    def handleAnswerLastIDs(self, conn, packet, loid, ltid, lptid):
        if not conn.isServerConnection():
            self.app.replicator.setCriticalTID(packet, ltid)
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleAnswerUnfinishedTransactions(self, conn, packet, tid_list):
        if not conn.isServerConnection():
            self.app.replicator.setUnfinishedTIDList(tid_list)
        else:
            self.handleUnexpectedPacket(conn, packet)

    def handleAskOIDs(self, conn, packet, first, last, partition):
        # This method is complicated, because I must return OIDs only
        # about usable partitions assigned to me.
        if first >= last:
            conn.answer(protocol.protocolError( 'invalid offsets'), packet)
            return

        app = self.app

        if partition == INVALID_PARTITION:
            # Collect all usable partitions for me.
            getCellList = app.pt.getCellList
            partition_list = []
            for offset in xrange(app.num_partitions):
                for cell in getCellList(offset, readable=True):
                    if cell.getUUID() == app.uuid:
                        partition_list.append(offset)
                        break
        else:
            partition_list = [partition]

        oid_list = app.dm.getOIDList(first, last - first,
                                     app.num_partitions, partition_list)
        conn.answer(protocol.answerOIDs(oid_list), packet)
