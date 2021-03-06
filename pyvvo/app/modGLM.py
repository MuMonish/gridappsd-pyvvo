"""
Module to write setpoint commands to a GridLAB-D model (.glm)

NOTE: This module is in 'prototype' mode. As such, it certainly isn't
optimally efficient.

Created on Jul 27, 2017

@author: thay838

"""

import re
import os
import helper
import csv
import copy

# Time formatting:
TIME_FMT = "%Y-%m-%d %H:%M:%S"
# Define some constants for GridLAB-D model parsing.
REGOBJ_REGEX = re.compile(r'\bobject\b(\s+)\bregulator\b')
REGCONF_REGEX = re.compile(r'\bobject\b(\s+)\bregulator_configuration\b')
CAP_REGEX = re.compile(r'\bobject\b(\s+)\bcapacitor\b')
CLOCK_REGEX = re.compile(r'\bclock\b(\s*)(?={)')
TAPE_REGEX1 = re.compile(r'\bmodule\b(\s+)\btape\b(\s*);')
TAPE_REGEX2 = re.compile(r'\bmodule\b(\s+)\btape\b(\s*)(?={)')
SWING_REGEX = re.compile(r'\bbustype\b(\s+)\bSWING\b')
OBJ_REGEX = re.compile(r'\bobject\b')
NODE_REGEX = re.compile(r'\bobject\b(\s+)\bnode\b')
METER_REGEX = re.compile(r'\bobject\b(\s+)\bmeter\b')
SUBSTATION_REGEX = re.compile(r'\bobject\b(\s+)\bsubstation\b')
PROFILER_REGEX = re.compile(r'#(\s*)\bset\b(\s+)\bprofiler\b(\s*)=(\s*)[01]')
SUPPRESS_REGEX = re.compile(r'#(\s*)\bset\b(\s+)\bsuppress_repeat_messages\b(\s*)=(\s*)[01]')
POWERFLOW_REGEX = re.compile((r'\bmodule\b(\s+)\bpowerflow\b'))
CONTROL_REGEX = re.compile(r'(?<=(c|C)ontrol(\s))(\s*)(m|M)(a|A)(n|N)(u|U)(a|A)(l|L)(\s*);(\s*)//')
COMMENT_REGEX = re.compile(r'(\S+);')
TRIPLEX_LOAD_REGEX = re.compile(r'\bobject\b(\s+)\btriplex_load\b')
TRIPLEX_METER_REGEX = re.compile(r'\bobject\b(\s+)\btriplex_meter\b')
TRIPLEX_LOAD_OR_METER = re.compile(r'\bobject\b(\s+)((\btriplex_load\b)|(\btriplex_meter\b))')
OBJEND_REGEX = re.compile(r'(\s*)}(\s*)(;*)$')
VOLTDUMP_REGEX = re.compile(r'\bobject\b(\s+)\bvoltdump\b')
HOUSE_REGEX = re.compile(r'\bobject\b(\s+)\bhouse\b')
GROUP_RECORDER_REGEX = re.compile(r'\bobject\b(\s+)\bgroup_recorder\b')
OBJY_BY_NAME = r'\bname\b(\s+)("?){}("?)(\s*);'
VOLT_VAR_REGEX = re.compile(r'\bobject\b(\s+)\bvolt_var_control\b')
FROM_REGEX = r'\bfrom\b(\s+)("?){}("?)(\s*);'
# Expression below doesn't work since it can match multiple objects at once...
# OBJ_BY_TYPE_NAME = r'\bobject\b(\s+)\b{}\b(.+?)\bname\b(\s+)("?){}("?)(\s*);' # Use with re.DOTALL

def readModel(modelIn):
    '''Simple function to read file as string'''
    with open(modelIn, 'r') as f:
        s = f.read()
    return s

