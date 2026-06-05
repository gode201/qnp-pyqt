from ctypes import *
import os

# DLL 파일명 (64-bit Python용)
_DLL_NAME = "nF_interface_x64.dll"
_DLL_DIR = os.path.dirname(os.path.abspath(__file__))

CMD_ID_TSL = 0x2041 # Target selection 
CMD_ID_WCR = 0x3000 # wave table clear
CMD_ID_WAV = 0x3001 # define wave table
CMD_ID_WSL = 0x3012 # wave table selection
CMD_ID_WGO = 0x3140 # wgo enable
CMD_ID_WGC = 0x3142 # wgo cycles
CMD_ID_WES = 0x3151 # wgo event selection
CMD_ID_HVE = 0x22FE # High-voltage output enable

CMD_ID_RCR = 0x4000 # recorder table clear
CMD_ID_REN = 0x4040 # recorder enable
CMD_ID_RCF = 0x4050 # configure recorder table
CMD_ID_RES = 0x4051 # recorder event selection
CMD_ID_EEN = 0xD041 # event enable
CMD_ID_EST = 0xD042 # event set

handle = 0
intfFd = 0

def xDev_init(handle0, sIntf, sParam):
    # function: check DLL and connect to device
    global handle         # the handle of nF_interface.dll 
    #print("xDev_init()...")
    handle = handle0
    func_rev = handle.nF_get_dll_revision
    func_rev.restype = c_float
    print("nF_interface.DLL rev. is: %5.2f." % func_rev())
    res = handle.nF_get_dll_last_error()
    print("nF_interface.DLL error code: %d" % res)
    res = xDev_connect_intf(sIntf, sParam)
    if res != 0: return res
    res = handle.nF_get_dev_error()
    print("Device error code: %d" % res)
    if res <= -2000: #Software problem
        print("Connection failed!")
        return 1
    return 0

def xDev_exit():
    global intfFd, handle
    #print("xDev_exit...")
    if (handle !=0 ) and intfFd >=0 :
        handle.nF_intf_disconnect(intfFd)
    print("Device interface disconnected.")
    return 0

def xDev_connect_intf(sIntf, sParam):
    global intfFd, handle

    print("Selected interface: %s, parameter: %s" % (sIntf.decode(), sParam.decode()) )
    sIntfCmp = sIntf.lower()
    if (sIntfCmp== b'rs232') or (sIntfCmp==b'com')  or (sIntfCmp==b'uart'):
        #------------------------------------------
        # for RS232 interface
        #------------------------------------------
        func_connect = handle.nF_intf_connect_com
        intfFd = func_connect(int(sParam ))
    elif sIntfCmp== b'simu' :
        #------------------------------------------
        # for simulation
        #------------------------------------------
        func_connect = handle.nF_intf_connect_local
        arg = create_string_buffer(b"EBD-1202x0")
        func_connect.argtypes = [c_char_p]
        intfFd = func_connect(arg)
    elif sIntfCmp== b'usb' :
        #------------------------------------------
        # for USB (windows RNDIS-driver)
        #------------------------------------------
        func_connect = handle.nF_intf_connect_tcpip
        arg = create_string_buffer(b"192.168.168.168") # IP of controller (fixed)
        func_connect.argtypes = [c_char_p]
        intfFd = func_connect(arg)
    else:
        #------------------------------------------
        # for TCP/IP
        #------------------------------------------
        timeout = 2000 #ms
        udpRspLen = 256
        udpRsp = create_string_buffer(udpRspLen)
        res = handle.nF_udp_search(udpRsp, udpRspLen, timeout)
        if res != 0:
            print("UDP response error %d!" % res)
            return res 
        print("UDP response:%s" % (udpRsp.value).decode("utf-8") )
        ipaddr = create_string_buffer(16)
        res = handle.nF_udp_rsp_to_ipaddr(udpRsp, ipaddr, 16)
        if res != 0:
            print("UDP parser error %d!" % res)
            return res 
        print("UDP address: %s" % (ipaddr.value).decode("utf-8") )

        func_connect = handle.nF_intf_connect_tcpip
        func_connect.argtypes = [c_char_p]
        intfFd = func_connect(ipaddr)

    if intfFd < 0 :
        res = handle.nF_get_sys_last_error()
        print("DLL system-error code: %d" % res)
        print("Connection failed!")
        return 1
    
    #print("interface intfFd:%d" % intfFd)
    print("Device interface connected.")
    return 0

