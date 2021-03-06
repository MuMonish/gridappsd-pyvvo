'''
Helper module for basic database functionality.

Prerequisites: mysql-connector-python.

Created on Aug 29, 2017

@author: thay838
'''
import mysql.connector
import mysql.connector.pooling as pooling
from mysql.connector import errorcode
import helper
from helper import strRepDict
import constants
import time
import datetime

# Define how we handle time bounds.
LEFT_BOUND = '>='
RIGHT_BOUND = '<='

class db:
    """Class to handle database operations in a threadsafe manner. The
    constructor opens up a connection pool.
    
    All methods should follow the format of:
    
    prepare query --> function specific, then call getTimeAndIDFilter
    getCnxnAndCursor
    try:
        do stuff
    finally:
        closeCnxnAndCursor
        
    The reason the query is prepared first is to ensure only 1 connection is
    ever used at a time.
        
    NOTE: When forming MySQL queries, the parameter bindings work ONLY for
        column values. https://stackoverflow.com/questions/10077046/prevent-mysql-python-from-inserting-quotes-around-database-name-parameter
    """
    
    def __init__(self, user='gridlabd', password='gridlabd',
                 host='localhost', database='gridlabd',
                 pool_size=1, **kwargs):
        """Initializing the db class creates a pool of database connections.
        """
        # Set attributes
        self.user=user
        self.password=password
        self.host=host
        self.database=database
        
        # Handle pool size --> make sure server can handle it.
        # Make a single server connection, and check 'max_connections'
        cnxn = self.connect()
        cursor = cnxn.cursor()
        cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
        # This should just return one row, fetch it. 
        result = cursor.fetchall()
        
        # Clean up.
        cursor.close()
        cnxn.close()
        
        # Columns are 'Variable_name' and 'Value.' We just care about value
        serverMax = int(result[0][1])
        
        # Change pooling variable if necessary.
        if (pool_size <= serverMax) and (pool_size > pooling.CNX_POOL_MAXSIZE):
            # Notify we're changing the default.
            print(('Increasing mysql.connector.pooling.CNX_POOL_MAXSIZE '
                   + 'from {} to {}'.format(pooling.CNX_POOL_MAXSIZE,
                                            pool_size)))
            # Change it.
            pooling.CNX_POOL_MAXSIZE = pool_size
        elif (pool_size > serverMax):
            # Case of the requested pool_size being too large.
            errStr = ("The requested pool_size, {}, ".format(pool_size)
                      + "is larger than the server's 'max_connections' "
                      + "variable, which is set to {}.\n".format(serverMax)
                      + "Try again with a smaller pool, or have the "
                      + "administrator of the MySQL server increase the "
                      + "value of 'max_connections.'") 
            raise ValueError(errStr)
        
        if pool_size >= (0.8 * serverMax):
            print(("The requested pool_size will be using at least 80% of "
                   "the server's maximum connections ({}).".format(serverMax)))
            
        # Set the pool_size
        self.pool_size=pool_size
        
        # Connect to database
        self.cnxnPool = self.connectPool() 
        
    def connectPool(self):
        """Method to create and return mysql connection pool. This is threadsafe.
        
        NOTE: This pooling technique doesn't allow the 'use_pure' option. For
            GridLAB-D we already have to install the MySQL Connector C library,
            so if it's thread-safe we could use the 'faster' option, but have 
            to repeadetly open and close connections..
        
        INPUTS:
            Initialized db object. See __init__
        """
        try:
            cnxn = pooling.MySQLConnectionPool(user=self.user,
                                               password=self.password,
                                               host=self.host,
                                               database=self.database,
                                               pool_size=self.pool_size)
        except mysql.connector.Error as err:
            self._printError(err)
            raise err
        else:
            return cnxn
        
    def getCnxnAndCursor(self, cursorOptions={}, attempts=10, delay=0.1):
        """Method to get a connection from the pool, and a cursor from it. Each
        method which forms and executes a query should use this method.
        
        INPUTS:
            self: initialized db object
            cursorOptions: dictionary of cursor options to pass to cursor
                constructor. Check out https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlcursor.html
            attempts: number of times the method will try to get a connection.
            delay: delay between attempts.
        OUTPUTS:
            database connection, connection cursor
            
        NOTE: If a connection is not available, a PoolError is raised. We'll
            try 10 times before erroring out.
        """
        itCount = 1
        while True:
            try:
                cnxn = self.cnxnPool.get_connection()
            except mysql.connector.errors.PoolError as err:
                # No connections are available. 
                
                # Raise the exception if we've exceeded the iteration count.
                if itCount >= attempts:
                    print(('Failed to obtain connection from pool after '
                           + '{} attempts.').format(itCount))
                    raise err
                
                # Increment iteration count and sleep to try again.
                itCount += 1
                time.sleep(delay)
            else:
                # Leave the loop.
                break
        
        cursor = cnxn.cursor(**cursorOptions)
        
        return cnxn, cursor
    
    @staticmethod
    def closeCnxnAndCursor(cnxn, cursor):
        """Method to close connection cursor, and then close connection. In the
        case of a pooled connection, the connection isn't closed, but rather
        returned to the pool.
        """
        # Exhaust the cursor
        for _ in cursor:
            pass
        # Close cursor and connection.
        cursor.close()
        cnxn.close()
        
    def connect(self, use_pure=False):
        """Method to create and return a single database connection. This
            implementation allows us to use the C connector, while the pool
            doesn't.
            
        INPUTS:
            self: Initialized db object. See __init__
            use_pure: True to use pure Python implementation, False to use C 
                connector. NOTE: C connector must be installed, and likely on
                the PATH.
        """
        try:
            cnxn = mysql.connector.connect(user=self.user,
                                           password=self.password,
                                           host=self.host,
                                           database=self.database,
                                           use_pure=use_pure)
        except mysql.connector.Error as err:
            self._printError(err)
            raise err
        else:
            return cnxn
        
    @staticmethod
    def _printError(err):
        """Print a connection error.
        """
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print("Database does not exist")
        else:
            print(err)
        
    def truncateTable(self, table):
        """Method to truncate a given table.
        """
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        try:
            # Truncate the table. Parameter bindings don't work here.
            cursor.execute('TRUNCATE TABLE {}'.format(table))
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
 
    def dropTable(self, table):
        """ Simple method to drop a table from the database.
        """
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Drop the table. Parameter bindings don't work here.
            cursor.execute('DROP TABLE {}'.format(table))
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
    
    def dropAllTables(self, tableSuffix=None):
        """Drop all tables in database.
        INPUT: database connection.
        
        Note: my efficient dual-loop method kept giving an 'unread results' error.
        
        INPUTS: tableSuffix - if provided, only tables ending with the given
            suffix will be dropped.
        """
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            q = ("SELECT table_name "
                 "FROM information_schema.tables "
                 "WHERE table_schema = '{}'").format(self.database)
            
            if tableSuffix:
                q += " AND table_name LIKE '%{}'".format(tableSuffix)
                
            # Get the names of all tables in database.
            cursor.execute(q)
            # Assume there aren't so many tables that we blow up memory with 
            # a fetch all.
            rows = cursor.fetchall()
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)  
            
        # Loop through and drop all tables.
        for row in rows:
            self.dropTable(row[0])
            
        return len(rows)
    
    def truncateTableBySuffix(self, suffix):
        """Function to truncate all tables with a given suffix.
        
        TODO and NOTE: This is HARD-CODED to work with the current
        implementation of the mysql group recorder in GridLAB-D, which creates
        additional tables for group recorders.
        """
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        try:
            # HARD-CODE the table suffixes.
            suff1 = r"%" + suffix.replace("_", r"\_") # escape underscore
            suff2 = suff1 + r"\__" # tables increment from 0 upward
            suff3 = suff1 + r"\_index" # there's an index table.
            
            # Form query to get tables.
            q = ("SELECT table_name FROM INFORMATION_SCHEMA.TABLES "
                 + "WHERE table_schema = '{db}' AND "
                 + "(table_name LIKE '{suff1}' OR table_name LIKE '{suff2}' "
                 + "OR table_name LIKE '{suff3}')"
                ).format(db=self.database, suff1=suff1, suff2=suff2,
                         suff3=suff3)
            
            # Execute the query.
            cursor.execute(q)
            # Fetch all the rows. If the tables returned cause a memory
            # issue, I should quite my job.
            # NOTE: we could loop over each row and use a seperate connection
            # to drop the table, but I'd rather do it this way to avoid 
            # taking up another connection.
            rows = cursor.fetchall()
            
            # Loop over the rows, and trucate the tables.
            for r in rows:
                cursor.execute('TRUNCATE TABLE {}'.format(r[0]))
            
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        
    def sumComplexPower(self, cols, table, idCol='id', tCol='t',
                        nameCol='name', starttime=None, stoptime=None):
        """Sum complex power in table.
        
        INPUTS:
            cols: names of columns to access and sum in a list
            table: table to query
            tCol: name of time column. GridLAB-D mysql defaults this to 't'
            idCol: name of ID column. GridLAB-D defaults to id
            starttime: aware datetime object for starttime (inclusive)
            stoptime: aware datetime object for stoptime (inclusive)
        
        IMPORTANT NOTE: All units in table are assumed to be the same.
        
        OUTPUT: Dictionary with 'rowSums' and 'unit' fields. 'rowSums' is a list
        """
        # Prepare query.
        q = "SELECT {} FROM {}".format(','.join(cols), table)
        # Add time filter, and ID filter if applicable
        q += self.getTimeAndIDFilter(starttime=starttime,
                                     stoptime=stoptime, table=table, 
                                     idCol=idCol, tCol=tCol,
                                     nameCol=nameCol)
            
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:    
            # Execute the query.
            cursor.execute(q)
            
            # Fetch the first row.
            row = cursor.fetchone()
            
            # Initialize rows
            rowSum = [] 
            # Loop over the rows and sum.
            while row:
                # Three phase power is simply the complex sum of the individual
                # phases.
                rowSum.append(0+0j)
                for ind in range(len(cols)):
                    # Get the complex value and its unit
                    v, u = helper.getComplex(row[ind]) 
                    # Add the value to the total.
                    rowSum[-1] += v
        
                # Advance the cursor.    
                row = cursor.fetchone()
        finally:   
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        
        # Assign return. NOTE: All units assumed to be the same.
        out = {'rowSums': rowSum, 'unit': u}
        return out
    
    def getComplexFromParts(self, table, cols, idCol='id', tCol='t',
                        nameCol='name', starttime=None, stoptime=None):
        """Function to get complex numbers from a table where the real and 
        imaginary parts are stored in different columns.
        
        NOTE: This depends on GridLAB-D's 'real' and 'reactive' terminology.
        
        NOTE: For now, assume only two columns (cols). This could easily be
        adapted for more in the future.
        """
        # Ensure there are only two elements in cols
        if len(cols) != 2:
            raise UserWarning('For now, only two columns are supported')
        
        # Find the indices of the real and reactive components.
        realList = [('_real' in s.lower()) for s in cols]
        reactiveList = [('_reactive' in s.lower()) for s in cols]
        # Here comes the part where we hard-code length of two (.index only
        # grabs first occurence)
        try:
            realInd = realList.index(True)
            reactiveInd = reactiveList.index(True)
        except ValueError:
            raise UserWarning('Columns provided lack _real and/or _reactive')
        
        # Prepare query.
        q = "SELECT {} FROM {}".format(','.join(cols), table)
        # Add time filter, and ID filter if applicable
        q += self.getTimeAndIDFilter(starttime=starttime,
                                     stoptime=stoptime, table=table, 
                                     idCol=idCol, tCol=tCol,
                                     nameCol=nameCol)
            
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        # Initialize return
        out = []
        try:    
            # Execute the query.
            cursor.execute(q)
            
            # Fetch the first row.
            row = cursor.fetchone()
            # Loop over the rows and sum.
            while row:
                # Convert values to complex
                out.append(complex(row[realInd], row[reactiveInd]))
                # Advance the cursor.
                row = cursor.fetchone()
        finally:   
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        
        # Done.
        return out
        
    
    def sumMatrix(self, table, cols, nameCol='name', idCol='id', tCol='t',
                  starttime=None, stoptime=None):
        """Method to element-wise sum given rows and columns. Note that this also
            works for single columns or multiple columns.
        
        INPUTS:
            cursor: cursor from database connection
            cols: names of columns to access and sum in a list
            name: Used to filter query by value in nameCol. Ex: 'R2-12-47-2_reg_2'
            nameCol: Name of name column for filtering. Defaults to 'name'
            table: table to query
            idCol: name of ID column. GridLAB-D defaults to 'id'
            tCol: name of time column. GridLAB-D mysql defaults this to 't'
            starttime: aware datetime object for starttime (inclusive)
            stoptime: aware datetime object for stoptime (inclusive)
        """
        # Prepare query - start with getting 'col1' + 'col2' + 'col3'...
        s = ' + '.join(cols)
        q = "SELECT SUM({}) FROM {}".format(s, table)
        # Add time filter, and ID filter if applicable
        q += self.getTimeAndIDFilter(starttime=starttime,
                                     stoptime=stoptime, table=table, 
                                     idCol=idCol, tCol=tCol,
                                     nameCol=nameCol)
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Execute query, return
            cursor.execute(q)
            r = cursor.fetchone()
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        
        return r[0]
    
    def fetchAll(self, table, cols, idCol='id', tCol='t', nameCol='name',
                 starttime=None, stoptime=None):
        """Function to read a table from the database. Returns a list of tuples.
        WARNING: If the table is huge, you're going to create a memory problem.
        
        INPUTS:
            cursor: database cursor
            table: table to fetch data from
            cols: List of columns containing desired data
            idCol: Name of the ID column
            tCol: Name of the time column
            starttime: aware datettime object, to create inclusive left hand bound 
            stoptime: aware datettime object, to create inclusive right hand bound      
        """
        # Create comma seperated list of columns
        colStr = ','.join(cols)
        
        # Create query
        q = "SELECT {} FROM {}".format(colStr, table)
        # Add time filter, and ID filter if applicable
        q += self.getTimeAndIDFilter(starttime=starttime,
                                     stoptime=stoptime, table=table, 
                                     idCol=idCol, tCol=tCol,
                                     nameCol=nameCol)
            
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Execute the query
            cursor.execute(q)
            
            # Fetch all
            rows = cursor.fetchall()
        
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        return rows
    
    def voltViolationsFromRecorder(self, table, lowerBound,
                                    upperBound, voltageCols, idCol='id',
                                    nameCol='name',  tCol='t',
                                    starttime=None, stoptime=None):
        """Function to loop through a group of tables which were created by
        GridLAB-D's mysql recorder (with a group) and sum up voltage violations.
        
        NOTE: bounds are exclusive for determining violations, in other words,
        voltages in the set [lowerBound, upperBound] will not incur a
        violation cost.
        
        TODO: for now, this simply counts violations. This could be extended to
        add more detail, but it would also make sense to just look up the data
        in the database for more detail...
        """
        # Create the base of the query.
        qBase = 'SELECT COUNT({idCol}) FROM {table}'.format(idCol=idCol,
                                                            table=table)
        
        # Add time filter, and ID filter if applicable
        qBase += self.getTimeAndIDFilter(starttime=starttime,
                                         stoptime=stoptime, table=table, 
                                         idCol=idCol, tCol=tCol,
                                         nameCol=nameCol)
        
        '''
        qBase = ('SELECT {tCol}, {nameCol}, {voltageCols} FROM {table} '
                 + 'WHERE ').format(tCol=tCol, nameCol=nameCol,
                                    voltageCols=', '.join(voltageCols),
                                    table=table)
        '''
                 
        # String for comparison
        compStr = '{col} {operator} {value}'
        
        # Only partly format the string (put in col, but nothing else)
        qBase += ' AND (' + compStr.format_map(strRepDict(col=voltageCols[0]))
        
        # Loop over the remaining voltage columns
        for vCol in voltageCols[1:]:
            qBase += ' OR ' + compStr.format_map(strRepDict(col=vCol))
            
        # Close the parentheses
        qBase += ')'
        
        # Create queries for high and low voltage
        qLow = qBase.format(operator='<', value=lowerBound)
        qHigh = qBase.format(operator='>', value=upperBound)
        queries = {'low': qLow, 'high': qHigh}
        
        # Initialize return
        out = {}
        
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Get the violations
            for key, query in queries.items():
                # Execute the query
                cursor.execute(query)
                violations = cursor.fetchall()
                # Assign output (it comes in a single-valued list which
                # contains a single-valued tuple)
                out[key] = violations[0][0]
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
            
        return out
    
    # Not using the following functions anymore, but it helps to keep it 
    # around.
    '''
    def getColumnNames(self, table, exceptList=None):
        """Function to get the columns for a given table.
        
        INPUTS:
            table: string, name of table to get columns for
            exceptList: list of columns to exclude (like 't' or 'id')
        
        SHOW COLUMNS FROM gridlabd.voltage_a_0 WHERE Field <> 'id' AND Field <> 't';
        select column_name from information_schema.columns where table_name='table'
        """
        # Build the query.
        q = ("SELECT column_name FROM information_schema.columns WHERE "
             + "table_name = '{}'").format(table)
             
        # If we're not including columns, add to the query for filtering.
        if exceptList is not None:
            # encase each list element in single quotes.
            exceptList = ["'" + s + "'" for s in exceptList]
            # Add to the query
            q += " AND column_name NOT IN ({})".format(','.join(exceptList))
        
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Execute the query
            cursor.execute(q)
            
            # Since we're fetching column names, we should be safe to fetch 
            # all here.
            rows = cursor.fetchall()
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
            
        # Return (database query returns list of single element tuples).
        return [k[0] for k in rows]
        
    def voltViolationsFromGroupRecorder(self, baseTable, lowerBound,
                                        upperBound, idCol='id', tCol='t',
                                        starttime=None, stoptime=None):
        """Function to loop through a group of tables which were created by
        GridLAB-D's group_recorder and sum up voltage violations.
        
        NOTE/TODO: group_recorder will hopefully be changed in March, meaning
        we can refactor and use SQL queries to do filtering instead of pulling
        out all the data and checking thresholds. 
        
        NOTE: bounds are exclusive for determining violations, in other words,
        voltages in the set [lowerBound, upperBound] will not incur a
        violation cost./
        """
        # First step is to get the list of tables from the 'index.' Formulate
        # the query.
        q = 'SELECT DISTINCT table_name FROM {}'.format(baseTable + '_index')
        
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        # Get the table names.
        try:
            # Execute the query, and do a fetchall (if the list of distinct
            # tables causes a memory issue, we have bigger fish to fry)
            cursor.execute(q)
            # Note this will give us a list of tuples with a single element.
            tables = cursor.fetchall()
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        
        # Initialize return.
        out = {'high': 0, 'low': 0, 'detail':{}}
        
        # Loop over each table and count the values outside of the range.
        for t in tables:
            thisOut = self.countValsOutOfRange(table=t[0],
                                               lowerBound=lowerBound,
                                               upperBound=upperBound,
                                               idCol=idCol, tCol=tCol,
                                               starttime=starttime,
                                               stoptime=stoptime)
            
            # Add this output to the overall output.
            out['high'] += thisOut['high']
            out['low'] += thisOut['low']
            # On the first iteration, simply take the details.
            if t == tables[0]:
                out['detail'] = thisOut['detail']
            else:
                # Loop and combine.
                for t in thisOut['detail']:
                    for k in ('high', 'low'):
                        out['detail'][t][k] = (out['detail'][t][k]
                                               + thisOut['detail'][t][k])
                        
        return out
            
    
    def countValsOutOfRange(self, table, lowerBound, upperBound,
                            idCol='id', tCol='t', starttime=None,
                            stoptime=None):
        """Function to count values that fall are < lowerBound and 
        > upperBound
        
        NOTE/TODO: In the future, we should change the group_recorder to stop
        making multiple tables, and instead make one big table with all the
        information we need. That way, we could perform this filtering directly
        within MySQL instead of extracting all the data and then filtering.
        """
        # Get the columns for the table in question. Include time.
        cols = self.getColumnNames(table=table, exceptList=[idCol,])
        
        timeIndex = cols.index(tCol)
        
        # Build column string. Note we need to use back-ticks.
        colStr = "`" + cols[0] + "`"
        for col in cols[1:]:
            colStr += ", `" + col + "`"
        
        # Create comma seperated list of columns
        #colStr = ', '.join(cols)
        
        # Create query
        q = "SELECT {} FROM {}".format(colStr, table)
        # Add time filter, and ID filter if applicable.
        # TODO: I'm leaving an error/confusion inducing time-bomb here by 
        # excluding the nameCol input to getTimeAndIDFilter. If we hit an 
        # 'ambiguous' time (DST fall back), chaos will ensue. The
        # getTimeAndIDFilter function was built to work with regular recorders,
        # and we built the group recorder to match tape (bad move looking back).
        # At any rate, when the mysql group_recorder gets redone so that its
        # output looks like regular recorders, this won't be an issue and we 
        # can add the nameCol input back in.
        q += self.getTimeAndIDFilter(starttime=starttime,
                                     stoptime=stoptime, table=table, 
                                     idCol=idCol, tCol=tCol)
        
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Initialize the output.
            out = {'high': 0, 'low': 0, 'detail': {}}
            
            # Execute the query
            cursor.execute(q)
            
            # Loop over the rows.
            row = cursor.fetchone()
            # Get generator of indices NOT including the time index. Counting
            # on all rows being the same length.
            rInd = chain(range(0, timeIndex), range(timeIndex+1, len(row)))
            while row:
                # Grab the time, add to detailed return
                t = row[timeIndex]
                out['detail'][t] = {'high': [], 'low':[]}
                
                # Loop over the data and tally violations.
                for ind in rInd:
                    val = row[ind]
                    if val < lowerBound:
                        out['low'] += 1
                        out['detail'][t]['low'].append(cols[ind])
                    elif val > upperBound:
                        out['high'] += 1
                        out['detail'][t]['high'].append(cols[ind])
                
                # Advance to the next row
                row = cursor.fetchone()
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
            
        # Return.
        return out
    '''
        
    
    def updateStatus(self, inDict, dictType, table, phaseCols, t,
                     nameCol='name', idCol='id', tCol='t'):
        """Function to update reg or cap dictionaries (defined in docstring of
        util.gld). The 'newState' of the given dictionary will be updated by
        reading the state from the database.
        
        INPUTS:
            inDict: dictionary to update. Formatted as defined in util.gld
            dictType: 'reg' or 'cap' to indiciate the type of dictionary inDict is
            cursor: database cursor
            table: table to read
            phaseCols: list of names of the columns which define state (switch
                status or tap position)
            t: aware datetime object indicating the time at which to pull the 
                newState from the database
            nameCol: name of the name column in the database
            tCol: name of the time column in the database
            idCol: name of the ID column in the database
            
        OUTPUT:
            inDict has its 'newState' updated for each phase, and is returned.
        """
        # Formulate query. Note how the name is intentionally put first.
        q = "SELECT {}, {} FROM {}".format(nameCol, ','.join(phaseCols),
                                           table)
        # Add time filter, and ID filter if applicable
        q += self.getTimeAndIDFilter(starttime=t,
                                     stoptime=t, table=table, 
                                     idCol=idCol, tCol=tCol,
                                     nameCol=nameCol)
            
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        
        try:
            # Based on the dictType, determine what to strip from the phaseCols
            # to just leave the phase behind.
            if dictType == 'reg':
                s = 'tap_'
            elif dictType == 'cap':
                s = 'switch'
            
            # Query the database.
            cursor.execute(q)
            
            # Iterate through the rows
            for row in cursor:
                # Extract the name, which will always be the first element.
                n = row[0]
                # Loop through the rest of the row.
                for k in range(1, len(phaseCols)+1):
                    # Infer the phase from the column name.
                    p = phaseCols[k-1].replace(s, '')
                    
                    # If this phase is in the dictionary, update status.
                    # Recall that we had to make a column for every phase, 
                    # even if this device isn't connected to the phase.
                    if p in inDict[n]['phases']:    
                        # Assign to 'newStatus'
                        inDict[n]['phases'][p]['newState'] = row[k]
                
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
        
        # Done. 
        return inDict
    
    def getTimeAndIDFilter(self, starttime, stoptime, table, idCol='id',
                           tCol='t', nameCol='name'):
        """Helper function to get WHERE clause for time-based query. Both times
            are considered inclusive. If the times are ambiguous (DST 'fall 
            back'), an additional ID filter is added.
        """
        # Start by getting the time filter.
        tFilter = self.timeWhere(starttime=starttime, stoptime=stoptime,
                                 tCol=tCol)
        
        # If the times are ambiguous, get the ID filter.
        ambiguous = any((helper.isAmbiguous(starttime),
                         helper.isAmbiguous(stoptime)))
        
        if ambiguous:
            idFilter = self.idFilter(tFilter=tFilter, table=table,
                                  starttime=starttime, stoptime=stoptime,
                                  idCol=idCol, tCol=tCol, nameCol=nameCol)
        else:
            idFilter = ''
            
        f = tFilter + idFilter
        return f
            
    @staticmethod
    def timeWhere(starttime, stoptime, tCol):
        """Helper function to get WHERE clause for time-based query. Both times 
            are considered inclusive.
        
        INPUTS:
            starttime: aware datetime object
            stoptime: aware datetime object
            tCol: name of the 'time' column
        """
        if starttime and stoptime:
            # Convert starttime to a string. 
            start_str = starttime.strftime(constants.DATE_FMT)
            # Check if the given datetimes aren't equal. We have to convert to
            # UTC to handle the DST 'fall back' issue. Stupid 'aware' datetime
            # objects will show up as equal even though they have a different
            # offset due to DST...
            if helper.dtToUTC(starttime) != helper.dtToUTC(stoptime):
                # Get the stop string.
                stop_str = stoptime.strftime(constants.DATE_FMT)
                # If the strings are equal, we're dealing with 'fall back' and
                # will have to rely on our ID filtering to sort things out.
                if start_str == stop_str:
                    # Increment by one hour.
                    stopTemp = stoptime + datetime.timedelta(seconds=3600)
                    stop_str = stopTemp.strftime(constants.DATE_FMT)
                    
                # Create time range.
                tFilter = (" WHERE ({tCol}{LEFT_BOUND}'{starttime}' AND "
                           "{tCol}{RIGHT_BOUND}'{stoptime}')").format(tCol=tCol,
                                                                      LEFT_BOUND=LEFT_BOUND,
                                                                      RIGHT_BOUND=RIGHT_BOUND,
                                                                      starttime=start_str,
                                                                      stoptime=stop_str)
            else:
                # Times are equal, use equality.
                tFilter = " WHERE ({tCol}='{starttime}')".format(tCol=tCol,
                                                                 starttime=start_str)

        elif (starttime or stoptime):
            raise ValueError(('If time information is given, it must be given for '
                              + 'both the starttime and stoptime.'))
        else:
            # Dates are None or 0, do no time filtering.
            tFilter = ''
    
        # Return the time filtering string.            
        return tFilter
    
    def idFilter(self, tFilter, table, starttime, stoptime, idCol,
                 tCol, nameCol):
        """Function to get an ID filter if dates are ambiguous.
        
        WARNING: if we're dealing with a crazy small recording interval, this
        function will probably use a lot of memory, as it needs to track
        names, times, and ID's.
        
        WARNING: this keys off of repeated times, and will throw an error
        if there is an interval which doesn't go evenly into 3600 seconds.
        """
                
        # Get connection and cursor.
        cnxn, cursor = self.getCnxnAndCursor()
        '''
        the following is problematic as it can't do further filtering. If 
        your table is tracking multiple things, you'll get timestamp 
        duplicates...
        
        q = ("SELECT {tCol} FROM {table} GROUP BY {tCol} HAVING "
             + "count(*) > 1").format(tCol=tCol, table=table)
        '''
        try:
            # Form query which returns duplicate time/name pairs for the given
            # time range.
            q = (("SELECT {}, {}, count(*) ".format(tCol, nameCol)
                  + "FROM {} ".format(table)
                  + tFilter + " "
                  + "GROUP BY {}, {} ".format(tCol, nameCol)
                  + "HAVING count(*) > 1")
                )
                
            # Query the database
            cursor.execute(q)
            
            if cursor.fetchone():
                # Query returned duplicates.
                duplicate = True
                # Exhaust the cursor
                for _ in cursor:
                    pass
            else:
                # Query returned no duplicates.
                duplicate = False
            # If we have a duplicate, get a string to filter entries by ID.
            # This assumes that with the exception of DST 'fall back' a
            # greater ID means a greater time.
            if duplicate:
                # Find the ID's based on the folds of the times. There are 
                # four possible cases:
                #    1) folds = (0, 0)
                #    2) folds = (0, 1)
                #    3) folds = (1, 1)
                #    4) folds = (1, 0)
                # It's worth noting that there can never be duplicate times for
                # cases 1 and 3, so we don't need to check for those.
                # We'll find the first repeated time, and take action from
                # there by finding the ID we need and creating a filter.
                folds = (starttime.fold, stoptime.fold)
                    
                # Create list of columns and fetch them.
                cols = [idCol, tCol, nameCol]
                idInd = 0
                tInd = 1
                nInd = 2
                colStr = ','.join(cols)
                q = ("SELECT {} FROM {}".format(colStr, table) + tFilter
                     + " ORDER BY {}".format(idCol))
                cursor.execute(q)
                
                # Figure out the 'time flip' to determine the idStr.
                
                # Create dictionary to track previous id's and t's for 
                # each name.
                d = {}
                # Track the associated names of repeated times.
                repeatList = []
                # Track the corresponding id's.
                repeatID = []
                # We need to track timedeltas and throw an error if either
                # they're irregulor or don't go into 3600 (sec in hour).
                delta = None
                # We need to track if all times are the same.
                allT = True
                t1 = None
                # Loop.
                for row in cursor:
                    # Save id, time, and name as variables for convenience.
                    tID = row[idInd]
                    t = row[tInd]
                    n = row[nInd]
                    
                    # If the 'name' isn't in the dictionary, add it.
                    if n not in d:
                        # Put 'name' as a key to a tuple of (id, t).
                        # NOTE that this matches idInd and tInd as defined
                        # above.
                        d[n] = [[tID], [t]]
                    else:
                        # Check for a repeated time
                        if t in d[n][tInd]:
                            # We've found a repeated time. 
                            # Put the ID in the list.
                            repeatID.append(tID)
                            # Put this name in the list and sort it.
                            repeatList.append(n)
                            repeatList.sort()
                            # Check to see if our repeatList contains all the
                            # keys of our dictionary.
                            keys = list(d.keys())
                            keys.sort()
                            if repeatList == keys:
                                # All 'names' have a repeated time. We've
                                # searched as far as we need to.
                                break
                        
                        # Append id
                        d[n][idInd].append(tID)
                        # Append t
                        d[n][tInd].append(t)
                    
                    # Ensure we're in ship-shape with time deltas.
                    if len(d[n][tInd]) > 1 and (delta is not None):
                        # Find the difference between the last two times.
                        td = (d[n][tInd][-2]
                              - d[n][tInd][-1]).total_seconds()
                        if (td > 0) and (3600 % td) != 0:
                            # This time difference doesn't go into 3600
                            # (sec in hour)
                            raise ValueError(("Bad interval! 3600 is not "
                                              "divisble by {}.").format(td)) 
                        elif td != delta:
                            # Inconsistent interval...
                            raise ValueError(("Inconsistent interval! "
                                              "{}s does not equal {}s"
                                              ).format(td, delta))
                    elif len(d[n][tInd]) > 1 and (delta is None):
                        # Get our first delta
                        delta = (d[n][tInd][-2]
                                 - d[n][tInd][-1]).total_seconds()
                                 
                    # Track if all times are the same.
                    if t1 is not None:
                        # Update allT.
                        allT = allT and (t == t1)
                    else:
                        # Get t1
                        t1 = t
                    
                    '''
                    # Check to see if this time is less than the previous
                    # time. If so, we've found the 'time flip'. Since
                    # we've added t to the list, we need to check the -2
                    # position.
                    if t <= d[n][tInd][-2]:
                        # At this point, 'name' must be in the dictionary. 
                        # Check to see if this "name's" iteration time is
                        # <= the previous iteratoin's time --> this 
                        # indicates a flip.
                         
                        # If the times have 'flipped,' we're done. The ID 
                        # of the previous loop iteration is our threshold
                    
                        # Break the for loop.
                        ID = d[row[nInd]]
                        break
                    
                    # Get the id.
                    ID = row[idInd]
                    '''
                
                # Form the ID query according to the case we're in.
                if (folds == (0, 1)) or (folds == (0, 0)):
                    # Here we're going from a 'non-folded' time (first 
                    # occurence of a possibly repeated time) to a 'folded' time
                    # (second occurence of a possibly repeated time), or not
                    # going into folded times at all.
                    # We need to look at values 'to the left'
                    # or 'before' this ID. In general, we'll use an inclusive 
                    # <=, but in the special case of all times being the same,
                    # we need to use '<'.
                    if allT:
                        # All times are the same - use an exclusive operator.
                        rb = '<'
                        # We want to use the minimum ID.
                        ID = min(repeatID)
                    else:
                        if folds == (0, 0):
                            # Not all times are the same, and we're staying
                            # in fold=0. A repeated time has fold=1. We do NOT
                            # want to include the value we repeated.
                            rb = '<'
                            ID = min(repeatID)
                        else:
                            # Use the RIGHT_BOUND.
                            rb = RIGHT_BOUND
                            # Whether we use 'max' or 'min' ID depends on rb
                            if rb == '<=':
                                ID = max(repeatID)
                            elif rb == '<':
                                ID = min(repeatID)
                            else:
                                assert False, "Bad RIGHT_BOUND"
                    
                    # Create the ID string.
                    idStr = " AND ({idCol}{rb}{ID})".format(idCol=idCol,
                                                            rb=rb,
                                                            ID=ID)
                elif (folds == (1, 0)) or (folds == (1, 1)):
                    # We need to look at values 'to the right'
                    # or 'after' this ID. For this case, since we've moved
                    # past the repeated times and are only looking 'to the
                    # right,' we don't need different logic for the two
                    # different fold cases like we did previously.
                    if allT:
                        # All times are the same. Use an inclusive operator
                        lb = '>='
                        # We want to use the minimum ID.
                        ID = min(repeatID)
                    else:
                        lb = LEFT_BOUND
                        # Choose ID based on lb
                        if lb == '>=':
                            ID = min(repeatID)
                        elif lb == '>':
                            ID = max(repeatID)
                        else:
                            assert False, "Why isn't the left bound '>=' or '>'?"
                        
                    idStr = " AND ({idCol}{lb}{ID})".format(idCol=idCol,
                                                            lb=lb,
                                                            ID=ID)
                else:
                    raise ValueError('Totally unexpected value for folds.')
                        
            else:
                # No time/name pair duplicates.
                idStr = ''
                
        finally:
            # Clean up.
            self.closeCnxnAndCursor(cnxn, cursor)
            
        return idStr

