#
# Copyright (C) 2009  Nexedi SA
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

import os
import unittest
from neo import logging
from mock import Mock
from struct import pack, unpack
from neo.tests import NeoTestBase
from neo import protocol
from neo.protocol import Packet, NodeTypes, NodeStates, INVALID_UUID
from neo.master.handlers.election import ClientElectionHandler, ServerElectionHandler
from neo.master.app import Application
from neo.protocol import ERROR, REQUEST_NODE_IDENTIFICATION, ACCEPT_NODE_IDENTIFICATION, \
     PING, PONG, ASK_PRIMARY_MASTER, ANSWER_PRIMARY_MASTER, ANNOUNCE_PRIMARY_MASTER, \
     REELECT_PRIMARY_MASTER, NOTIFY_NODE_INFORMATION, START_OPERATION, \
     STOP_OPERATION, ASK_LAST_IDS, ANSWER_LAST_IDS, ASK_PARTITION_TABLE, \
     ANSWER_PARTITION_TABLE, SEND_PARTITION_TABLE, NOTIFY_PARTITION_CHANGES, \
     ASK_UNFINISHED_TRANSACTIONS, ANSWER_UNFINISHED_TRANSACTIONS, \
     ASK_OBJECT_PRESENT, ANSWER_OBJECT_PRESENT, \
     DELETE_TRANSACTION, COMMIT_TRANSACTION, ASK_BEGIN_TRANSACTION, ANSWER_BEGIN_TRANSACTION, \
     FINISH_TRANSACTION, NOTIFY_TRANSACTION_FINISHED, LOCK_INFORMATION, \
     NOTIFY_INFORMATION_LOCKED, INVALIDATE_OBJECTS, UNLOCK_INFORMATION, \
     ASK_NEW_OIDS, ANSWER_NEW_OIDS, ASK_STORE_OBJECT, ANSWER_STORE_OBJECT, \
     ABORT_TRANSACTION, ASK_STORE_TRANSACTION, ANSWER_STORE_TRANSACTION, \
     ASK_OBJECT, ANSWER_OBJECT, ASK_TIDS, ANSWER_TIDS, ASK_TRANSACTION_INFORMATION, \
     ANSWER_TRANSACTION_INFORMATION, ASK_OBJECT_HISTORY, ANSWER_OBJECT_HISTORY, \
     ASK_OIDS, ANSWER_OIDS
from neo.exception import OperationFailure, ElectionFailure     
from neo.tests import DoNothingConnector
from neo.connection import ClientConnection

# patch connection so that we can register _addPacket messages
# in mock object
def _addPacket(self, packet):
    if self.connector is not None:
        self.connector._addPacket(packet)
def expectMessage(self, packet):
    if self.connector is not None:
        self.connector.expectMessage(packet)