def xDev_write_command(cmdId, parNum, par):
    # for commands with U32-parameters 
    # example: 0x2040 0 1
    #   cmdId = 0x2040
    #   parNum = 2
    #   par[0] = 0
    #   par[1] = 1
    global handle
    return handle.nF_intf_write_command_u32(cmdId, parNum, par)
    
def xDev_write_command_u32(cmdId, parNum, par): 
    global handle
    return handle.nF_intf_write_command_u32(cmdId, parNum, par)

def xDev_write_command_float(cmdId, parNum, par):
    # for commands with float-parameters
    # example: 0x2002 0 10.0 
    #   par = (c_float*2)()
    #   par[0] = 0.0 # axis-id: is 0
    #   par[1] = 10.0 # vel value
    #   xDev_write_command_float(0x2002, 2, par )
    global handle
    return handle.nF_intf_write_command_float(cmdId, parNum, par)

def xDev_read_command_u32(cmdId, parNum, par, rsp):
    # read data from controller (also for 'float' data-format)
    # example: ?0x2040 0 1
    #   rsp = (c_int*8)()
    #   par = (c_int*2)()
    #   parNum = 2
    #   par[0] = 0
    #   par[1] = 1
    #   xDev_read_command_u32(0x2040, 2, byref(par), byref(rsp) )
    #   print(rsp[0], rsp[1], rsp[2])
    # example: ?0x2002 0 (float data)
    #   rsp = (c_float*4)()
    #   par[0] = 0
    #   xDev_read_command_u32(0x2002, 1, byref(par), byref(rsp) )
    #   print(rsp[1]) 
    global handle
    rspNum = c_int(0)
    err = handle.nF_intf_read_command_u32(cmdId, parNum, par, byref(rspNum), rsp)
    if err : return 0
    return rspNum.value

def xDev_pop_error():
    # pop (read-back and clear) device error-code
    global handle
    errCode = handle.nF_get_dev_error()
    #print("Device error code: %d" % errCode)
    return errCode

def xDev_get_svo(axis):
    # get axis servo-status
    global handle
    ch = c_int(axis) 
    svo = c_int(0)
    err = handle.nF_get_dev_axis_svo(1, byref(ch), byref(svo) )
    if err : return 0
    return svo.value

def xDev_set_svo(axis, bSvo):
    #Set axis servo-controlling
    global handle
    ch = c_int(axis) 
    svo = c_int(bSvo) 
    return handle.nF_set_dev_axis_svo(1, byref(ch), byref(svo) )

def xDev_set_svo_softly(axis, bOn) :
    # avoid jumping when changes SVO status
    pos = xDev_get_pos(axis)
    cVol = xDev_get_cVol(axis)
    
    if bOn : # set current position as target
        posMin = xDev_get_param_float(axis, 0x20400031)
        posMax = xDev_get_param_float(axis, 0x20400030)
        if pos<posMin : pos=posMin
        elif pos>posMax : pos = posMax
        xDev_move(axis, pos)
    else : # set current voltage as target
        xDev_sva(axis, cVol)
        
    xDev_set_svo(axis, bOn)    
    return 0
    
def xDev_get_ont(axis):
    # get axis on-target-status
    global handle
    ch = c_int(axis) 
    ont = c_int(0)
    err = handle.nF_get_dev_axis_ont(1, byref(ch), byref(ont) )
    if err : return 0
    return ont.value

def xDev_get_pos(axis):
    # get axis position
    global handle
    maxTry = 3
    ch = c_int(axis) 
    pos = c_float(0.0)
    
    for i in range(0, maxTry):
        err = handle.nF_get_dev_axis_position(1, byref(ch), byref(pos) )
        if err==0 : break        
    if err : return 0.0
    return pos.value

