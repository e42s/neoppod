#
# Copyright (C) 2009-2010  Nexedi SA
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

import unittest
import threading
from mock import Mock, ReturnValues
from neo.tests import NeoTestBase
from neo import protocol
from neo.pt import PartitionTable
from neo.protocol import UnexpectedPacketError, INVALID_UUID, INVALID_PTID
from neo.protocol import NodeTypes, NodeStates, CellStates, Packets
from neo.client.handlers import BaseHandler
from neo.client.handlers.master import PrimaryBootstrapHandler
from neo.client.handlers.master import PrimaryNotificationsHandler, PrimaryAnswersHandler

MARKER = []


class MasterHandlerTests(NeoTestBase):

    def setUp(self):
        pass


class MasterBootstrapHandlerTests(NeoTestBase):

    def setUp(self):
        self.app = Mock()
        self.handler = PrimaryBootstrapHandler(self.app)

    def test_notReady(self):
        app = Mock({'setNodeNotReady': None})
        dispatcher = self.getDispatcher()
        conn = self.getConnection()
        client_handler = StorageBootstrapHandler(app)
        client_handler.notReady(conn, None)
        self.assertEquals(len(app.mockGetNamedCalls('setNodeNotReady')), 1)

    def test_clientAcceptIdentification(self):
        class App:
            nm = Mock({'getByAddress': None})
            storage_node = None
            pt = None
        app = App()
        dispatcher = self.getDispatcher()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        uuid = self.getNewUUID()
        app.uuid = 'C' * 16
        client_handler.acceptIdentification(conn, NodeTypes.CLIENT,
            uuid, 0, 0, INVALID_UUID)
        self.checkClosed(conn)
        self.assertEquals(app.storage_node, None)
        self.assertEquals(app.pt, None)
        self.assertEquals(app.uuid, 'C' * 16)

    def test_masterAcceptIdentification(self):
        node = Mock({'setUUID': None})
        class FakeLocal:
            from Queue import Queue
            queue = Queue()
        class App:
            nm = Mock({'getByAddress': node})
            storage_node = None
            pt = None
            local_var = FakeLocal()
        app = App()
        dispatcher = self.getDispatcher()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        uuid = self.getNewUUID()
        your_uuid = 'C' * 16
        app.uuid = INVALID_UUID
        client_handler.acceptIdentification(conn, NodeTypes.MASTER,
            uuid, 10, 2, your_uuid)
        self.checkNotClosed(conn)
        self.checkUUIDSet(conn, uuid)
        self.assertEquals(app.storage_node, None)
        self.assertTrue(app.pt is not None)
        self.assertEquals(app.uuid, your_uuid)

    def test_storageAcceptIdentification(self):
        node = Mock({'setUUID': None})
        class App:
            nm = Mock({'getByAddress': node})
            storage_node = None
            pt = None
        app = App()
        dispatcher = self.getDispatcher()
        client_handler = StorageBootstrapHandler(app)
        conn = self.getConnection()
        uuid = self.getNewUUID()
        app.uuid = 'C' * 16
        client_handler.acceptIdentification(conn, NodeTypes.STORAGE,
            uuid, 0, 0, INVALID_UUID)
        self.checkNotClosed(conn)
        self.checkUUIDSet(conn, uuid)
        self.assertEquals(app.pt,  None)
        self.assertEquals(app.uuid, 'C' * 16)

    def test_nonMasterAnswerPrimary(self):
        for node_type in (NodeTypes.CLIENT, NodeTypes.STORAGE):
            node = Mock({'getType': node_type})
            class App:
                nm = Mock({'getByUUID': node, 'getByAddress': None, 'add': None})
                trying_master_node = None
            app = App()
            client_handler = PrimaryBootstrapHandler(app)
            conn = self.getConnection()
            client_handler.answerPrimary(conn, 0, [])
            # Check that nothing happened
            self.assertEqual(len(app.nm.mockGetNamedCalls('getByAddress')), 0)
            self.assertEqual(len(app.nm.mockGetNamedCalls('add')), 0)

    def test_unknownNodeAnswerPrimary(self):
        node = Mock({'getType': NodeTypes.MASTER})
        class App:
            nm = Mock({'getByAddress': None, 'add': None})
            primary_master_node = None
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        test_master_list = [(('127.0.0.1', 10010), self.getNewUUID())]
        client_handler.answerPrimary(conn, INVALID_UUID, test_master_list)
        # Check that yet-unknown master node got added
        getByAddress_call_list = app.nm.mockGetNamedCalls('getByAddress')
        add_call_list = app.nm.mockGetNamedCalls('add')
        self.assertEqual(len(getByAddress_call_list), 1)
        self.assertEqual(len(add_call_list), 1)
        (address, port), test_uuid = test_master_list[0]
        getByAddress_call = getByAddress_call_list[0]
        add_call = add_call_list[0]
        self.assertEquals((address, port), getByAddress_call.getParam(0))
        node_instance = add_call.getParam(0)
        self.assertEquals(test_uuid, node_instance.getUUID())
        # Check that primary master was not updated (it is not known yet,
        # hence INVALID_UUID in call).
        self.assertEquals(app.primary_master_node, None)

    def test_knownNodeUnknownUUIDNodeAnswerPrimary(self):
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': None, 'setUUID': None})
        class App:
            nm = Mock({'getByAddress': node, 'add': None})
            primary_master_node = None
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        test_node_uuid = self.getNewUUID()
        test_master_list = [(('127.0.0.1', 10010), test_node_uuid)]
        client_handler.answerPrimary(conn, INVALID_UUID, test_master_list)
        # Test sanity checks
        getByAddress_call_list = app.nm.mockGetNamedCalls('getByAddress')
        self.assertEqual(len(getByAddress_call_list), 1)
        self.assertEqual(getByAddress_call_list[0].getParam(0), test_master_list[0][0])
        # Check that known master node did not get added
        getByAddress_call_list = app.nm.mockGetNamedCalls('getByAddress')
        add_call_list = app.nm.mockGetNamedCalls('add')
        self.assertEqual(len(getByAddress_call_list), 1)
        self.assertEqual(len(add_call_list), 0)
        # Check that node UUID got updated
        self.checkUUIDSet(node, test_node_uuid)
        # Check that primary master was not updated (it is not known yet,
        # hence INVALID_UUID in call).
        self.assertEquals(app.primary_master_node, None)

    def test_knownNodeKnownUUIDNodeAnswerPrimary(self):
        test_node_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': test_node_uuid, 'setUUID': None})
        class App:
            nm = Mock({'getByAddress': node, 'add': None})
            primary_master_node = None
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        test_master_list = [(('127.0.0.1', 10010), test_node_uuid)]
        client_handler.answerPrimary(conn, INVALID_UUID, test_master_list)
        # Test sanity checks
        getByAddress_call_list = app.nm.mockGetNamedCalls('getByAddress')
        self.assertEqual(len(getByAddress_call_list), 1)
        self.assertEqual(getByAddress_call_list[0].getParam(0), test_master_list[0][0])
        # Check that known master node did not get added
        add_call_list = app.nm.mockGetNamedCalls('add')
        self.assertEqual(len(add_call_list), 0)
        # Check that node UUID was untouched
        setUUIDCalls = node.mockGetNamedCalls('setUUID')
        if len(setUUIDCalls) == 1:
            self.assertEquals(setUUIDCalls[0].getParam(0), test_node_uuid)
        # Check that primary master was not updated (it is not known yet,
        # hence INVALID_UUID in call).
        self.assertEquals(app.primary_master_node, None)

    # TODO: test known node, known but different uuid (not detected in code,
    # desired behaviour unknown)

    def test_alreadyDifferentPrimaryAnswerPrimary(self):
        test_node_uuid = self.getNewUUID()
        test_primary_node_uuid = test_node_uuid
        while test_primary_node_uuid == test_node_uuid:
            test_primary_node_uuid = self.getNewUUID()
        test_primary_master_node = Mock({'getUUID': test_primary_node_uuid})
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': test_node_uuid, 'setUUID': None})
        class App:
            nm = Mock({'getByUUID': node, 'getByAddress': node, 'add': None})
            primary_master_node = test_primary_master_node
            trying_master_node = None
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        # If primary master is already set *and* is not given primary master
        # handle call raises.
        # Check that the call doesn't raise
        client_handler.answerPrimary(conn, test_node_uuid, [])
        # Check that the primary master changed
        self.assertTrue(app.primary_master_node is node)
        # Test sanity checks
        getByUUID_call_list = app.nm.mockGetNamedCalls('getByUUID')
        self.assertEqual(len(getByUUID_call_list), 1)
        self.assertEqual(getByUUID_call_list[0].getParam(0), test_node_uuid)
        getByAddress_call_list = app.nm.mockGetNamedCalls('getByAddress')
        self.assertEqual(len(getByAddress_call_list), 0)

    def test_alreadySamePrimaryAnswerPrimary(self):
        test_node_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': test_node_uuid, 'setUUID': None})
        class App:
            nm = Mock({'getByUUID': node, 'getByAddress': node, 'add': None})
            primary_master_node = node
            trying_master_node = node
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        client_handler.answerPrimary(conn, test_node_uuid, [])
        # Check that primary node is (still) node.
        self.assertTrue(app.primary_master_node is node)

    def test_unknownNewPrimaryAnswerPrimary(self):
        test_node_uuid = self.getNewUUID()
        test_primary_node_uuid = test_node_uuid
        while test_primary_node_uuid == test_node_uuid:
            test_primary_node_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': test_node_uuid, 'setUUID': None})
        class App:
            nm = Mock({'getByUUID': None, 'getByAddress': node, 'add': None})
            primary_master_node = None
            trying_master_node = None
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        client_handler.answerPrimary(conn, test_primary_node_uuid, [])
        # Test sanity checks
        getByUUID_call_list = app.nm.mockGetNamedCalls('getByUUID')
        self.assertEqual(len(getByUUID_call_list), 1)
        self.assertEqual(getByUUID_call_list[0].getParam(0), test_primary_node_uuid)
        # Check that primary node was not updated.
        self.assertTrue(app.primary_master_node is None)

    def test_AnswerPrimary(self):
        test_node_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': test_node_uuid, 'setUUID': None})
        class App:
            nm = Mock({'getByUUID': node, 'getByAddress': node, 'add': None})
            primary_master_node = None
            trying_master_node = None
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = self.getConnection()
        test_master_list = [(('127.0.0.1', 10010), test_node_uuid)]
        client_handler.answerPrimary(conn, test_node_uuid, test_master_list)
        # Test sanity checks
        getByUUID_call_list = app.nm.mockGetNamedCalls('getByUUID')
        self.assertEqual(len(getByUUID_call_list), 1)
        self.assertEqual(getByUUID_call_list[0].getParam(0), test_node_uuid)
        getByAddress_call_list = app.nm.mockGetNamedCalls('getByAddress')
        self.assertEqual(len(getByAddress_call_list), 1)
        self.assertEqual(getByAddress_call_list[0].getParam(0), test_master_list[0][0])
        # Check that primary master was updated to known node
        self.assertTrue(app.primary_master_node is node)



