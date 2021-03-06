"""Module for interfacing with GridLAB-D.

IMPORTANT: 
For consistency, there will be one global dictionary format for regulators and
one global dictionary format for capacitors. That is defined below:

Global regulator dictionary:
Top level keys are regulator names.

regulators={'reg_VREG4': {'raise_taps': 16,
                          'lower_taps': 16,
                          'phases': {'A': {'newState': 10, 'prevState': 11,
                                           'chromInd': (0, 4)},
                                     'B': {'newState': 7, 'prevState': 11, 
                                           'chromInd': (4, 8)},
                                     'C': {'newState': 2, 'prevState': 4,
                                           'chromInd': (8, 12)},
                                  },
                          'Control': 'MANUAL'
                         },
            'reg_VREG2': {'raise_taps': 16,
                          'lower_taps': 16,
                          'phases': {'A': {'newState': 10, 'prevState': 11,
                                           'chromInd': (12, 16)},
                                     'B': {'newState': 7, 'prevState': 11, 
                                           'chromInd': (16, 20)},
                                     'C': {'newState': 2, 'prevState': 4,
                                           'chromInd': (20, 24)},
                                  },
                          'Control': 'MANUAL'
                          }
            }

capacitors={'cap_capbank2a': {'phases': {'A': {'newState': 'CLOSED',
                                               'prevState': 'OPEN', 
                                               'chromInd': 0
                                               },
                                         'B': {'newState': 'OPEN',
                                               'prevState': 'OPEN',
                                               'chromInd': 1
                                               },
                                         },
                              'control': 'MANUAL'
                             },
            'cap_capbank2c': {'phases': {'A': {'newState': 'CLOSED',
                                               'prevState': 'OPEN',
                                               'chromInd': 2
                                               },
                                         'C': {'newState': 'OPEN',
                                               'prevState': 'OPEN',
                                               'chromInd': 3}
                                         }
                              }
            }
            
COST DICTIONARY:
For evaluating 'costs' of a model, this is what the dictionary should look
like (see computeCosts for more details):

COSTS = {'realEnergy': 0.00008,
         'powerFactorLead': {'limit': 0.99, 'cost': 0.1},
         'powerFactorLag': {'limit': 0.99, 'cost': 0.1},
         'tapChange': 0.5, 'capSwitch': 2,
         'undervoltage': {'limit': 228, 'cost': 0.05},
         'overvoltage': {'limit': 252, 'cost': 0.05}
        }

Created on Aug 29, 2017

@author: thay838
"""
import subprocess
import os
import helper

# definitions for regulator and capacitor properties
REG_CHANGE_PROPS = ['tap_A_change_count', 'tap_B_change_count',
                    'tap_C_change_count']
REG_STATE_PROPS = ['tap_A', 'tap_B', 'tap_C']
REG_PROPS = REG_CHANGE_PROPS + REG_STATE_PROPS
CAP_CHANGE_PROPS = ['cap_A_switch_count', 'cap_B_switch_count',
                    'cap_C_switch_count']
CAP_STATE_PROPS = ['switchA', 'switchB', 'switchC']
CAP_PROPS = CAP_CHANGE_PROPS + CAP_STATE_PROPS
MEASURED_POWER = ['measured_power_A', 'measured_power_B', 'measured_power_C']
MEASURED_ENERGY = ['measured_real_energy']
TRIPLEX_VOLTAGE = ['measured_voltage_12']