def xDev_get_tgt(axis, svo) :
    # get axis target (svo=1 for close-loop, 0 for open-loop)
    global handle
    ch = c_int(axis) 
    tgt = c_float(0.0) 
    handle.nF_get_dev_axis_target(svo, 1, byref(ch), byref(tgt) )
    return tgt.value
    
def xDev_get_cVol(axis) :
    # get control-voltage of controller
    global handle
    ch = c_int(axis) 
    cVol = c_float(0.0) 
    err = handle.nF_get_dev_axis_cVol(1, byref(ch), byref(cVol) )
    if err : return 0.0
    return cVol.value

def xDev_get_senPos(ch) :
    # get sensor-position
    global handle
    val = c_float(0.0) 
    handle.nF_intf_read_value1(0x2111, c_int(ch), byref(val) )
    return val.value
    
def xDev_get_filtered_senPos(ch) :
    # gGet filtered sensor-position
    global handle
    val = c_float(0.0) 
    err = handle.nF_intf_read_value1(0x2112, c_int(ch), byref(val) )
    if err : return 0.0
    return val.value
    
def xDev_move(axis, tgt):
    # set axis close-loop target
    global handle
    ch = c_int(axis) 
    val = c_float(tgt) 
    return handle.nF_set_dev_axis_target(1, 1, byref(ch), byref(val) )

def xDev_move_inc(axis, inc):
    # incremental-moving
    global handle
    argInF = (c_float*2)()
    argInF[0] = c_float(axis) 
    argInF[1] = c_float(inc)
    return handle.nF_intf_write_command_float(0x2003, 2, byref(argInF) )

def xDev_moveN(num, axisArr, tgtArr):
    # set axis close-loop target, more axes
    # example:
    #   axisN = (c_int * 3)(0, 2, 1)
    #   tgtN = (c_float * 3)(5, 6, 7)
    #   xDev_moveN(3, axisN, tgtN)
    global handle
    return handle.nF_set_dev_axis_target(1, num, byref(axisArr), byref(tgtArr) )

def xDev_sva(axis, tgt):
    # set axis open-loop target
    global handle
    ch = c_int(axis) 
    val = c_float(tgt) 
    return handle.nF_set_dev_axis_target(0, 1, byref(ch), byref(val) )

def xDev_sva_inc(axis, inc):
    # incremental-moving
    global handle
    argInF = (c_float*2)()
    argInF[0] = c_float(axis) 
    argInF[1] = c_float(inc)
    return handle.nF_intf_write_command_float(0x2005, 2, byref(argInF) )
    
def xDev_svaN(num, axisArr, tgtArr):
    # set axis open-loop target, more axes
    # example:
    #   axisN = (c_int * 3)(0, 2, 1)
    #   tgtN = (c_float * 3)(5, 6, 7)
    #   xDev_svaN(3, axisN, tgtN)
    global handle
    return handle.nF_set_dev_axis_target(0, num, byref(axisArr), byref(tgtArr) )

def xDev_get_param_int(ch, parId):
    # get parameter (integer type)
    global handle
    arg1 = c_int(ch)
    arg2 = c_long(parId)
    arg3 = c_int(0) #fmt
    arg4 = c_int() #value
    err = handle.nF_get_dev_parameter_ram(arg1, arg2, byref(arg3), byref(arg4) )
    if err : return 0
    return arg4.value

def xDev_get_param_float(ch, parId):
    # get parameter (float type)
    global handle
    arg1 = c_int(ch)
    arg2 = c_long(parId)
    arg3 = c_int(0) #fmt
    arg4 = c_float() #value
    err = handle.nF_get_dev_parameter_ram(arg1, arg2, byref(arg3), byref(arg4) )
    if err: return 0.0
    return arg4.value

def xDev_set_param_float(ch, parId, val):
    # set parameter (can be used for float/int type)
    global handle
    arg1 = c_int(ch)
    arg2 = c_long(parId)
    arg3 = c_float(val)
    
    res = handle.nF_set_dev_parameter_ram(arg1, arg2, 2, byref(arg3) )
    if res != 0 :
        print("Error xDev_set_param_float(%d, 0x%08x, %f)" % (ch, parId, val) )
    return res

