#!/bin/env python
from rw_reg import *
from mcs import *
from time import *
import array
import struct

SLEEP_BETWEEN_COMMANDS=0.1
DEBUG=False
CTP7HOSTNAME = "eagle33"

class Colors:            
    WHITE   = '\033[97m' 
    CYAN    = '\033[96m' 
    MAGENTA = '\033[95m' 
    BLUE    = '\033[94m' 
    YELLOW  = '\033[93m' 
    GREEN   = '\033[92m' 
    RED     = '\033[91m' 
    ENDC    = '\033[0m'  

REG_CTP7_BOARD_ID = None
REG_OH1_FW = None
REG_OH1_VFAT_MASK = None
REG_VFAT_CONTROL_REG = None

def main():

    instructions=""

    if len(sys.argv) < 2:
        print('Usage: evkatest.py <instructions>')
        print('instructions:')
        print('  contains ctp7:     test ctp7 reg access')
        print('  contains oh:       test oh reg access')
        print('  contains vfat:     test vfat reg access')
        return
    else:
        instructions = sys.argv[1]

    parseXML()
    initRegAddrs()

    if instructions == 'ctp7':
        subheading('Testing CTP7')
        regTest(REG_CTP7_BOARD_ID, 0xbeef, 0xffff, True, 100000)
    elif instructions == 'oh':
        subheading('Testing OH1')
        regTest(REG_OH1_FW, 0x20170302, 0xffffffff, False, 100000)


def initRegAddrs():
    global REG_CTP7_BOARD_ID
    global REG_OH1_FW
    global REG_OH1_VFAT_MASK
    global REG_VFAT_CONTROL_REG
    REG_CTP7_BOARD_ID = getNode('GEM_AMC.GEM_SYSTEM.BOARD_ID').real_address
    REG_OH1_FW = getNode('GEM_AMC.OH.OH1.STATUS.FW.DATE').real_address
    REG_OH1_VFAT_MASK = getNode('GEM_AMC.OH.OH1.CONTROL.VFAT.SBIT_MASK').real_address
    REG_VFAT_CONTROL_REG = getNode('GEM_AMC.OH.OH1.GEB.VFATS.VFAT10.VFATChannels.ChanReg0').real_address

def regTest(regAddress, initValue, regMask, doInitWrite, numIterations):
    if (doInitWrite):
        wReg(regAddress, initValue)

    busErrors = 0
    valueErrors = 0

    timeStart = clock()
    for i in range(0, numIterations):
        sleep(0.001)
        value = rReg(regAddress) & regMask
        if value != initValue & regMask:
            if value == 0xdeaddead & regMask:
                busErrors += 1
            else:
                valueErrors += 1
                printRed("Value error. Expected " + hex(initValue & regMask) + ", got " + hex(value) + " in iteration #" + str(i))

    totalTime = clock() - timeStart
        
    printCyan("Test finished " + str(numIterations) + " iterations in " + str(totalTime) + " seconds. Bus errors = " + str(busErrors) + ", value errors = " + str(valueErrors))

# freqDiv -- JTAG frequency expressed as a divider of 20MHz, so e.g. a value of 2 would give 10MHz, value of 10 would give 2MHz
def enableJtag(freqDiv=None):
    subheading('Disabling SCA ADC monitoring')                                                                                          
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.ADC_MONITORING.MONITORING_OFF'), 0x1)                                                    
    sleep(0.01)                                                                                                                         
    subheading('Enable JTAG module')                                                                                                    
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.CTRL.ENABLE'), 0x1)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.CTRL.SHIFT_MSB'), 0x0)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.CTRL.EXPERT.EXEC_ON_EVERY_TDO'), 0x0)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.CTRL.EXPERT.NO_SCA_LENGTH_UPDATE'), 0x0)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.CTRL.EXPERT.SHIFT_TDO_ASYNC'), 0x0)

    if freqDiv is not None:
        subheading('Setting JTAG CLK frequency to ' + str(20 / (freqDiv)) + 'MHz (divider value = ' + hex((freqDiv - 1) << 24) + ')')
        sendScaCommand(0x13, 0x90, 0x4, (freqDiv - 1) << 24, False)


def disableJtag():
    subheading('Disabling JTAG module')                                                                                                 
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.CTRL.ENABLE'), 0x0)
#    subheading('Enabling SCA ADC monitoring')                                                                                           
#    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.ADC_MONITORING.MONITORING_OFF'), 0x0)                                                    


