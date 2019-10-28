from PyQt5.QtWidgets import QApplication
from py_ctp.ctp_struct import *
from py_ctp.ctp_quote import *
from py_ctp.eventEngine import *
from py_ctp.eventType import *
from parameter import *

class MdApi:
    def __init__(self, userid, password, brokerid, address):
        # 登陆的账户与密码
        self.userid = userid
        self.password = password
        self.brokerid = brokerid
        self.address = address
        # 创建Quote对象
        self.q = Quote()
        api = self.q.CreateApi()
        spi = self.q.CreateSpi()
        self.q.RegisterSpi(spi)
        self.q.OnFrontConnected = self.onFrontConnected  # 交易服务器登陆相应
        self.q.OnFrontDisconnected = self.onFrontDisconnected
        self.q.OnRspUserLogin = self.onRspUserLogin  # 用户登陆
        self.q.OnRspUserLogout = self.onRspUserLogout  # 用户登出
        self.q.OnRspError = self.onRspError
        self.q.OnRspSubMarketData = self.onRspSubMarketData
        self.q.OnRtnDepthMarketData = self.onRtnDepthMarketData
        self.q.RegCB()
        self.q.RegisterFront(self.address)
        self.q.Init()
        self.islogin = False  # 判断是否登陆成功

    def onFrontConnected(self):
        """服务器连接"""
        downLogProgram('行情服务器连接成功')
        self.q.ReqUserLogin(BrokerID=self.brokerid, UserID=self.userid, Password=self.password)

    def onFrontDisconnected(self, n):
        """服务器断开"""
        downLogProgram('行情服务器连接断开')

    def onRspUserLogin(self, data, error, n, last):
        """登陆回报"""
        if error.getErrorID() == 0:
            log = '行情服务器登陆成功'
            self.islogin = True
            downLogProgram(log)
            downLogProgram("订阅主力合约")
            for goodsCode in dictGoodsInstrument.keys():
                dictGoodsTick[goodsCode] = pd.DataFrame(columns=listTick)
                instrument = dictGoodsInstrument[goodsCode]
                self.q.SubscribeMarketData(instrument)
        else:
            log = '行情服务器登陆回报，错误代码：' + str(error.getErrorID()) + \
                  ',   错误信息：' + str(error.getErrorMsg())
            downLogProgram(log)

    def onRspUserLogout(self, data, error, n, last):
        if error.getErrorID() == 0:
            log = '行情服务器登出成功'
            self.islogin = False
        else:
            log = '行情服务器登出回报，错误代码：' + str(error.getErrorID()) + \
                  ',   错误信息：' + str(error.getErrorMsg())
        downLogProgram(log)

    def onRspError(self, error, n, last):
        """错误回报"""
        log = '行情错误回报，错误代码：' + str(error.getErrorID()) \
              + '错误信息：' + + str(error.getErrorMsg())
        downLogProgram(log)

    def onRspSubMarketData(self, data, info, n, last):
        pass

    def onRtnDepthMarketData(self, data):
        """行情推送"""
        event = Event(type_=EVENT_MARKETDATA_CONTRACT)
        event.dict_['InstrumentID'] = data.getInstrumentID()
        event.dict_['TradingDay'] = data.getTradingDay()
        event.dict_['UpdateTime'] = data.getUpdateTime()
        event.dict_['UpdateMillisec'] = data.getUpdateMillisec()
        event.dict_['LastPrice'] = data.getLastPrice()
        event.dict_['Volume'] = data.getVolume()
        event.dict_['Turnover'] = data.getTurnover()
        event.dict_['OpenInterest'] = data.getOpenInterest()
        ee.put(event)