class modGLM:
    """"Class for reading GridLAB-D model and changing it.
    
        Some capabilities: regulator taps, capacitor switches, clock change,
            mysql connection, swing recorder
    """
    
    def __init__(self, strModel='', pathModelOut='', pathModelIn=''):
        """"Initialize class with input/output GridLAB-D models
        
        strModel should be a string representing a GridLAB-D model.
            Can be obtained by calling readModel function in this module.
            It will be modified to send new commands.
            
        pathModelOut is the path to the new output model.
        """

        # If strModel is defined, simply set it. Otherwise, read the path in.
        if strModel:
            # No need to do a copy here since strings are immutable in Python.
            self.strModel = strModel
        else:
            self.strModel = readModel(pathModelIn)
            
        self.pathModelIn = pathModelIn
        self.pathModelOut = pathModelOut
        
    def writeModel(self):
        """"Simple method to write strModel to file"""
        with open(self.pathModelOut, 'w') as f:
            f.write(self.strModel)
    
    def commandRegulators(self, reg):
        """"Function to change tap positions and control for regulators.
        
        INPUT: regulator dictionary as described in the gld module docstring
        
        OUTPUT: The GridLAB-D model in self.strModel is modified
        """
        # Loop through regulators
        for r in reg:
            # Find regulator by name.
            d = self.extractObjectByNameAndType(name=r, objRegEx=REGOBJ_REGEX,
                                                minLength=\
                                                    len('object regulator'))
            
            # Extract its configuration
            c = self.extractProperties(d['obj'], ['configuration'])
            
            # Loop through phases and add to property dictionary.
            regPropDict = {}
            confPropDict = {}
            for p in reg[r]['phases']:
                # Note that regulator objects have 'tap_A' etc. while
                # regulator_configuration objects have 'tap_pos_A' etc.
                
                # Use newState if it exists, otherwise use prevState
                if 'newState' in reg[r]['phases'][p]:
                    state = 'newState'
                else:
                    state = 'prevState'
                    
                regPropDict['tap_' + p] = reg[r]['phases'][p][state]
                confPropDict['tap_pos_' + p] = reg[r]['phases'][p][state]
                
            # Modify the object's properties.
            d['obj'] = self.modObjProps(objStr=d['obj'], propDict=regPropDict)
            
            # Splice in the modified object.
            self.replaceObject(d)
            
            # If we're given a control mode, use it.
            try:
                confPropDict['Control'] = reg[r]['Control']
            except KeyError:
                # If we don't have 'Control', nothing to do.
                pass
            
            # Extract the configuration.
            d2 = self.extractObjectByNameAndType(name=\
                                                    c['configuration']['prop'],
                                                 objRegEx=REGCONF_REGEX,
                                                 minLength=len(
                                                                ('object '
                                                                'regulator_'
                                                                'configuration'
                                                                )
                                                               )
                                                 )

            # Modify its properties.
            d2['obj'] = self.modObjProps(objStr=d2['obj'],
                                         propDict=confPropDict)
            
            # Splice in the modified object.
            self.replaceObject(d2)
        
    def commandCapacitors(self, cap):
        """"Function to change state of capacitors.
        
        INPUT: capacitor dictionary as described in the gld module docstring.
        
        OUTPUT: The GridLAB-D model in self.strModel is modified
        """
        
        # Loop through the capacitors
        for c in cap:
            # Find the object by name
            d = self.extractObjectByNameAndType(name=c, objRegEx=CAP_REGEX,
                                                minLength=\
                                                    len('object capacitor'))
            
            # Loop through phases and add to property dictionary.
            propDict = {}
            for p in cap[c]['phases']:
                # Note capacitor position are designated by 'switchA' etc.
                
                # Use newState if it exists, otherwise use prevState
                if 'newState' in cap[c]['phases'][p]:
                    state = 'newState'
                else:
                    state = 'prevState'
                
                propDict['switch' + p] = cap[c]['phases'][p][state]
            
            # If we're given a control mode, use it. 
            if 'control' in cap[c]:
                propDict['control'] = cap[c]['control']
                  
            # Modify the object's properties.
            d['obj'] = self.modObjProps(objStr=d['obj'], propDict=propDict)
            
            # Splice in the modified object.
            self.replaceObject(d)
            
    def updateClock(self, starttime=None, stoptime=None, timezone=None):
        """Function to set model time. If there's no clock object, it will be
            created.
        
        INPUTS:
            start: simulation start time
            stop: simulation stop time (stoptime in GLD). Same format as start.
            timezone: simulation time zone, specified like it is in GridLAB-D's
                tzinfo.txt file.
            
            NOTE: Timezones can be included in start and stop.
        """

        # Look for clock object
        clockMatch = CLOCK_REGEX.search(self.strModel)
        if clockMatch is not None:
            # If clock object exists, extract it.
            clock = self.extractObject(objMatch=clockMatch)
            
            # Build a dictionary of properties
            propDict = {}
            if starttime:
                propDict['starttime'] = "'{}'".format(starttime)
                
            if stoptime:
                propDict['stoptime'] = "'{}'".format(stoptime)
                
            if timezone:
                propDict['timezone'] = timezone
            
            # Modify properties.
            clock['obj'] = self.modObjProps(objStr=clock['obj'],
                                            propDict=propDict)
            
            # Splice in new clock object
            self.replaceObject(clock)
        else:
            # Build the clock string.
            clockStr = "clock {\n"
            
            # Add defined properties.
            if timezone:
                clockStr += "  timezone {};\n".format(timezone)
                
            if starttime:
                #clockStr += "  starttime '{}{}';\n".format(starttime,tzStr)
                clockStr += "  starttime '{}';\n".format(starttime)
                
            if stoptime:
                #clockStr += "  stoptime '{}{}';\n".format(stoptime,tzStr)
                clockStr += "  stoptime '{}';\n".format(stoptime)
                
            clockStr += "}\n"
            
            # Add clock to the beginning of the model.
            self.strModel = clockStr + self.strModel
            
    def updatePowerflow(self, solver_method='NR', line_capacitance='TRUE',
                        lu_solver='"KLU"'):
        """Update powerflow module or create it if it doesn't exit.
        
        INPUTS: 
            solver_method: FBS or NR. GS is deprecated. 
            line_capacitance: TRUE or FALSE
            lu_solver: Third party solver. KLU is fast. Download from here:
                https://github.com/gridlab-d/tools/tree/master/solver_klu
                To use native solver, pass None for lu_solver
        """
        pfMatch = POWERFLOW_REGEX.search(self.strModel)
        if pfMatch is not None:
            # If powerflow module definition exists, extract it.
            pf = self.extractObject(objMatch=pfMatch)
            # Modify the properties
            propDict = {'solver_method': solver_method,
                        'line_capacitance': line_capacitance}
            if lu_solver:
                propDict['lu_solver'] = lu_solver
                
            pf['obj'] = self.modObjProps(objStr=pf['obj'],
                                         propDict=propDict
                                         )
            # Splice in new powerflow object
            self.replaceObject(pf)
            
        else:
            # Create module string.
            s = (
                "module powerflow {{\n"
                "  solver_method {solver_method};\n"
                "  line_capacitance {line_capacitance};\n"
                ).format(solver_method=solver_method,
                         line_capacitance=line_capacitance)
                
            if lu_solver:
                s += '  lu_solver {};\n'.format(lu_solver)
                
            s += "};\n"
                
            # Add to model.
            self.strModel = s + self.strModel
            
    def addModule(self, module):
        """Super simple function to add simple module definition to model.
        """
        self.strModel = 'module {};\n'.format(module) + self.strModel
        
    def removeTape(self):
        """Method to remove tape module from model."""
        # First, look for simple version: 'module tape;'
        tapeMatch = TAPE_REGEX1.search(self.strModel)
        
        # If simple version is found, eliminate it
        if tapeMatch is not None:
            s = tapeMatch.span()[0]
            e = tapeMatch.span()[1]
            self.strModel = self.strModel[0:s] + self.strModel[e+1:]
        else:
            # Find "more full" definition of tape
            tapeMatch = TAPE_REGEX2.search(self.strModel)
            if tapeMatch is not None:
                # Extract the object
                tapeObj = self.extractObject(objMatch=tapeMatch)
                # Eliminate the object
                self.strModel = (self.strModel[0:tapeObj['start']]
                                 + self.strModel[tapeObj['end']+1:])
                
    def addDatabase(self, host='localhost', user='gridlabd',
                 password='gridlabd', database='gridlabd', port='3306',
                 socketname='/var/run/mysqld/mysqld.sock', tz_offset=0):
        """Method to add mysql database connection to model
        
        For now, it will simply be added to the beginning of the model.
        
        Note that GridLAB-D must be built with the mysql connector, the
        connector library must be on the system path, and to run a model the
        database server must be running.
        
        Two relevant GridLAB-D wiki pages:
        http://gridlab-d.shoutwiki.com/wiki/Mysql
        http://gridlab-d.shoutwiki.com/wiki/Database
        
        Add more database inputs as necessary.
            
        NOTE: On Brandon's VM, socket location is /var/run/mysqld/mysqld.sock,
        but the 'default' location is /tmp/mysql.sock
        """
        # Construct the beginning of the necessary string
        dbStr = (
            "object database {{\n"
            '   hostname "{host}";\n'
            '   username "{usr}";\n'
            '   password "{pwd}";\n'
            '   schema "{database}";\n'
            '   port {port};\n'
            '   tz_offset {tz_offset};\n'
            ).format(host=host, usr=user, pwd=password,
                     database=database, port=port, tz_offset=tz_offset)
        # If we're on Mac or Linux, need to include the sockenamae
        if os.name == 'posix':
            dbStr += 'socketname "{sock}";\n'.format(sock=socketname)
            
        self.strModel = dbStr + '}\n' + self.strModel
        
    def addClass(self, className, properties):
        """Method to add a custom class to the beginning of a .gld model
        
        INPUTS:
            className: class definition --> object className {
            properties: dictionary of names mapped to types. e.g. 
                {'value': 'double'}
        """
        # Build the start of the string 
        s = "class {} {{\n".format(className)
        
        # Loop over the dict and build up the string
        for n, t in properties.items():
            s += '  {} {};\n'.format(t, n)
            
        # Add string to model
        self.strModel = s + '}\n' + self.strModel
        
    def addObject(self, objType, properties, place='beginning', objStr=None):
        """Method to add an object to a .gld model
        
        INPUTS:
            objType: object defition --> object objType  {
            properties: dictionary of properties mapped to their values. e.g.
                {'name': 'zipload_schedule'}.
            place: 'beginning' or 'end' --> this is where object will be placed
            objStr: if objStr is None, object will be added to self.strModel.
                Otherwise, object will be nested into the given string object.
                
        NOTE: 'place' input does nothing if objStr is not None. Nested object
            will always be placed at the end of objStr
        """
        # Build the start of the string
        s = "object {} {{\n".format(objType)
        
        # Loop over the dict and build up the model
        for prop, val in properties.items():
            s += '  {} {};\n'.format(prop, val)
         
        # Close object. Include semi-colon just in case.    
        s += '};\n'
        
        if objStr is None:
            # Add string to model.
            if place == 'beginning':
                self.strModel = s +  self.strModel
            elif place == 'end':
                self.strModel = self.strModel + '\n' + s
            else:
                assert False, ("'place' inputs must be 'beginning' "
                               "or 'end.' '{}' was given.".format(place))
            return None
        else:
            # Add string to the end of the object.
            # Find the end.
            e = OBJEND_REGEX.search(objStr)
            # Splice new object into old object
            strOut = objStr[:e.span()[0]] + '\n' + s + e.group(0)
            return strOut
        
    def addTapePlayer(self, name, file, parent=None, prop=None, loop=0):
        """Method to add a player from the tape module to a model.
        
        INPUTS: see recorder in GridLAB-D Wiki. prop short for property -->
            (Python reserverd keyword)
            
        NOTE: maybe this should leverage addObject, since this only adds to the
        beginning of the file, which makes it all too easy to get GridLAB-D
        errors if tape isn't defined yet. The tricky bit is exposing the value
        via the class player part. 
        """
        # Build string
        s = (
            "object tape.player {{\n"
            "  name {name};\n"
            '  file "{file}";\n'
            "  loop {loop};\n"
            ).format(name=name, file=file, loop=loop)
        
        # Add parent if given.
        if parent:
            s += "  parent {};\n".format(parent)
        
        # Add property if given.
        if prop:
            s += "  property {};\n".format(prop)
        
        # Close the object.
        s += "}\n"
        
        # If neither parent nor property are given, we need to expose the 
        # player's value.
        if (not parent) and (not prop):
            s = "class player {\n  double value;\n}\n" + s
        
        # Add to model
        self.strModel = s + self.strModel
        
    def addLine(self, line):
        """Simple method to add a line to a model.
        """
        self.strModel = line + '\n' + self.strModel
        
        
    def repeatMessages(self, val=1):
        """Method to set 'suppress_repeat_messages'
        """
        # See if the model already has the constant
        m = SUPPRESS_REGEX.search(self.strModel)
        if m:
            # Simply replace last character.
            self.strModel = (self.strModel[0:(m.span()[1] - 1)] + str(val)
                             + self.strModel[m.span()[1]:])
        else:
            # Add to beginning of model.
            self.strModel = ('#set suppress_repeat_messages={}'.format(val) 
                             + '\n') + self.strModel
                         
    def toggleProfile(self, val=0):
        """Method to toggle the profiler
        """
        # See if the model has the profiler set already
        m = PROFILER_REGEX.search(self.strModel)
        if m:
            # Simply replace the last character with val.
            self.strModel = (self.strModel[0:(m.span()[1] - 1)] + str(val)
                             + self.strModel[m.span()[1]:])
        else:
            # Add the profiler string.
            self.strModel = ('#set profiler={}'.format(val) + '\n'
                             + self.strModel)
        
    def findSwing(self):
        """Method to find the name of the swing bus.
        
        Returns name of the swing bus.
        
        IMPORTANT NOTE: This WILL NOT WORK if there are nested objects in the
            swing node object.
            
        IMPORTANT NOTE 2: Multiple swing buses will also ruin this.
            
        TODO: Rather than finding the swing by traversing the model, this
            should be pulled from the CIM.
            
        TODO: Handle multiple swing case
        """
        # Find the swing node
        swingMatch = SWING_REGEX.search(self.strModel)
        
        # Find the closest open curly brace:
        sInd = swingMatch.span()[0]
        c = self.strModel[sInd]
        while c != '{':
            sInd -= 1
            c = self.strModel[sInd]
        
        # Find the closest close curly brace:
        eInd = swingMatch.span()[1]
        c = self.strModel[eInd]
        while c != '}':
            eInd += 1
            c = self.strModel[eInd]
            
        # To ensure eInd includes the curly brace, add one to it.
        eInd += 1
        
        # Extract the name of the swing
        sName = self.extractProperties(self.strModel[sInd:eInd+1], ['name'])
        
        # Find the true beginning of the node by finding the nearest 'object'
        swingIter = OBJ_REGEX.finditer(self.strModel, 0, sInd)
        
        # Loop over the iterator until the last one. This feels dirty.
        for m in swingIter:
            pass
        
        # Extract the starting index of the object.
        sInd = m.span()[0]
        
        return {'name': sName['name']['prop'], 'start': sInd, 'end': eInd,
                'obj': self.strModel[sInd:eInd]}
    
    def meterSwing(self):
        """Ensure we have a meter for the swing node of our model.
        
        NOTE: swing will be changed from node to meter if it's a node
        
        INPUTS:
            interval: interval (seconds) to record
            suffix: table name will be 'swing_' + suffix
        
        OUTPUT: dict in form of {'table': tableName,
                                 'swingColumns': swingColumns}
                where swingColumns are the names of the fields in the table.
        """
        # Find the name and indices of the swing.
        swing = self.findSwing()
        
        # Find out if the swing is a node, meter, or substation object
        nodeMatch = NODE_REGEX.match(swing['obj'])
        meterMatch = METER_REGEX.match(swing['obj'])
        substationMatch = SUBSTATION_REGEX.match(swing['obj'])
        
        if nodeMatch is not None:
            # Replace 'object node' with 'object meter'
            swing['obj'] = (swing['obj'][0:nodeMatch.span()[0]] 
                             + 'object meter' 
                             + swing['obj'][nodeMatch.span()[1]:])
            
            # Splice in the new object
            self.replaceObject(swing)
            meterName = swing['name']
            
        elif substationMatch is not None:
            # Add a meter to track the substation.
            # Extract the phase and nominal voltage properties
            props = self.extractProperties(objString=swing['obj'],
                                           props=['phases', 'nominal_voltage'])
            
            # Get the properties into a usable dictionary
            propDict = {}
            for p in props:
                propDict[p] = props[p]['prop']
                
            # Add 'parent' and 'name'
            propDict['parent'] = swing['name']
            propDict['name'] = 'swing_meter'
            meterName = propDict['name']
            
            # Add a meter object
            self.addObject(objType='meter', properties=propDict, place='end')
            
            # We've added the meter, but now we need to take all objects 
            # connected to the substation node and connect them to the meter
            # instead of the substation object.
            
            # First, compile the regular expression
            regExp = re.compile(FROM_REGEX.format(swing['name']))
            
            # Replace all connections to the swing with connections to the
            # meter.
            self.strModel = regExp.sub('from {};'.format(meterName),
                                       self.strModel)
            
        elif meterMatch is not None:
            meterName = swing['name']
        else:
            # Raise error
            raise UnexpectedSwingType()
        
        return meterName
    
    def addGroupToObjects(self, objectRegex, groupName, nameList=None):
        """Method to add a groupid to a given type of object.
        
        INPUTS: 
            objectRegex: compiled regular expression for the object type
                desired.
            groupName: desired groupid to be added to objects.
            nameList: Optional. If provided, should be a list of object
                names. Only objects with their name in the list will be
                modified.
        """
        # Make a copy of the list, since we'll be removing items as we go.
        nameListC = copy.copy(nameList)
        
        # Get the first match.
        m = objectRegex.search(self.strModel)
        
        # Loop over all the matches
        while m:
            # Extract the object
            obj = self.extractObject(objMatch=m)
            
            if nameList is not None:
                # Extract the name
                n = self.extractProperties(obj['obj'], ['name'])
                
                try:
                    # Remove the name from our list.
                    nameListC.remove(n['name']['prop'])
                except ValueError:
                    # Name not in the list. Get the next object match and carry
                    # on.
                    m = objectRegex.search(self.strModel, 
                                           m.span()[0] + len(obj['obj']))
                    continue
            
            # Add a groupid.
            obj['obj'] = self.modObjProps(obj['obj'], {'groupid': groupName})
            
            # Replace the previous object with the new one.
            self.replaceObject(obj)
            
            # Get the next match, offsetting by length of new object.
            m = objectRegex.search(self.strModel,
                                   m.span()[0] + len(obj['obj']))
    
    def recordTriplex(self, suffix, interval=60):
        """Method to add a recorder for each 'triplex_load' object.
        
        For now, this will only look for triplex_load objects and record the
        voltage_12 property.
        
        INPUTS:
            table: table to put recorded results in.
            interval: interval at which to record results.
        """
        # Define table name
        table = 'triplex_' + str(suffix)
        
        # Get iterator of triplex matches. Note that since we tack recorders
        # onto the end, we don't screw up the indices in each match's span
        # property.
        matches = TRIPLEX_LOAD_REGEX.finditer(self.strModel)
        
        # Loop over each triplex load, and add a recorder for each one.
        for m in matches:
            # Extract the object:
            tObj = self.extractObject(objMatch=m)
            
            # Get the name
            n = self.extractProperties(tObj['obj'], ['name'])
            name = n['name']['prop']
            
            # Add a mysql recorder
            self.addMySQLRecorder(parent=name, table=table,
                                  propList=['voltage_12'], interval=interval)
            
        # Return the table name and columns
        return {'table': table, 'columns': ['voltage_12'], 'interval':interval}
    
    def addTriplexMeters(self):
        """Method to add a triplex_meter to each triplex_load
        """
        # Get iterator of triplex matches. Note that since we'll tack meters
        # onto the end, we don't screw up the indices in each match's span
        # property.
        matches = TRIPLEX_LOAD_REGEX.finditer(self.strModel)
        
        # Loop over each triplex load, and add a recorder for each one.
        for m in matches:
            # Extract the object:
            tObj = self.extractObject(objMatch=m)
            
            # Get the name, phases, and nominal_voltage
            n = self.extractProperties(tObj['obj'], ['name', 'phases',
                                                     'nominal_voltage'])
            
            # Add a triplex meter to the end of the model
            self.addObject(objType='triplex_meter',
                           properties = {'name': n['name']['prop'] + '_meter',
                                         'parent': n['name']['prop'],
                                         'phases': n['phases']['prop'],
                                         'nominal_voltage': n['nominal_voltage']['prop']},
                           place='end')
        
    def addMySQLRecorder(self, table, propList, interval,
                         header_fieldnames='name', options=None, mode=None,
                         limit=-1, parent=None, group=None,
                         query_buffer_limit=None):
        """Method to add database recorder to end of model
        
        INPUTS:
            parent: name of object to record
            table: database table to save outputs in
            propList: list of properties to record. Ex: ['power_A',
                'power_B', 'power_C']
            interval: interval in seconds to record
            header_fieldnames: Specifies the header data to store in each
                record inserted. Valid fieldnames are "name", "class",
                "latitude", and "longitude"
            options: PURGE|UNITS - PURGE drops and recreates table on init.
                NOTE: Brandon found PURGE to be VERY slow experimentally for 
                multiple recorders sharing a table. Table should be truncated
                before use OUTSIDE of GridLAB-D. Maybe all this is true...
            limit: Maximum number of rows. Negative means no limit.
            
        Add more properties as needed.
        """
        # Add formatted string to end of model.
        recorder = ('\n'
                    'object mysql.recorder {{\n'
                    '  table "{table}";\n'
                    '  property {propList};\n'
                    '  interval {interval};\n'
                    '  header_fieldnames "{header_fieldnames}";\n'
                    '  limit {limit};\n'
                    ).format(table=table,
                             propList=('"' + ','.join(propList) + '"'),
                             interval=interval,
                             header_fieldnames=header_fieldnames,
                             limit=limit)
        
        # Add options if included
        if options:
            recorder += '  options {options};\n'.format(options=options)
            
        # Add mode if included
        if mode:
            recorder += '  mode {mode};\n'.format(mode=mode)
            
        # If given a parent
        if parent:
            recorder += '  parent {parent};\n'.format(parent=parent)
            
        # Add group if included
        if group:
            recorder += '  group "groupid={group}";\n'.format(group=group)
            
        if query_buffer_limit:
            recorder += '  query_buffer_limit {};\n'.format(query_buffer_limit)
            
            
        self.strModel = self.strModel + recorder + '}'
        
    def addTapeGroup_Recorder(self, group, prop, interval, file,
                              limit=-1, complex_part=None):
        """Method to add a group_recorder object from the tape module.
        
        INPUTS:
            group: groupid of the objects to record. NOTE: GridLAB-D can do 
                things like "class=meter", but this method will be hard-coded
                to use "groupid=..."
            prop: property to measure (property is reserved built-in)
            interval: interval to record (s)
            file: name of output file
            complex_part: If desired, complex part of imaginary value to record
            limit: Maximum number of rows. Negative means no limit.
        """
        # Create first part of string
        recorder = ('\n'
                    'object tape.group_recorder {{\n'
                    '  group "groupid={group}";\n'
                    '  property {prop};\n'
                    '  interval {interval};\n'
                    '  file "{file}";\n'
                    '  limit {limit};\n'
                    ).format(group=group, prop=prop, interval=interval,
                             file=file, limit=limit)
        
        # Add optional pieces
        if complex_part is not None:
            recorder += '  complex_part "{complex_part}";\n'.format(complex_part=complex_part)
            
        # Add to the model
        self.strModel += recorder + '}'
        
    def addMySQLGroup_Recorder(self, group, prop, interval, table,
                               limit=-1, complex_part=None, mode=None):
        """Method to add a group_recorder object from the tape module.
        
        TODO: Make this better after documentation has been written for the 
            mysql group_recorder
            
        INPUTS:
            group: groupid of the objects to record. NOTE: GridLAB-D can do 
                things like "class=meter", but this method will be hard-coded
                to use "groupid=..."
            prop: property to measure (property is reserved built-in)
            interval: interval to record (s)
            table: name of table. Note that based on the column limit there may
                be multiple tables which use this prefix.
            complex_part: LIST of complext parts to record. The MySQL group
                recorder can measure multiple complex parts. It'll simply add
                somethign like '_REAL' to the column name. 
        """
        # Create first part of string
        recorder = ('\n'
                    'object mysql.group_recorder {{\n'
                    '  group "groupid={group}";\n'
                    '  property {prop};\n'
                    '  interval {interval};\n'
                    '  table "{table}";\n'
                    '  limit {limit};\n'
                    ).format(group=group, prop=prop, interval=interval,
                             table=table, limit=limit)
        
        # Add optional pieces
        if complex_part is not None:
            # complex parts are seperated by a pipe.
            complexStr = ' | '.join(complex_part)
            recorder += '  complex_part "{}";\n'.format(complexStr)
            
        if mode is not None:
            recorder += '  mode {};\n'.format(mode)
            
        # Add to the model
        self.strModel += recorder + '}'
            
    def replaceObject(self, objDict):
        """Function to replace object in the model string with a modified
        one.
        
        INPUTS: objDict: object dictionary in the format returned by 
            modGLM.extractObject
            
        OUTPUS: directly modifies self.strModel to replace object with new one
        """
        self.strModel = (self.strModel[0:objDict['start']] + objDict['obj']
                         + self.strModel[objDict['end']:])
                                
    @staticmethod
    def modObjProps(objStr, propDict):
        """"Function to modify an object's properties"""
        
        # Loop through the properties and modify/create them
        for prop, value in propDict.items():
            try:
                propVal = modGLM.extractProperties(objStr, [prop])
            except PropNotInObjError:
                # If the property doesn't exist, append it to end of object
                objStr = (objStr[0:-1] + "  " + prop + " " + str(value)
                          + ";\n" + objStr[-1])
            else:
                # Replace previous property value with this one
                objStr = (objStr[0:propVal[prop]['start']] + " " + str(value)
                          + objStr[propVal[prop]['end']:])
                         
        # Return the modified object
        return objStr
    
    def extractObjectByNameAndType(self, *, name, objRegEx, minLength=1):
        """Function to extract a GridLAB-D object given its name and type.
            Nested objects will be included.
            
        INPUTS:
            name: name of the object.
            objRegEx: pre-compiled regular expression for the desired object
                type.
            minLength: minimum possible match length of the objRegEx. This
                will save a few iterations - not critical.
        """
        # Find the name line.
        m = re.search(OBJY_BY_NAME.format(name), self.strModel)
        
        # Raise exception if not found.
        if not m:
            raise ObjNotFoundError(obj=name, model=self.pathModelIn)
        
        # Extract the starting index of the match. This represents the ending 
        # index of the search for the beginning of the associated object.
        eInd = m.span()[0]
        
        # Initialize the starting index of the search for the associated
        # object.
        sInd = eInd - minLength
        
        # Work backward until a match on the objRegEx is found.
        m2 = objRegEx.match(self.strModel, sInd, eInd)
        while (m2 is None) and (sInd >= 0):
            # Decrement the starting index 
            sInd -= 1
            # Look for a match again
            m2 = objRegEx.match(self.strModel, sInd, eInd)
            
        # If sInd < 0, the object definition doesn't exist.
        if sInd < 0:
            raise ObjNotFoundError(obj=name, model=self.pathModelIn)
            
        # Extract and return the full object.
        out = self.extractObject(startInd=sInd)
        return out
            
                
    def extractObject(self, *, objMatch=None, startInd=None):
        """"Function to extract a GridLAB-D object from the larger model.
        
        INPUTS:
            NOTE: Only *one* of objMatch or startInd should be provided.
            objMatch: a match object returned from the re package after calling
                re.search or one member of re.finditer.
            startInd: the starting index of the object.
        
        OUTPUT:
        dict with three fields: 'start,' 'end,' and 'obj'
            start indicates the starting index of the object in the full model
            end indicates the ending index of the object in the full model
            
        """
        
        # If objMatch is provided, extract the starting index. Otherwise, use
        # provided index
        if objMatch:
            # Extract the starting index of the regular expression match.
            startInd =  objMatch.span()[0]
        elif startInd is None:
            assert False, "If objMatch is not provided, startInd must be."
        
        # Initialize the ending index (to be incremented in loop).
        endInd = startInd
        # Initialize counter for braces (to avoid problems with nested objects)
        braceCount = 0
        
        for c in self.strModel[startInd:]:
            # Increment the index
            endInd += 1
            
            # To avoid troubles with nested objects, keep track of braces
            if c == '{':
                braceCount += 1
            elif c == '}':
                braceCount -= 1
                
            # Break loop if c is a closing curly brace. Since the index is
            # incremented first, we ensure the closing bracket is included.
            if c == '}' and braceCount == 0:
                break
            
        # We now know the range of this object. Extract it.
        objStr = self.strModel[startInd:endInd]
        out = {'start':startInd, 'end':endInd, 'obj':objStr}
        return out
    
    @staticmethod
    def extractProperties(objString, props):
        """"Function to extract properties from a string of an object.
        
        INPUTS:
            objString: string representing object
            props: list of desired properties to extract
            
        OUTPUT: 
            dict mapping props to extracted values
        """
        # Initialize return
        outDict = dict()
        
        # Loop over the properties
        for p in props:
            # Create regular expression to extract the property after the 
            # property name and before the semi-colon.
            exp = r'(?<=\b' + p + r'\b)(\s+)(.*?)(?=;)'
            prop = re.search(exp, objString)
            
            # If the property was not found, raise an exception.
            # TODO: make exception better
            if not prop:
                raise PropNotInObjError(obj = objString, prop = p)
            
            # Get property value and assign to output dictionary. Note that
            # we're stripping whitespace then quotes.
            propStr = prop.group().strip().strip('"')
            outDict[p] = {'prop': propStr, 'start': prop.span()[0],
                          'end': prop.span()[1]} 
            
        return outDict
    
    @staticmethod
    def addFileSuffix(inPath, suffix='', outDir=None):
        """Simple function to create a filepath to a file with _suffix 
            added and in the desired directory.
        """
        # Get the filename and extension of original file
        fParts = os.path.splitext(os.path.basename(inPath)) 
        
        # If outDir isn't included, make file path point to directory of inPath
        if outDir is None:
            outDir = os.path.dirname(inPath)
            
        if suffix != '':
            suffix = '_' + str(suffix)
        
        # Define the output path by adding suffix    
        outPath = os.path.join(outDir, fParts[0] + str(suffix) + fParts[1]).replace("\\", "/")
        
        # Done.
        return outPath
    
    def setupModel(self, starttime=None, stoptime=None, timezone=None,
                   vSource=None, playerFile=None, database=None,
                   profiler=0, triplexGroup=None, triplexList=None,
                   powerflowFlag=False):
        """Function to add the basics to get a running model. Designed with 
        the output from Tom McDermott's CIM exporter in mind.
        
        NOTE: most of these functions tack lines onto the beginning of the
            file. That's why things might feel like they're in reverse order.
            
        TODO: Document inputs when this is done. Database inputs are going to
            need to be added.
        """
        # Relax naming rules
        self.addLine(line='#set relax_naming_rules=1')
        
        # Add definition of source voltage
        if vSource:
            self.addLine(line='#define VSOURCE={}'.format(vSource))
        
        # Add player details.
        if playerFile:
            # Add a player.
            self.addTapePlayer(name='zip_sched', parent='zipload_schedule',
                                   prop='value', file=playerFile, loop=1)
            # Add hacky object (working around mysql player not being able to 
            # expose 'value', and working around mysql + tape coexistence
            # issues)
            self.addObject(objType='pOut',
                           properties={'name': 'zipload_schedule'})
            # Add hacky class
            self.addClass(className='pOut', properties={'value': 'double'})
            
            # Since we're using a player file, we'll need the tape module.
            self.addModule('tape')
        
        # Add database and MySQL module if necessary.
        if database:
            self.addDatabase(**database)
            # Add mysql modules
            self.addModule('mysql')
            
        # Update powerflow (add if it doesn't exist).
        if powerflowFlag:
            self.updatePowerflow()
            
        # Ensure we're suppressing messages.
        self.repeatMessages()
        # Set profiler.
        self.toggleProfile(profiler)
        
        # Update the clock (add if it doesn't exist).
        if starttime or stoptime or timezone:
            self.updateClock(starttime=starttime, stoptime=stoptime,
                                 timezone=timezone)
            
        # Add groupid to triplex_meter objects
        if triplexGroup:
            self.addGroupToObjects(objectRegex=TRIPLEX_METER_REGEX,
                                   groupName=triplexGroup,
                                   nameList=triplexList)
            
        # If the swing bus isn't a meter object, we need to add a meter to it
        # so we can measure the desired properties.
        swingMeterName = self.meterSwing()
        
        return swingMeterName
        '''
        # Add group_recorders for triplex group. Note that we have to create
        # two recorders - one for phase 1, one for phase 2. We'll assume
        # there's no need to monitor neutral currents here.
        if triplex_group_recorder:
            # We're going to make a table for each phase. Note that the MySQL
            # group recorder will make tables voltage_1_0, voltage_1_1, etc.
            phases = ['voltage_1', 'voltage_2']
            prop = ['measured_' + s for s in phases]
            # Loop over the phases
            for ind in range(len(phases)):
                # Add a group recorder
                self.addMySQLGroup_Recorder(group=triplex_group_recorder['group'],
                                            prop=prop[ind],
                                            interval=triplex_group_recorder['interval'],
                                            table=phases[ind],
                                            limit=triplex_group_recorder['limit'],
                                            complex_part=triplex_group_recorder['complex_part'])
                
        else:
            phases = None
        
        return phases
        '''
        
    def switchControl(self):
        """If file has commented out control options, use them instead.
        Example: 'Control MANUAL; // OUTPUT_VOLTAGE;' will be replaced with
        'Control OUTPUT_VOLTAGE;'
        """
        # Find the first control match.
        m = CONTROL_REGEX.search(self.strModel)
        
        # Loop until we've found all CONTROL_REGEX instances.
        while m:
            # Get the indices of the match.
            sInd = m.span()[0]
            eInd = m.span()[1]
            # See if there is another control option after the comment
            m2 = COMMENT_REGEX.search(self.strModel, eInd)
            # If there's another control option, remove the first match to
            # splice in the new one
            if m2:
                self.strModel = self.strModel[:sInd] + self.strModel[eInd:]
                
            # Find the next match, starting with eInd
            # NOTE: starting with eInd may not be 100% robust, but it shouldn't
            # ever be a problem.
            m = CONTROL_REGEX.search(self.strModel, eInd)
            
    def addMetricsCollectorWriter(self, interval=60, suffix=''):
        """Function to add a metrics collector writer.
        """
        # Define filename
        if suffix:
            suffix = '_' + suffix
            
        fName = 'metrics' + suffix + '.json'
        
        # Create object
        self.addObject(objType='metrics_collector_writer', place='end',
                       properties={'interval': interval, 'filename': fName})
        
        # Return the name
        return fName
    
    def addMetricsCollectors(self, interval=60):
        """Function to add metrics collectors to all triplex_meter objects.
        
        If needed, this can easily be adopted to a different type of object.
        
        NOTE: Make sure to add meters first.
        """
        # Find the first triplex_meter.
        m = TRIPLEX_METER_REGEX.search(self.strModel)
        
        # Loop over all the matches
        while m:
            # Extract the object
            tObj = self.extractObject(objMatch=m)
            
            # Splice in the metrics collector
            tObj['obj'] = self.addObject(objType='metrics_collector',
                                    properties = {'interval': interval},
                                    objStr=tObj['obj'])
            
            # Replace the previous object with the new one.
            self.replaceObject(tObj)
            
            # Get the next match, offsetting by length of new object.
            m = TRIPLEX_METER_REGEX.search(self.strModel,
                                          m.span()[0] + len(tObj['obj']))
    
    '''
    def addVoltDumps(self, num, group, mode='polar', outDir=None):
        """Function to add voltage dumps for a given group, times, and interval
        
        NOTE: There's an important assumption here - models will be run in
            a directory that doesn't contain other running models.
            
        """
        
        # To make things simpler and more clear, track file names.
        n = []
        c = 0
        for _ in range(num):
            f = 'vDump_' + str(c) + '.csv'
            # If outDir is specified, add it to filename
            if outDir:
                f = os.path.join(outDir, f).replace("\\", "/")
            # Add the file to the list.    
            n.append(f)
            self.addObject(objType='voltdump',
                           properties={'group': group,
                                       'filename': '"{}"'.format(n[-1]),
                                       'mode': mode},
                           place='end'
                          )
            c += 1
            
        return(n)
    '''
    
    '''
    def addRuntimeToVoltDumps(self, starttime, stoptime, interval=60):
        """Function to add runtimes to existing voltage dump objects.
        """
        
        # Find a voltdump object.
        m = VOLTDUMP_REGEX.search(self.strModel)
        
        # Loop over all the matches to add runtimes.
        while m and (starttime <= stoptime):
            # Extract the object
            obj = self.extractObject(objMatch=m)
            
            # Add the runtime.
            start_str = starttime.strftime(util.constants.DATE_TZ_FMT)
            obj['obj'] = self.modObjProps(obj['obj'],
                                          {'runtime': "'{}'".format(start_str),
                                          }
                                         )
            
            # Replace the previous object with the new one.
            self.replaceObject(obj)
            
            # Increment the time.
            # NOTE: This sucks. But fortunately, GridLAB-D will correct bad 
            # times. Like 2am PST turns to 3am PDT. It works for fall back too.
            starttime += datetime.timedelta(seconds=interval)
            
            # Get the next match, offsetting by length of new object.
            m = VOLTDUMP_REGEX.search(self.strModel,
                                          m.span()[0] + len(obj['obj']))
    '''
            
    def removeObjectsByType(self, typeList=[], objStr='object'):
        """Function to simply remove objects by type.
        
        INPUTS:
            typeList: list of strings containing object types to remove
        """
        
        # Loop over each type
        for t in typeList:
            # Construct regular expression to find the beginning of this type
            exp = re.compile(r'\b' + objStr + r'\b(\s+)\b' + t + r'\b')
            
            # Find the first object
            m = exp.search(self.strModel)
            
            # Loop over all matches and eliminate the objects.
            while m:
                # Extract the object
                obj = self.extractObject(objMatch=m)
                
                # Replace the object string with the empty string
                obj['obj'] = ''
                
                # Check to see if the object ends with a semi-colon. If so,
                # make sure it's included for removal
                if self.strModel[obj['end']] == ';':
                    # Increment ending index so semi-colon gets removed.
                    obj['end'] += 1
                
                # Eliminate the object from the model
                self.replaceObject(obj)
                
                # Find the next match
                m = exp.search(self.strModel)
                
    def addVVO(self, starttime):
        """Very hard-coded function to add a volt_var_control object to the 
        R2-12-47-2 feeder. Values from SGIG analysis, using technology 1 (t1)
        
        NOTE: In order to ensure tap counting is correct, we need to hack 
        things to include a player, which switches the control to 'ACTIVE'
        after one second of simulation. Be careful - we're starting the 
        control_method at STANDBY. If player stuff fails, this thing will do
        absolutely nothing.
        
        TODO: make modular
        
        KEY ASSUMPTION: If a volt_var_control object already exists, the only
        necessary task is to write a new player file.
        """
        
        # Since we have to add a player, we need a defined output model so we
        # can write a player to that directory.
        if not self.pathModelOut:
            # Poor error handling, but oh well
            raise Exception(('modGLM object does not have pathModelOut '
                             'defined! This is necessary for addVVO.'))
        
        # No matter what, we need to create a player file for VVO to prevent
        # things from double-operating at model startup.    
        file = 'volt_var_control.player'
        
        m = VOLT_VAR_REGEX.search(self.strModel)
        if not m:
            name = 'volt_var_control'
            # Create dictionary of properties
            propDict = {
                'name': name,
                'control_method': 'STANDBY',
                'capacitor_delay': 60.0,
                'regulator_delay': 60.0,
                'desired_pf': 0.99,
                'pf_phase': 'ABC',
                'd_max': 0.8,
                'd_min': 0.1,
                'substation_link': '"substation_transformer"',
                'regulator_list': '"R2-12-47-2_reg_1,R2-12-47-2_reg_2"',
                'capacitor_list': '"R2-12-47-2_cap_1,R2-12-47-2_cap_2,R2-12-47-2_cap_3,R2-12-47-2_cap_4"',
                'voltage_measurements': '"R2-12-47-2_node_146_2,1,R2-12-47-2_node_240,2,R2-12-47-2_node_103,2,R2-12-47-2_node_242,2"',
                'maximum_voltages': 9000.00,
                'minimum_voltages': 5000.00,
                'max_vdrop': 50,
                'high_load_deadband': 60.00,
                'desired_voltages': 7080.00,
                'low_load_deadband': 60.00
                }
            
            # Add the object to the end of the model.
            self.addObject(objType='volt_var_control', properties=propDict,
                               place='end')
            
            # Check for the tape module. If it doesn't exist, add it.
            t = self.checkForModule(module='tape')
            if t is None:
                # Add tape module
                self.addModule(module='tape')
                
            # Now we have to do the gross dirty work of writing a player file
            # and creating a player
            propDict = {'parent': name, 'property': 'control_method',
                        'file': file}
            self.addObject(objType='tape.player', properties=propDict,
                       place='end')
        
        # Create string for player file
        s = '{}, STANDBY\n+1s, ACTIVE'.format(starttime)
        
        # Create full path to player file, using output model's directory
        fullfile = (os.path.dirname(self.pathModelOut).replace('\\', '/')
                    + '/' + file)
        
        # Write string to file
        with open(fullfile, 'w') as f:
            f.write(s)
            
        return os.path.basename(fullfile)
            
    def addZIP(self, zipDir, starttime, stoptime, avgFlag=False):
        """Function to read the correct zip model file and apply zip loads to
        meters.
        
        NOTE: At the moment, this will only work for triplex_meters. Plenty
        of hard-coding in here.
        
        NOTE: For the R2-12-47-2 experiment (and any other populated feeders), 
        the triplex_meter objects must be REPLACED with triplex_load objects.
        It doesn't work to parent a triplex_load to these triplex_meters - it 
        creates grandchildren which isn't allowed in GridLAB-D at the moment.
        Another option would be to trace up the tree and add the triplex_load
        further up, but I don't see a point to that now.
        
        avgFlag: Files are different if we're using a two week window instead
            of seasonal fits. False to use seasonal fits, True to use two week
            window files.
        """
        # First, get time information. This function will error if interval
        # isn't proper. Pretty rudiemntary for now, but hey, it'll work :)
        t = helper.timeInfoForZIP(starttime=starttime, stoptime=stoptime)
        
        if not avgFlag:
            
            # Craft the filename
            file = (zipDir.replace('\\', '/') + '/' + 'ZIP_S' + str(t['season'])
                    + '_' + t['wday'] + '_' + str(t['hour']) + '.csv')
        else:
            # Infer folder name from date.
            folder = starttime.strftime('%Y-%m-%d')
            file = (zipDir.replace('\\', '/') + '/' + folder + '/ZIP_'
                    + str(t['hour']) + '.csv')
            
        
        # Hard code phase information
        phase = '_12'
        
        # Get a .csv reader
        with open(file, newline='') as f:
            r = csv.reader(f, delimiter=',')
            # Discard rows until the first element is '# load'
            row = r.__next__()
            while row[0].lstrip() != '# load':
                row = r.__next__()
            
            # Save this row, it has our headers.
            headers = row
            
            # Removed 'to-do' note since this is going to change once the 
            # function to get zip coefficients is complete
            # Should we use a DictReader? Would the be more efficient?
            # We're building our own dict each time here...
            
            # Loop over each row
            for row in r:
                # HARD-CODING: extract the meter name
                name = row[0].lstrip()
                
                # Initialize property dictionary
                propDict = {}
                
                # Loop over the rest of the data and add to dictionary
                for ind in range(1, len(headers)):
                    propDict[(headers[ind].lstrip() + phase)] = \
                        row[ind].lstrip()
                    
                # Extract the triplex_meter object by name
                tObj = \
                    self.extractObjectByNameAndType(name=name,
                                                    objRegEx=TRIPLEX_LOAD_OR_METER)
                    
                # Replace the object's type
                tObj['obj'] = re.sub(TRIPLEX_METER_REGEX,
                                     'object triplex_load', tObj['obj'])
                
                # Add the ZIP properties
                tObj['obj'] = self.modObjProps(objStr=tObj['obj'],
                                               propDict=propDict)
                
                # Splice in the new object
                self.replaceObject(objDict=tObj)
        
    def checkForModule(self, module):
        """Simple function to check if a module is in a model. Returns None if
        the module doesn't exist, returns a regular expression match if the
        module does exist
        """
        # Build regular expression
        s = r'\bmodule\b(\s+){}'.format(module) + r'(\s*)[{;]'
        # Search model and return
        out = re.search(s, self.strModel)
        return out
            