# restoreIdle -- if True then will restore to IDLE state before doing anything else
# ir          -- instruction register, set it to None if it's not needed to shift the instruction register
# irLen       -- number of bits in the instruction register
# dr          -- data register, set it to None if it's not needed to shift the data register
# drLen       -- number of bits in the data register
# drRead      -- read the TDI during the data register shifting
def jtagCommand(restoreIdle, ir, irLen, dr, drLen, drRead):
    totalLen = 0
    if ir is not None:
        totalLen += irLen + 6       # instruction register length plus 6 TMS bits required to get to the IR shift state and back to IDLE
    if dr is not None:
        totalLen += drLen + 5       # data register length plus 5 TMS bits required to get to the DR shift state and back to IDLE
    if restoreIdle:
        totalLen += 6
    if totalLen > 128:
        raise ValueError('JTAG command request needs more than 128 bits -- not possible. Please break up your command into smaller pieces.')

    tms = 0
    tdo = 0
    len = 0
    readIdx = 0
    
    if restoreIdle:
        tms = 0b011111
        len = 6

    if ir is not None:
        tms |= 0b0011 << len         # go to IR SHIFT state
        len += 4
        tdo |= ir << len
        tms |= 0b1 << (irLen - 1 + len)  # exit IR shift
        len += irLen
        tms |= 0b01 << len    # update IR and go to IDLE
        len += 2

    if dr is not None:
        tms |= 0b001 << len    # go to DR SHIFT state
        len += 3
        readIdx = len
        tdo |= dr << len
        tms |= 0b1 << (drLen -1 + len) # exit DR shift
        len += drLen
        tms |= 0b01 << len     # update DR and go to IDLE
        len += 2
        

    debug('Length = ' + str(len))
    debug('TMS = ' + binary(tms, len))
    debug('TDO = ' + binary(tdo, len))
    debug('Read start index = ' + str(readIdx))
    
    debugCyan('Setting command length = ' + str(len))
    fw_len = len if len < 128 else 0 # in firmware 0 means 128 bits
    #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.NUM_BITS'), fw_len)
    wReg(ADDR_JTAG_LENGTH, fw_len)

    # ================= SENDING LENGTH COMMAND JUST FOR TEST!! ===================
    #debugCyan('Setting config registers: bit number = ' + hex(fw_len))                                               
    #sendScaCommand(0x13, 0x80, 0x4, 0xc00 | (fw_len << 24), False) # TX falling edge, shift LSB first, and set length
    # ============================================================================

    #raw_input("press any key to send tms and tdo")

    debugCyan('Setting TMS 0 = ' + binary(tms & 0xffffffff, 32))
    #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TMS'), tms0)
    wReg(ADDR_JTAG_TMS, tms & 0xffffffff)

    debugCyan('Setting TDO 0 = ' + binary(tdo & 0xffffffff, 32))
    #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDO'), tdo0)
    wReg(ADDR_JTAG_TDO, tdo & 0xffffffff)

    if len > 32:
        tms = tms >> 32
        debugCyan('Setting TMS 1 = ' + binary(tms & 0xffffffff, 32))
        #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TMS'), tms1)
        wReg(ADDR_JTAG_TMS, tms & 0xffffffff)

        #raw_input("press any key to send the last TDO")

        tdo = tdo >> 32
        debugCyan('Setting TDO 1 = ' + binary(tdo & 0xffffffff, 32))
        #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDO'), tdo1)
        wReg(ADDR_JTAG_TDO, tdo & 0xffffffff)

    if len > 64:                                                               
        tms = tms >> 32                                                                                                                 
        debugCyan('Setting TMS 2 = ' + binary(tms & 0xffffffff, 32))
        #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TMS'), tms2)
        wReg(ADDR_JTAG_TMS, tms & 0xffffffff)

        tdo = tdo >> 32                                                                                           
        debugCyan('Setting TDO 2 = ' + binary(tdo & 0xffffffff, 32))
        #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDO'), tdo2)
        wReg(ADDR_JTAG_TDO, tdo & 0xffffffff)

    if len > 96:                                                                                                                                                          
        tms = tms >> 32                                                                                                                                                   
        debugCyan('Setting TMS 3 = ' + binary(tms & 0xffffffff, 32))
        #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TMS'), tms3)
        wReg(ADDR_JTAG_TMS, tms & 0xffffffff)
                                                                                                                                                                          
        tdo = tdo >> 32                                                                                                                                                   
        debugCyan('Setting TDO 3 = ' + binary(tdo & 0xffffffff, 32))
        #writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDO'), tdo3)
        wReg(ADDR_JTAG_TDO, tdo & 0xffffffff)

    # ================= SENDING JTAG GO COMMAND JUST FOR TEST!! ===================                                
    #debugCyan('JTAG GO!')                                                                                                         
    #sendScaCommand(0x13, 0xa2, 0x1, 0x0, False) 
    # ============================================================================                                                        

    #raw_input("Press any key to read TDI...")

    if drRead:
        debugCyan('Read TDI 0')                                                                                  
        tdi = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDI')))
        #tdi0_fast = parseInt(rReg(parseInt(ADDR_JTAG_TDI)))
        #print('normal tdi read = ' + hex(tdi0) + ', fast C tdi read = ' + hex(tdi0_fast) + ', parsed = ' + '{0:#010x}'.format(tdi0_fast))
        debug('tdi = ' + hex(tdi))

        if len > 32:
            debugCyan('Read TDI 1')                                                                                                                                          
            tdi1 = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDI')))        
            tdi |= tdi1 << 32
            debug('tdi1 = ' + hex(tdi1))
            debug('tdi = ' + hex(tdi))
        
        if len > 64:                                                                                                                                                      
            debugCyan('Read TDI 2')                                                                                                                                       
            tdi2 = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDI')))                                                                                                             
            tdi |= tdi2 << 64
            debug('tdi2 = ' + hex(tdi2))                                                                                          
            debug('tdi = ' + hex(tdi)) 

        if len > 96:                                                                                                                                                      
            debugCyan('Read TDI 3')                                                                                                                                       
            tdi3 = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.JTAG.TDI')))                                                                                                             
            tdi |= tdi3 << 96
            debug('tdi3 = ' + hex(tdi3))                                                                                          
            debug('tdi = ' + hex(tdi)) 

        readValue = (tdi >> readIdx) & (0xffffffffffffffffffffffffffffffff >> (128  - drLen))
        debug('Read pos = ' + str(readIdx))
        debug('Read = ' + hex(readValue))
        return readValue
    else:
        return 0

    