class MasterNotificationsHandlerTests(NeoTestBase):

    def setUp(self):
        self.app = Mock()
        self.dispatcher = Mock()
        self.handler = PrimaryNotificationsHandler(self.app, self.dispatcher)

    def test_StopOperation(self):
        raise NotImplementedError

    def test_InvalidateObjects(self):
        class App:
            def _cache_lock_acquire(self):
                pass

            def _cache_lock_release(self):
                pass

            def registerDB(self, db, limit):
                self.db = db

            def getDB(self):
                return self.db

            mq_cache = Mock({'__delitem__': None})
        app = App()
        dispatcher = self.getDispatcher()
        client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
        conn = self.getConnection()
        test_tid = 1
        test_oid_list = ['\x00\x00\x00\x00\x00\x00\x00\x01', '\x00\x00\x00\x00\x00\x00\x00\x02']
        test_db = Mock({'invalidate': None})
        app.registerDB(test_db, None)
        client_handler.invalidateObjects(conn, test_oid_list[:], test_tid)
        # 'invalidate' is called just once
        db = app.getDB()
        self.assertTrue(db is test_db)
        invalidate_call_list = db.mockGetNamedCalls('invalidate')
        self.assertEquals(len(invalidate_call_list), 1)
        invalidate_call = invalidate_call_list[0]
        invalidate_tid = invalidate_call.getParam(0)
        self.assertEquals(invalidate_tid, test_tid)
        invalidate_oid_dict = invalidate_call.getParam(1)
        self.assertEquals(len(invalidate_oid_dict), len(test_oid_list))
        self.assertEquals(set(invalidate_oid_dict), set(test_oid_list))
        self.assertEquals(set(invalidate_oid_dict.itervalues()), set([test_tid]))
        # '__delitem__' is called once per invalidated object
        delitem_call_list = app.mq_cache.mockGetNamedCalls('__delitem__')
        self.assertEquals(len(delitem_call_list), len(test_oid_list))
        oid_list = [x.getParam(0) for x in delitem_call_list]
        self.assertEquals(set(oid_list), set(test_oid_list))


    def test_newSendPartitionTable(self):
        node = Mock({'getType': NodeTypes.MASTER})
        test_ptid = 0
        class App:
            nm = Mock({'getByUUID': node})
            pt = PartitionTable(1, 1)
        app = App()
        client_handler = PrimaryNotificationsHandler(app, Mock())
        conn = self.getConnection()
        client_handler.sendPartitionTable(conn, test_ptid + 1, [])
        # Check that partition table got cleared and ptid got updated
        self.assertEquals(app.pt.getID(), 1)

    def test_nonMasterNotifyNodeInformation(self):
        for node_type in (NodeTypes.CLIENT, NodeTypes.STORAGE):
            test_master_uuid = self.getNewUUID()
            node = Mock({'getType': node_type})
            class App:
                nm = Mock({'getByUUID': node})
            app = App()
            client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
            conn = self.getConnection(uuid=test_master_uuid)
            client_handler.notifyNodeInformation(conn, ())

    def test_nonIterableParameterRaisesNotifyNodeInformation(self):
        # XXX: this test is here for sanity self-check: it verifies the
        # assumption described in test_nonMasterNotifyNodeInformation
        # by making a valid call with a non-iterable parameter given as
        # node_list value.
        test_master_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER})
        class App:
            nm = Mock({'getByUUID': node})
        app = App()
        client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
        conn = self.getConnection(uuid=test_master_uuid)
        self.assertRaises(TypeError, client_handler.notifyNodeInformation,
            conn, None)

    def _testNotifyNodeInformation(self, test_node, getByAddress=None, getByUUID=MARKER):
        invalid_uid_test_node = (test_node[0], (test_node[1][0],
                    test_node[1][1] + 1), INVALID_UUID, test_node[3])
        test_node_list = [test_node, invalid_uid_test_node]
        test_master_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER})
        if getByUUID is not MARKER:
            getByUUID = ReturnValues(node, getByUUID)
        class App:
            nm = Mock({'getByUUID': getByUUID,
                       'getByAddress': getByAddress,
                       'add': None,
                       'remove': None})
        app = App()
        dispatcher = self.getDispatcher()
        client_handler = PrimaryNotificationsHandler(app, dispatcher)
        conn = self.getConnection(uuid=test_master_uuid)
        client_handler.notifyNodeInformation(conn, test_node_list)
        # Return nm so caller can check handler actions.
        return app.nm

    def test_unknownMasterNotifyNodeInformation(self):
        # first notify unknown master nodes
        uuid = self.getNewUUID()
        test_node = (NodeTypes.MASTER, ('127.0.0.1', 10010), uuid,
                     NodeStates.RUNNING)
        nm = self._testNotifyNodeInformation(test_node, getByUUID=None)
        # Check that two nodes got added (second is with INVALID_UUID)
        update_call_list = nm.mockGetNamedCalls('update')
        self.assertEqual(len(update_call_list), 1)
        updated_node_list = update_call_list[0].getParam(0)
        self.assertEquals(len(updated_node_list), 2)

    def test_knownMasterNotifyNodeInformation(self):
        node = Mock({})
        uuid = self.getNewUUID()
        test_node = (NodeTypes.MASTER, ('127.0.0.1', 10010), uuid,
                     NodeStates.RUNNING)
        nm = self._testNotifyNodeInformation(test_node, getByAddress=node,
                getByUUID=node)
        # Check that node got replaced
        update_call_list = nm.mockGetNamedCalls('update')
        self.assertEquals(len(update_call_list), 1)

    def test_unknownStorageNotifyNodeInformation(self):
        test_node = (NodeTypes.STORAGE, ('127.0.0.1', 10010), self.getNewUUID(),
                     NodeStates.RUNNING)
        nm = self._testNotifyNodeInformation(test_node, getByUUID=None)
        # Check that node got added
        update_call_list = nm.mockGetNamedCalls('update')
        self.assertEqual(len(update_call_list), 1)
        updateed_node = update_call_list[0].getParam(0)
        # XXX: this test does not check that node state got updated.
        # This is because there would be no way to tell the difference between
        # an updated state and default state if they are the same value (we
        # don't control node class/instance here)
        # Likewise for server address and node uuid.

    def test_knownStorageNotifyNodeInformation(self):
        node = Mock({'setState': None, 'setAddress': None})
        test_node = (NodeTypes.STORAGE, ('127.0.0.1', 10010), self.getNewUUID(),
                     NodeStates.RUNNING)
        nm = self._testNotifyNodeInformation(test_node, getByUUID=node)
        # Check that node got replaced
        update_call_list = nm.mockGetNamedCalls('update')
        self.assertEquals(len(update_call_list), 1)

    def test_initialNotifyPartitionChanges(self):
        class App:
            nm = None
            pt = None
            ptid = INVALID_PTID
        app = App()
        client_handler = PrimaryBootstrapHandler(app)
        conn = Mock({'getUUID': None})
        self._testHandleUnexpectedPacketCalledWithMedhod(
            client_handler.notifyPartitionChanges,
            args=(conn, None, None, None))

    def test_nonMasterNotifyPartitionChanges(self):
        for node_type in (NodeTypes.CLIENT, NodeTypes.STORAGE):
            test_master_uuid = self.getNewUUID()
            node = Mock({'getType': node_type, 'getUUID': test_master_uuid})
            class App:
                nm = Mock({'getByUUID': node})
                pt = Mock()
                ptid = INVALID_PTID
                primary_master_node = node
            app = App()
            client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
            conn = self.getConnection(uuid=test_master_uuid)
            client_handler.notifyPartitionChanges(conn, 0, [])
            # Check that nothing happened
            self.assertEquals(len(app.pt.mockGetNamedCalls('setCell')), 0)
            self.assertEquals(len(app.pt.mockGetNamedCalls('removeCell')), 0)

    def test_noPrimaryNotifyPartitionChanges(self):
        node = Mock({'getType': NodeTypes.MASTER})
        class App:
            nm = Mock({'getByUUID': node})
            pt = Mock()
            ptid = INVALID_PTID
            primary_master_node = None
        app = App()
        client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
        conn = self.getConnection()
        client_handler.notifyPartitionChanges(conn, 0, [])
        # Check that nothing happened
        self.assertEquals(len(app.pt.mockGetNamedCalls('setCell')), 0)
        self.assertEquals(len(app.pt.mockGetNamedCalls('removeCell')), 0)

    def test_nonPrimaryNotifyPartitionChanges(self):
        test_master_uuid = self.getNewUUID()
        test_sender_uuid = test_master_uuid
        while test_sender_uuid == test_master_uuid:
            test_sender_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER})
        test_master_node = Mock({'getUUID': test_master_uuid})
        class App:
            nm = Mock({'getByUUID': node})
            pt = Mock()
            ptid = INVALID_PTID
            primary_master_node = test_master_node
        app = App()
        client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
        conn = self.getConnection(uuid=test_sender_uuid)
        client_handler.notifyPartitionChanges(conn, 0, [])
        # Check that nothing happened
        self.assertEquals(len(app.pt.mockGetNamedCalls('setCell')), 0)
        self.assertEquals(len(app.pt.mockGetNamedCalls('removeCell')), 0)

    def test_ignoreOutdatedPTIDNotifyPartitionChanges(self):
        test_master_uuid = self.getNewUUID()
        node = Mock({'getType': NodeTypes.MASTER, 'getUUID': test_master_uuid})
        test_ptid = 1
        class App:
            nm = Mock({'getByUUID': node})
            pt = Mock()
            primary_master_node = node
            ptid = test_ptid
        app = App()
        client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
        conn = self.getConnection(uuid=test_master_uuid)
        client_handler.notifyPartitionChanges(conn, test_ptid, [])
        # Check that nothing happened
        self.assertEquals(len(app.pt.mockGetNamedCalls('setCell')), 0)
        self.assertEquals(len(app.pt.mockGetNamedCalls('removeCell')), 0)
        self.assertEquals(app.ptid, test_ptid)

    # TODO: confirm condition under which an unknown node should be added with a TEMPORARILY_DOWN (implementation is unclear)

    def test_knownNodeNotifyPartitionChanges(self):
        test_ptid = 1
        uuid1, uuid2 = self.getNewUUID(), self.getNewUUID()
        uuid3, uuid4 = self.getNewUUID(), self.getNewUUID()
        test_node = Mock({'getType': NodeTypes.MASTER, 'getUUID': uuid1})
        class App:
            nm = Mock({'getByUUID': ReturnValues(test_node, None, None, None), 'add': None})
            pt = Mock({'setCell': None})
            primary_master_node = test_node
            ptid = test_ptid
            uuid = uuid4
        app = App()
        client_handler = PrimaryNotificationsHandler(app, self.getDispatcher())
        conn = self.getConnection(uuid=uuid1)
        test_cell_list = [
            (0, uuid1, CellStates.UP_TO_DATE),
            (0, uuid2, CellStates.DISCARDED),
            (0, uuid3, CellStates.FEEDING),
            (0, uuid4, CellStates.UP_TO_DATE),
        ]
        client_handler.notifyPartitionChanges(conn, None, test_ptid + 1, test_cell_list)
        # Check that the three last node got added
        calls = app.nm.mockGetNamedCalls('add')
        self.assertEquals(len(calls), 3)
        self.assertEquals(calls[0].getParam(0).getUUID(), uuid2)
        self.assertEquals(calls[1].getParam(0).getUUID(), uuid3)
        self.assertEquals(calls[2].getParam(0).getUUID(), uuid4)
        self.assertEquals(calls[0].getParam(0).getState(), NodeStates.TEMPORARILY_DOWN)
        self.assertEquals(calls[1].getParam(0).getState(), NodeStates.TEMPORARILY_DOWN)
        # and the others are updated
        self.assertEqual(app.ptid, test_ptid + 1)
        calls = app.pt.mockGetNamedCalls('setCell')
        self.assertEqual(len(calls), 4)
        self.assertEquals(calls[0].getParam(1).getUUID(), uuid1)
        self.assertEquals(calls[1].getParam(1).getUUID(), uuid2)
        self.assertEquals(calls[2].getParam(1).getUUID(), uuid3)
        self.assertEquals(calls[3].getParam(1).getUUID(), uuid4)


