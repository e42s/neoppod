##############################################################################
#
# Copyright (c) 2011 Nexedi SARL and Contributors. All Rights Reserved.
#                    Julien Muchembled <jm@nexedi.com>
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsibility of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# guarantees and support are strongly advised to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
##############################################################################

from neo.lib.exception import PrimaryFailure
from neo.lib.handler import EventHandler
from neo.lib.protocol import CellStates

class BackupHandler(EventHandler):
    """Handler dedicated to upstream master during BACKINGUP state"""

    def connectionLost(self, conn, new_state):
        if self.app.app.listening_conn: # if running
            raise PrimaryFailure('connection lost')

    def answerPartitionTable(self, conn, ptid, row_list):
        self.app.pt.load(ptid, row_list, self.app.nm)

    def notifyPartitionChanges(self, conn, ptid, cell_list):
        self.app.pt.update(ptid, cell_list, self.app.nm)

    def answerNodeInformation(self, conn):
        pass

    def notifyNodeInformation(self, conn, node_list):
        self.app.nm.update(node_list)

    def answerLastTransaction(self, conn, tid):
        app = self.app
        app.invalidatePartitions(tid, set(xrange(app.pt.getPartitions())))

    def invalidateObjects(self, conn, tid, oid_list):
        app = self.app
        getPartition = app.app.pt.getPartition
        partition_set = set(map(getPartition, oid_list))
        partition_set.add(getPartition(tid))
        app.invalidatePartitions(tid, partition_set)