def sendScaCommand(sca_channel, sca_command, data_length, data, doRead):
    #print('fake send: channel ' + hex(sca_channel) + ', command ' + hex(sca_command) + ', length ' + hex(data_length) + ', data ' + hex(data) + ', doRead ' + str(doRead))
    #return    

    d = data

    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.MANUAL_CONTROL.SCA_CMD_CHANNEL'), sca_channel)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.MANUAL_CONTROL.SCA_CMD_COMMAND'), sca_command)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.MANUAL_CONTROL.SCA_CMD_LENGTH'), data_length)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.MANUAL_CONTROL.SCA_CMD_DATA'), d)
    writeReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.MANUAL_CONTROL.SCA_CMD_EXECUTE'), 0x1)
    reply = 0
    if doRead:
        reply = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.MANUAL_CONTROL.SCA_RPY_DATA')))
    return reply

def checkStatus():
    rxReady       = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.STATUS.READY')))
    criticalError = parseInt(readReg(getNode('GEM_AMC.SLOW_CONTROL.SCA.STATUS.CRITICAL_ERROR')))
    return (rxReady == 1) and (criticalError == 0)

def check_bit(byteval,idx):
    return ((byteval&(1<<idx))!=0);

def debug(string):
    if DEBUG:
        print('DEBUG: ' + string)

def debugCyan(string):
    if DEBUG:
        printCyan('DEBUG: ' + string)

def heading(string):                                                                    
    print Colors.BLUE                                                             
    print '\n>>>>>>> '+str(string).upper()+' <<<<<<<'
    print Colors.ENDC                   
                                                      
def subheading(string):                         
    print Colors.YELLOW                                        
    print '---- '+str(string)+' ----',Colors.ENDC                    
                                                                     
def printCyan(string):                                                
    print Colors.CYAN                                    
    print string, Colors.ENDC                                                                     
                                                                      
def printRed(string):                                                                                                                       
    print Colors.RED                                                                                                                                                            
    print string, Colors.ENDC                                           

def hex(number):
    if number is None:
        return 'None'
    else:
        return "{0:#0x}".format(number)

def binary(number, length):
    if number is None:
        return 'None'
    else:
        return "{0:#0{1}b}".format(number, length + 2)

if __name__ == '__main__':
    main()
