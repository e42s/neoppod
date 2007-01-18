import logging
import MySQLdb
import os
from time import time
from struct import pack, unpack

from neo.config import ConfigurationManager
from neo.protocol import Packet, ProtocolError, \
        RUNNING_STATE, TEMPORARILY_DOWN_STATE, DOWN_STATE, BROKEN_STATE, \
        INVALID_UUID, INVALID_OID, INVALID_TID, INVALID_PTID
from neo.node import NodeManager, MasterNode, StorageNode, ClientNode
from neo.event import EventManager
from neo.storage.mysqldb import MySQLDatabaseManager
from neo.util import dump
from neo.connection import ListeningConnection, ClientConnection, ServerConnection
from neo.exception import OperationFailure, PrimaryFailure
from neo.pt import PartitionTable
from neo.storage.bootstrap import BoostrapEventHandler
from neo.storage.verification import VerificationEventHandler
from neo.storage.operation import OperationEventHandler

class Application(object):
    """The storage node application."""

    def __init__(self, file, section, reset = False):
        config = ConfigurationManager(file, section)

        self.num_partitions = config.getPartitions()
        self.name = config.getName()
        logging.debug('the number of replicas is %d, the number of partitions is %d, the name is %s',
                      self.num_replicas, self.num_partitions, self.name)

        self.server = config.getServer()
        logging.debug('IP address is %s, port is %d', *(self.server))

        self.master_node_list = config.getMasterNodeList()
        logging.debug('master nodes are %s', self.master_node_list)

        # Internal attributes.
        self.em = EventManager()
        self.nm = NodeManager()
        self.dm = MySQLDatabaseManager(database = config.getDatabase(), 
                                       user = config.getUser(), 
                                       password = config.getPassword())
        self.pt = PartitionTable(self.num_partitions, 0)

        self.primary_master_node = None

        self.dm.setup(reset)
        self.loadConfiguration()
        self.loadPartitionTable()

    def loadConfiguration(self):
        """Load persistent configuration data from the database.
        If data is not present, generate it."""
        dm = self.dm

        self.uuid = dm.getUUID()
        if self.uuid is None:
            # XXX Generate an UUID for self. For now, just use a random string.
            # Avoid an invalid UUID.
            while 1:
                uuid = os.urandom(16)
                if uuid != INVALID_UUID:
                    break
            self.uuid = uuid
            dm.setUUID(uuid)

        num_partitions = dm.getNumPartitions()
        if num_partitions is None:
            dm.setNumPartitions(self.num_partitions)
        elif num_partitions != self.num_partitions:
            raise RuntimeError('partitions do not match with the database')

        name = dm.getName()
        if name is None:
            dm.setName(self.name)
        elif name != self.name:
            raise RuntimeError('name does not match with the database')

        ptid = dm.getPTID()
        if ptid is None:
            self.ptid = INVALID_PTID
            dm.setPTID(self.ptid)
        else:
            self.ptid = ptid

    def loadPartitionTable(self):
        """Load a partition table from the database."""
        nm = self.nm
        pt = self.pt
        for offset, uuid, state in self.dm.getPartitionTable():
            node = nm.getNodeByUUID(uuid)
            if node is None:
                node = StorageNode(uuid = uuid)
                if uuid != self.uiid:
                    # If this node is not self, assume that it is temporarily
                    # down at the moment. This state will change once every
                    # node starts to connect to a primary master node.
                    node.setState(TEMPORARILY_DOWN_STATE)
                nm.add(node)

            pt.setCell(offset, node, state)

    def run(self):
        """Make sure that the status is sane and start a loop."""
        if self.num_partitions <= 0:
            raise RuntimeError, 'partitions must be more than zero'
        if len(self.name) == 0:
            raise RuntimeError, 'cluster name must be non-empty'

        for server in self.master_node_list:
            self.nm.add(MasterNode(server = server))

        # Make a listening port.
        ListeningConnection(self.em, None, addr = self.server)

        # Connect to a primary master node, verify data, and
        # start the operation. This cycle will be executed permentnly,
        # until the user explicitly requests a shutdown.
        while 1:
            self.connectToPrimaryMaster()
            try:
                while 1:
                    try:
                        self.verifyData()
                        self.doOperation()
                    except OperationFailure:
                        logging.error('operation stopped')
            except PrimaryFailure:
                logging.error('primary master is down')

    def connectToPrimaryMaster(self):
        """Find a primary master node, and connect to it.

        If a primary master node is not elected or ready, repeat
        the attempt of a connection periodically.
        
        Note that I do not accept any connection from non-master nodes
        at this stage."""
        logging.info('connecting to a primary master node')

        handler = BootstrapEventHandler(self)
        em = self.em
        nm = self.nm

        # First of all, make sure that I have no connection.
        for conn in em.getConnectionList():
            if not isinstance(conn, ListeningConnection):
                conn.close()

        # Make sure that every connection has the boostrap event handler.
        for conn in em.getConnectionList():
            conn.setHandler(handler)

        index = 0
        self.trying_master_node = None
        t = 0
        while 1:
            em.poll(1)
            if self.primary_master_node is not None:
                # If I know which is a primary master node, check if
                # I have a connection to it already.
                for conn in em.getConnectionList():
                    if isinstance(conn, ClientConnection):
                        uuid = conn.getUUID()
                        if uuid is not None:
                            node = nm.getNodeByUUID(uuid)
                            if node is self.primary_master_node:
                                # Yes, I have.
                                return

            if self.trying_master_node is None and t + 1 < time():
                # Choose a master node to connect to.
                if self.primary_master_node is not None:
                    # If I know a primary master node, pinpoint it.
                    self.trying_master_node = self.primary_master_node
                else:
                    # Otherwise, check one by one.
                    master_list = nm.getMasterNodeList()
                    try:
                        self.trying_master_node = master_list[index]
                    except IndexError:
                        index = 0
                        self.trying_master_node = master_list[0]
                    index += 1

                ClientConnection(em, handler, \
                        addr = self.trying_master_node.getServer())
                t = time()

    def verifyData(self):
        """Verify data under the control by a primary master node.
        Connections from client nodes may not be accepted at this stage."""
        logging.info('verifying data')

        handler = VerificationEventHandler(self)
        em = self.em

        # Make sure that every connection has the verfication event handler.
        for conn in em.getConnectionList():
            conn.setHandler(handler)

        self.operational = False
        while not self.operational:
            em.poll(1)

    def doOperation(self):
        """Handle everything, including replications and transactions."""
        logging.info('doing operation')

        handler = OperationEventHandler(self)
        em = self.em
        nm = self.nm

        # Make sure that every connection has the verfication event handler.
        for conn in em.getConnectionList():
            conn.setHandler(handler)

        # Forget all client nodes.
        for node in nm.getClientNodeList():
            nm.remove(node)

        while 1:
            em.poll(1)

    def getPartition(self, oid_or_tid):
        return unpack('!Q', oid_or_tid)[0] % self.num_partitions
