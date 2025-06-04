import sys
import os
import json
import time
import threading
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import python_bithumb
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from dotenv import load_dotenv
import matplotlib.dates as mdates
from PyQt5.QtCore import QTimer
import traceback

# 한글 폰트 설정 (모든 차트에 적용)
plt.rcParams['font.family'] = 'Malgun Gothic'

class BithumbTrader(QMainWindow):
    def __init__(self):
        super().__init__()
        # .env 파일 로드
        load_dotenv()
        self.initUI()
        self.is_connected = False
        self.current_price = 0
        self.trading_enabled = False
        self.price_update_thread = None
        self.bithumb = None
        
        # 실시간 데이터 저장용 변수
        self.realtime_price_data = []
        self.realtime_time_data = []
        self.realtime_volume_data = []
        
        # 실시간 차트 상태 변수
        self.realtime_running = False
        self.realtime_timer = QTimer()
        self.realtime_timer.timeout.connect(self.fetch_realtime_data)
        self.realtime_chart_window = None
        
    def initUI(self):
        self.setWindowTitle('Bithumb Auto Trader')
        self.setGeometry(100, 100, 1400, 1000)  # 창 크기 증가
        
        # 메인 위젯 설정
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # 전체를 감싸는 가로 레이아웃
        main_hbox = QHBoxLayout()
        
        # 왼쪽(기존) 세로 레이아웃
        layout = QVBoxLayout()
        
        # 상단 컨트롤 패널
        control_panel = QHBoxLayout()
        
        # 코인 선택
        self.coin_combo = QComboBox()
        self.coin_combo.addItems(['BTC', 'ETH', 'XRP', 'ADA'])
        self.coin_combo.currentIndexChanged.connect(self.on_coin_changed)
        control_panel.addWidget(QLabel('코인:'))
        control_panel.addWidget(self.coin_combo)
        
        # API 키는 .env에서 로드하고 GUI에는 표시하지 않음
        self.api_key = os.getenv('BITHUMB_API_KEY', '')
        self.api_secret = os.getenv('BITHUMB_API_SECRET', '')
        
        # 연결 버튼
        self.connect_btn = QPushButton('연결')
        self.connect_btn.clicked.connect(self.toggle_connection)
        control_panel.addWidget(self.connect_btn)
        
        # 자동매매 토글 버튼
        self.auto_trade_btn = QPushButton('자동매매 시작')
        self.auto_trade_btn.clicked.connect(self.toggle_auto_trade)
        self.auto_trade_btn.setEnabled(False)
        control_panel.addWidget(self.auto_trade_btn)
        
        layout.addLayout(control_panel)
        
        # 공개 API 기능 패널
        public_api_panel = QGroupBox("공개 API 기능")
        public_api_layout = QGridLayout()
        
        # 현재가 조회
        self.current_price_btn = QPushButton('현재가 조회')
        self.current_price_btn.clicked.connect(self.get_current_price)
        public_api_layout.addWidget(self.current_price_btn, 0, 0)
        
        # 호가 정보 조회
        self.orderbook_btn = QPushButton('호가 정보 조회')
        self.orderbook_btn.clicked.connect(self.get_orderbook)
        public_api_layout.addWidget(self.orderbook_btn, 0, 1)
        
        # 거래량 조회
        self.volume_btn = QPushButton('거래량 조회')
        self.volume_btn.clicked.connect(self.get_volume)
        public_api_layout.addWidget(self.volume_btn, 0, 2)
        
        # 캔들 차트 패널
        candle_panel = QGroupBox("캔들 차트")
        candle_layout = QGridLayout()
        
        # 시간 단위 선택
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(['1분', '3분', '5분', '15분', '30분', '60분', '240분', '일', '주', '월'])
        candle_layout.addWidget(QLabel('시간 단위:'), 0, 0)
        candle_layout.addWidget(self.interval_combo, 0, 1)
        
        # 캔들 개수 선택
        self.count_combo = QComboBox()
        self.count_combo.addItems(['30', '50', '100', '200'])
        candle_layout.addWidget(QLabel('캔들 개수:'), 0, 2)
        candle_layout.addWidget(self.count_combo, 0, 3)
        
        # 차트 조회 버튼
        self.candle_btn = QPushButton('차트 조회')
        self.candle_btn.clicked.connect(self.get_candle_data)
        candle_layout.addWidget(self.candle_btn, 0, 4)
        
        candle_panel.setLayout(candle_layout)
        public_api_layout.addWidget(candle_panel, 1, 0, 1, 3)
        
        # 마켓 코드 조회
        self.market_codes_btn = QPushButton('마켓 코드 조회')
        self.market_codes_btn.clicked.connect(self.get_market_codes)
        public_api_layout.addWidget(self.market_codes_btn, 2, 0)
        
        # 가상자산 경고 조회
        self.warning_btn = QPushButton('가상자산 경고 조회')
        self.warning_btn.clicked.connect(self.get_virtual_asset_warning)
        public_api_layout.addWidget(self.warning_btn, 2, 1)
        
        public_api_panel.setLayout(public_api_layout)
        layout.addWidget(public_api_panel)
        
        # 개인 API 기능 패널과 실시간 계산기 패널을 GroupBox로 감싸고, QHBoxLayout으로 나란히 배치 (넓게 균등하게)
        private_calc_hbox = QHBoxLayout()
        # 개인 API 기능 GroupBox (QVBoxLayout으로 버튼 세로 배치)
        private_api_group = QGroupBox('개인 API 기능 (API 키 필요)')
        private_api_vbox = QVBoxLayout()
        # 버튼들 세로로 추가
        self.balance_btn = QPushButton('잔고 조회')
        self.balance_btn.clicked.connect(self.get_balance)
        self.balance_btn.setEnabled(False)
        private_api_vbox.addWidget(self.balance_btn)
        self.order_chance_btn = QPushButton('주문 가능 정보 조회')
        self.order_chance_btn.clicked.connect(self.get_order_chance)
        self.order_chance_btn.setEnabled(False)
        private_api_vbox.addWidget(self.order_chance_btn)
        self.buy_limit_btn = QPushButton('지정가 매수')
        self.buy_limit_btn.clicked.connect(self.buy_limit_order)
        self.buy_limit_btn.setEnabled(False)
        private_api_vbox.addWidget(self.buy_limit_btn)
        self.sell_limit_btn = QPushButton('지정가 매도')
        self.sell_limit_btn.clicked.connect(self.sell_limit_order)
        self.sell_limit_btn.setEnabled(False)
        private_api_vbox.addWidget(self.sell_limit_btn)
        self.buy_market_btn = QPushButton('시장가 매수')
        self.buy_market_btn.clicked.connect(self.buy_market_order)
        self.buy_market_btn.setEnabled(False)
        private_api_vbox.addWidget(self.buy_market_btn)
        self.sell_market_btn = QPushButton('시장가 매도')
        self.sell_market_btn.clicked.connect(self.sell_market_order)
        self.sell_market_btn.setEnabled(False)
        private_api_vbox.addWidget(self.sell_market_btn)
        private_api_group.setLayout(private_api_vbox)
        # 실시간 계산기 GroupBox (세로 배치, 시인성 개선)
        calc_group = QGroupBox('실시간 계산기')
        calc_vbox = QVBoxLayout()
        type_hbox = QHBoxLayout()
        type_label = QLabel('매수/매도:')
        self.calc_type_combo = QComboBox()
        self.calc_type_combo.addItems(['매수', '매도'])
        type_hbox.addWidget(type_label)
        type_hbox.addWidget(self.calc_type_combo)
        calc_vbox.addLayout(type_hbox)
        amt_hbox = QHBoxLayout()
        amt_label = QLabel('금액(원):')
        self.calc_amt_input = QDoubleSpinBox()
        self.calc_amt_input.setDecimals(0)
        self.calc_amt_input.setRange(0, 1000000000)
        amt_hbox.addWidget(amt_label)
        amt_hbox.addWidget(self.calc_amt_input)
        calc_vbox.addLayout(amt_hbox)
        price_hbox = QHBoxLayout()
        price_label = QLabel('가격:')
        self.calc_price_input = QDoubleSpinBox()
        self.calc_price_input.setDecimals(0)
        self.calc_price_input.setRange(0, 1000000000)
        now_price = python_bithumb.get_current_price(f"KRW-{self.coin_combo.currentText()}")
        self.calc_price_input.setValue(now_price)
        price_hbox.addWidget(price_label)
        price_hbox.addWidget(self.calc_price_input)
        calc_vbox.addLayout(price_hbox)
        self.calc_qty_label = QLabel('예상 수량: 0')
        self.calc_qty_label.setStyleSheet('font-size:12px; color:#333; margin-top:8px;')
        calc_vbox.addWidget(self.calc_qty_label)
        calc_group.setLayout(calc_vbox)
        # 좌우로 넓게 균등하게 배치
        private_calc_hbox.addWidget(private_api_group, stretch=1)
        private_calc_hbox.addWidget(calc_group, stretch=1)
        layout.addLayout(private_calc_hbox)
        # 실시간 계산 함수
        def update_calc_qty():
            amt = self.calc_amt_input.value()
            price = self.calc_price_input.value()
            qty = round(amt / price, 8) if price > 0 else 0
            self.calc_qty_label.setText(f'예상 수량: {qty} {self.coin_combo.currentText()}')
        self.calc_amt_input.valueChanged.connect(update_calc_qty)
        self.calc_price_input.valueChanged.connect(update_calc_qty)
        self.calc_type_combo.currentIndexChanged.connect(update_calc_qty)
        update_calc_qty()
        
        # 실시간 차트 컨트롤 패널
        realtime_panel = QGroupBox("실시간 차트 컨트롤")
        realtime_layout = QHBoxLayout()
        self.realtime_start_btn = QPushButton('실시간 차트 새 창')
        self.realtime_start_btn.clicked.connect(self.open_realtime_chart_window)
        realtime_layout.addWidget(self.realtime_start_btn)
        realtime_panel.setLayout(realtime_layout)
        layout.addWidget(realtime_panel)
        
        # 차트 영역
        chart_panel = QGroupBox("차트")
        chart_layout = QVBoxLayout()
        
        # 캔들 차트
        self.figure = Figure(figsize=(8, 4))
        self.canvas = FigureCanvas(self.figure)
        chart_layout.addWidget(self.canvas)
        
        chart_panel.setLayout(chart_layout)
        layout.addWidget(chart_panel)
        
        # 하단 정보 패널
        info_panel = QHBoxLayout()
        
        # 현재가 표시
        self.price_label = QLabel('현재가: 0')
        info_panel.addWidget(self.price_label)
        
        # 보유량 표시
        self.balance_label = QLabel('보유량: 0')
        info_panel.addWidget(self.balance_label)
        
        # 수익률 표시
        self.profit_label = QLabel('수익률: 0%')
        info_panel.addWidget(self.profit_label)
        
        layout.addLayout(info_panel)
        
        # 왼쪽 레이아웃을 main_hbox에 추가
        main_hbox.addLayout(layout, stretch=3)
        
        # 오른쪽 패널 (결과 출력)
        right_panel = QVBoxLayout()
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumWidth(400)
        self.result_text.setMaximumWidth(400)
        right_panel.addWidget(QLabel('실행 결과/로그'))
        right_panel.addWidget(self.result_text)
        main_hbox.addLayout(right_panel, stretch=1)
        
        main_widget.setLayout(main_hbox)
        
        # 데이터 저장용 변수
        self.price_data = []
        self.time_data = []
        
    def on_coin_changed(self):
        # 코인 변경 시 데이터 초기화
        self.price_data = []
        self.time_data = []
        self.realtime_price_data = []
        self.realtime_time_data = []
        self.realtime_volume_data = []
        self.update_chart()
        self.update_realtime_chart()
        
    def toggle_connection(self):
        if not self.is_connected:
            if not self.api_key or not self.api_secret:
                QMessageBox.warning(self, '경고', 'API 키가 설정되지 않았습니다. .env 파일을 확인해주세요.')
                return
            try:
                self.bithumb = python_bithumb.Bithumb(self.api_key, self.api_secret)
                self.connect_btn.setText('연결 해제')
                self.is_connected = True
                self.enable_private_buttons(True)
            except Exception as e:
                QMessageBox.critical(self, '오류', f'연결 실패: {str(e)}')
        else:
            self.connect_btn.setText('연결')
            self.is_connected = False
            self.enable_private_buttons(False)
            
    def enable_private_buttons(self, enable):
        self.balance_btn.setEnabled(enable)
        self.order_chance_btn.setEnabled(enable)
        self.buy_limit_btn.setEnabled(enable)
        self.sell_limit_btn.setEnabled(enable)
        self.buy_market_btn.setEnabled(enable)
        self.sell_market_btn.setEnabled(enable)
            
    def toggle_auto_trade(self):
        self.trading_enabled = not self.trading_enabled
        if self.trading_enabled:
            self.auto_trade_btn.setText('자동매매 중지')
            self.start_price_updates()
        else:
            self.auto_trade_btn.setText('자동매매 시작')
            self.stop_price_updates()
            
    def start_price_updates(self):
        def update_price():
            while self.trading_enabled:
                try:
                    price = python_bithumb.get_current_price(f"KRW-{self.coin_combo.currentText()}")
                    current_time = datetime.now()
                    # 실시간 데이터 저장
                    self.realtime_price_data.append(price)
                    self.realtime_time_data.append(current_time)
                    # 거래량 데이터 (가격 변화량으로 대체)
                    if len(self.realtime_price_data) > 1:
                        volume = abs(price - self.realtime_price_data[-2])
                        self.realtime_volume_data.append(volume)
                    # 데이터 개수 제한 (최근 100개만 유지)
                    if len(self.realtime_price_data) > 100:
                        self.realtime_price_data.pop(0)
                        self.realtime_time_data.pop(0)
                        self.realtime_volume_data.pop(0)
                    # UI 업데이트
                    self.price_label.setText(f'현재가: {price:,.0f}')
                    self.update_chart()
                    self.update_realtime_chart()
                    # 자동매매 로직 실행
                    if self.trading_enabled:
                        self.run_trading_strategy()
                    time.sleep(1)
                except Exception as e:
                    print(f"가격 업데이트 실패: {str(e)}")
                    time.sleep(5)
        self.price_update_thread = threading.Thread(target=update_price)
        self.price_update_thread.daemon = True
        self.price_update_thread.start()
        
    def stop_price_updates(self):
        self.trading_enabled = False
        if self.price_update_thread:
            self.price_update_thread.join()
            
    def update_chart(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot(self.time_data, self.price_data)
        ax.set_title(f'{self.coin_combo.currentText()} 가격 차트')
        ax.set_xlabel('시간')
        ax.set_ylabel('가격')
        self.figure.autofmt_xdate()
        self.canvas.draw()
        
    def update_realtime_chart(self):
        if not self.realtime_running or self.realtime_figure is None:
            return
        try:
            self.realtime_figure.clear()
            ax1 = self.realtime_figure.add_subplot(211)
            ax1.plot(self.realtime_time_data, self.realtime_price_data, 'b-', label='현재가')
            ax1.axhline(1e8, color='gray', linestyle='--', linewidth=1, label='기준(1e8)')
            ax1.set_title(f'{self.coin_combo.currentText()} 실시간 차트 (Y축: 실제 가격)')
            ax1.set_ylabel('가격')
            ax1.grid(True, alpha=0.3)
            if len(self.realtime_time_data) > 10:
                step = len(self.realtime_time_data) // 10
                ax1.set_xticks(self.realtime_time_data[::step])
            # Y축을 기준값 ±0.1%로 고정, 벗어나면 기준값 갱신
            if len(self.realtime_price_data) > 0:
                last_price = self.realtime_price_data[-1]
                if self.realtime_ycenter is None:
                    self.realtime_ycenter = last_price
                # 벗어났는지 체크
                y_min = self.realtime_ycenter * 0.999
                y_max = self.realtime_ycenter * 1.001
                if last_price < y_min or last_price > y_max:
                    self.realtime_ycenter = last_price
                    y_min = self.realtime_ycenter * 0.999
                    y_max = self.realtime_ycenter * 1.001
                ax1.set_ylim(y_min, y_max)
                # 눈금 간격 자동
                y_range = y_max - y_min
                if y_range < 1e5:
                    tick_step = 1e3
                elif y_range < 1e6:
                    tick_step = 1e4
                elif y_range < 1e7:
                    tick_step = 1e5
                elif y_range < 1e8:
                    tick_step = 1e6
                else:
                    tick_step = 1e7
                ticks = np.arange(np.floor(y_min / tick_step) * tick_step, np.ceil(y_max / tick_step) * tick_step, tick_step)
                ax1.set_yticks(ticks)
            # 거래량 차트 (점으로 표시)
            ax2 = self.realtime_figure.add_subplot(212)
            if len(self.realtime_volume_data) > 0:
                ax2.scatter(self.realtime_time_data[1:], self.realtime_volume_data, color='limegreen', s=20, label='거래량')
            ax2.set_xlabel('시간')
            ax2.set_ylabel('거래량')
            ax2.grid(True, alpha=0.3)
            if len(self.realtime_time_data) > 10:
                step = len(self.realtime_time_data) // 10
                ax2.set_xticks(self.realtime_time_data[::step])
            for ax in [ax1, ax2]:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
            self.realtime_figure.tight_layout()
            self.realtime_canvas.draw()
        except Exception as e:
            print(f"실시간 차트 업데이트 실패: {str(e)}")
        
    def run_trading_strategy(self):
        if len(self.price_data) < 20:
            return
            
        # 이동평균선 계산
        ma5 = np.mean(self.price_data[-5:])
        ma20 = np.mean(self.price_data[-20:])
        
        # 현재 보유량 확인
        balance = self.bithumb.get_balance(self.coin_combo.currentText())
        
        # 매매 신호 발생
        if ma5 > ma20 and balance == 0:  # 매수 신호
            self.buy_market_order()
        elif ma5 < ma20 and balance > 0:  # 매도 신호
            self.sell_market_order()
            
    # 공개 API 기능들
    def get_current_price(self):
        try:
            price = python_bithumb.get_current_price(f"KRW-{self.coin_combo.currentText()}")
            self.result_text.append(f"현재가: {price:,.0f}원")
        except Exception as e:
            self.result_text.append(f"현재가 조회 실패: {str(e)}")
            
    def get_orderbook(self):
        try:
            orderbook = python_bithumb.get_orderbook(f"KRW-{self.coin_combo.currentText()}")
            self.result_text.append("\n=== 호가 정보 ===")
            self.result_text.append("매수 호가:")
            for unit in orderbook['orderbook_units']:
                self.result_text.append(f"가격: {unit['bid_price']:,.0f}원, 수량: {unit['bid_size']:.8f}")
            self.result_text.append("\n매도 호가:")
            for unit in orderbook['orderbook_units']:
                self.result_text.append(f"가격: {unit['ask_price']:,.0f}원, 수량: {unit['ask_size']:.8f}")
        except Exception as e:
            self.result_text.append(f"호가 정보 조회 실패: {str(e)}")
            
    def get_volume(self):
        try:
            df = python_bithumb.get_ohlcv(f"KRW-{self.coin_combo.currentText()}")
            self.result_text.append(f"\n=== 거래량 정보 ===")
            self.result_text.append(f"24시간 거래량: {df['volume'].iloc[-1]:,.2f}")
        except Exception as e:
            self.result_text.append(f"거래량 조회 실패: {str(e)}")
            
    def get_candle_data(self):
        try:
            interval = self.interval_combo.currentText()
            count = int(self.count_combo.currentText())
            
            # 시간 단위 변환
            if interval == '1분':
                interval = 'minute1'
            elif interval == '3분':
                interval = 'minute3'
            elif interval == '5분':
                interval = 'minute5'
            elif interval == '15분':
                interval = 'minute15'
            elif interval == '30분':
                interval = 'minute30'
            elif interval == '60분':
                interval = 'minute60'
            elif interval == '240분':
                interval = 'minute240'
            elif interval == '일':
                interval = 'day'
            elif interval == '주':
                interval = 'week'
            elif interval == '월':
                interval = 'month'
            
            df = python_bithumb.get_ohlcv(f"KRW-{self.coin_combo.currentText()}", interval=interval, count=count)
            self.result_text.append(f"\n=== {interval} 캔들 데이터 ===")
            self.result_text.append(df.tail().to_string())
            
            # 차트 업데이트
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            # 캔들스틱 차트 그리기
            width = 0.6
            width2 = width * 0.8
            
            # x축 위치 계산
            x = np.arange(len(df))
            
            up = df[df.close >= df.open]
            down = df[df.close < df.open]
            
            # 상승봉
            up_x = x[df.close >= df.open]
            ax.bar(up_x, up.close-up.open, width, bottom=up.open, color='red', alpha=0.7)
            ax.vlines(up_x, up.low, up.high, color='red', linewidth=1)
            
            # 하락봉
            down_x = x[df.close < df.open]
            ax.bar(down_x, down.close-down.open, width, bottom=down.open, color='blue', alpha=0.7)
            ax.vlines(down_x, down.low, down.high, color='blue', linewidth=1)
            
            # x축 레이블 설정
            if interval in ['day', 'week', 'month']:
                ax.set_xticks(x[::5])  # 5개 캔들마다 레이블 표시
                ax.set_xticklabels(df.index[::5].strftime('%Y-%m-%d'), rotation=45)
            else:
                ax.set_xticks(x[::10])  # 10개 캔들마다 레이블 표시
                ax.set_xticklabels(df.index[::10].strftime('%H:%M'), rotation=45)
            
            # 한글 폰트 설정
            plt.rcParams['font.family'] = 'Malgun Gothic'
            
            ax.set_title(f'{self.coin_combo.currentText()} {interval} 캔들 차트')
            ax.set_xlabel('시간')
            ax.set_ylabel('가격')
            ax.grid(True, alpha=0.3)
            
            # y축 범위 설정
            y_min = df['low'].min() * 0.999
            y_max = df['high'].max() * 1.001
            ax.set_ylim(y_min, y_max)
            
            self.figure.tight_layout()
            self.canvas.draw()
            
        except Exception as e:
            self.result_text.append(f"캔들 데이터 조회 실패: {str(e)}")
            
    def get_market_codes(self):
        try:
            markets = python_bithumb.get_market_all()
            self.result_text.append("\n=== 마켓 코드 목록 ===")
            for market in markets:
                self.result_text.append(f"마켓: {market['market']}, 한글명: {market['korean_name']}")
        except Exception as e:
            self.result_text.append(f"마켓 코드 조회 실패: {str(e)}")
            
    def get_virtual_asset_warning(self):
        try:
            warnings = python_bithumb.get_virtual_asset_warning()
            self.result_text.append("\n=== 가상자산 경고 목록 ===")
            for warning in warnings:
                self.result_text.append(f"마켓: {warning['market']}, 경고: {warning['warning']}")
        except Exception as e:
            self.result_text.append(f"가상자산 경고 조회 실패: {str(e)}")
            
    # 개인 API 기능들
    def get_balance(self):
        try:
            balances = self.bithumb.get_balances()
            self.result_text.append("\n=== 잔고 정보 ===")
            for balance in balances:
                self.result_text.append(f"화폐: {balance['currency']}, 잔고: {balance['balance']}")
        except Exception as e:
            self.result_text.append(f"잔고 조회 실패: {str(e)}")
            
    def get_order_chance(self):
        try:
            chance = self.bithumb.get_order_chance(f"KRW-{self.coin_combo.currentText()}")
            self.result_text.append("\n=== 주문 가능 정보 ===")
            
            # 수수료 정보
            self.result_text.append("\n[수수료 정보]")
            self.result_text.append(f"매수 수수료: {chance['bid_fee']}%")
            self.result_text.append(f"매도 수수료: {chance['ask_fee']}%")
            self.result_text.append(f"마켓 매수 수수료: {chance['maker_bid_fee']}%")
            self.result_text.append(f"마켓 매도 수수료: {chance['maker_ask_fee']}%")
            
            # 마켓 정보
            market = chance['market']
            self.result_text.append("\n[마켓 정보]")
            self.result_text.append(f"마켓 ID: {market['id']}")
            self.result_text.append(f"마켓 이름: {market['name']}")
            self.result_text.append(f"지원 주문 방식: {', '.join(market['order_types'])}")
            self.result_text.append(f"매수 주문 방식: {', '.join(market['bid_types'])}")
            self.result_text.append(f"매도 주문 방식: {', '.join(market['ask_types'])}")
            self.result_text.append(f"지원 주문 종류: {', '.join(market['order_sides'])}")
            self.result_text.append(f"마켓 상태: {market['state']}")
            self.result_text.append(f"최대 매도/매수 금액: {market['max_total']}")
            
            # 매수 제약사항
            bid = market['bid']
            self.result_text.append("\n[매수 제약사항]")
            self.result_text.append(f"화폐: {bid['currency']}")
            self.result_text.append(f"최소 주문금액: {bid['min_total']}")
            
            # 매도 제약사항
            ask = market['ask']
            self.result_text.append("\n[매도 제약사항]")
            self.result_text.append(f"화폐: {ask['currency']}")
            self.result_text.append(f"최소 주문금액: {ask['min_total']}")
            
            # 계정 정보
            bid_account = chance['bid_account']
            self.result_text.append("\n[매수 계정 정보]")
            self.result_text.append(f"화폐: {bid_account['currency']}")
            self.result_text.append(f"주문가능 금액: {bid_account['balance']}")
            self.result_text.append(f"주문중인 금액: {bid_account['locked']}")
            self.result_text.append(f"매수평균가: {bid_account['avg_buy_price']}")
            self.result_text.append(f"매수평균가 수정여부: {bid_account['avg_buy_price_modified']}")
            self.result_text.append(f"평단가 기준 화폐: {bid_account['unit_currency']}")
            
            ask_account = chance['ask_account']
            self.result_text.append("\n[매도 계정 정보]")
            self.result_text.append(f"화폐: {ask_account['currency']}")
            self.result_text.append(f"주문가능 수량: {ask_account['balance']}")
            self.result_text.append(f"주문중인 수량: {ask_account['locked']}")
            self.result_text.append(f"매수평균가: {ask_account['avg_buy_price']}")
            self.result_text.append(f"매수평균가 수정여부: {ask_account['avg_buy_price_modified']}")
            self.result_text.append(f"평단가 기준 화폐: {ask_account['unit_currency']}")
            
        except Exception as e:
            self.result_text.append(f"주문 가능 정보 조회 실패: {str(e)}")
            
    def buy_limit_order(self):
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
                    qty_label.setText(f'예상 수량: {qty} {self.coin_combo.currentText()}')
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
                        order = self.bithumb.buy_limit_order(f"KRW-{self.coin_combo.currentText()}", price, volume)
                        self.result_text.append(f"\n지정가 매수 주문 성공: {order}")
                    except Exception as e:
                        self.result_text.append(f"지정가 매수 실패: {str(e)}")
                        if 'HTTP 201' in str(e):
                            self.result_text.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.result_text.append(f"지정가 매수 실패: {str(e)}")

    def sell_limit_order(self):
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
                    qty_label.setText(f'예상 수량: {qty} {self.coin_combo.currentText()}')
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
                        order = self.bithumb.sell_limit_order(f"KRW-{self.coin_combo.currentText()}", price, volume)
                        self.result_text.append(f"\n지정가 매도 주문 성공: {order}")
                    except Exception as e:
                        self.result_text.append(f"지정가 매도 실패: {str(e)}")
                        if 'HTTP 201' in str(e):
                            self.result_text.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.result_text.append(f"지정가 매도 실패: {str(e)}")

    def buy_market_order(self):
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
            price = python_bithumb.get_current_price(f"KRW-{self.coin_combo.currentText()}")
            qty_label = QLabel('예상 수량: 0')
            vbox.addWidget(qty_label)
            def update_qty():
                amt = amount_input.value()
                qty = round(amt / price, 8) if price > 0 else 0
                qty_label.setText(f'예상 수량: {qty} {self.coin_combo.currentText()}')
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
                    chance = self.bithumb.get_order_chance(f"KRW-{self.coin_combo.currentText()}")
                    min_total = float(chance['market']['bid']['min_total'])
                    if amount < min_total:
                        self.result_text.append(f"[경고] 최소 주문 금액({min_total:,.0f}원) 미만입니다.")
                        return
                except Exception as e:
                    pass
                try:
                    order = self.bithumb.buy_market_order(f"KRW-{self.coin_combo.currentText()}", amount)
                    self.result_text.append(f"\n시장가 매수 주문 성공: {order}")
                except Exception as e:
                    self.result_text.append(f"시장가 매수 실패: {str(e)}")
                    if 'HTTP 201' in str(e):
                        self.result_text.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.result_text.append(f"시장가 매수 실패: {str(e)}")

    def sell_market_order(self):
        try:
            price = python_bithumb.get_current_price(f"KRW-{self.coin_combo.currentText()}")
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
                qty_label.setText(f'예상 수량: {qty} {self.coin_combo.currentText()}')
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
                    chance = self.bithumb.get_order_chance(f"KRW-{self.coin_combo.currentText()}")
                    min_total = float(chance['market']['ask']['min_total'])
                    if amount < min_total:
                        self.result_text.append(f"[경고] 최소 주문 금액({min_total:,.0f}원) 미만입니다.")
                        return
                except Exception as e:
                    pass
                try:
                    order = self.bithumb.sell_market_order(f"KRW-{self.coin_combo.currentText()}", volume)
                    self.result_text.append(f"\n시장가 매도 주문 성공: {order}")
                except Exception as e:
                    self.result_text.append(f"시장가 매도 실패: {str(e)}")
                    if 'HTTP 201' in str(e):
                        self.result_text.append("※ 실제로는 주문이 정상적으로 체결되었을 수 있습니다. (201 응답)")
        except Exception as e:
            self.result_text.append(f"시장가 매도 실패: {str(e)}")

    def open_realtime_chart_window(self):
        if self.realtime_chart_window is not None:
            self.realtime_chart_window.close()
        self.realtime_chart_window = QDialog(self)
        self.realtime_chart_window.setWindowTitle('실시간 차트')
        self.realtime_chart_window.setGeometry(200, 200, 1200, 700)
        layout = QVBoxLayout()
        # 큰 차트 생성
        self.realtime_figure = Figure(figsize=(12, 6))
        self.realtime_canvas = FigureCanvas(self.realtime_figure)
        layout.addWidget(self.realtime_canvas)
        # 중지 버튼
        stop_btn = QPushButton('실시간 차트 중지 및 창 닫기')
        stop_btn.clicked.connect(self.close_realtime_chart_window)
        layout.addWidget(stop_btn)
        self.realtime_chart_window.setLayout(layout)
        self.realtime_running = True
        self.realtime_price_data = []
        self.realtime_time_data = []
        self.realtime_volume_data = []
        self.realtime_ycenter = None  # 기준값 변수 추가
        self.realtime_timer.start(1000)
        self.realtime_chart_window.finished.connect(self.close_realtime_chart_window)
        self.realtime_chart_window.show()

    def close_realtime_chart_window(self):
        self.realtime_running = False
        self.realtime_timer.stop()
        if self.realtime_chart_window is not None:
            self.realtime_chart_window.close()
            self.realtime_chart_window = None

    def fetch_realtime_data(self):
        if not self.realtime_running:
            return
        try:
            price = python_bithumb.get_current_price(f"KRW-{self.coin_combo.currentText()}")
            now = datetime.now()
            self.realtime_price_data.append(price)
            self.realtime_time_data.append(now)
            if len(self.realtime_price_data) > 1:
                volume = abs(price - self.realtime_price_data[-2])
                self.realtime_volume_data.append(volume)
            if len(self.realtime_price_data) > 100:
                self.realtime_price_data.pop(0)
                self.realtime_time_data.pop(0)
                self.realtime_volume_data.pop(0)
            self.update_realtime_chart()
        except Exception as e:
            print(f"실시간 차트 오류: {str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BithumbTrader()
    ex.show()
    sys.exit(app.exec_())