class MasterClientElectionTests(NeoTestBase):

    def setUp(self):
        # create an application object
        config = self.getMasterConfiguration()
        self.app = Application(**config)
        self.app.pt.clear()
        self.app.em = Mock({"getConnectionList" : []})
        self.app.finishing_transaction_dict = {}
        for address in self.app.master_node_list:
            self.app.nm.createMaster(address=address)
        self.election = ClientElectionHandler(self.app)
        self.app.unconnected_master_node_set = set()
        self.app.negotiating_master_node_set = set()
        for node in self.app.nm.getMasterList():
            self.app.unconnected_master_node_set.add(node.getAddress())
            node.setState(NodeStates.RUNNING)
        # define some variable to simulate client and storage node
        self.client_port = 11022
        self.storage_port = 10021
        self.master_port = 10011
        # apply monkey patches
        self._addPacket = ClientConnection._addPacket
        self.expectMessage = ClientConnection.expectMessage
        ClientConnection._addPacket = _addPacket
        ClientConnection.expectMessage = expectMessage
        
    def tearDown(self):
        # restore patched methods
        ClientConnection._addPacket = self._addPacket
        ClientConnection.expectMessage = self.expectMessage
        NeoTestBase.tearDown(self)

    def identifyToMasterNode(self, port=10000, ip='127.0.0.1'):
        uuid = self.getNewUUID()
        address = (ip, port)
        self.app.nm.createMaster(address=address, uuid=uuid,
                state=NodeStates.RUNNING)
        return uuid

    def test_01_connectionStarted(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.election.connectionStarted(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        

    def test_02_connectionCompleted(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.election.connectionCompleted(conn)
        self.checkAskPrimaryMaster(conn)
    

    def test_03_connectionFailed(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.election.connectionStarted(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.RUNNING)
        self.election.connectionFailed(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.TEMPORARILY_DOWN)

    def test_11_handleAskPrimaryMaster(self):
        election = self.election
        uuid = self.identifyToMasterNode(port=self.master_port)
        packet = protocol.askPrimaryMaster()
        conn = Mock({"_addPacket" : None,
                     "getUUID" : uuid,
                     "isServer" : True,
                     "getConnector": Mock(),
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.assertEqual(len(self.app.nm.getMasterList()), 2)
        election.handleAskPrimaryMaster(conn, packet)        
        self.assertEquals(len(conn.mockGetNamedCalls("answer")), 1)
        self.assertEquals(len(conn.mockGetNamedCalls("abort")), 0)
        self.checkAnswerPrimaryMaster(conn)

    def test_09_handleAnswerPrimaryMaster1(self):
        # test with master node and greater uuid
        uuid = self.getNewUUID()
        if uuid < self.app.uuid:
            self.app.uuid, uuid = self.app.uuid, uuid
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        conn.setUUID(uuid)
        p = protocol.askPrimaryMaster()
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.election.handleAnswerPrimaryMaster(conn, p, INVALID_UUID, [])
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(self.app.primary, False)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)


    def test_09_handleAnswerPrimaryMaster2(self):
        # test with master node and lesser uuid
        uuid = self.getNewUUID()
        if uuid > self.app.uuid:
            self.app.uuid, uuid = self.app.uuid, uuid
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        conn.setUUID(uuid)
        p = protocol.askPrimaryMaster()
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.election.handleAnswerPrimaryMaster(conn, p, INVALID_UUID, [])
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(self.app.primary, None)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)


    def test_09_handleAnswerPrimaryMaster3(self):
        # test with master node and given uuid for PMN
        uuid = self.getNewUUID()
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        conn.setUUID(uuid)
        p = protocol.askPrimaryMaster()
        self.app.nm.createMaster(address=("127.0.0.1", self.master_port), uuid=uuid)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 2)
        self.assertEqual(self.app.primary_master_node, None)
        self.election.handleAnswerPrimaryMaster(conn, p, uuid, [])
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 2)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertNotEqual(self.app.primary_master_node, None)
        self.assertEqual(self.app.primary, False)


    def test_09_handleAnswerPrimaryMaster4(self):
        # test with master node and unknown uuid for PMN
        uuid = self.getNewUUID()
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        conn.setUUID(uuid)
        p = protocol.askPrimaryMaster()
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.assertEqual(self.app.primary_master_node, None)
        self.election.handleAnswerPrimaryMaster(conn, p, uuid, [])
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertEqual(self.app.primary_master_node, None)
        self.assertEqual(self.app.primary, None)


    def test_09_handleAnswerPrimaryMaster5(self):
        # test with master node and new uuid for PMN
        uuid = self.getNewUUID()
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        conn.setUUID(uuid)
        p = protocol.askPrimaryMaster()
        self.app.nm.createMaster(address=("127.0.0.1", self.master_port), uuid=uuid)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 2)
        self.assertEqual(self.app.primary_master_node, None)
        master_uuid = self.getNewUUID()
        self.election.handleAnswerPrimaryMaster(conn, p, master_uuid,
                [(("127.0.0.1", self.master_port+1), master_uuid,)])
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.assertEqual(len(self.app.nm.getMasterList()), 3)
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertNotEqual(self.app.primary_master_node, None)
        self.assertEqual(self.app.primary, False)
        # Now tell it's another node which is primary, it must raise 
        self.assertRaises(ElectionFailure, self.election.handleAnswerPrimaryMaster, conn, p, uuid, [])

        

class MasterServerElectionTests(NeoTestBase):

    def setUp(self):
        # create an application object
        config = self.getMasterConfiguration()
        self.app = Application(**config)
        self.app.pt.clear()
        self.app.em = Mock({"getConnectionList" : []})
        self.app.finishing_transaction_dict = {}
        for address in self.app.master_node_list:
            self.app.nm.createMaster(address=address)
        self.election = ServerElectionHandler(self.app)
        self.app.unconnected_master_node_set = set()
        self.app.negotiating_master_node_set = set()
        for node in self.app.nm.getMasterList():
            self.app.unconnected_master_node_set.add(node.getAddress())
            node.setState(NodeStates.RUNNING)
        # define some variable to simulate client and storage node
        self.client_port = 11022
        self.storage_port = 10021
        self.master_port = 10011
        # apply monkey patches
        self._addPacket = ClientConnection._addPacket
        self.expectMessage = ClientConnection.expectMessage
        ClientConnection._addPacket = _addPacket
        ClientConnection.expectMessage = expectMessage
        
    def tearDown(self):
        NeoTestBase.tearDown(self)
        # restore environnement
        ClientConnection._addPacket = self._addPacket
        ClientConnection.expectMessage = self.expectMessage

    def identifyToMasterNode(self, node_type=NodeTypes.STORAGE, ip="127.0.0.1",
                             port=10021):
        """Do first step of identification to MN
        """
        uuid = self.getNewUUID()
        return uuid

        
    def checkCalledAskPrimaryMaster(self, conn, packet_number=0):
        """ Check ask primary master has been send"""
        call = conn.mockGetNamedCalls("_addPacket")[packet_number]
        packet = call.getParam(0)
        self.assertTrue(isinstance(packet, Packet))
        self.assertEquals(packet.getType(),ASK_PRIMARY_MASTER)

    # Tests

    def test_04_connectionClosed(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.RUNNING)
        self.election.connectionClosed(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.TEMPORARILY_DOWN)

    def test_05_timeoutExpired(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodesStates.RUNNING)
        self.election.timeoutExpired(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.TEMPORARILY_DOWN)

    def test_06_peerBroken1(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.RUNNING)
        self.election.peerBroken(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.DOWN)

    def test_06_peerBroken2(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        # Without a client connection
        conn = Mock({"getUUID" : uuid,
                     "isServer" : True,
                     "getAddress" : ("127.0.0.1", self.master_port),})
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        self.election.connectionStarted(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.RUNNING)
        self.election.peerBroken(conn)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.BROKEN)

    def test_07_packetReceived(self):
        uuid = self.identifyToMasterNode(port=self.master_port)
        p = protocol.acceptNodeIdentification(NodeTypes.MASTER, uuid,
                       ("127.0.0.1", self.master_port), 1009, 2, self.app.uuid)

        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        node = self.app.nm.getByAddress(conn.getAddress())
        node.setState(NodeStates.DOWN)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.DOWN)
        self.election.packetReceived(conn, p)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getState(),
                NodeStates.RUNNING)

    def test_08_handleAcceptNodeIdentification1(self):
        # test with storage node, must be rejected
        uuid = self.getNewUUID()
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        args = (NodeTypes.MASTER, uuid, ('127.0.0.1', self.master_port),
                self.app.pt.getPartitions(), self.app.pt.getReplicas(), self.app.uuid)
        p = protocol.acceptNodeIdentification(*args)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getUUID(), None)
        self.assertEqual(conn.getUUID(), None)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.election.handleAcceptNodeIdentification(conn, p, NodeTypes.STORAGE,
                                                     uuid, "127.0.0.1", self.master_port,
                                                     self.app.pt.getPartitions(), 
                                                     self.app.pt.getReplicas(),
                                                     self.app.uuid
                                                     )
        self.assertEqual(conn.getConnector(), None)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        
    def test_08_handleAcceptNodeIdentification2(self):
        # test with bad address, must be rejected
        uuid = self.getNewUUID()
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        args = (NodeTypes.MASTER, uuid, ('127.0.0.1', self.master_port),
                self.app.pt.getPartitions(), self.app.pt.getReplicas(), self.app.uuid)
        p = protocol.acceptNodeIdentification(*args)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getUUID(), None)
        self.assertEqual(conn.getUUID(), None)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)
        self.election.handleAcceptNodeIdentification(conn, p, NodeTypes.STORAGE,
                                                     uuid, ("127.0.0.2", self.master_port),
                                                     self.app.pt.getPartitions(), 
                                                     self.app.pt.getReplicas(),
                                                     self.app.uuid)
        self.assertEqual(conn.getConnector(), None)

    def test_08_handleAcceptNodeIdentification3(self):
        # test with master node, must be ok
        uuid = self.getNewUUID()
        conn = ClientConnection(self.app.em, self.election, addr = ("127.0.0.1", self.master_port),
                                connector_handler = DoNothingConnector)
        args = (NodeTypes.MASTER, uuid, ('127.0.0.1', self.master_port),
                self.app.pt.getPartitions(), self.app.pt.getReplicas(), self.app.uuid)
        p = protocol.acceptNodeIdentification(*args)
        self.assertEqual(len(self.app.unconnected_master_node_set), 0)
        self.assertEqual(len(self.app.negotiating_master_node_set), 1)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getUUID(), None)
        self.assertEqual(conn.getUUID(), None)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),1)

        self.election.handleAcceptNodeIdentification(conn, p, NodeTypes.MASTER,
                                                     uuid, ("127.0.0.1", self.master_port),
                                                     self.app.pt.getPartitions(), 
                                                     self.app.pt.getReplicas(),
                                                     self.app.uuid)
        self.assertEqual(self.app.nm.getByAddress(conn.getAddress()).getUUID(), uuid)
        self.assertEqual(conn.getUUID(), uuid)
        self.assertEqual(len(conn.getConnector().mockGetNamedCalls("_addPacket")),2)
        self.checkCalledAskPrimaryMaster(conn.getConnector(), 1)
        

    def test_10_handleRequestNodeIdentification(self):
        election = self.election
        uuid = self.getNewUUID()
        args = (NodeTypes.MASTER, uuid, ('127.0.0.1', self.storage_port), 
                'INVALID_NAME')
        packet = protocol.requestNodeIdentification(*args)
        # test alien cluster
        conn = Mock({"_addPacket" : None, "abort" : None,
                     "isServer" : True})
        self.checkProtocolErrorRaised(
                election.handleRequestNodeIdentification,
                conn,
                packet=packet,
                node_type=NodeTypes.MASTER,
                uuid=uuid,
                address=('127.0.0.1', self.storage_port),
                name="INVALID_NAME",)
        # test connection of a storage node
        conn = Mock({"_addPacket" : None, "abort" : None, "expectMessage" : None,
                    "isServer" : True})
        self.checkNotReadyErrorRaised(
                election.handleRequestNodeIdentification,
                conn,
                packet=packet,
                node_type=NodeTypes.STORAGE,
                uuid=uuid,
                address=('127.0.0.1', self.storage_port),
                name=self.app.name,)

        # known node
        conn = Mock({"_addPacket" : None, "abort" : None, "expectMessage" : None,
                    "isServer" : True})
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        node = self.app.nm.getMasterList()[0]
        self.assertEqual(node.getUUID(), None)
        self.assertEqual(node.getState(), NodeStates.RUNNING)
        election.handleRequestNodeIdentification(conn,
                                                packet=packet,
                                                node_type=NodeTypes.MASTER,
                                                uuid=uuid,
                                                address=('127.0.0.1', self.master_port),
                                                name=self.app.name,)
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.assertEqual(node.getUUID(), uuid)
        self.assertEqual(node.getState(), NodeStates.RUNNING)
        self.checkAcceptNodeIdentification(conn, answered_packet=packet)
        # unknown node
        conn = Mock({"_addPacket" : None, "abort" : None, "expectMessage" : None,
                    "isServer" : True})
        new_uuid = self.getNewUUID()
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.assertEqual(len(self.app.unconnected_master_node_set), 1)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        election.handleRequestNodeIdentification(conn,
                                                packet=packet,
                                                node_type=NodeTypes.MASTER,
                                                uuid=new_uuid,
                                                address=('127.0.0.1',
                                                    self.master_port+1),
                                                name=self.app.name,)
        self.assertEqual(len(self.app.nm.getMasterList()), 2)
        self.checkAcceptNodeIdentification(conn, answered_packet=packet)
        self.assertEqual(len(self.app.unconnected_master_node_set), 2)
        self.assertEqual(len(self.app.negotiating_master_node_set), 0)
        # broken node
        conn = Mock({"_addPacket" : None, "abort" : None, "expectMessage" : None,
                    "isServer" : True})
        node = self.app.nm.getByAddress(("127.0.0.1", self.master_port+1))
        self.assertEqual(node.getUUID(), new_uuid)
        self.assertEqual(node.getState(), NodeStates.RUNNING)
        node.setState(NodeStates.BROKEN)
        self.assertEqual(node.getState(), NodeStates.BROKEN)
        self.checkBrokenNodeDisallowedErrorRaised(
                election.handleRequestNodeIdentification,
                conn,
                packet=packet,
                node_type=NodeTypes.MASTER,
                uuid=new_uuid,
                ip_address='127.0.0.1',
                port=self.master_port+1,
                name=self.app.name,)        


    def test_12_handleAnnouncePrimaryMaster(self):
        election = self.election
        uuid = self.identifyToMasterNode(port=self.master_port)
        packet = Packet(msg_type=ANNOUNCE_PRIMARY_MASTER)
        # No uuid
        conn = Mock({"_addPacket" : None,
                     "getUUID" : None,
                     "isServer" : True,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.assertEqual(len(self.app.nm.getMasterList()), 1)
        self.checkIdenficationRequired(election.handleAnnouncePrimaryMaster, conn, packet)
        # announce
        conn = Mock({"_addPacket" : None,
                     "getUUID" : uuid,
                     "isServer" : True,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.assertEqual(self.app.primary, None)
        self.assertEqual(self.app.primary_master_node, None)
        election.handleAnnouncePrimaryMaster(conn, packet)        
        self.assertEqual(self.app.primary, False)
        self.assertNotEqual(self.app.primary_master_node, None)
        # set current as primary, and announce another, must raise
        conn = Mock({"_addPacket" : None,
                     "getUUID" : uuid,
                     "isServer" : True,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.app.primary = True
        self.assertEqual(self.app.primary, True)
        self.assertRaises(ElectionFailure, election.handleAnnouncePrimaryMaster, conn, packet)        
        

    def test_13_handleReelectPrimaryMaster(self):
        election = self.election
        uuid = self.identifyToMasterNode(port=self.master_port)
        packet = protocol.askPrimaryMaster()
        # No uuid
        conn = Mock({"_addPacket" : None,
                     "getUUID" : None,
                     "isServer" : True,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        self.assertRaises(ElectionFailure, election.handleReelectPrimaryMaster, conn, packet)

    def test_14_handleNotifyNodeInformation(self):
        election = self.election
        uuid = self.identifyToMasterNode(port=self.master_port)
        packet = Packet(msg_type=NOTIFY_NODE_INFORMATION)
        # do not answer if no uuid
        conn = Mock({"getUUID" : None,
                     "getAddress" : ("127.0.0.1", self.master_port)})
        node_list = []
        self.checkIdenficationRequired(election.handleNotifyNodeInformation, conn, packet, node_list)
        # tell the master node about itself, must do nothing
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})                
        node_list = [(NodeTypes.MASTER, ('127.0.0.1', self.master_port - 1),
            self.app.uuid, NodeStates.DOWN),]
        node = self.app.nm.getByAddress(("127.0.0.1", self.master_port-1))
        self.assertEqual(node, None)
        election.handleNotifyNodeInformation(conn, packet, node_list)
        node = self.app.nm.getByAddress(("127.0.0.1", self.master_port-1))
        self.assertEqual(node, None)
        # tell about a storage node, do nothing
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})                
        node_list = [(NodeTypes.STORAGE, ('127.0.0.1', self.master_port - 1),
            self.getNewUUID(), NodeStates.DOWN),]
        self.assertEqual(len(self.app.nm.getStorageList()), 0)
        election.handleNotifyNodeInformation(conn, packet, node_list)
        self.assertEqual(len(self.app.nm.getStorageList()), 0)
        # tell about a client node, do nothing
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})                
        node_list = [(NodeTypes.CLIENT, ('127.0.0.1', self.master_port - 1),
            self.getNewUUID(), NodeStates.DOWN),]
        self.assertEqual(len(self.app.nm.getNodeList()), 0)
        election.handleNotifyNodeInformation(conn, packet, node_list)
        self.assertEqual(len(self.app.nm.getNodeList()), 0)
        # tell about another master node
        conn = Mock({"getUUID" : uuid,
                     "getAddress" : ("127.0.0.1", self.master_port)})                
        node_list = [(NodeTypes.MASTER, ('127.0.0.1', self.master_port + 1),
            self.getNewUUID(), NodeStates.RUNNING),]
        node = self.app.nm.getByAddress(("127.0.0.1", self.master_port+1))
        self.assertEqual(node, None)
        election.handleNotifyNodeInformation(conn, packet, node_list)
        node = self.app.nm.getByAddress(("127.0.0.1", self.master_port+1))
        self.assertNotEqual(node, None)
        self.assertEqual(node.getAddress(), ("127.0.0.1", self.master_port+1))
        self.assertEqual(node.getState(), NodeStates.RUNNING)
        # tell that node is down
        node_list = [(NodeTypes.MASTER, '127.0.0.1', self.master_port + 1,
            self.getNewUUID(), NodeStates.DOWN),]
        election.handleNotifyNodeInformation(conn, packet, node_list)
        node = self.app.nm.getByAddress(("127.0.0.1", self.master_port+1))
        self.assertNotEqual(node, None)
        self.assertEqual(node.getAddress(), ("127.0.0.1", self.master_port+1))
        self.assertEqual(node.getState(), NodeStates.DOWN)

    
if __name__ == '__main__':
    unittest.main()