def runModel(modelPath, DIR=None, LD_LIBRARY_PATH=None):
    #, gldPath=r'C:/gridlab-d/develop'):
    """Function to run GridLAB-D model.
    
    DIR should point to the directory gridlab-d was built in.
    LD_LIBRARY_PATH can be needed on Linux to properly hook-up MySQL.

    See http://gridlab-d.shoutwiki.com/wiki/MinGW/Eclipse_Installation#Linux_Installation
    and do a search for 'Environment Setup'
    In short, assuming build is in gridlab-d/develop:
        PATH must contain gridlab-d/develop/bin
        GLPATH must contain gridlab-d/develop/lib/gridlabd and gridlab-d/develop/share/gridlabd
        CXXFLAGS must be set to include gridlab-d/develop/share/gridlabd
    """
    cwd, model = os.path.split(modelPath)

    # Setup environment if necessary
    if DIR:
        # We'll use forward slashes here since GLD can have problems with 
        # backslashes... Ugh.
        DIR = DIR.replace('\\', '/')
        env = os.environ
        binStr = "{}/bin".format(DIR)
        # We can form a kind of memory leak where we grow the environment
        # variables if we add these elements repeatedly, so check before 
        # adding or changing.
        if binStr not in env['PATH']:
            env['PATH'] = binStr + os.pathsep + env['PATH']

        env['GLPATH'] = ("{}/lib/gridlabd".format(DIR) + os.pathsep
                         + "{}/share/gridlabd".format(DIR))
        
        env['CXXFLAGS'] = "-I{}/share/gridlabd".format(DIR)
    else:
        env = None
    
    # LD_LIBRARY_PATH stuff. 
    # TODO: May want to make the gldPath mandatory - it doesn't make much
    # sense to have the ld_library_path variable depend on whether or not 
    # gridlabd is on the path.
    if (env is not None) and LD_LIBRARY_PATH is not None:
        # Need to set the LD_LIBRARY_PATH so MySQL will work.
        try:
            env['LD_LIBRARY_PATH']
        except KeyError:
            # Not set, simpley set it.
            env['LD_LIBRARY_PATH'] = LD_LIBRARY_PATH
        else:
            # Concatenate.
            env['LD_LIBRARY_PATH'] = (env['LD_LIBRARY_PATH'] + os.pathsep
                                      + LD_LIBRARY_PATH) 
    
    # Run command. Note with check=True exception will be thrown on failure.
    # With check=True, a CalledProcessError will be raised. This should
    # be handled in some way, but probably outside of this function.
    # NOTE: it's best practice to pass args as a list. If args is a list, using
    # shell=True creates differences across platforms. Just don't do it.
    output = subprocess.run(['gridlabd', model], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, env=env,
                            check=True)
    return output

def translateTaps(lowerTaps, pos):
    """Method to translate tap integer in range 
    [0, lowerTaps + raiseTaps] to range [-lower_taps, raise_taps]
    """
    # Hmmm... is it this simple? 
    posOut = pos - lowerTaps
    return posOut

def inverseTranslateTaps(lowerTaps, pos):
    """Method to translate tap integer in range
        [-lower_taps, raise_taps] to range [0, lowerTaps + raiseTaps]
    """
    # Hmmm... is it this simle? 
    posOut = pos + lowerTaps
    return posOut