class Error(Exception):
    """"Base class for exceptions in this module"""
    pass

class ObjNotFoundError(Error):
    """"Exception raised if requested object doesn't exist in model
    
    Attributes:
        obj: requested object
        model: model file in question
        message: simple message
    """
    def __init__(self, obj, model):
        self.obj = obj
        self.model = model
        self.message = "The object '" + obj + "' doesn't exist in " + model
        
    def __str__(self):
        return(repr(self.message))
        
class PropNotInObjError(Error):
    """"Exception raised if an object doesn't have the property required
    
    Attributes:
        obj: object in which a property is being looked for in
        prop: property being searched for in an object
        model: model file being searched
        message: simple message
    """
    def __init__(self, obj, prop, model=''):
        self.obj = obj
        self.prop = prop
        self.model = model
        self.message = ("The property '" + prop + "' doesn't exist in "
                        + "the object '" + obj + "' in the model " + model)
            
    def __str__(self):
        return(repr(self.message))
    
class UnexpectedSwingType(Error):
    """Exception raised if the swing object isn't a node, meter, or substation.
    """
    def __init__(self):
        self.message = ("The given SWING object isn't a node, meter, or "
                        + "substation object. This wasn't anticipated.")
        
    def __str__(self):
        return(repr(self.message))
    
if __name__ == '__main__':
    obj = modGLM(pathModelIn='E:/pmaps/experiment/R2_12_47_2/R2_12_47_2_populated.glm')
    s = '2013-02-01 01:00:00'
    e = '2013-02-01 02:00:00'
    zipDir = 'E:/pmaps/experiment/zip'
    obj.addZIP(zipDir=zipDir, starttime=s, stoptime=e)