from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5 import uic
import python_bithumb
import pyupbit
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sqlite3
import os
from dotenv import load_dotenv
from autotrade import AutoTradeWindow
from chart import ChartWindow
import matplotlib.pyplot as plt
import threading
import time
import traceback

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # UI 로드
        uic.loadUi('main.ui', self)
        
        # 변수 초기화
        self.is_connected = False
        self.bithumb = None
        self.current_price = 0
        self.order_book = None
        self.volume = None
        self.market_codes = None
        
        # .env 파일 로드
        load_dotenv()
        
        # 시그널/슬롯 연결
        self.setup_connections()
        
    def setup_connections(self):
        # 코인 선택 변경
        self.coinCombo.currentTextChanged.connect(self.on_coin_changed)
        
        # API 연결 버튼
        self.connectBtn.clicked.connect(self.toggle_connection)
        
        # 자동매매 시작 버튼
        self.autoTradeBtn.clicked.connect(self.show_auto_trade_window)
        
        # 실시간 차트 버튼
        self.realtimeStartBtn.clicked.connect(self.show_chart_window)
        
        # 공개 API 기능
        self.currentPriceBtn.clicked.connect(self.get_current_price)
        self.orderbookBtn.clicked.connect(self.get_order_book)
        self.volumeBtn.clicked.connect(self.get_volume)
        self.candleBtn.clicked.connect(self.get_candles)
        self.marketCodesBtn.clicked.connect(self.get_market_codes)
        self.warningBtn.clicked.connect(self.get_warning)
        
        # 실시간 계산기
        self.calcAmtInput.valueChanged.connect(self.calculate_quantity)
        self.calcPriceInput.valueChanged.connect(self.calculate_quantity)
        
        # private API 기능 버튼 연결
        self.balanceBtn.clicked.connect(self.get_balance)
        self.orderChanceBtn.clicked.connect(self.get_order_chance)
        self.buyLimitBtn.clicked.connect(self.buy_limit_order)
        self.sellLimitBtn.clicked.connect(self.sell_limit_order)
        self.buyMarketBtn.clicked.connect(self.buy_market_order)
        self.sellMarketBtn.clicked.connect(self.sell_market_order)
        
    def on_coin_changed(self):
        if self.is_connected:
            self.get_current_price()
            
    def toggle_connection(self):
        if not self.is_connected:
            self.connect_api()
        else:
            self.disconnect_api()
            
    def connect_api(self):
        try:
            api_key = os.getenv('BITHUMB_API_KEY')
            api_secret = os.getenv('BITHUMB_API_SECRET')
            if not api_key or not api_secret:
                QMessageBox.warning(self, "경고", "API 키가 설정되지 않았습니다.")
                return
            self.bithumb = python_bithumb.Bithumb(api_key, api_secret)
            self.is_connected = True
            self.connectBtn.setText("연결 해제")
            self.statusBar().showMessage("API 연결됨")
            self.enable_private_buttons(True)
            # 초기 데이터 로드
            self.get_current_price()
            self.get_order_book()
            self.get_volume()
            self.get_market_codes()
        except Exception as e:
            QMessageBox.warning(self, "오류", f"API 연결 실패: {str(e)}")
            
    def disconnect_api(self):
        self.bithumb = None
        self.is_connected = False
        self.connectBtn.setText("연결")
        self.statusBar().showMessage("API 연결 해제됨")
        self.enable_private_buttons(False)
        
    def enable_private_buttons(self, enabled):
        self.balanceBtn.setEnabled(enabled)
        self.orderChanceBtn.setEnabled(enabled)
        self.buyLimitBtn.setEnabled(enabled)
        self.sellLimitBtn.setEnabled(enabled)
        self.buyMarketBtn.setEnabled(enabled)
        self.sellMarketBtn.setEnabled(enabled)
        self.autoTradeBtn.setEnabled(enabled)  # 자동매매 버튼도 활성화/비활성화
        
    def show_auto_trade_window(self):
        if not self.is_connected:
            QMessageBox.warning(self, "경고", "API에 먼저 연결해주세요.")
            return
            
        self.auto_trade_window = AutoTradeWindow(self)
        self.auto_trade_window.show()
        
    def show_chart_window(self):
        self.chart_window = ChartWindow()
        self.chart_window.show()
        
    def get_current_price(self):
        try:
            coin = self.coinCombo.currentText()
            price = python_bithumb.get_current_price(f"KRW-{coin}")
            if price:
                self.current_price = price
                self.priceLabel_2.setText(f"현재가: {price:,.0f}원")
                self.calcPriceInput.setValue(price)
                self.resultText.append(f"[{coin}] 현재가: {price:,.0f}원")
            else:
                self.resultText.append(f"[{coin}] 현재가 조회 실패: 데이터 없음")
        except Exception as e:
            self.statusBar().showMessage(f"현재가 조회 실패: {str(e)}")
            self.resultText.append(f"현재가 조회 실패: {str(e)}")
            
    def get_order_book(self):
        try:
            coin = self.coinCombo.currentText()
            order_book = python_bithumb.get_orderbook(f"KRW-{coin}")
            if order_book and 'orderbook_units' in order_book:
                self.order_book = order_book
                self.resultText.append(f"\n[{coin}] === 매수 호가 ===")
                for unit in order_book['orderbook_units'][:5]:
                    price = unit.get('bid_price')
                    size = unit.get('bid_size')
                    self.resultText.append(f"가격: {price:,.0f}원, 수량: {size:.8f}")
                self.resultText.append("=== 매도 호가 ===")
                for unit in order_book['orderbook_units'][:5]:
                    price = unit.get('ask_price')
                    size = unit.get('ask_size')
                    self.resultText.append(f"가격: {price:,.0f}원, 수량: {size:.8f}")
            else:
                self.resultText.append(f"[{coin}] 호가 정보 조회 실패: 데이터 없음 또는 형식 오류\n{order_book}")
        except Exception as e:
            self.statusBar().showMessage(f"호가창 조회 실패: {str(e)}")
            self.resultText.append(f"호가창 조회 실패: {str(e)}")
            
    def get_volume(self):
        try:
            coin = self.coinCombo.currentText()
            market = f"KRW-{coin}"
            # 24시간 거래량은 ohlcv에서 volume 합산
            df = python_bithumb.get_ohlcv(market, interval="day", count=1)
            if not df.empty:
                volume = df.iloc[0]['volume']
                self.volume = volume
                self.resultText.append(f"\n[{coin}] === 24시간 거래량 ===\n{volume:,.0f}")
            else:
                self.resultText.append(f"[{coin}] 거래량 조회 실패: 데이터 없음")
        except Exception as e:
            self.statusBar().showMessage(f"거래량 조회 실패: {str(e)}")
            self.resultText.append(f"거래량 조회 실패: {str(e)}")
            
    def get_market_codes(self):
        """마켓 코드 조회"""
        try:
            all_markets = python_bithumb.get_market_all()  # 리스트 반환, 각 항목은 dict
            markets = [m['market'] for m in all_markets if 'market' in m]
            self.resultText.append("=== 마켓 코드 목록 ===")
            self.resultText.append("KRW 마켓:")
            for code in markets:
                if code.startswith('KRW-'):
                    self.resultText.append(f"- {code}")
            self.resultText.append("\nBTC 마켓:")
            for code in markets:
                if code.startswith('BTC-'):
                    self.resultText.append(f"- {code}")
            self.resultText.append("\n")
        except Exception as e:
            self.resultText.append(f"마켓 코드 조회 실패: {str(e)}")
            
    def get_warning(self):
        """가상자산 경고 조회"""
        try:
            if self.bithumb:
                warnings = self.bithumb.get_warning()
            else:
                warnings = python_bithumb.get_virtual_asset_warning()
                
            if warnings:
                self.resultText.append("=== 가상자산 경고 현황 ===")
                self.resultText.append("거래량 급증:")
                for warning in warnings:
                    if warning.get('warning_type') == 'TRADING_VOLUME_SUDDEN_FLUCTUATION':
                        self.resultText.append(f"- {warning['market']} (종료: {warning['end_date']})")
                
                self.resultText.append("\n예수금 급증:")
                for warning in warnings:
                    if warning.get('warning_type') == 'DEPOSIT_AMOUNT_SUDDEN_FLUCTUATION':
                        self.resultText.append(f"- {warning['market']} (종료: {warning['end_date']})")
                self.resultText.append("\n")
            else:
                self.resultText.append("현재 경고 대상이 없습니다.\n")
        except Exception as e:
            self.resultText.append(f"가상자산 경고 조회 실패: {str(e)}")
            
    def calculate_quantity(self):
        try:
            amount = self.calcAmtInput.value()
            price = self.calcPriceInput.value()
            
            if price > 0:
                quantity = amount / price
                self.calcQtyLabel.setText(f"예상 수량: {quantity:.8f}")
            else:
                self.calcQtyLabel.setText("예상 수량: 0")
                
        except ValueError:
            self.calcQtyLabel.setText("예상 수량: 0")
            
    def get_candles(self):
        try:
            import matplotlib
            matplotlib.rc('font', family='Malgun Gothic')
            matplotlib.rcParams['axes.unicode_minus'] = False
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
            import mplfinance as mpf

            coin = self.coinCombo.currentText()
            interval_text = self.intervalCombo.currentText()
            count = int(self.countCombo.currentText())

            # interval 변환
            interval_map = {
                "1분": "minute1",
                "3분": "minute3",
                "5분": "minute5",
                "15분": "minute15",
                "30분": "minute30",
                "60분": "minute60",
                "240분": "minute240",
                "일": "day",
                "주": "week",
                "월": "month"
            }
            interval = interval_map.get(interval_text, "minute1")
            market = f"KRW-{coin}"
            
            # API에서 직접 데이터 요청
            df = python_bithumb.get_ohlcv(market, interval=interval, count=count)
            
            if df is not None and not df.empty:
                # chartWidget에 기존 차트 제거
                layout = self.chartWidget.layout()
                if layout is None:
                    from PyQt5.QtWidgets import QVBoxLayout
                    layout = QVBoxLayout(self.chartWidget)
                    self.chartWidget.setLayout(layout)
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    if widget:
                        widget.setParent(None)

                # 캔들스틱 차트 생성
                fig = Figure(figsize=(8, 4))
                ax = fig.add_subplot(111)
                
                # 캔들스틱 스타일 설정
                mc = mpf.make_marketcolors(up='red', down='blue',
                                         edge='inherit',
                                         wick='inherit',
                                         volume='in')
                s = mpf.make_mpf_style(marketcolors=mc,
                                     gridstyle='dotted',
                                     y_on_right=False)
                
                # 캔들스틱 차트 그리기
                mpf.plot(df, type='candle', style=s, ax=ax,
                        volume=False, show_nontrading=True)
                
                # 차트 제목 및 레이블 설정
                ax.set_title(f"{market} {interval_text} 캔들스틱 차트")
                ax.set_xlabel('시간')
                ax.set_ylabel('가격')
                
                # x축 날짜 포맷 설정
                fig.autofmt_xdate()
                
                # 그리드 추가
                ax.grid(True, linestyle='--', alpha=0.7)
                
                # y축 가격 포맷 설정
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: format(int(x), ',')))
                
                canvas = FigureCanvas(fig)
                layout.addWidget(canvas)
                
                # 차트 정보 표시
                self.resultText.append(f"\n=== {market} 차트 정보 ===")
                self.resultText.append(f"기간: {interval_text}")
                self.resultText.append(f"시작가: {df.iloc[0]['open']:,.0f}원")
                self.resultText.append(f"종가: {df.iloc[-1]['close']:,.0f}원")
                self.resultText.append(f"고가: {df['high'].max():,.0f}원")
                self.resultText.append(f"저가: {df['low'].min():,.0f}원")
                self.resultText.append(f"거래량: {df['volume'].sum():,.0f}")
                
            else:
                self.resultText.append(f"[{coin}] 캔들 차트 조회 실패: 데이터 없음")
        except Exception as e:
            self.statusBar().showMessage(f"캔들 차트 조회 실패: {str(e)}")
            self.resultText.append(f"캔들 차트 조회 실패: {str(e)}")
            
    def get_balance(self):
        if not self.is_connected or not self.bithumb:
            self.resultText.append("API 연결이 필요합니다.")
            return
        try:
            # 전체 잔고 조회
            balances = self.bithumb.get_balances()
            self.resultText.append("\n=== 잔고 정보 ===")
            
            # KRW와 선택된 코인의 잔고만 표시
            for balance in balances:
                currency = balance['currency']
                if currency == 'KRW' or currency == self.coinCombo.currentText():
                    self.resultText.append(f"화폐: {currency}")
                    self.resultText.append(f"보유량: {float(balance['balance']):.8f}")
                    if 'locked' in balance:
                        self.resultText.append(f"거래 중: {float(balance['locked']):.8f}")
                    if 'avg_buy_price' in balance:
                        self.resultText.append(f"평균 매수가: {float(balance['avg_buy_price']):,.0f}원")
                    self.resultText.append("")
                
        except Exception as e:
            self.resultText.append(f"잔고 조회 실패: {str(e)}")
            self.resultText.append(f"반환된 데이터: {balances}")  # 디버깅을 위해 반환된 데이터 출력

    def get_order_chance(self):
        if not self.is_connected or not self.bithumb:
            self.resultText.append("API 연결이 필요합니다.")
            return
        try:
            chance = self.bithumb.get_order_chance(f"KRW-{self.coinCombo.currentText()}")
            self.resultText.append("\n=== 주문 가능 정보 ===")
            
            # 수수료 정보
            self.resultText.append("\n[수수료 정보]")
            self.resultText.append(f"매수 수수료: {chance['bid_fee']}%")
            self.resultText.append(f"매도 수수료: {chance['ask_fee']}%")
            self.resultText.append(f"마켓 매수 수수료: {chance['maker_bid_fee']}%")
            self.resultText.append(f"마켓 매도 수수료: {chance['maker_ask_fee']}%")
            
            # 마켓 정보
            market = chance['market']
            self.resultText.append("\n[마켓 정보]")
            self.resultText.append(f"마켓 ID: {market['id']}")
            self.resultText.append(f"마켓 이름: {market['name']}")
            self.resultText.append(f"지원 주문 방식: {', '.join(market['order_types'])}")
            self.resultText.append(f"매수 주문 방식: {', '.join(market['bid_types'])}")
            self.resultText.append(f"매도 주문 방식: {', '.join(market['ask_types'])}")
            self.resultText.append(f"지원 주문 종류: {', '.join(market['order_sides'])}")
            self.resultText.append(f"마켓 상태: {market['state']}")
            self.resultText.append(f"최대 매도/매수 금액: {market['max_total']}")
            
            # 매수 제약사항
            bid = market['bid']
            self.resultText.append("\n[매수 제약사항]")
            self.resultText.append(f"화폐: {bid['currency']}")
            self.resultText.append(f"최소 주문금액: {bid['min_total']}")
            
            # 매도 제약사항
            ask = market['ask']
            self.resultText.append("\n[매도 제약사항]")
            self.resultText.append(f"화폐: {ask['currency']}")
            self.resultText.append(f"최소 주문금액: {ask['min_total']}")
            
            # 계정 정보
            bid_account = chance['bid_account']
            self.resultText.append("\n[매수 계정 정보]")
            self.resultText.append(f"화폐: {bid_account['currency']}")
            self.resultText.append(f"주문가능 금액: {bid_account['balance']}")
            self.resultText.append(f"주문중인 금액: {bid_account['locked']}")
            self.resultText.append(f"매수평균가: {bid_account['avg_buy_price']}")
            self.resultText.append(f"매수평균가 수정여부: {bid_account['avg_buy_price_modified']}")
            self.resultText.append(f"평단가 기준 화폐: {bid_account['unit_currency']}")
            
            ask_account = chance['ask_account']
            self.resultText.append("\n[매도 계정 정보]")
            self.resultText.append(f"화폐: {ask_account['currency']}")
            self.resultText.append(f"주문가능 수량: {ask_account['balance']}")
            self.resultText.append(f"주문중인 수량: {ask_account['locked']}")
            self.resultText.append(f"매수평균가: {ask_account['avg_buy_price']}")
            self.resultText.append(f"매수평균가 수정여부: {ask_account['avg_buy_price_modified']}")
            self.resultText.append(f"평단가 기준 화폐: {ask_account['unit_currency']}")
            
        except Exception as e:
            self.resultText.append(f"주문 가능 정보 조회 실패: {str(e)}")
            
    def buy_limit_order(self):
        if not self.is_connected or not self.bithumb:
            self.resultText.append("API 연결이 필요합니다.")
            return
        try:
            price, ok = QInputDialog.getDouble(self, '지정가 매수', '가격을 입력하세요:', 0, 0, 1000000000, 2)
            if ok:
                dlg = QDialog(self)
                dlg.setWindowTitle('지정가 매수')
                vbox = QVBoxLayout()
                label = QLabel('구매할 금액(원)을 입력하세요:')
                vbox.addWidget(label)
                amount_input = QDoubleSpinBox()
                amount_input.setDecimals(0)
                amount_input.setRange(0, 1000000000)
                vbox.addWidget(amount_input)
                qty_label = QLabel('예상 수량: 0')
                vbox.addWidget(qty_label)
                def update_qty():
                    amt = amount_input.value()
                    qty = round(amt / price, 8) if price > 0 else 0
                    qty_label.setText(f'예상 수량: {qty} {self.coinCombo.currentText()}')
                amount_input.valueChanged.connect(update_qty)
                update_qty()
                btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                vbox.addWidget(btns)
                dlg.setLayout(vbox)
                btns.accepted.connect(dlg.accept)
                btns.rejected.connect(dlg.reject)
                if dlg.exec_() == QDialog.Accepted:
                    amount = amount_input.value()
                    volume = round(amount / price, 8)
                    try:
                        order = self.bithumb.buy_limit_order(f"KRW-{self.coinCombo.currentText()}", price, volume)
                        self.resultText.append(f"\n지정가 매수 주문 성공: {order}")
                    except Exception as e:
                        self.resultText.append(f"지정가 매수 실패: {str(e)}")
                        if 'HTTP 201' in str(e):
                            self.resultText.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.resultText.append(f"지정가 매수 실패: {str(e)}")

    def sell_limit_order(self):
        if not self.is_connected or not self.bithumb:
            self.resultText.append("API 연결이 필요합니다.")
            return
        try:
            price, ok = QInputDialog.getDouble(self, '지정가 매도', '가격을 입력하세요:', 0, 0, 1000000000, 2)
            if ok:
                dlg = QDialog(self)
                dlg.setWindowTitle('지정가 매도')
                vbox = QVBoxLayout()
                label = QLabel('판매 금액(원)을 입력하세요:')
                vbox.addWidget(label)
                amount_input = QDoubleSpinBox()
                amount_input.setDecimals(0)
                amount_input.setRange(0, 1000000000)
                vbox.addWidget(amount_input)
                qty_label = QLabel('예상 수량: 0')
                vbox.addWidget(qty_label)
                def update_qty():
                    amt = amount_input.value()
                    qty = round(amt / price, 8) if price > 0 else 0
                    qty_label.setText(f'예상 수량: {qty} {self.coinCombo.currentText()}')
                amount_input.valueChanged.connect(update_qty)
                update_qty()
                btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                vbox.addWidget(btns)
                dlg.setLayout(vbox)
                btns.accepted.connect(dlg.accept)
                btns.rejected.connect(dlg.reject)
                if dlg.exec_() == QDialog.Accepted:
                    amount = amount_input.value()
                    volume = round(amount / price, 8)
                    try:
                        order = self.bithumb.sell_limit_order(f"KRW-{self.coinCombo.currentText()}", price, volume)
                        self.resultText.append(f"\n지정가 매도 주문 성공: {order}")
                    except Exception as e:
                        self.resultText.append(f"지정가 매도 실패: {str(e)}")
                        if 'HTTP 201' in str(e):
                            self.resultText.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.resultText.append(f"지정가 매도 실패: {str(e)}")

    def buy_market_order(self):
        if not self.is_connected or not self.bithumb:
            self.resultText.append("API 연결이 필요합니다.")
            return
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle('시장가 매수')
            vbox = QVBoxLayout()
            label = QLabel('구매할 금액(원)을 입력하세요:')
            vbox.addWidget(label)
            amount_input = QDoubleSpinBox()
            amount_input.setDecimals(0)
            amount_input.setRange(0, 1000000000)
            vbox.addWidget(amount_input)
            price = python_bithumb.get_current_price(f"KRW-{self.coinCombo.currentText()}")
            qty_label = QLabel('예상 수량: 0')
            vbox.addWidget(qty_label)
            def update_qty():
                amt = amount_input.value()
                qty = round(amt / price, 8) if price > 0 else 0
                qty_label.setText(f'예상 수량: {qty} {self.coinCombo.currentText()}')
            amount_input.valueChanged.connect(update_qty)
            update_qty()
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            vbox.addWidget(btns)
            dlg.setLayout(vbox)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            if dlg.exec_() == QDialog.Accepted:
                amount = amount_input.value()
                try:
                    chance = self.bithumb.get_order_chance(f"KRW-{self.coinCombo.currentText()}")
                    min_total = float(chance['market']['bid']['min_total'])
                    if amount < min_total:
                        self.resultText.append(f"[경고] 최소 주문 금액({min_total:,.0f}원) 미만입니다.")
                        return
                except Exception as e:
                    pass
                try:
                    order = self.bithumb.buy_market_order(f"KRW-{self.coinCombo.currentText()}", amount)
                    self.resultText.append(f"\n시장가 매수 주문 성공: {order}")
                except Exception as e:
                    self.resultText.append(f"시장가 매수 실패: {str(e)}")
                    if 'HTTP 201' in str(e):
                        self.resultText.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.resultText.append(f"시장가 매수 실패: {str(e)}")

    def sell_market_order(self):
        if not self.is_connected or not self.bithumb:
            self.resultText.append("API 연결이 필요합니다.")
            return
        try:
            price = python_bithumb.get_current_price(f"KRW-{self.coinCombo.currentText()}")
            dlg = QDialog(self)
            dlg.setWindowTitle('시장가 매도')
            vbox = QVBoxLayout()
            label = QLabel('판매 금액(원)을 입력하세요:')
            vbox.addWidget(label)
            amount_input = QDoubleSpinBox()
            amount_input.setDecimals(0)
            amount_input.setRange(0, 1000000000)
            vbox.addWidget(amount_input)
            qty_label = QLabel('예상 수량: 0')
            vbox.addWidget(qty_label)
            def update_qty():
                amt = amount_input.value()
                qty = round(amt / price, 8) if price > 0 else 0
                qty_label.setText(f'예상 수량: {qty} {self.coinCombo.currentText()}')
            amount_input.valueChanged.connect(update_qty)
            update_qty()
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            vbox.addWidget(btns)
            dlg.setLayout(vbox)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            if dlg.exec_() == QDialog.Accepted:
                amount = amount_input.value()
                volume = round(amount / price, 8)
                try:
                    chance = self.bithumb.get_order_chance(f"KRW-{self.coinCombo.currentText()}")
                    min_total = float(chance['market']['ask']['min_total'])
                    if amount < min_total:
                        self.resultText.append(f"[경고] 최소 주문 금액({min_total:,.0f}원) 미만입니다.")
                        return
                except Exception as e:
                    pass
                try:
                    order = self.bithumb.sell_market_order(f"KRW-{self.coinCombo.currentText()}", volume)
                    self.resultText.append(f"\n시장가 매도 주문 성공: {order}")
                except Exception as e:
                    self.resultText.append(f"시장가 매도 실패: {str(e)}")
                    if 'HTTP 201' in str(e):
                        self.resultText.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.resultText.append(f"시장가 매도 실패: {str(e)}")

if __name__ == '__main__':
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec_() 