import MySQLdb
from MySQLdb import OperationalError
from MySQLdb.constants.CR import SERVER_GONE_ERROR, SERVER_LOST
import logging

from neo.storage.database import DatabaseManager
from neo.exception import DatabaseFailure
from neo.util import dump
from neo.protocol import DISCARDED_STATE

class MySQLDatabaseManager(DatabaseManager):
    """This class manages a database on MySQL."""

    def __init__(self, **kwargs):
        self.db = kwargs['database']
        self.user = kwargs['user']
        self.passwd = kwargs.get('password')
        self.conn = None
        self.connect()
        super(MySQLDatabaseManager, self).__init__(**kwargs)

    def connect(self):
        kwd = {'db' : self.db, 'user' : self.user}
        if self.passwd is not None:
            kwd['passwd'] = self.passwd
        logging.info('connecting to MySQL on the database %s with user %s',
                     self.db, self.user)
        self.conn = MySQLdb.connect(**kwd)
        self.conn.autocommit(False)

    def begin(self):
        self.query("""BEGIN""")

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def query(self, query):
        """Query data from a database."""
        conn = self.conn
        try:
            logging.debug('querying %s...', query.split('\n', 1)[0])
            conn.query(query)
            r = conn.store_result()
            if r is not None:
                r = r.fetch_row(r.num_rows())
        except OperationalError, m:
            if m[0] in (SERVER_GONE_ERROR, SERVER_LOST):
                logging.info('the MySQL server is gone; reconnecting')
                self.connect()
                return self.query(query)
            raise DatabaseFailure('MySQL error %d: %s' % (m[0], m[1]))
        return r
 
    def escape(self, s):
        """Escape special characters in a string."""
        return self.conn.escape_string(s)

    def setup(self, reset = 0):
        q = self.query

        if reset:
            q("""DROP TABLE IF EXISTS config, pt, trans, obj, ttrans, tobj""")

        # The table "config" stores configuration parameters which affect the
        # persistent data.
        q("""CREATE TABLE IF NOT EXISTS config (
                 name VARBINARY(16) NOT NULL PRIMARY KEY,
                 value VARBINARY(255) NOT NULL
             ) ENGINE = InnoDB""")

        # The table "pt" stores a partition table.
        q("""CREATE TABLE IF NOT EXISTS pt (
                 rid INT UNSIGNED NOT NULL,
                 uuid BINARY(16) NOT NULL,
                 state TINYINT UNSIGNED NOT NULL,
                 PRIMARY KEY (rid, uuid)
             ) ENGINE = InnoDB""")

        # The table "trans" stores information on committed transactions.
        q("""CREATE TABLE IF NOT EXISTS trans (
                 tid BINARY(8) NOT NULL PRIMARY KEY,
                 oids MEDIUMBLOB NOT NULL,
                 user BLOB NOT NULL,
                 desc BLOB NOT NULL,
                 ext BLOB NOT NULL
             ) ENGINE = InnoDB""")

        # The table "obj" stores committed object data.
        q("""CREATE TABLE IF NOT EXISTS obj (
                 oid BINARY(8) NOT NULL,
                 serial BINARY(8) NOT NULL,
                 checksum BINARY(4) NOT NULL,
                 compression TINYINT UNSIGNED NOT NULL,
                 value MEDIUMBLOB NOT NULL,
                 PRIMARY KEY (oid, serial)
             ) ENGINE = InnoDB""")

        # The table "ttrans" stores information on uncommitted transactions.
        q("""CREATE TABLE IF NOT EXISTS ttrans (
                 tid BINARY(8) NOT NULL,
                 oids MEDIUMBLOB NOT NULL,
                 user BLOB NOT NULL,
                 desc BLOB NOT NULL,
                 ext BLOB NOT NULL
             ) ENGINE = InnoDB""")

        # The table "tobj" stores uncommitted object data.
        q("""CREATE TABLE IF NOT EXISTS tobj (
                 oid BINARY(8) NOT NULL,
                 serial BINARY(8) NOT NULL,
                 checksum BINARY(4) NOT NULL,
                 compression TINYINT UNSIGNED NOT NULL,
                 value MEDIUMBLOB NOT NULL
             ) ENGINE = InnoDB""")

    def getConfiguration(self, key):
        q = self.query
        e = self.escape
        key = e(str(key))
        r = q("""SELECT value FROM config WHERE name = '%s'""" % key)
        try:
            return r[0][0]
        except IndexError:
            return None

    def setConfiguration(self, key, value):
        q = self.query
        e = self.escape
        key = e(str(key))
        value = e(str(value))
        q("""INSERT config VALUES ('%s', '%s')""" % (key, value))

    def getUUID(self):
        return self.getConfiguration('uuid')

    def setUUID(self, uuid):
        self.begin()
        try:
            self.setConfiguration('uuid', uuid)
        except:
            self.rollback()
            raise
        self.commit()

    def getNumPartitions(self):
        n = self.getConfiguration('partitions')
        if n is not None:
            return int(n)

    def setNumPartitions(self, num_partitions):
        self.begin()
        try:
            self.setConfiguration('partitions', num_partitions)
        except:
            self.rollback()
            raise
        self.commit()

    def getName(self):
        return self.getConfiguration('name')

    def setName(self, name):
        self.begin()
        try:
            self.setConfiguration('name', name)
        except:
            self.rollback()
            raise
        self.commit()

    def getPTID(self):
        return self.getConfiguration('ptid')

    def setPTID(self, ptid):
        self.begin()
        try:
            self.setConfiguration('ptid', ptid)
        except:
            self.rollback()
            raise
        self.commit()

    def getPartitionTable(self):
        q = self.query
        return q("""SELECT rid, uuid, state FROM pt""")

    def getLastOID(self, all = True):
        q = self.query
        self.begin()
        loid = q("""SELECT MAX(oid) FROM obj""")[0][0]
        if all:
            tmp_loid = q("""SELECT MAX(oid) FROM tobj""")[0][0]
            if loid is None or (tmp_loid is not None and loid < tmp_loid):
                loid = tmp_loid
        self.commit()
        return loid

    def getLastTID(self, all = True):
        # XXX this does not consider serials in obj.
        # I am not sure if this is really harmful. For safety,
        # check for tobj only at the moment. The reason why obj is
        # not tested is that it is too slow to get the max serial
        # from obj when it has a huge number of objects, because
        # serial is the second part of the primary key, so the index
        # is not used in this case. If doing it, it is better to
        # make another index for serial, but I doubt the cost increase
        # is worth.
        q = self.query
        self.begin()
        ltid = q("""SELECT MAX(tid) FROM trans""")[0][0]
        if all:
            tmp_ltid = q("""SELECT MAX(tid) FROM ttrans""")[0][0]
            if ltid is None or (tmp_ltid is not None and ltid < tmp_ltid):
                ltid = tmp_ltid
            tmp_serial = q("""SELECT MAX(serial) FROM tobj""")[0][0]
            if ltid is None or (tmp_serial is not None and ltid < tmp_serial):
                ltid = tmp_serial
        self.commit()
        return ltid

    def getUnfinishedTIDList(self):
        q = self.query
        tid_set = set()
        self.begin()
        r = q("""SELECT tid FROM ttrans""")
        tid_set.add((t[0] for t in r))
        r = q("""SELECT serial FROM tobj""")
        self.commit()
        tid_set.add((t[0] for t in r))
        return list(tid_set)

    def getOIDListByTID(self, tid, all = False):
        q = self.query
        e = self.escape
        tid = e(tid)
        self.begin()
        r = q("""SELECT oids FROM trans WHERE tid = '%s'""" % tid)
        if not r and all:
            r = q("""SELECT oids FROM ttrans WHERE tid = '%s'""" % tid)
        self.commit()
        if r:
            oids = r[0][0]
            if (len(oids) % 8) != 0 or len(oids) == 0:
                raise DatabaseFailure('invalid oids for tid %s' % dump(tid))
            oid_list = []
            for i in xrange(0, len(oids), 8):
                oid_list.append(oids[i:i+8])
            return oid_list
        return None

    def objectPresent(self, oid, tid, all = True):
        q = self.query
        e = self.escape
        oid = e(oid)
        tid = e(tid)
        self.begin()
        r = q("""SELECT oid FROM obj WHERE oid = '%s' AND serial = '%s'""" \
                % (oid, tid))
        if not r and all:
            r = q("""SELECT oid FROM tobj WHERE oid = '%s' AND serial = '%s'""" \
                    % (oid, tid))
        self.commit()
        if r:
            return True
        return False

    def doSetPartitionTable(self, ptid, cell_list, reset):
        q = self.query
        e = self.escape
        self.begin()
        try:
            if reset:
                q("""TRUNCATE pt""")
            for offset, uuid, state in cell_list:
                uuid = e(uuid)
                if state == DISCARDED_STATE:
                    q("""DELETE FROM pt WHERE offset = %d AND uuid = '%s'""" \
                            % (offset, uuid))
                else:
                    q("""INSERT INTO pt VALUES (%d, '%s', %d)
                            ON DUPLICATE KEY UPDATE state = %d""" \
                                    % (offset, uuid, state, state))
            ptid = e(ptid)
            q("""UPDATE config SET value = '%s' WHERE name = 'ptid'""" % ptid)
        except:
            self.rollback()
            raise
        self.commit()

    def changePartitionTable(self, ptid, cell_list):
        self.doSetPartitionTable(ptid, cell_list, True)

    def setPartitionTable(self, ptid, cell_list):
        self.doSetPartitionTable(ptid, cell_list, False)