def xDev_get_param_string(ch, parId):
    # get parameter (string type)
    global handle
    arg1 = c_int(ch)
    arg2 = c_long(parId)
    arg3 = c_int(4) #fmt
    arg4 = create_string_buffer(32) #value
    err = handle.nF_get_dev_parameter_ram(arg1, arg2, byref(arg3), byref(arg4) )
    if err : return b'Error'
    return arg4.value

def xDev_set_param_string(ch, parId, sVal):
    # set parameter (string type)
    global handle
    #print("String input is:%s" % sVal)
    arg1 = c_int(ch)
    arg2 = c_long(parId)
    arg3 = create_string_buffer( sVal.encode('utf-8') )
    res = handle.nF_set_dev_parameter_ram(arg1, arg2, 4, byref(arg3) )
    if res != 0 :
        print("Error xDev_set_param_string(%d, 0x%08x, %s)" % (ch, parId, sVal) )
    return res

def xDev_set_param_float_flash(ch, parId, val):
    # set parameter to flash(can be used for float/int type)
    global handle
    arg1 = c_int(ch)
    arg2 = c_long(parId)
    arg3 = c_float(val) 
    return handle.nF_set_dev_parameter_flash(arg1, arg2, 2, byref(arg3) )

def xDev_get_AIN_vol(ch) :
    # get analog-input-voltage (command: 0x2114)
    global handle
    argIn = c_int(ch)
    rsp = (c_float*2)()
    num = c_int()
    err = handle.nF_intf_read_command_u32(0x2114, 1, byref(argIn), byref(num), byref(rsp) )
    #print("rsp num:%d" % num.value)
    if err : return 0.0
    return rsp[1]

def xDev_get_monitor_HV(ch) :
    # get monitor value of high-voltage (command: 0x2116, piezo-voltage)
    # for high-end controller only
    global intfFd, handle
    argIn = c_int(ch*2)
    rsp = (c_float*2)()
    num = c_int()
    err = handle.nF_intf_read_command_u32(0x2116, 1, byref(argIn), byref(num), byref(rsp) )
    #print("rsp num:%d" % num.value)
    if err : return 0.0
    return rsp[1]

def xDev_get_monitor_vol(ch) :
    # get monitor voltage (command: 0x2116, aux-voltage)
    # for high-end controller only
    global handle
    argIn = c_int(ch*2 + 1)
    rsp = (c_float*2)()
    num = c_int()
    err = handle.nF_intf_read_command_u32(0x2116, 1, byref(argIn), byref(num), byref(rsp) )
    #print("rsp num:%d" % num.value)
    if err : return 0.0
    return rsp[1]

def xDev_set_monitor_src(ch, src) :
    # select monitor source
    global handle
    args = (c_int*2)()
    args[0] = c_int(ch)
    args[1] = c_int(src)
    print("Monitor source selection ch:%d src:%d" % (args[0], args[1]) )
    return handle.nF_intf_write_command_u32(0x21FE, 2, byref(args) )

def xDev_start_rec(rate, ch) : 
    # start data recorder
    #   rate: recorder rate (save data in how many servo-loops)
    #   ch: position of which channel for saving
    global handle
    argIn = (c_int*3)()

    # cancel old action: disable-event
    argIn[0] = 0
    argIn[1] = 0
    handle.nF_intf_write_command_u32(CMD_ID_EEN, 2, byref(argIn) )
    handle.nF_intf_write_command_u32(CMD_ID_EST, 2, byref(argIn) )

    # clear recorder table
    handle.nF_intf_write_command_u32(CMD_ID_RCR, 0, byref(argIn) )

    # set recorder rate
    xDev_set_param_float(0, 0x40400000, rate)
    
    # set source to position (ch)
    argIn[0] = 0 # recorder 0
    argIn[1] = 1 # source = position, change to get other data
    argIn[2] = ch # channel
    handle.nF_intf_write_command_u32(CMD_ID_RCF, 3, byref(argIn) )

    # recorder to event0
    argIn[0] = 0
    argIn[1] = 0
    handle.nF_intf_write_command_u32(CMD_ID_RES, 2, byref(argIn) )

    # enable recorder
    argIn[0] = 0
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_REN, 2, byref(argIn) )

    # enable event
    argIn[0] = 0
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_EEN, 2, byref(argIn) )

    # set event: recorder then starts
    argIn[0] = 0
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_EST, 2, byref(argIn) )

    return 0