if __name__ == '__main__':
    dbObj = db(pool_size=10, database='zip')
    dbObj.truncateTableBySuffix(suffix='_2')
    '''
    cnxn1, crsr1 = dbObj.getCnxnAndCursor()
    try:
        crsr1.execute('SELECT * FROM voltage_a_3')
    except mysql.connector.ProgrammingError as err:
        # This is the error code for a non-existant table. We should use this
        # when dealing with group_recorders.
        if err.errno == 1146:
            print('success.')
        else:
            print('failure')
    except Exception as err:
        print(err)
    '''
        
    print('yay')
    #cnxn2, _ = dbObj.getCnxnAndCursor()
    #cnxn3, _ = dbObj.getCnxnAndCursor()
    '''
    cnxn = connect()
    dropAllTables(cnxn)
    cursor = cnxn.cursor()
    '''
    # dropTable(cursor, 'swing_benchmark')
    """
    r1 = sumMatrix(cursor=cursor, table='capcount_benchmark',
                  cols=['cap_A_switch_count', 'cap_B_switch_count',
                        'cap_C_switch_count'],
                  tCol='t',
                  starttime='2009-07-21 00:00:00',
                  stoptime='2009-07-21 00:15:00')
    
    r2 = sumMatrix(cursor=cursor, table='regcount_benchmark',
                  cols=['tap_A_change_count', 'tap_B_change_count',
                        'tap_C_change_count'], tCol='t',
                  starttime='2009-07-21 00:00:00',
                  stoptime='2009-07-21 00:15:00')
    
    print(r1)
    print(r2)
    """
        