class MasterAnswersHandlerTests(NeoTestBase):

    def setUp(self):
        self.app = Mock()
        self.handler = PrimaryAnswersHandler(self.app)

    def test_AnswerBeginTransaction(self):
        app = Mock({'setTID': None})
        dispatcher = self.getDispatcher()
        client_handler = PrimaryAnswersHandler(app)
        conn = self.getConnection()
        test_tid = 1
        client_handler.answerBeginTransaction(conn, test_tid)
        setTID_call_list = app.mockGetNamedCalls('setTID')
        self.assertEquals(len(setTID_call_list), 1)
        self.assertEquals(setTID_call_list[0].getParam(0), test_tid)

    def test_AnswerTransactionFinished(self):
        test_tid = 1
        app = Mock({'getTID': test_tid, 'setTransactionFinished': None})
        dispatcher = self.getDispatcher()
        client_handler = PrimaryAnswersHandler(app)
        conn = self.getConnection()
        client_handler.answerTransactionFinished(conn, test_tid)
        self.assertEquals(len(app.mockGetNamedCalls('setTransactionFinished')), 1)
        # TODO: decide what to do when non-current transaction is notified as finished, and test that behaviour

    def test_AnswerNewOIDs(self):
        class App:
            new_oid_list = []
        app = App()
        dispatcher = self.getDispatcher()
        client_handler = PrimaryAnswersHandler(app)
        conn = self.getConnection()
        test_oid_list = ['\x00\x00\x00\x00\x00\x00\x00\x01', '\x00\x00\x00\x00\x00\x00\x00\x02']
        client_handler.answerNewOIDs(conn, test_oid_list[:])
        self.assertEquals(set(app.new_oid_list), set(test_oid_list))



