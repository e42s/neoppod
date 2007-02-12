import MySQLdb
from MySQLdb import OperationalError
from MySQLdb.constants.CR import SERVER_GONE_ERROR, SERVER_LOST
import logging
from array import array
import string
from struct import pack, unpack

from neo.storage.database import DatabaseManager
from neo.exception import DatabaseFailure
from neo.util import dump
from neo.protocol import DISCARDED_STATE

def p64(n):
    return pack('!Q', n)

def u64(s):
    return unpack('!Q', s)[0]

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
        self.under_transaction = False

    def begin(self):
        if self.under_transaction:
            try:
                self.commit()
            except:
                # Ignore any error for this implicit commit.
                pass
        self.query("""BEGIN""")
        self.under_transaction = True

    def commit(self):
        self.conn.commit()
        self.under_transaction = False

    def rollback(self):
        self.conn.rollback()
        self.under_transaction = False

    def query(self, query):
        """Query data from a database."""
        conn = self.conn
        try:
            printable_char_list = []
            for c in query.split('\n', 1)[0][:70]:
                if c not in string.printable or c in '\t\x0b\x0c\r':
                    c = '\\x%02x' % ord(c)
                printable_char_list.append(c)
            query_part = ''.join(printable_char_list)

            logging.debug('querying %s...', query_part)
            conn.query(query)
            r = conn.store_result()
            if r is not None:
                new_r = []
                for row in r.fetch_row(r.num_rows()):
                    new_row = []
                    for d in row:
                        if isinstance(d, array):
                            d = d.tostring()
                        new_row.append(d)
                    new_r.append(tuple(new_row))
                r = tuple(new_r)

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
                 tid BIGINT UNSIGNED NOT NULL PRIMARY KEY,
                 oids MEDIUMBLOB NOT NULL,
                 user BLOB NOT NULL,
                 description BLOB NOT NULL,
                 ext BLOB NOT NULL
             ) ENGINE = InnoDB""")

        # The table "obj" stores committed object data.
        q("""CREATE TABLE IF NOT EXISTS obj (
                 oid BIGINT UNSIGNED NOT NULL,
                 serial BIGINT UNSIGNED NOT NULL,
                 compression TINYINT UNSIGNED NOT NULL,
                 checksum INT UNSIGNED NOT NULL,
                 value MEDIUMBLOB NOT NULL,
                 PRIMARY KEY (oid, serial)
             ) ENGINE = InnoDB""")

        # The table "ttrans" stores information on uncommitted transactions.
        q("""CREATE TABLE IF NOT EXISTS ttrans (
                 tid BIGINT UNSIGNED NOT NULL,
                 oids MEDIUMBLOB NOT NULL,
                 user BLOB NOT NULL,
                 description BLOB NOT NULL,
                 ext BLOB NOT NULL
             ) ENGINE = InnoDB""")

        # The table "tobj" stores uncommitted object data.
        q("""CREATE TABLE IF NOT EXISTS tobj (
                 oid BIGINT UNSIGNED NOT NULL,
                 serial BIGINT UNSIGNED NOT NULL,
                 compression TINYINT UNSIGNED NOT NULL,
                 checksum INT UNSIGNED NOT NULL,
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
        if loid is not None:
            loid = p64(loid)
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
        if ltid is not None:
            ltid = p64(ltid)
        return ltid

    def getUnfinishedTIDList(self):
        q = self.query
        tid_set = set()
        self.begin()
        r = q("""SELECT tid FROM ttrans""")
        tid_set.update((p64(t[0]) for t in r))
        r = q("""SELECT serial FROM tobj""")
        self.commit()
        tid_set.update((p64(t[0]) for t in r))
        return list(tid_set)

    def objectPresent(self, oid, tid, all = True):
        q = self.query
        oid = u64(oid)
        tid = u64(tid)
        self.begin()
        r = q("""SELECT oid FROM obj WHERE oid = %d AND serial = %d""" \
                % (oid, tid))
        if not r and all:
            r = q("""SELECT oid FROM tobj WHERE oid = %d AND serial = %d""" \
                    % (oid, tid))
        self.commit()
        if r:
            return True
        return False

    def getObject(self, oid, tid = None, before_tid = None):
        q = self.query
        oid = u64(oid)
        if tid is not None:
            tid = u64(tid)
            r = q("""SELECT serial, compression, checksum, value FROM obj
                        WHERE oid = %d AND serial = %d""" \
                    % (oid, tid))
            try:
                serial, compression, checksum, data = r[0]
                next_serial = None
            except IndexError:
                return None
        elif before_tid is not None:
            before_tid = u64(before_tid)
            r = q("""SELECT serial, compression, checksum, value FROM obj
                        WHERE oid = %d AND serial < %d
                        ORDER BY serial DESC LIMIT 1""" \
                    % (oid, before_tid))
            try:
                serial, compression, checksum, data = r[0]
                r = q("""SELECT serial FROM obj
                            WHERE oid = %d AND serial >= %d
                            ORDER BY serial LIMIT 1""" \
                        % (oid, before_tid))
                try:
                    next_serial = r[0][0]
                except IndexError:
                    next_serial = None
            except IndexError:
                return None
        else:
            # XXX I want to express "HAVING serial = MAX(serial)", but
            # MySQL does not use an index for a HAVING clause!
            r = q("""SELECT serial, compression, checksum, value FROM obj
                        WHERE oid = %d ORDER BY serial DESC LIMIT 1""" \
                    % oid)
            try:
                serial, compression, checksum, data = r[0]
                next_serial = None
            except IndexError:
                return None

        if serial is not None:
            serial = p64(serial)
        if next_serial is not None:
            next_serial = p64(next_serial)
        return serial, next_serial, compression, checksum, data

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
                    q("""DELETE FROM pt WHERE rid = %d AND uuid = '%s'""" \
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

    def dropUnfinishedData(self):
        q = self.query
        self.begin()
        try:
            q("""TRUNCATE tobj""")
            q("""TRUNCATE ttrans""")
        except:
            self.rollback()
            raise
        self.commit()

    def storeTransaction(self, tid, object_list, transaction, temporary = True):
        q = self.query
        e = self.escape
        tid = u64(tid)

        if temporary:
            obj_table = 'tobj'
            trans_table = 'ttrans'
        else:
            obj_table = 'obj'
            trans_table = 'trans'

        self.begin()
        try:
            # XXX it might be more efficient to insert multiple objects
            # at a time, but it is potentially dangerous, because
            # a packet to MySQL can exceed the maximum packet size.
            # However, I do not think this would be a big problem, because 
            # tobj has no index, so inserting one by one should not be
            # significantly different from inserting many at a time.
            for oid, compression, checksum, data in object_list:
                oid = u64(oid)
                data = e(data)
                q("""REPLACE INTO %s VALUES (%d, %d, %d, %d, '%s')""" \
                        % (obj_table, oid, tid, compression, checksum, data))
            if transaction is not None:
                oid_list, user, desc, ext = transaction
                oids = e(''.join(oid_list))
                user = e(user)
                desc = e(desc)
                ext = e(ext)
                q("""REPLACE INTO %s VALUES (%d, '%s', '%s', '%s', '%s')""" \
                        % (trans_table, tid, oids, user, desc, ext))
        except:
            self.rollback()
            raise
        self.commit()

    def finishTransaction(self, tid):
        q = self.query
        tid = u64(tid)
        self.begin()
        try:
            q("""INSERT INTO obj SELECT * FROM tobj WHERE tobj.serial = %d""" \
                    % tid)
            q("""DELETE FROM tobj WHERE serial = %d""" % tid)
            q("""INSERT INTO trans SELECT * FROM ttrans WHERE ttrans.tid = %d""" \
                    % tid)
            q("""DELETE FROM ttrans WHERE tid = %d""" % tid)
        except:
            self.rollback()
            raise
        self.commit()

    def deleteTransaction(self, tid, all = False):
        q = self.query
        tid = u64(tid)
        self.begin()
        try:
            q("""DELETE FROM tobj WHERE serial = %d""" % tid)
            q("""DELETE FROM ttrans WHERE tid = %d""" % tid)
            if all:
                # Note that this can be very slow.
                q("""DELETE FROM obj WHERE serial = %d""" % tid)
                q("""DELETE FROM trans WHERE tid = %d""" % tid)
        except:
            self.rollback()
            raise
        self.commit()

    def getTransaction(self, tid, all = False):
        q = self.query
        tid = u64(tid)
        self.begin()
        r = q("""SELECT oids, user, description, ext FROM trans
                    WHERE tid = %d""" \
                % tid)
        if not r and all:
            r = q("""SELECT oids, user, description, ext FROM ttrans
                        WHERE tid = %d""" \
                    % tid)
        self.commit()
        if r:
            oids, user, desc, ext = r[0]
            if (len(oids) % 8) != 0 or len(oids) == 0:
                raise DatabaseFailure('invalid oids for tid %x' % tid)
            oid_list = []
            for i in xrange(0, len(oids), 8):
                oid_list.append(oids[i:i+8])
            return oid_list, user, desc, ext
        return None

    def getOIDList(self, offset, length, num_partitions, partition_list):
        q = self.query
        r = q("""SELECT DISTINCT oid FROM obj WHERE MOD(oid,%d) in (%s)
                    ORDER BY oid DESC LIMIT %d,%d""" \
                % (num_partitions, 
                   ','.join([str(p) for p in partition_list]), 
                   offset, length))
        return [p64(t[0]) for t in r]

    def getObjectHistory(self, oid, offset = 0, length = 1):
        q = self.query
        oid = u64(oid)
        r = q("""SELECT serial, LENGTH(value) FROM obj WHERE oid = %d
                    ORDER BY serial DESC LIMIT %d,%d""" \
                % (oid, offset, length))
        if r:
            return [(p64(serial), length) for serial, length in r]
        return None

    def getTIDList(self, offset, length, num_partitions, partition_list):
        q = self.query
        r = q("""SELECT tid FROM trans WHERE MOD(tid,%d) in (%s)
                    ORDER BY tid DESC LIMIT %d,%d""" \
                % (num_partitions, 
                   ','.join([str(p) for p in partition_list]), 
                   offset, length))
        return [p64(t[0]) for t in r]

    def getTIDListPresent(self, tid_list):
        q = self.query
        r = q("""SELECT tid FROM trans WHERE tid in (%s)""" \
                % ','.join([str(u64(tid)) for tid in tid_list]))
        return [p64(t[0]) for t in r]