def xDev_get_rec_data(dataLen, bufAddr) : 
    global handle
    recCh = 0
    recFrom = 0
    
    # check whether all data valid
    for i in range(10) :
        valid = handle.nF_get_dev_rec_length(recCh)
        if valid >= dataLen : break
        
    if valid < dataLen :
        return -valid
    
    handle.nF_get_dev_rec_data(recCh, recFrom, dataLen, bufAddr)
    return 0

def xDev_start_sin(ch):
    # start a sinus waveform:
    # for High-end controller only
    global handle
    argIn = (c_int*4)()
    argInF = (c_float*9)()

    event = 0
    offset = -30.0    # from
    vMax = 150.0      # to
    freq = 20.0
    phase = 0.0
    cycle = 1200    # number of cycles
    
    # cancel old action: disable-event
    argIn[0] = event
    argIn[1] = 0
    handle.nF_intf_write_command_u32(CMD_ID_EEN, 2, byref(argIn) )
    handle.nF_intf_write_command_u32(CMD_ID_EST, 2, byref(argIn) )

    # example: for 100k-SPS, 20Hz = 50ms, total 5000 points
    svo_time = xDev_get_param_float(0, 0xFF00000F) # servo-loop time
    wLen = 1.0/(svo_time*freq) # number of wave-data
    rate = 1 # TODO: if the setting of wave-buffer-size in controller is less than, increase this value 
    xDev_set_param_float(ch, 0x31400000, rate)

    # clear wave-table
    argIn[0] = ch   # channel
    handle.nF_intf_write_command_u32(CMD_ID_WCR, 1, byref(argIn) )

    # set cycles
    argIn[0] = ch   # channel
    argIn[1] = cycle
    handle.nF_intf_write_command_u32(CMD_ID_WGC, 2, byref(argIn) )

    # wave data
    argInF[0] = float(ch)   # which channel
    argInF[1] = float(0)    # mode = new
    argInF[2] = float(1)    # SIN form
    argInF[3] = float(0)    # x0
    argInF[4] = float(wLen) # wave-segLength
    argInF[5] = vMax - offset # amplitude
    argInF[6] = wLen        # length
    argInF[7] = offset      # Offset
    argInF[8] = phase
    handle.nF_intf_write_command_float(CMD_ID_WAV, 9, byref(argInF) )

    # wgo to wave-table
    argIn[0] = ch   # ID of wgo-channel
    argIn[1] = ch   # ID of wave-table
    handle.nF_intf_write_command_u32(CMD_ID_WSL, 2, byref(argIn) )
    
    # wgo event selection
    argIn[0] = ch   # wgo channel
    argIn[1] = event
    handle.nF_intf_write_command_u32(CMD_ID_WES, 2, byref(argIn) )
    
    # HV output enable
    argIn[0] = ch   # channel
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_HVE, 2, byref(argIn) )

    # Target selction: to wgo
    argIn[0] = ch   # channel
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_TSL, 2, byref(argIn) )
    
    # wgo enable
    argIn[0] = ch   # channel
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_WGO, 2, byref(argIn) )

    # enable event
    argIn[0] = event
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_EEN, 2, byref(argIn) )

    # set event: wgo starts
    argIn[0] = event
    argIn[1] = 1
    handle.nF_intf_write_command_u32(CMD_ID_EST, 2, byref(argIn) )

    return 0

#--------------------------------------------------------------
#    Read & write command
#--------------------------------------------------------------
class _CMD_CFG_(Structure) :
    _fields_ = ("cmdId", c_ushort), ("customId", c_ushort), \
        ("option", c_ubyte), ("dataNum", c_int), \
        ("pDataFmt", POINTER(c_ubyte)), ("pDataIn", POINTER(c_uint))