def computeCosts(dbObj, energyTable, powerTable, triplexTable, tapChangeCount,
                 capSwitchCount, costs, starttime, stoptime, nameCol='name',
                 tCol='t', idCol='id'):
    """Method to compute VVO costs for a given time interval. This includes
    cost of energy, capacitor switching, and regulator tap changing. Later this
    should include cost of DER engagement.
    
    INPUTS:
        dbObj: initialized util/db.db class object
        energyTable: dict with the following fields:
            table: name of table for getting total energy.
            columns: name of the columns corresponding to the swing table.
                These will vary depending on node-type (substation vs. meter)
        powerTable: dict with 'table' and 'energy' fields for measuring total
            power in order to compute the power factor. Peak power costs could
            be included in the future.
        triplexTable: dict with 'table' and 'complex_part' fields for measuring
            voltage violations at triplex loads.
        tapChangeCount: total number of all tap changes.
        capSwitchCount: total number of all capacitor switching events.
        costs: dictionary with the following fields:
            realEnergy: price of energy in $/Wh
            tapChange: cost ($) of changing one regulator tap one position.
            capSwitch: cost ($) of switching a single capacitor
            undervoltage: dict with two fields:
                limit: voltage threshold for voltage violation. Limit is 
                    exclusive, a value = to the limit will not inucr a penalty
                cost: penalty incurred for an undervoltage violation
            overvoltage: dict with two fields:
                limit: voltage trheshold for voltage violation. Limit is
                    exclusive, a value = to the limit will not incur a penalty
                cost: penalty incurred for an overvoltage violation
            powerFactorLead: dict with two fields:
                limit: minimum tolerable leading powerfactor
                cost: cost of a 0.01 pf deviation from the lead limit
            powerFactorLag: dict with two fields:
                limit: minimum tolerable lagging powerfactor
                cost: cost of a 0.01 pf deviation from the lag limit
        starttime: starting timestamp (yyyy-mm-dd HH:MM:SS) of interval in
            question.
        stoptime: stopping ""
        tCol: name of time column. Assumed to be the same for tap/cap tables.
            Only include if a table is given.
            
    NOTE: At this point, all capacitors and regulators are assigned the same
    cost. If desired later, it wouldn't be too taxing to break that cost down
    by piece of equipment.
    """
    # Initialize dictionary
    costDict = {}
    # *************************************************************************
    # ENERGY COST
    
    # Read energy database. Note times - this should return a single row only.
    energyRows = dbObj.fetchAll(table=energyTable['table'],
                                cols=energyTable['columns'],
                                starttime=stoptime, stoptime=stoptime)

    # Due to time and ID filtering, we should get exactly one row.
    if len(energyRows) != 1:
        raise UserWarning(('Something has gone wrong, and there are multiple'
                           ' energy rows for the same time!'))
    
    # Compute the cost
    costDict['realEnergy'] = energyRows[0][0] * costs['realEnergy']
    #**************************************************************************
    # POWER FACTOR COST
    # Initialize costs
    costDict['powerFactorLead'] = 0
    costDict['powerFactorLag'] = 0
    
    # Code below may be necessary if recording 3-phase voltage from a
    # 'subastation' object instead of a 'meter' object
    '''
    # Get list of sums of rows (sum three phase power) from the database
    # Note the return is a dict with 'rowSums' containing the power values.
    power = dbObj.sumComplexPower(table=powerTable['table'],
                                  cols=powerTable['columns'],
                                  starttime=starttime, stoptime=stoptime)
    '''
    
    # Get complex power
    power = dbObj.getComplexFromParts(table=powerTable['table'], 
                                  cols=powerTable['columns'],
                                  starttime=starttime, stoptime=stoptime)
    
    # Loop over each row, compute power factor, and assign cost
    for p in power:
        pf, direction = helper.powerFactor(p)
         
        # Construct the field. Note that the possible returns of direction are
        # 'lead' and 'lag'
        field = 'powerFactor' + 'L' + direction[1:]
        # If the pf is below the limit, add to the relevant cost 
        if pf < costs[field]['limit']:
            # Cost represents cost of a 0.01 deviation, so multiply violation
            # by 100 before multiplying by the cost.
            costDict[field] += ((costs[field]['limit'] - pf) * 100
                                * costs[field]['cost'])
    
    # *************************************************************************
    # TAP CHANGING COST
        
    # Simply multiply cost by number of operations.   
    costDict['tapChange'] = costs['tapChange'] * tapChangeCount
    
    # *************************************************************************
    # CAP SWITCHING COST
        
    # Simply multiply cost by number of operations.   
    costDict['capSwitch'] = costs['capSwitch'] * capSwitchCount
    
    # *************************************************************************
    # TRIPLEX VOLTAGE VIOLATION COSTS
    
    # Note that the function for determining violations relies heavily on the
    # operations of GridLAB-D's mysql recorder.
    v = dbObj.voltViolationsFromRecorder(table=triplexTable['table'],
                                         lowerBound=costs['undervoltage']['limit'],
                                         upperBound=costs['overvoltage']['limit'],
                                         voltageCols=triplexTable['columns'],
                                         nameCol=nameCol, idCol=idCol,
                                         tCol=tCol,
                                         starttime=starttime,
                                         stoptime=stoptime)
    costDict['overvoltage'] = v['high'] * costs['overvoltage']['cost']
    costDict['undervoltage'] = v['low'] * costs['undervoltage']['cost']
    
    '''
    if voltFilesDir and voltFiles:
        # Get all voltage violations. Use default voltages and tolerances for
        # now.
        v = violationsFromRecorderFiles(fileDir=voltFilesDir, files=voltFiles)
        costDict['overvoltage'] = sum(v['high']) * costs['overvoltage']
        costDict['undervoltage'] = sum(v['low']) * costs['undervoltage']
    '''
    
    # *************************************************************************
    # DER COSTS
    # TODO
    
    # *************************************************************************
    # TOTAL AND RETURN
    t = 0
    for _, v in costDict.items():
        t += v
    
    costDict['total'] = t
    return costDict

def getRegOrCapRecordDict(objName, table, objType, timeInterval, limit=-1):
    """Helper function to build dictionary used to write recorders for
    regulators or capacitors.
    
    INPUTS: 
        objName: name of object to record
        table: desired table for recording
        objType: either 'reg' or 'cap'
        timeInterval: interval for recording
    """
    # We'll record all phases even if they aren't connected
    # I believe that this is necessary due to how GridLAB-D performs inserts.
    if objType == 'reg':
        propList = REG_PROPS
    elif objType == 'cap':
        propList = CAP_PROPS
    else:
        raise UserWarning("objType must be 'reg' or 'cap'")
    
    # Build the dictionary of properties
    propDict = {'parent': objName,
                'table': table,
                'interval': timeInterval,
                'propList': propList,
                'limit': limit}
    
    return propDict

def propToCol(propList):
    """Helper function which translates recorder properties to column
        names for MySQL. This should replicate how GridLAB-D does this
        translation
    """
    # replace periods with underscores
    cols = [s.replace('.', '_') for s in propList]
    return cols
    