from PyQt5.QtWidgets import QApplication
from qtpy.QtCore import QTimer
import sys
from parameter import *
from mdApi import *
from tdApi import *
import threading
from completeDb import *
import socket, select

class RdMdUi():

    # 程序初始化操作
    def __init__(self):
        # 是否切换合约的统计
        self.listChgDate = []
        self.execQtimer = False
        self.getEngine()  # 建立事件注册引擎
        self.getSecondEngine()  # 创建次要引擎事件
        self.getSocket()  # 建立 socket 事件
        self.getInit()  # 更新切换合约表和数据更新
        # 建立 qtimer 的检测合成事件
        self.timer0 = QTimer()
        self.timer0.timeout.connect(self.checkHeCheng)
        # 建立 自动登陆 的界面操作
        self.timer1 = QTimer()
        self.timer1.timeout.connect(self.autoLogin)
        # qtimer 可以执行，但是，我是想在内存读取完毕后，再进行操作
        self.timer0.start(1000 * 5)
        self.timer1.start(1000 * 5)

    # region 主引擎事件
    def getEngine(self):
        downLogProgram("创建事件主引擎")
        ee.register(EVENT_LOGINMA, self.loginMa)  # 登陆事件
        ee.register(EVENT_LOGINTD, self.loginTd)  # 登陆事件
        ee.register(EVENT_MARKETDATA_CONTRACT, self.dealTickData)  # tick数据处理方式
        self.listInstrumentInformation = []
        ee.register(EVENT_INSTRUMENT, self.judgeChgInstrument)  # 判断是否切换主力合约
        ee.start(timer=False)

    def loginMa(self, event):  # 登陆事件
        downLogProgram("获取主力合约，并登陆行情与交易接口")
        self.listExec = []  # 用于记录已经合成的品种
        # 账号的登陆信息
        userid = dictLoginInformation['userid']
        password = dictLoginInformation['password']
        brokerid = dictLoginInformation['broker']
        # 登陆行情接口
        self.md = MdApi(userid, password, brokerid, dictLoginInformation['front_addr'].split(',')[1])

    def loginTd(self, event):
        downLogProgram("登陆交易接口，目的是检测是否切换主力合约")
        self.listExec = []  # 用于记录已经合成的品种
        # 账号的登陆信息
        userid = dictLoginInformation['userid']
        password = dictLoginInformation['password']
        brokerid = dictLoginInformation['broker']
        product_info = dictLoginInformation['product_info']
        auth_code = dictLoginInformation['auth_code']
        app_id = dictLoginInformation['app_id']
        # 登陆交易接口
        self.td = TdApi(userid, password, brokerid, dictLoginInformation['front_addr'].split(',')[0], product_info, app_id, auth_code)
        t = 0
        while not self.td.isLogin and t < 10000:
            t += 1
            ttt.sleep(0.01)
        if t >= 10000:
            downLogProgram('{} 账号登陆失败，请查看帐号密码是否正确。'.format(userid))
        else:
            # 执行是否切换合约的判断
            self.td.t.ReqQryDepthMarketData()

    def dealTickData(self, event):
        data = {}
        if event.dict_["InstrumentID"][-4:].isdigit():
            chg = dictGoodsChg[event.dict_["InstrumentID"][:-4]]
            goodsCode = event.dict_["InstrumentID"][:-4] + '.' + chg
            goodsInstrument = event.dict_["InstrumentID"] + '.' + chg
            data['goodsCode'] = goodsInstrument
        else:
            chg = dictGoodsChg[event.dict_["InstrumentID"][:-3]]
            goodsCode = event.dict_["InstrumentID"][:-3] + '.' + chg
            goodsInstrument = event.dict_["InstrumentID"] + '.' + chg
            data['goodsCode'] = goodsInstrument
        tradeTime = pd.to_datetime(event.dict_["TradingDay"] + ' '
                                    + event.dict_["UpdateTime"] + '.'
                                    + str(event.dict_["UpdateMillisec"]))
        now = datetime.now()  # 如果获取的时间比当时要早，则进行操作
        if tradeTime > now:
            tradeTime = datetime(now.year, now.month, now.day, tradeTime.hour,
                                    tradeTime.minute, tradeTime.second, tradeTime.microsecond)
        data['close'] = round(event.dict_["LastPrice"], 4)
        if dictGoodsVolume[goodsCode]['amt'] == 0:  # 计算出 volume 与 amt
            data['volume'] = 0
            data['amt'] = 0
        else:
            data['volume'] = event.dict_["Volume"] - \
                             dictGoodsVolume[goodsCode]['volume']
            data['amt'] = event.dict_["Turnover"] - \
                          dictGoodsVolume[goodsCode]['amt']
        dictGoodsVolume[goodsCode]['volume'] = event.dict_["Volume"]
        dictGoodsVolume[goodsCode]['amt'] = event.dict_["Turnover"]
        data['position'] = event.dict_["OpenInterest"]
        # 需要避免一些严重的错误：
        if tradeTime < now + timedelta(minutes = 10) and tradeTime > now - timedelta(minutes = 10):  # 因为 theTradeTime会出现 2018-10-19 23:30:00 这一种错误的数据
            dictGoodsTick[goodsCode].loc[tradeTime] = [data[x] for x in listTick]
            strTick = str(tradeTime) + ' ' + str(data)
            downLogTick(strTick)
            minute = datetime(tradeTime.year,
                              tradeTime.month,
                              tradeTime.day,
                              tradeTime.hour,
                              tradeTime.minute)
            if tradeTime.second == 59 and tradeTime.microsecond >= 500000:
                minute += timedelta(minutes=1)
                self.heCheng(goodsCode, minute)
                self.listExec.append(goodsCode)
            elif goodsCode in self.listExec or (dictGoodsTick[goodsCode].shape[0] > 1
                                              and tradeTime.minute != dictGoodsTick[goodsCode].index[-2].minute
                                              and minute.time() in dictGoodsOneMin[goodsCode]):
                for goodsCode in dictGoodsName.keys():
                    if goodsCode not in self.listExec:
                        if minute.time() in dictGoodsOneMin[goodsCode]:
                            self.heCheng(goodsCode, minute)
                self.listExec = []
                
    def heCheng(self, goodsCode, minute):
        if minute.time() in dictGoodsOneMin[goodsCode]:
            theIndex = dictGoodsOneMin[goodsCode].index(minute.time())
            if minute.time() not in dictGoodsSend[goodsCode]:  # 如果当前分钟刚好是 收盘的数据前 如 11：30，  15：00 ， 能不需要急着合成数据
                dictGoodsOneMin[goodsCode] = dictGoodsOneMin[goodsCode][theIndex + 1:]  # 不然的话，都是可以合成的
                self.excHeCheng(goodsCode, minute)
        else:
            downLogProgram("时刻点 {} , 居然不在 dictGoodsOneMin 的 {} 上，请查看".format(minute.time(), goodsCode))
    
    def excHeCheng(self, goodsCode, minute):
        if minute.time() in dictGoodsSend[goodsCode]:
            dfTick = dictGoodsTick[goodsCode][dictGoodsTick[goodsCode].index >= minute - timedelta(minutes=1)]
            # 删除数据
            dictGoodsTick[goodsCode] = dictGoodsTick[goodsCode][0:0]
        else:
            dfTick = dictGoodsTick[goodsCode][(dictGoodsTick[goodsCode].index < minute)
                                                 & (dictGoodsTick[goodsCode].index >= minute - timedelta(minutes=1))]
            # 删除数据
            dictGoodsTick[goodsCode] = dictGoodsTick[goodsCode][dictGoodsTick[goodsCode].index >= minute]
        if dfTick.shape[0] > 0:
            theDict = {}
            theDict['goods_code'] = dfTick['goodsCode'][0]
            theDict['goods_name'] = dictGoodsName[goodsCode]
            theDict['theCode'] = goodsCode
            theDict['trade_time'] = minute
            theDict['close'] = round(dfTick['close'].iat[-1], 4)
            theDict['volume'] = int(dfTick['volume'].sum())
            theDict['amt'] = dfTick['amt'].sum()
            theDict['high'] = round(dfTick['close'].max(), 4)
            theDict['low'] = round(dfTick['close'].min(), 4)
            theDict['open'] = round(dfTick['close'][0], 4)
            theDict['oi'] = dfTick['position'].iat[-1]
            # 发送到各个策略上
            for each in self.listSend:
                try:
                    dictTemp = theDict.copy()
                    dictTemp['goods_name'] = dictTemp['goods_code']
                    each.sendall(str(dictTemp).encode())
                except:
                    downLogProgram("某个东西发不出去了")
                    print(each)
            self.queue.put(theDict)  # 放到次引擎上
        else:
            theDict = {}
            theDict['goods_code'] = dictGoodsInstrument[goodsCode]
            theDict['goods_name'] = dictGoodsName[goodsCode]
            theDict['theCode'] = goodsCode
            theDict['trade_time'] = minute
            theDict['close'] = dictData[1][dictGoodsName[goodsCode] + '_调整表']['close'].iat[-1]
            theDict['volume'] = 0
            theDict['amt'] = 0
            theDict['high'] = theDict['close']
            theDict['low'] = theDict['close']
            theDict['open'] = theDict['close']
            theDict['oi'] = dictData[1][dictGoodsName[goodsCode] + '_调整表']['oi'].iat[-1]
            # 发送到各个策略上
            for each in self.listSend:
                try:
                    dictTemp = theDict.copy()
                    dictTemp['goods_name'] = dictTemp['goods_code']
                    each.sendall(str(dictTemp).encode())
                except:
                    downLogProgram("某个东西发不出去了")
                    print(each)
            # 放到次引擎上
            self.queue.put(theDict)

    def judgeChgInstrument(self, event):
        dictTemp = event.dict_
        self.listInstrumentInformation.append(dictTemp)
        if dictTemp['last']:
            downLogProgram('查询主力合约是否变化完成')
            ret = pd.DataFrame(self.listInstrumentInformation)
            # 当天交易日时间为：
            now = datetime.now()
            tradeDayTemp = tradeDatetime[tradeDatetime >= now - timedelta(hours=17, minutes=15)].iat[0]
            for goodsCode in dictGoodsName.keys():
                goodsName = dictGoodsName[goodsCode]
                goodsIcon = goodsCode.split('.')[0]
                # 进行判断切换合约操作
                df = ret.loc[ret['ProductID'] == goodsIcon]  # 得到某一品种的所有持仓量
                df = df.reset_index(drop = True)
                if df.shape[0] > 0:
                    positionPath = 'position_max\\{} position_max.csv'.format(goodsCode.upper())
                    dfPosition = pd.read_csv(positionPath, encoding='gbk',
                                             parse_dates=['trade_time']).set_index('trade_time')
                    theGoodsInstrument = dfPosition['stock'].iat[-1].upper()
                    if goodsCode.split('.')[1] in ['CZC', 'CFE']:
                        theInstrument = theGoodsInstrument.split('.')[0].upper()
                    else:
                        theInstrument = theGoodsInstrument.split('.')[0].lower()
                    index = df['InstrumentID'].tolist().index(theInstrument)
                    df = df[index:]
                    df = df.sort_values(by='OpenInterest')
                    if df['InstrumentID'].iat[-1] == theInstrument:
                        dfPosition.loc[tradeDayTemp] = [theGoodsInstrument, df['OpenInterest'].iat[-1]]
                        dfPosition.to_csv(positionPath, encoding = "gbk")
                        # 重新写 chgAdjust， 因为没有切换合约， 所以只需要改日期即可
                        chgPath = 'chg_data\\{} chg_data.csv'.format(goodsCode.upper())
                        dfChgData = pd.read_csv(chgPath, encoding='gbk', parse_dates=['adjdate'])
                        dfChgData['adjdate'].iat[-1] = tradeDayTemp
                        dfChgData.to_csv(chgPath, encoding='gbk', index = False)
                    else:  # 切换主力合约
                        # 取消订阅旧合约 theInstrument
                        try:
                            self.md.q.UnSubscribeMarketData(theInstrument)
                        except:
                            downLogProgram("尚未登陆行情接口，不需要取消订阅")
                        agio = df['LastPrice'].iat[-1] - df['LastPrice'][df['InstrumentID'] == theInstrument].iat[0]
                        newGoodsInstrument = df['InstrumentID'].iat[-1] + '.' + theGoodsInstrument.split('.')[1].upper()
                        dfPosition.loc[tradeDayTemp] = [newGoodsInstrument.upper(), df['OpenInterest'].iat[-1]]
                        dfPosition.to_csv(positionPath, encoding="gbk")
                        # 重新写 chgAdjust
                        chgPath = 'chg_data\\{} chg_data.csv'.format(goodsCode.upper())
                        dfChgData = pd.read_csv(chgPath, encoding='gbk', parse_dates=['adjdate'])
                        dfChgData = dfChgData[:-1]
                        dfChgData.loc[dfChgData.shape[0] + 1] = {'id': dfChgData.shape[0] + 1,
                                                                 'goods_code': goodsCode.upper(),
                                                                 'goods_name': goodsName,
                                                                 'adjdate':tradeDayTemp,
                                                                 'adjinterval':agio,
                                                                 'stock':newGoodsInstrument.upper()}
                        dfChgData.loc[dfChgData.shape[0] + 1] = {'id': dfChgData.shape[0] + 1,
                                                                 'goods_code': goodsCode.upper(),
                                                                 'goods_name': goodsName,
                                                                 'adjdate': tradeDayTemp,
                                                                 'adjinterval': 0,
                                                                 'stock': newGoodsInstrument.upper()}
                        dfChgData.to_csv(chgPath, encoding='gbk', index=False)
                        # 写入 CTA 1 的调整时刻表
                        table = dictFreqCon[1][goodsName + '_调整时刻表']
                        theDict = {'goods_code' : newGoodsInstrument,
                                   'goods_name': goodsName,
                                   'adjdate': tradeDayTemp,
                                   'adjinterval': agio}
                        table.insert_one(theDict)
                print('重新设置 {} 的 dictGoodsOneMin'.format(goodsCode))
                dictGoodsOneMin[goodsCode] = dictFreqGoodsClose[1][goodsCode]
            self.listInstrumentInformation = []
            checkChg()
            # 进行 MA 登陆操作
            event = Event(type_=EVENT_LOGINMA)  # 重新登陆的操作
            ee.put(event)
    # endregion

    # region 次引擎事件
    def getSecondEngine(self):
        self.queue = Queue()
        threading.Thread(target=self.execEngine, daemon=True).start()

    def execEngine(self):
        while True:
            try:
                dictTemp = self.queue.get(block=True, timeout=1)  # 获取事件阻塞设为1秒
                onBar(dictTemp)
            except Empty:
                pass
    # endregion

    # region 建立 socket 事件
    def getSocket(self):
        threading.Thread(target=self.createSocket, daemon=True).start()

    def createSocket(self):
        downLogProgram("正在建立 socket 通信")
        CONNECTION_LIST = []
        self.listSend = []
        serverSocket = socket.socket()
        try:
            serverSocket.bind(('', port))
        except:
            downLogProgram("该端口不可用")
        else:
            serverSocket.listen(20)  # 最多支持 20 个客户端
            CONNECTION_LIST.append(serverSocket)
            downLogProgram("socket 通信建立完成")
            while 1:
                read_sockets, write_sockets, error_sockets = select.select(CONNECTION_LIST, [], [])  # 等待接收事件
                for sock in read_sockets:
                    if sock == serverSocket:
                        sockfd, addr = serverSocket.accept()
                        CONNECTION_LIST.append(sockfd)
                        self.listSend.append(sockfd)
                        downLogProgram("地址{}成功接入".format(addr[0]))
                    else:  # 主要判断连接是否已经关闭，如果是关闭的话，那么将 CONNECTION_LIST 中的 sock 去除：
                        try:
                            sock.send(b'')
                        except:
                            CONNECTION_LIST.remove(sock)
                            self.listSend.remove(sock)
                            sock.close()
                            downLogProgram("某一地址退出连接")
    # endregion

    # region 自动更新 chg_data 与 position_data
    def getInit(self):
        threading.Thread(target=self.getData, daemon=True).start()

    def getData(self):
        downLogProgram("正在从 mongodb 上读取 CTA 数据到内存")
        for freq in listFreqPlus:
            dictData[freq] = {}
            con = dictFreqCon[freq]
            downLogProgram("将 CTA{} 数据写入内存上".format(freq))
            for goodsName in dictGoodsName.values():
                if freq == 1:
                    dictData[freq][goodsName + '_调整表'] = readMongoNum(con, '{}_调整表'.format(goodsName), readNum).set_index('trade_time').sort_index()
                    dictData[freq][goodsName + '_调整表'] = dictData[freq][goodsName + '_调整表'][listMin]
                else:
                    dictData[freq][goodsName + '_调整表'] = readMongoNum(con, '{}_调整表'.format(goodsName), readNum).set_index('trade_time').sort_index()
                    dictData[freq][goodsName + '_均值表'] = readMongoNum(con, '{}_均值表'.format(goodsName), readNum).set_index('trade_time').sort_index()
                    dictData[freq][goodsName + '_重叠度表'] = readMongoNum(con, '{}_重叠度表'.format(goodsName), readNum).set_index('trade_time').sort_index()
                    dictData[freq][goodsName + '_调整表'] = dictData[freq][goodsName + '_调整表'][listMin]
                    dictData[freq][goodsName + '_均值表'] = dictData[freq][goodsName + '_均值表'][listMa]
                    dictData[freq][goodsName + '_重叠度表'] = dictData[freq][goodsName + '_重叠度表'][listOverLap]
        downLogProgram('将数据库数据写入内存上操作完成')
        # 开始补充数据
        completeDb()
        downLogProgram('重叠度数据计算完成')
        # 需要执行到这时，才进行 QTimer 的操作
        self.execQtimer = True
    # endregion

    # region QTimer 的循环操作
    def checkHeCheng(self):  # 这个 qtimer 主要用于检查，是否存在 有一些 到了需要合成分钟的时候，但是却没有合成 1 分钟的数据
        now = datetime.now() - timedelta(seconds = 10)
        now = datetime(now.year, now.month, now.day, now.hour, now.minute)
        if not self.execQtimer:
            return
        # 查看是否有缺分钟的数量
        for goodsCode in dictGoodsName.keys():
            if len(dictGoodsOneMin[goodsCode]) > 0:
                if dictGoodsOneMin[goodsCode][0] not in dictGoodsFront[goodsCode] and now.time() == dictGoodsOneMin[goodsCode][0]:
                    minute = now
                    dictGoodsOneMin[goodsCode] = dictGoodsOneMin[goodsCode][1:]
                    if minute.time() not in dictGoodsSend[goodsCode]:  # 合成指定的分钟数据
                        downLogProgram("商品{} ，在{}时刻上没有接收到tick数据".format(goodsCode, minute))
                    self.excHeCheng(goodsCode, minute)  # 合成操作

    def autoLogin(self):  # 自动重新登陆操作
        now = datetime.now()
        now = datetime(now.year, now.month, now.day, now.hour, now.minute)
        if not self.execQtimer:
            return
        if (now + timedelta(hours = 3, minutes = 30)).strftime('%Y-%m-%d') not in self.listChgDate:  # 因为我想在晚上 8:30 分准时执行
            # 重新登陆 LoginTD 的操作
            event = Event(type_=EVENT_LOGINTD)  # 登陆 tdApi 的操作：
            ee.put(event)
            self.listChgDate.append((now + timedelta(hours = 3, minutes = 30)).strftime('%Y-%m-%d'))
    # endregion

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ui = RdMdUi()
    sys.exit(app.exec_())