class _RSP_MSG_(Structure) :
    _fields_ = ("cmdId", c_ushort), ("customId", c_ushort), \
        ("seq", c_int), ("pPackage", c_char_p), ("dataNum", c_int), \
        ("pDataFmt", POINTER(c_ubyte)), ("pDataOut", POINTER(c_uint) )

def xDev_test_cmd():
    global intfFd, handle
    #print("Fd: %d" % intfFd)
    
    fmt = (c_ubyte*3)(0, 0, 0)
    axis = (c_uint*3)(0, 0, 0)
    cmdCfg = _CMD_CFG_(c_ushort(0x2001), 0x0000, 0x00, 3) # option can be set to 0x20
    cmdCfg.pDataFmt = cast(fmt, POINTER(c_ubyte) )
    cmdCfg.pDataIn = cast(axis, POINTER(c_uint))
    
    # function call
    ppRsp = POINTER(_RSP_MSG_)()
    cmd_rd = handle.nF_intf_read_command
    cmd_rd.argtypes = [c_int, POINTER(_CMD_CFG_), POINTER(POINTER(_RSP_MSG_))]
    cmd_rd.restype = c_int
    res = cmd_rd(intfFd, byref(cmdCfg), byref(ppRsp) )

    # show response
    if res != 0:
        print("Response error: %d" % res)
        return -1
    
    print("Response: res=%d, cmdID=0x%04x, num=%d" % (res, ppRsp[0].cmdId, ppRsp[0].dataNum) )
    pFmt = cast(ppRsp[0].pDataFmt, POINTER(c_ubyte) )
    pData = cast(ppRsp[0].pDataOut, POINTER(c_int) )
    for i in range( ppRsp[0].dataNum ) :
        fmt = pFmt[i]
        data = pData[i]
        if fmt == 2 : #float data
            nData = c_int(data)
            fpData = cast(byref(nData), POINTER(c_float) )
            fData = fpData.contents
            print("response format: float, data: %7.3f" % fData.value)
        elif fmt == 10 : # line-feed
            continue
        else :
            print("response format: %d, data:%d" % (fmt, data) )

    # free the memory
    rsp_free = handle.nF_free_rspMsg
    rsp_free.argtypes = [POINTER(_RSP_MSG_)]
    rsp_free(ppRsp)
    return 0

def xDev_load_dll():
    """DLL을 스크립트 위치 기준 상대 경로로 로드"""
    os.add_dll_directory(_DLL_DIR)
    return cdll.LoadLibrary(os.path.join(_DLL_DIR, _DLL_NAME))

def xDev_test():
    global handle
    handle = xDev_load_dll()
    res = xDev_init(handle, b'com', b'4') # for COM4
    if res != 0: return res
    
    args = (c_float*2)()
    args[0] = 0.0 # axis-id: is 0
    args[1] = 10.0 # velocity value
    xDev_write_command_float(0x2050, 2, byref(args) )

    axis = 0
    xDev_set_svo(axis, 0)
    xDev_sva(axis, 10.0)
    pos = xDev_get_pos(axis)
    print("servo ch%d: %d"  % (axis, xDev_get_svo(axis)) )
    print("position ch%d: %7.3f" % (axis, pos) )
    print("PID ch:%d, P-Term: %7.3f" % (axis, xDev_get_param_float(axis, 0x20400100) ) )

    axisN = (c_int * 3)(0, 2, 1)
    tgtN = (c_float * 3)(5, 6, 7)
    xDev_svaN(3, axisN, tgtN)
    for axis in range(3) :
        print("Target of axis%d is %0.3f" % (axis, xDev_get_tgt(axis, 0)) )

    rate = 1
    axis = 0
    xDev_start_rec(rate, axis)

    recLen = 100
    recBuf = (c_float*recLen)()
    xDev_get_rec_data(recLen, recBuf)
    for i in range(recLen) : print("\t%0.3f" % recBuf[i])
    
    xDev_test_cmd()
    
    xDev_exit()
    del handle
    return 0

if __name__ == "__main__":
    xDev_test()
    input("Press Enter to exit...")