class _(object):

    def getConnection(self, uuid=None, port=10010, next_id=None, ip='127.0.0.1'):
        if uuid is None:
            uuid = self.getNewUUID()
        return Mock({'_addPacket': None,
                     'getUUID': uuid,
                     'getAddress': (ip, port),
                     'getNextId': next_id,
                     'getPeerId': 0,
                     'lock': None,
                     'unlock': None})

    def getDispatcher(self, queue=None):
        return Mock({'getQueue': queue, 'connectToPrimaryNode': None})

    def buildHandler(self, handler_class, app, dispatcher):
        # some handlers do not accept the second argument
        try:
            return handler_class(app, dispatcher)
        except TypeError:
            return handler_class(app)

    def test_ping(self):
        """
        Simplest test: check that a PING packet is answered by a PONG
        packet.
        """
        dispatcher = self.getDispatcher()
        client_handler = BaseHandler(None, dispatcher)
        conn = self.getConnection()
        packet = protocol.Ping()
        client_handler.packetReceived(conn, packet)
        self.checkAnswerPacket(conn, protocol.PONG)

    def _testInitialMasterWithMethod(self, method):
        class App:
            primary_master_node = None
            trying_master_node = 1
        app = App()
        method(self.getDispatcher(), app, PrimaryBootstrapHandler)
        self.assertEqual(app.primary_master_node, None)

    def _testMasterWithMethod(self, method, handler_class):
        uuid = self.getNewUUID()
        app = Mock({'connectToPrimaryNode': None})
        app.primary_master_node = Mock({'getUUID': uuid})
        app.master_conn = Mock({'close': None, 'getUUID': uuid, 'getAddress': ('127.0.0.1', 10000)})
        dispatcher = self.getDispatcher()
        method(dispatcher, app, handler_class, uuid=uuid, conn=app.master_conn)
        # XXX: should connection closure be tested ? It's not implemented in all cases
        #self.assertEquals(len(App.master_conn.mockGetNamedCalls('close')), 1)
        #self.assertEquals(app.master_conn, None)
        #self.assertEquals(app.primary_master_node, None)


if __name__ == '__main__':
    unittest.main()
