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

from neo import logging

from neo import protocol
from neo.master.handlers import MasterHandler
from neo.protocol import RUNNING_STATE, TEMPORARILY_DOWN_STATE, DOWN_STATE, \
        HIDDEN_STATE, PENDING_STATE, RUNNING_CLUSTER_STATE
from neo.util import dump

class AdministrationHandler(MasterHandler):
    """This class deals with messages from the admin node only"""

    def connectionLost(self, conn, new_state):
        node = self.app.nm.getNodeByUUID(conn.getUUID())
        self.app.nm.remove(node)

    def handleAskPrimaryMaster(self, conn, packet):
        app = self.app
        # I'm the primary
        conn.answer(protocol.answerPrimaryMaster(app.uuid, []), packet.getId())

    def handleSetClusterState(self, conn, packet, state):
        self.app.changeClusterState(state)
        p = protocol.noError('cluster state changed')
        conn.answer(p, packet.getId())
        if state == protocol.STOPPING_CLUSTER_STATE:
            self.app.cluster_state = state
            self.app.shutdown()

    def handleSetNodeState(self, conn, packet, uuid, state, modify_partition_table):
        logging.info("set node state for %s-%s : %s" % (dump(uuid), state, modify_partition_table))
        app = self.app
        node = app.nm.getNodeByUUID(uuid)
        if node is None:
            raise protocol.ProtocolError('unknown node')

        if uuid == app.uuid:
            node.setState(state)
            # get message for self
            if state != RUNNING_STATE:
                p = protocol.noError('node state changed')
                conn.answer(p, packet.getId())
                app.shutdown()

        if node.getState() == state:
            # no change, just notify admin node
            p = protocol.noError('node state changed')
            conn.answer(p, packet.getId())
            return

        if state == protocol.RUNNING_STATE:
            # first make sure to have a connection to the node
            node_conn = None
            for node_conn in app.em.getConnectionList():
                if node_conn.getUUID() == node.getUUID():
                    break
            else:
                # no connection to the node
                raise protocol.ProtocolError('no connection to the node')

        elif state == protocol.DOWN_STATE and node.isStorage():
            # modify the partition table if required
            cell_list = []
            if modify_partition_table:
                # remove from pt
                cell_list = app.pt.dropNode(node)
            else:
                # outdate node in partition table
                cell_list = app.pt.outdate()
            if len(cell_list) != 0:
                ptid = app.pt.setNextID()
                app.broadcastPartitionChanges(ptid, cell_list)

        # /!\ send the node information *after* the partition table change
        node.setState(state)
        p = protocol.noError('state changed')
        conn.answer(p, packet.getId())
        app.broadcastNodeInformation(node)

    def handleAddPendingNodes(self, conn, packet, uuid_list):
        uuids = ', '.join([dump(uuid) for uuid in uuid_list])
        logging.debug('Add nodes %s' % uuids)
        app, nm, em, pt = self.app, self.app.nm, self.app.em, self.app.pt
        cell_list = []
        uuid_set = set()
        # take all pending nodes
        for node in nm.getStorageNodeList():
            if node.getState() == PENDING_STATE:
                uuid_set.add(node.getUUID())
        # keep only selected nodes
        if uuid_list:
            uuid_set = uuid_set.intersection(set(uuid_list))
        # nothing to do
        if not uuid_set:
            logging.warning('No nodes added')
            p = protocol.noError('no nodes added')
            conn.answer(p, packet.getId())
            return
        uuids = ', '.join([dump(uuid) for uuid in uuid_set])
        logging.info('Adding nodes %s' % uuids)
        # switch nodes to running state
        for uuid in uuid_set:
            node = nm.getNodeByUUID(uuid)
            new_cells = pt.addNode(node)
            cell_list.extend(new_cells)
            node.setState(RUNNING_STATE)
            app.broadcastNodeInformation(node)
        # start nodes
        for s_conn in em.getConnectionList():
            if s_conn.getUUID() in uuid_set:
                s_conn.notify(protocol.notifyLastOID(app.loid))
                s_conn.notify(protocol.startOperation())
        # broadcast the new partition table
        app.broadcastPartitionChanges(app.pt.setNextID(), cell_list)
        p = protocol.noError('node added')
        conn.answer(p, packet.getId())
