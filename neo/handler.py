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
from neo.protocol import Packet, ProtocolError
from neo.connection import ServerConnection

from protocol import ERROR, REQUEST_NODE_IDENTIFICATION, ACCEPT_NODE_IDENTIFICATION, \
        PING, PONG, ASK_PRIMARY_MASTER, ANSWER_PRIMARY_MASTER, ANNOUNCE_PRIMARY_MASTER, \
        REELECT_PRIMARY_MASTER, NOTIFY_NODE_INFORMATION, START_OPERATION, \
        STOP_OPERATION, ASK_LAST_IDS, ANSWER_LAST_IDS, ASK_PARTITION_TABLE, \
        ANSWER_PARTITION_TABLE, SEND_PARTITION_TABLE, NOTIFY_PARTITION_CHANGES, \
        ASK_UNFINISHED_TRANSACTIONS, ANSWER_UNFINISHED_TRANSACTIONS, \
        ASK_OBJECT_PRESENT, ANSWER_OBJECT_PRESENT, \
        DELETE_TRANSACTION, COMMIT_TRANSACTION, ASK_NEW_TID, ANSWER_NEW_TID, \
        FINISH_TRANSACTION, NOTIFY_TRANSACTION_FINISHED, LOCK_INFORMATION, \
        NOTIFY_INFORMATION_LOCKED, INVALIDATE_OBJECTS, UNLOCK_INFORMATION, \
        ASK_NEW_OIDS, ANSWER_NEW_OIDS, ASK_STORE_OBJECT, ANSWER_STORE_OBJECT, \
        ABORT_TRANSACTION, ASK_STORE_TRANSACTION, ANSWER_STORE_TRANSACTION, \
        ASK_OBJECT, ANSWER_OBJECT, ASK_TIDS, ANSWER_TIDS, ASK_TRANSACTION_INFORMATION, \
        ANSWER_TRANSACTION_INFORMATION, ASK_OBJECT_HISTORY, ANSWER_OBJECT_HISTORY, \
        ASK_OIDS, ANSWER_OIDS, \
        NOT_READY_CODE, OID_NOT_FOUND_CODE, SERIAL_NOT_FOUND_CODE, TID_NOT_FOUND_CODE, \
        PROTOCOL_ERROR_CODE, TIMEOUT_ERROR_CODE, BROKEN_NODE_DISALLOWED_CODE, \
        INTERNAL_ERROR_CODE

class EventHandler(object):
    """This class handles events."""
    def __init__(self):
        self.initPacketDispatchTable()
        self.initErrorDispatchTable()

    def connectionStarted(self, conn):
        """Called when a connection is started."""
        logging.debug('connection started for %s:%d', *(conn.getAddress()))

    def connectionCompleted(self, conn):
        """Called when a connection is completed."""
        logging.debug('connection completed for %s:%d', *(conn.getAddress()))

    def connectionFailed(self, conn):
        """Called when a connection failed."""
        logging.debug('connection failed for %s:%d', *(conn.getAddress()))

    def connectionAccepted(self, conn, connector, addr):
        """Called when a connection is accepted."""
        logging.debug('connection accepted from %s:%d', *addr)
        new_conn = ServerConnection(conn.getEventManager(), conn.getHandler(),
                                    connector = connector, addr = addr)
        # A request for a node identification should arrive.
        new_conn.expectMessage(timeout = 10, additional_timeout = 0)

    def timeoutExpired(self, conn):
        """Called when a timeout event occurs."""
        logging.debug('timeout expired for %s:%d', *(conn.getAddress()))

    def connectionClosed(self, conn):
        """Called when a connection is closed by the peer."""
        logging.debug('connection closed for %s:%d', *(conn.getAddress()))

    def packetReceived(self, conn, packet):
        """Called when a packet is received."""
        self.dispatch(conn, packet)

    def packetMalformed(self, conn, packet, error_message):
        """Called when a packet is malformed."""
        logging.info('malformed packet %x from %s:%d: %s',
                     packet.getType(), conn.getAddress()[0], 
                     conn.getAddress()[1], error_message)
        conn.send(protocol.protocolError(error_message))
        conn.abort()
        self.peerBroken(conn)

    def peerBroken(self, conn):
        """Called when a peer is broken."""
        logging.error('%s:%d is broken', *(conn.getAddress()))

    def dispatch(self, conn, packet):
        """This is a helper method to handle various packet types."""
        t = packet.getType()
        try:
            method = self.packet_dispatch_table[t]
            args = packet.decode() or ()
            method(conn, packet, *args)
        except (KeyError, ValueError):
            self.handleUnexpectedPacket(conn, packet)
        except ProtocolError, m:
            self.packetMalformed(conn, packet, m[1])

    def handleUnexpectedPacket(self, conn, packet, message = None):
        """Handle an unexpected packet."""
        if message is None:
            message = 'unexpected packet type %s' % packet.getType()
        else:
            message = 'unexpected packet: ' + message
        logging.info('%s', message)
        conn.send(protocol.protocolError(message))
        conn.abort()
        self.peerBroken(conn)

    # Packet handlers.

    def handleError(self, conn, packet, code, message):
        try:
            method = self.error_dispatch_table[code]
            method(conn, packet, message)
        except ValueError:
            self.handleUnexpectedPacket(conn, packet, message)

    def handleRequestNodeIdentification(self, conn, packet, node_type,
                                        uuid, ip_address, port, name):
        self.handleUnexpectedPacket(conn, packet)

    def handleAcceptNodeIdentification(self, conn, packet, node_type,
                                       uuid, ip_address, port,
                                       num_partitions, num_replicas, your_uuid):
        self.handleUnexpectedPacket(conn, packet)

    def handlePing(self, conn, packet):
        logging.info('got a ping packet; am I overloaded?')
        conn.answer(protocol.pong(), packet)

    def handlePong(self, conn, packet):
        pass

    def handleAskPrimaryMaster(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerPrimaryMaster(self, conn, packet, primary_uuid,
                                  known_master_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnnouncePrimaryMaster(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleReelectPrimaryMaster(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleNotifyNodeInformation(self, conn, packet, node_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskLastIDs(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerLastIDs(self, conn, packet, loid, ltid, lptid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskPartitionTable(self, conn, packet, offset_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerPartitionTable(self, conn, packet, ptid, row_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleSendPartitionTable(self, conn, packet, ptid, row_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleNotifyPartitionChanges(self, conn, packet, ptid, cell_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleStartOperation(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleStopOperation(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskUnfinishedTransactions(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerUnfinishedTransactions(self, conn, packet, tid_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskObjectPresent(self, conn, packet, oid, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerObjectPresent(self, conn, packet, oid, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleDeleteTransaction(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleCommitTransaction(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskNewTID(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerNewTID(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskNewOIDs(self, conn, packet):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerNewOIDs(self, conn, packet, oid_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleFinishTransaction(self, conn, packet, oid_list, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleNotifyTransactionFinished(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleLockInformation(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleNotifyInformationLocked(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleInvalidateObjects(self, conn, packet, oid_list, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleUnlockInformation(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskStoreObject(self, conn, packet, oid, serial,
                             compression, checksum, data, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerStoreObject(self, conn, packet, status, oid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAbortTransaction(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskStoreTransaction(self, conn, packet, tid, user, desc,
                                  ext, oid_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerStoreTransaction(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskObject(self, conn, packet, oid, serial, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerObject(self, conn, packet, oid, serial_start,
                           serial_end, compression, checksum, data):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskTIDs(self, conn, packet, first, last, partition):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerTIDs(self, conn, packet, tid_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskTransactionInformation(self, conn, packet, tid):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerTransactionInformation(self, conn, packet, tid, 
                                           user, desc, ext, oid_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskObjectHistory(self, conn, packet, oid, first, last):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerObjectHistory(self, conn, packet, oid, history_list):
        self.handleUnexpectedPacket(conn, packet)

    def handleAskOIDs(self, conn, packet, first, last, partition):
        self.handleUnexpectedPacket(conn, packet)

    def handleAnswerOIDs(self, conn, packet, oid_list):
        self.handleUnexpectedPacket(conn, packet)

    # Error packet handlers.

    handleNotReady = handleUnexpectedPacket
    handleOidNotFound = handleUnexpectedPacket
    handleSerialNotFound = handleUnexpectedPacket
    handleTidNotFound = handleUnexpectedPacket

    def handleProtocolError(self, conn, packet, message):
        raise RuntimeError, 'protocol error: %s' % (message,)

    def handleTimeoutError(self, conn, packet, message):
        raise RuntimeError, 'timeout error: %s' % (message,)

    def handleBrokenNodeDisallowedError(self, conn, packet, message):
        raise RuntimeError, 'broken node disallowed error: %s' % (message,)

    def handleInternalError(self, conn, packet, message):
        self.peerBroken(conn)
        conn.close()

    def initPacketDispatchTable(self):
        d = {}

        d[ERROR] = self.handleError
        d[REQUEST_NODE_IDENTIFICATION] = self.handleRequestNodeIdentification
        d[ACCEPT_NODE_IDENTIFICATION] = self.handleAcceptNodeIdentification
        d[PING] = self.handlePing
        d[PONG] = self.handlePong
        d[ASK_PRIMARY_MASTER] = self.handleAskPrimaryMaster
        d[ANSWER_PRIMARY_MASTER] = self.handleAnswerPrimaryMaster
        d[ANNOUNCE_PRIMARY_MASTER] = self.handleAnnouncePrimaryMaster
        d[REELECT_PRIMARY_MASTER] = self.handleReelectPrimaryMaster
        d[NOTIFY_NODE_INFORMATION] = self.handleNotifyNodeInformation
        d[ASK_LAST_IDS] = self.handleAskLastIDs
        d[ANSWER_LAST_IDS] = self.handleAnswerLastIDs
        d[ASK_PARTITION_TABLE] = self.handleAskPartitionTable
        d[ANSWER_PARTITION_TABLE] = self.handleAnswerPartitionTable
        d[SEND_PARTITION_TABLE] = self.handleSendPartitionTable
        d[NOTIFY_PARTITION_CHANGES] = self.handleNotifyPartitionChanges
        d[START_OPERATION] = self.handleStartOperation
        d[STOP_OPERATION] = self.handleStopOperation
        d[ASK_UNFINISHED_TRANSACTIONS] = self.handleAskUnfinishedTransactions
        d[ANSWER_UNFINISHED_TRANSACTIONS] = self.handleAnswerUnfinishedTransactions
        d[ASK_OBJECT_PRESENT] = self.handleAskObjectPresent
        d[ANSWER_OBJECT_PRESENT] = self.handleAnswerObjectPresent
        d[DELETE_TRANSACTION] = self.handleDeleteTransaction
        d[COMMIT_TRANSACTION] = self.handleCommitTransaction
        d[ASK_NEW_TID] = self.handleAskNewTID
        d[ANSWER_NEW_TID] = self.handleAnswerNewTID
        d[FINISH_TRANSACTION] = self.handleFinishTransaction
        d[NOTIFY_TRANSACTION_FINISHED] = self.handleNotifyTransactionFinished
        d[LOCK_INFORMATION] = self.handleLockInformation
        d[NOTIFY_INFORMATION_LOCKED] = self.handleNotifyInformationLocked
        d[INVALIDATE_OBJECTS] = self.handleInvalidateObjects
        d[UNLOCK_INFORMATION] = self.handleUnlockInformation
        d[ASK_NEW_OIDS] = self.handleAskNewOIDs
        d[ANSWER_NEW_OIDS] = self.handleAnswerNewOIDs
        d[ASK_STORE_OBJECT] = self.handleAskStoreObject
        d[ANSWER_STORE_OBJECT] = self.handleAnswerStoreObject
        d[ABORT_TRANSACTION] = self.handleAbortTransaction
        d[ASK_STORE_TRANSACTION] = self.handleAskStoreTransaction
        d[ANSWER_STORE_TRANSACTION] = self.handleAnswerStoreTransaction
        d[ASK_OBJECT] = self.handleAskObject
        d[ANSWER_OBJECT] = self.handleAnswerObject
        d[ASK_TIDS] = self.handleAskTIDs
        d[ANSWER_TIDS] = self.handleAnswerTIDs
        d[ASK_TRANSACTION_INFORMATION] = self.handleAskTransactionInformation
        d[ANSWER_TRANSACTION_INFORMATION] = self.handleAnswerTransactionInformation
        d[ASK_OBJECT_HISTORY] = self.handleAskObjectHistory
        d[ANSWER_OBJECT_HISTORY] = self.handleAnswerObjectHistory
        d[ASK_OIDS] = self.handleAskOIDs
        d[ANSWER_OIDS] = self.handleAnswerOIDs

        self.packet_dispatch_table = d

    def initErrorDispatchTable(self):
        d = {}

        d[NOT_READY_CODE] = self.handleNotReady
        d[OID_NOT_FOUND_CODE] = self.handleOidNotFound
        d[SERIAL_NOT_FOUND_CODE] = self.handleSerialNotFound
        d[TID_NOT_FOUND_CODE] = self.handleTidNotFound
        d[PROTOCOL_ERROR_CODE] = self.handleProtocolError
        d[TIMEOUT_ERROR_CODE] = self.handleTimeoutError
        d[BROKEN_NODE_DISALLOWED_CODE] = self.handleBrokenNodeDisallowedError
        d[INTERNAL_ERROR_CODE] = self.handleInternalError

        self.error_dispatch_table = d
