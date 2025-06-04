import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import python_bithumb
import pyupbit  # 업비트 API 추가
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from dotenv import load_dotenv
import matplotlib.dates as mdates
from PyQt5.QtCore import QTimer
import traceback
import sqlite3

# 한글 폰트 설정 (모든 차트에 적용)
plt.rcParams['font.family'] = 'Malgun Gothic'

class BithumbTrader(QMainWindow):
    # 시그널 정의
    update_sim_status = pyqtSignal(str)
    
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
        
        # 시뮬레이션 상태 변수
        self.simulation_enabled = False
        self.simulation_thread = None
        
        # 시그널 연결
        self.update_sim_status.connect(self.update_simulation_status)
        
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
                self.auto_trade_btn.setEnabled(True)
            except Exception as e:
                QMessageBox.critical(self, '오류', f'연결 실패: {str(e)}')
        else:
            self.connect_btn.setText('연결')
            self.is_connected = False
            self.enable_private_buttons(False)
            self.auto_trade_btn.setEnabled(False)
            
    def enable_private_buttons(self, enable):
        self.balance_btn.setEnabled(enable)
        self.order_chance_btn.setEnabled(enable)
        self.buy_limit_btn.setEnabled(enable)
        self.sell_limit_btn.setEnabled(enable)
        self.buy_market_btn.setEnabled(enable)
        self.sell_market_btn.setEnabled(enable)
            
    def toggle_auto_trade(self):
        # 자동매매 별도 창 오픈
        self.open_auto_trade_window()

    def open_auto_trade_window(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('자동매매')
        dlg.setGeometry(300, 200, 1000, 800)
        vbox = QVBoxLayout()
        
        # 탭 위젯
        tab = QTabWidget()
        
        # 데이터 수집/저장 탭
        data_tab = QWidget()
        data_layout = QVBoxLayout()
        data_param_hbox = QHBoxLayout()
        data_param_hbox.addWidget(QLabel('코인:'))
        self.data_coin_combo = QComboBox()
        self.data_coin_combo.addItems(['BTC', 'ETH', 'XRP', 'ADA'])
        data_param_hbox.addWidget(self.data_coin_combo)
        data_param_hbox.addWidget(QLabel('시작일(YYYY-MM-DD):'))
        self.data_start_date = QLineEdit('2023-01-01')
        self.data_start_date.setFixedWidth(100)
        data_param_hbox.addWidget(self.data_start_date)
        data_param_hbox.addWidget(QLabel('종료일(YYYY-MM-DD):'))
        self.data_end_date = QLineEdit('2023-12-31')
        self.data_end_date.setFixedWidth(100)
        data_param_hbox.addWidget(self.data_end_date)
        self.data_fetch_btn = QPushButton('데이터 수집')
        data_param_hbox.addWidget(self.data_fetch_btn)
        data_layout.addLayout(data_param_hbox)
        self.data_result = QTextEdit()
        self.data_result.setReadOnly(True)
        data_layout.addWidget(self.data_result)
        data_tab.setLayout(data_layout)
        tab.addTab(data_tab, '데이터 수집/저장')

        # 데이터 수집 버튼 클릭 이벤트 연결
        self.data_fetch_btn.clicked.connect(self.fetch_and_store_ohlcv)

        # 백테스팅 탭 추가
        backtest_tab = QWidget()
        backtest_layout = QVBoxLayout()
        
        # 백테스팅 파라미터 설정
        param_group = QGroupBox("백테스팅 파라미터")
        param_layout = QGridLayout()
        
        # 코인 선택
        param_layout.addWidget(QLabel('코인:'), 0, 0)
        self.backtest_coin_combo = QComboBox()
        self.backtest_coin_combo.addItems(['BTC', 'ETH', 'XRP', 'ADA'])
        param_layout.addWidget(self.backtest_coin_combo, 0, 1)
        
        # 날짜 선택
        param_layout.addWidget(QLabel('시작일:'), 1, 0)
        self.backtest_start_date = QLineEdit('2023-01-01')
        param_layout.addWidget(self.backtest_start_date, 1, 1)
        
        param_layout.addWidget(QLabel('종료일:'), 2, 0)
        self.backtest_end_date = QLineEdit('2023-12-31')
        param_layout.addWidget(self.backtest_end_date, 2, 1)
        
        # 시간 단위 선택
        param_layout.addWidget(QLabel('시간 단위:'), 3, 0)
        self.backtest_interval_combo = QComboBox()
        self.backtest_interval_combo.addItems(['1분봉', '3분봉', '5분봉', '15분봉', '30분봉', '60분봉', '일봉'])
        param_layout.addWidget(self.backtest_interval_combo, 3, 1)
        
        # 전략 선택
        param_layout.addWidget(QLabel('전략:'), 4, 0)
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems([
            'RSI', 
            '볼린저밴드', 
            'RSI + 볼린저밴드',
            'MACD',
            '이동평균선 교차',
            '스토캐스틱',
            'ATR 기반 변동성 돌파',
            '캔들 패턴',
            'ShortPercent'
        ])
        param_layout.addWidget(self.strategy_combo, 4, 1)
        
        # 전략 파라미터 그룹
        self.param_groups = {}
        
        # RSI 파라미터
        rsi_group = QGroupBox("RSI 파라미터")
        rsi_layout = QGridLayout()
        rsi_layout.addWidget(QLabel('RSI 기간:'), 0, 0)
        self.rsi_period = QSpinBox()
        self.rsi_period.setRange(2, 50)
        self.rsi_period.setValue(14)
        rsi_layout.addWidget(self.rsi_period, 0, 1)
        rsi_group.setLayout(rsi_layout)
        param_layout.addWidget(rsi_group, 5, 0, 1, 2)
        self.param_groups['RSI'] = rsi_group
        self.param_groups['RSI + 볼린저밴드'] = rsi_group
        
        # 볼린저밴드 파라미터
        bb_group = QGroupBox("볼린저밴드 파라미터")
        bb_layout = QGridLayout()
        bb_layout.addWidget(QLabel('볼린저밴드 기간:'), 0, 0)
        self.bb_period = QSpinBox()
        self.bb_period.setRange(5, 100)
        self.bb_period.setValue(20)
        bb_layout.addWidget(self.bb_period, 0, 1)
        bb_layout.addWidget(QLabel('볼린저밴드 표준편차:'), 1, 0)
        self.bb_std = QDoubleSpinBox()
        self.bb_std.setRange(0.1, 5.0)
        self.bb_std.setValue(2.0)
        self.bb_std.setSingleStep(0.1)
        bb_layout.addWidget(self.bb_std, 1, 1)
        bb_group.setLayout(bb_layout)
        param_layout.addWidget(bb_group, 6, 0, 1, 2)
        self.param_groups['볼린저밴드'] = bb_group
        self.param_groups['RSI + 볼린저밴드'] = bb_group
        
        # MACD 파라미터
        macd_group = QGroupBox("MACD 파라미터")
        macd_layout = QGridLayout()
        macd_layout.addWidget(QLabel('MACD 빠른선:'), 0, 0)
        self.macd_fast = QSpinBox()
        self.macd_fast.setRange(5, 50)
        self.macd_fast.setValue(12)
        macd_layout.addWidget(self.macd_fast, 0, 1)
        macd_layout.addWidget(QLabel('MACD 느린선:'), 1, 0)
        self.macd_slow = QSpinBox()
        self.macd_slow.setRange(10, 100)
        self.macd_slow.setValue(26)
        macd_layout.addWidget(self.macd_slow, 1, 1)
        macd_layout.addWidget(QLabel('MACD 시그널:'), 2, 0)
        self.macd_signal = QSpinBox()
        self.macd_signal.setRange(5, 50)
        self.macd_signal.setValue(9)
        macd_layout.addWidget(self.macd_signal, 2, 1)
        macd_group.setLayout(macd_layout)
        param_layout.addWidget(macd_group, 7, 0, 1, 2)
        self.param_groups['MACD'] = macd_group
        
        # 이동평균선 파라미터
        ma_group = QGroupBox("이동평균선 파라미터")
        ma_layout = QGridLayout()
        ma_layout.addWidget(QLabel('단기 이동평균:'), 0, 0)
        self.ma_short = QSpinBox()
        self.ma_short.setRange(5, 50)
        self.ma_short.setValue(20)
        ma_layout.addWidget(self.ma_short, 0, 1)
        ma_layout.addWidget(QLabel('장기 이동평균:'), 1, 0)
        self.ma_long = QSpinBox()
        self.ma_long.setRange(10, 200)
        self.ma_long.setValue(50)
        ma_layout.addWidget(self.ma_long, 1, 1)
        ma_group.setLayout(ma_layout)
        param_layout.addWidget(ma_group, 8, 0, 1, 2)
        self.param_groups['이동평균선 교차'] = ma_group
        
        # 스토캐스틱 파라미터
        stoch_group = QGroupBox("스토캐스틱 파라미터")
        stoch_layout = QGridLayout()
        stoch_layout.addWidget(QLabel('스토캐스틱 기간:'), 0, 0)
        self.stoch_period = QSpinBox()
        self.stoch_period.setRange(5, 50)
        self.stoch_period.setValue(14)
        stoch_layout.addWidget(self.stoch_period, 0, 1)
        stoch_group.setLayout(stoch_layout)
        param_layout.addWidget(stoch_group, 9, 0, 1, 2)
        self.param_groups['스토캐스틱'] = stoch_group
        
        # ATR 파라미터
        atr_group = QGroupBox("ATR 파라미터")
        atr_layout = QGridLayout()
        atr_layout.addWidget(QLabel('ATR 기간:'), 0, 0)
        self.atr_period = QSpinBox()
        self.atr_period.setRange(5, 50)
        self.atr_period.setValue(14)
        atr_layout.addWidget(self.atr_period, 0, 1)
        atr_layout.addWidget(QLabel('ATR 승수:'), 1, 0)
        self.atr_multiplier = QDoubleSpinBox()
        self.atr_multiplier.setRange(0.1, 5.0)
        self.atr_multiplier.setValue(2.0)
        self.atr_multiplier.setSingleStep(0.1)
        atr_layout.addWidget(self.atr_multiplier, 1, 1)
        atr_group.setLayout(atr_layout)
        param_layout.addWidget(atr_group, 10, 0, 1, 2)
        self.param_groups['ATR 기반 변동성 돌파'] = atr_group
        
        # ShortPercent 파라미터
        short_group = QGroupBox("ShortPercent 파라미터")
        short_layout = QGridLayout()
        short_layout.addWidget(QLabel('총 투자 금액(원):'), 0, 0)
        self.short_total_investment = QSpinBox()
        self.short_total_investment.setRange(100000, 10000000)
        self.short_total_investment.setValue(1000000)
        self.short_total_investment.setSingleStep(100000)
        short_layout.addWidget(self.short_total_investment, 0, 1)
        short_layout.addWidget(QLabel('일회 투자 금액(원):'), 1, 0)
        self.short_single_investment = QSpinBox()
        self.short_single_investment.setRange(10000, 1000000)
        self.short_single_investment.setValue(100000)
        self.short_single_investment.setSingleStep(10000)
        short_layout.addWidget(self.short_single_investment, 1, 1)
        short_layout.addWidget(QLabel('매수 기준 하락률(%):'), 2, 0)
        self.short_buy_percent = QDoubleSpinBox()
        self.short_buy_percent.setRange(0.1, 5.0)
        self.short_buy_percent.setValue(0.5)
        self.short_buy_percent.setSingleStep(0.1)
        short_layout.addWidget(self.short_buy_percent, 2, 1)
        short_layout.addWidget(QLabel('매도 기준 상승률(%):'), 3, 0)
        self.short_sell_percent = QDoubleSpinBox()
        self.short_sell_percent.setRange(0.1, 5.0)
        self.short_sell_percent.setValue(0.5)
        self.short_sell_percent.setSingleStep(0.1)
        short_layout.addWidget(self.short_sell_percent, 3, 1)
        short_group.setLayout(short_layout)
        param_layout.addWidget(short_group, 11, 0, 1, 2)
        self.param_groups['ShortPercent'] = short_group
        
        # 전략 변경 시 파라미터 그룹 표시/숨김 처리
        self.strategy_combo.currentTextChanged.connect(self.update_param_groups)
        
        # 초기 파라미터 그룹 표시
        self.update_param_groups(self.strategy_combo.currentText())
        
        param_group.setLayout(param_layout)
        backtest_layout.addWidget(param_group)
        
        # 백테스팅 실행 버튼
        self.backtest_btn = QPushButton('백테스팅 실행')
        self.backtest_btn.clicked.connect(self.run_backtest)
        backtest_layout.addWidget(self.backtest_btn)
        
        # 백테스팅 결과
        self.backtest_result = QTextEdit()
        self.backtest_result.setReadOnly(True)
        backtest_layout.addWidget(self.backtest_result)
        
        backtest_tab.setLayout(backtest_layout)
        tab.addTab(backtest_tab, '백테스팅')
        
        # 시뮬레이션 탭 추가
        simulation_tab = QWidget()
        simulation_layout = QVBoxLayout()
        
        # 시뮬레이션 설정
        sim_group = QGroupBox("시뮬레이션 설정")
        sim_layout = QGridLayout()
        
        # 코인 선택
        sim_layout.addWidget(QLabel('코인:'), 0, 0)
        self.sim_coin_combo = QComboBox()
        self.sim_coin_combo.addItems(['BTC', 'ETH', 'XRP', 'ADA'])
        sim_layout.addWidget(self.sim_coin_combo, 0, 1)
        
        # 전략 선택
        sim_layout.addWidget(QLabel('전략:'), 1, 0)
        self.sim_strategy_combo = QComboBox()
        self.sim_strategy_combo.addItems([
            'RSI', 
            '볼린저밴드', 
            'RSI + 볼린저밴드',
            'MACD',
            '이동평균선 교차',
            '스토캐스틱',
            'ATR 기반 변동성 돌파',
            '캔들 패턴',
            'ShortPercent'
        ])
        sim_layout.addWidget(self.sim_strategy_combo, 1, 1)
        
        # 투자 금액
        sim_layout.addWidget(QLabel('투자 금액(원):'), 2, 0)
        self.sim_investment = QSpinBox()
        self.sim_investment.setRange(10000, 10000000)
        self.sim_investment.setValue(1000000)
        self.sim_investment.setSingleStep(10000)
        sim_layout.addWidget(self.sim_investment, 2, 1)
        
        # 전략 파라미터 그룹
        self.sim_param_groups = {}
        
        # RSI 파라미터
        sim_rsi_group = QGroupBox("RSI 파라미터")
        sim_rsi_layout = QGridLayout()
        sim_rsi_layout.addWidget(QLabel('RSI 기간:'), 0, 0)
        self.sim_rsi_period = QSpinBox()
        self.sim_rsi_period.setRange(2, 50)
        self.sim_rsi_period.setValue(14)
        sim_rsi_layout.addWidget(self.sim_rsi_period, 0, 1)
        sim_rsi_group.setLayout(sim_rsi_layout)
        sim_layout.addWidget(sim_rsi_group, 3, 0, 1, 2)
        self.sim_param_groups['RSI'] = sim_rsi_group
        self.sim_param_groups['RSI + 볼린저밴드'] = sim_rsi_group
        
        # 볼린저밴드 파라미터
        sim_bb_group = QGroupBox("볼린저밴드 파라미터")
        sim_bb_layout = QGridLayout()
        sim_bb_layout.addWidget(QLabel('볼린저밴드 기간:'), 0, 0)
        self.sim_bb_period = QSpinBox()
        self.sim_bb_period.setRange(5, 100)
        self.sim_bb_period.setValue(20)
        sim_bb_layout.addWidget(self.sim_bb_period, 0, 1)
        sim_bb_layout.addWidget(QLabel('볼린저밴드 표준편차:'), 1, 0)
        self.sim_bb_std = QDoubleSpinBox()
        self.sim_bb_std.setRange(0.1, 5.0)
        self.sim_bb_std.setValue(2.0)
        self.sim_bb_std.setSingleStep(0.1)
        sim_bb_layout.addWidget(self.sim_bb_std, 1, 1)
        sim_bb_group.setLayout(sim_bb_layout)
        sim_layout.addWidget(sim_bb_group, 4, 0, 1, 2)
        self.sim_param_groups['볼린저밴드'] = sim_bb_group
        self.sim_param_groups['RSI + 볼린저밴드'] = sim_bb_group
        
        # MACD 파라미터
        sim_macd_group = QGroupBox("MACD 파라미터")
        sim_macd_layout = QGridLayout()
        sim_macd_layout.addWidget(QLabel('MACD 빠른선:'), 0, 0)
        self.sim_macd_fast = QSpinBox()
        self.sim_macd_fast.setRange(5, 50)
        self.sim_macd_fast.setValue(12)
        sim_macd_layout.addWidget(self.sim_macd_fast, 0, 1)
        sim_macd_layout.addWidget(QLabel('MACD 느린선:'), 1, 0)
        self.sim_macd_slow = QSpinBox()
        self.sim_macd_slow.setRange(10, 100)
        self.sim_macd_slow.setValue(26)
        sim_macd_layout.addWidget(self.sim_macd_slow, 1, 1)
        sim_macd_layout.addWidget(QLabel('MACD 시그널:'), 2, 0)
        self.sim_macd_signal = QSpinBox()
        self.sim_macd_signal.setRange(5, 50)
        self.sim_macd_signal.setValue(9)
        sim_macd_layout.addWidget(self.sim_macd_signal, 2, 1)
        sim_macd_group.setLayout(sim_macd_layout)
        sim_layout.addWidget(sim_macd_group, 5, 0, 1, 2)
        self.sim_param_groups['MACD'] = sim_macd_group
        
        # 이동평균선 파라미터
        sim_ma_group = QGroupBox("이동평균선 파라미터")
        sim_ma_layout = QGridLayout()
        sim_ma_layout.addWidget(QLabel('단기 이동평균:'), 0, 0)
        self.sim_ma_short = QSpinBox()
        self.sim_ma_short.setRange(5, 50)
        self.sim_ma_short.setValue(20)
        sim_ma_layout.addWidget(self.sim_ma_short, 0, 1)
        sim_ma_layout.addWidget(QLabel('장기 이동평균:'), 1, 0)
        self.sim_ma_long = QSpinBox()
        self.sim_ma_long.setRange(10, 200)
        self.sim_ma_long.setValue(50)
        sim_ma_layout.addWidget(self.sim_ma_long, 1, 1)
        sim_ma_group.setLayout(sim_ma_layout)
        sim_layout.addWidget(sim_ma_group, 6, 0, 1, 2)
        self.sim_param_groups['이동평균선 교차'] = sim_ma_group
        
        # 스토캐스틱 파라미터
        sim_stoch_group = QGroupBox("스토캐스틱 파라미터")
        sim_stoch_layout = QGridLayout()
        sim_stoch_layout.addWidget(QLabel('스토캐스틱 기간:'), 0, 0)
        self.sim_stoch_period = QSpinBox()
        self.sim_stoch_period.setRange(5, 50)
        self.sim_stoch_period.setValue(14)
        sim_stoch_layout.addWidget(self.sim_stoch_period, 0, 1)
        sim_stoch_group.setLayout(sim_stoch_layout)
        sim_layout.addWidget(sim_stoch_group, 7, 0, 1, 2)
        self.sim_param_groups['스토캐스틱'] = sim_stoch_group
        
        # ATR 파라미터
        sim_atr_group = QGroupBox("ATR 파라미터")
        sim_atr_layout = QGridLayout()
        sim_atr_layout.addWidget(QLabel('ATR 기간:'), 0, 0)
        self.sim_atr_period = QSpinBox()
        self.sim_atr_period.setRange(5, 50)
        self.sim_atr_period.setValue(14)
        sim_atr_layout.addWidget(self.sim_atr_period, 0, 1)
        sim_atr_layout.addWidget(QLabel('ATR 승수:'), 1, 0)
        self.sim_atr_multiplier = QDoubleSpinBox()
        self.sim_atr_multiplier.setRange(0.1, 5.0)
        self.sim_atr_multiplier.setValue(2.0)
        self.sim_atr_multiplier.setSingleStep(0.1)
        sim_atr_layout.addWidget(self.sim_atr_multiplier, 1, 1)
        sim_atr_group.setLayout(sim_atr_layout)
        sim_layout.addWidget(sim_atr_group, 8, 0, 1, 2)
        self.sim_param_groups['ATR 기반 변동성 돌파'] = sim_atr_group
        
        # ShortPercent 파라미터
        sim_short_group = QGroupBox("ShortPercent 파라미터")
        sim_short_layout = QGridLayout()
        sim_short_layout.addWidget(QLabel('총 투자 금액(원):'), 0, 0)
        self.sim_short_total_investment = QSpinBox()
        self.sim_short_total_investment.setRange(100000, 10000000)
        self.sim_short_total_investment.setValue(1000000)
        self.sim_short_total_investment.setSingleStep(100000)
        sim_short_layout.addWidget(self.sim_short_total_investment, 0, 1)
        sim_short_layout.addWidget(QLabel('일회 투자 금액(원):'), 1, 0)
        self.sim_short_single_investment = QSpinBox()
        self.sim_short_single_investment.setRange(10000, 1000000)
        self.sim_short_single_investment.setValue(100000)
        self.sim_short_single_investment.setSingleStep(10000)
        sim_short_layout.addWidget(self.sim_short_single_investment, 1, 1)
        sim_short_layout.addWidget(QLabel('매수 기준 하락률(%):'), 2, 0)
        self.sim_short_buy_percent = QDoubleSpinBox()
        self.sim_short_buy_percent.setRange(0.1, 5.0)
        self.sim_short_buy_percent.setValue(0.5)
        self.sim_short_buy_percent.setSingleStep(0.1)
        sim_short_layout.addWidget(self.sim_short_buy_percent, 2, 1)
        sim_short_layout.addWidget(QLabel('매도 기준 상승률(%):'), 3, 0)
        self.sim_short_sell_percent = QDoubleSpinBox()
        self.sim_short_sell_percent.setRange(0.1, 5.0)
        self.sim_short_sell_percent.setValue(0.5)
        self.sim_short_sell_percent.setSingleStep(0.1)
        sim_short_layout.addWidget(self.sim_short_sell_percent, 3, 1)
        sim_short_group.setLayout(sim_short_layout)
        sim_layout.addWidget(sim_short_group, 9, 0, 1, 2)
        self.sim_param_groups['ShortPercent'] = sim_short_group
        
        # 전략 변경 시 파라미터 그룹 표시/숨김 처리
        self.sim_strategy_combo.currentTextChanged.connect(self.update_sim_param_groups)
        
        # 초기 파라미터 그룹 표시
        self.update_sim_param_groups(self.sim_strategy_combo.currentText())
        
        sim_group.setLayout(sim_layout)
        simulation_layout.addWidget(sim_group)
        
        # 시뮬레이션 시작/정지 버튼
        self.sim_start_btn = QPushButton('시뮬레이션 시작')
        self.sim_start_btn.clicked.connect(self.toggle_simulation)
        simulation_layout.addWidget(self.sim_start_btn)
        
        # 시뮬레이션 상태 및 로그
        self.sim_status = QTextEdit()
        self.sim_status.setReadOnly(True)
        simulation_layout.addWidget(self.sim_status)
        
        simulation_tab.setLayout(simulation_layout)
        tab.addTab(simulation_tab, '시뮬레이션')
        
        # 자동매매 탭 추가
        auto_trade_tab = QWidget()
        auto_trade_layout = QVBoxLayout()
        
        # 자동매매 설정
        trade_group = QGroupBox("자동매매 설정")
        trade_layout = QGridLayout()
        
        # 코인 선택
        trade_layout.addWidget(QLabel('코인:'), 0, 0)
        self.trade_coin_combo = QComboBox()
        self.trade_coin_combo.addItems(['BTC', 'ETH', 'XRP', 'ADA'])
        trade_layout.addWidget(self.trade_coin_combo, 0, 1)
        
        # 전략 선택
        trade_layout.addWidget(QLabel('전략:'), 1, 0)
        self.trade_strategy_combo = QComboBox()
        self.trade_strategy_combo.addItems([
            'RSI', 
            '볼린저밴드', 
            'RSI + 볼린저밴드',
            'MACD',
            '이동평균선 교차',
            '스토캐스틱',
            'ATR 기반 변동성 돌파',
            '캔들 패턴',
            'ShortPercent'
        ])
        trade_layout.addWidget(self.trade_strategy_combo, 1, 1)
        
        # 투자 금액
        trade_layout.addWidget(QLabel('투자 금액(원):'), 2, 0)
        self.trade_investment = QSpinBox()
        self.trade_investment.setRange(10000, 10000000)
        self.trade_investment.setValue(1000000)
        self.trade_investment.setSingleStep(10000)
        trade_layout.addWidget(self.trade_investment, 2, 1)
        
        # 전략 파라미터 그룹
        self.trade_param_groups = {}
        
        # RSI 파라미터
        trade_rsi_group = QGroupBox("RSI 파라미터")
        trade_rsi_layout = QGridLayout()
        trade_rsi_layout.addWidget(QLabel('RSI 기간:'), 0, 0)
        self.trade_rsi_period = QSpinBox()
        self.trade_rsi_period.setRange(2, 50)
        self.trade_rsi_period.setValue(14)
        trade_rsi_layout.addWidget(self.trade_rsi_period, 0, 1)
        trade_rsi_group.setLayout(trade_rsi_layout)
        trade_layout.addWidget(trade_rsi_group, 3, 0, 1, 2)
        self.trade_param_groups['RSI'] = trade_rsi_group
        self.trade_param_groups['RSI + 볼린저밴드'] = trade_rsi_group
        
        # 볼린저밴드 파라미터
        trade_bb_group = QGroupBox("볼린저밴드 파라미터")
        trade_bb_layout = QGridLayout()
        trade_bb_layout.addWidget(QLabel('볼린저밴드 기간:'), 0, 0)
        self.trade_bb_period = QSpinBox()
        self.trade_bb_period.setRange(5, 100)
        self.trade_bb_period.setValue(20)
        trade_bb_layout.addWidget(self.trade_bb_period, 0, 1)
        trade_bb_layout.addWidget(QLabel('볼린저밴드 표준편차:'), 1, 0)
        self.trade_bb_std = QDoubleSpinBox()
        self.trade_bb_std.setRange(0.1, 5.0)
        self.trade_bb_std.setValue(2.0)
        self.trade_bb_std.setSingleStep(0.1)
        trade_bb_layout.addWidget(self.trade_bb_std, 1, 1)
        trade_bb_group.setLayout(trade_bb_layout)
        trade_layout.addWidget(trade_bb_group, 4, 0, 1, 2)
        self.trade_param_groups['볼린저밴드'] = trade_bb_group
        self.trade_param_groups['RSI + 볼린저밴드'] = trade_bb_group
        
        # MACD 파라미터
        trade_macd_group = QGroupBox("MACD 파라미터")
        trade_macd_layout = QGridLayout()
        trade_macd_layout.addWidget(QLabel('MACD 빠른선:'), 0, 0)
        self.trade_macd_fast = QSpinBox()
        self.trade_macd_fast.setRange(5, 50)
        self.trade_macd_fast.setValue(12)
        trade_macd_layout.addWidget(self.trade_macd_fast, 0, 1)
        trade_macd_layout.addWidget(QLabel('MACD 느린선:'), 1, 0)
        self.trade_macd_slow = QSpinBox()
        self.trade_macd_slow.setRange(10, 100)
        self.trade_macd_slow.setValue(26)
        trade_macd_layout.addWidget(self.trade_macd_slow, 1, 1)
        trade_macd_layout.addWidget(QLabel('MACD 시그널:'), 2, 0)
        self.trade_macd_signal = QSpinBox()
        self.trade_macd_signal.setRange(5, 50)
        self.trade_macd_signal.setValue(9)
        trade_macd_layout.addWidget(self.trade_macd_signal, 2, 1)
        trade_macd_group.setLayout(trade_macd_layout)
        trade_layout.addWidget(trade_macd_group, 5, 0, 1, 2)
        self.trade_param_groups['MACD'] = trade_macd_group
        
        # 이동평균선 파라미터
        trade_ma_group = QGroupBox("이동평균선 파라미터")
        trade_ma_layout = QGridLayout()
        trade_ma_layout.addWidget(QLabel('단기 이동평균:'), 0, 0)
        self.trade_ma_short = QSpinBox()
        self.trade_ma_short.setRange(5, 50)
        self.trade_ma_short.setValue(20)
        trade_ma_layout.addWidget(self.trade_ma_short, 0, 1)
        trade_ma_layout.addWidget(QLabel('장기 이동평균:'), 1, 0)
        self.trade_ma_long = QSpinBox()
        self.trade_ma_long.setRange(10, 200)
        self.trade_ma_long.setValue(50)
        trade_ma_layout.addWidget(self.trade_ma_long, 1, 1)
        trade_ma_group.setLayout(trade_ma_layout)
        trade_layout.addWidget(trade_ma_group, 6, 0, 1, 2)
        self.trade_param_groups['이동평균선 교차'] = trade_ma_group
        
        # 스토캐스틱 파라미터
        trade_stoch_group = QGroupBox("스토캐스틱 파라미터")
        trade_stoch_layout = QGridLayout()
        trade_stoch_layout.addWidget(QLabel('스토캐스틱 기간:'), 0, 0)
        self.trade_stoch_period = QSpinBox()
        self.trade_stoch_period.setRange(5, 50)
        self.trade_stoch_period.setValue(14)
        trade_stoch_layout.addWidget(self.trade_stoch_period, 0, 1)
        trade_stoch_group.setLayout(trade_stoch_layout)
        trade_layout.addWidget(trade_stoch_group, 7, 0, 1, 2)
        self.trade_param_groups['스토캐스틱'] = trade_stoch_group
        
        # ATR 파라미터
        trade_atr_group = QGroupBox("ATR 파라미터")
        trade_atr_layout = QGridLayout()
        trade_atr_layout.addWidget(QLabel('ATR 기간:'), 0, 0)
        self.trade_atr_period = QSpinBox()
        self.trade_atr_period.setRange(5, 50)
        self.trade_atr_period.setValue(14)
        trade_atr_layout.addWidget(self.trade_atr_period, 0, 1)
        trade_atr_layout.addWidget(QLabel('ATR 승수:'), 1, 0)
        self.trade_atr_multiplier = QDoubleSpinBox()
        self.trade_atr_multiplier.setRange(0.1, 5.0)
        self.trade_atr_multiplier.setValue(2.0)
        self.trade_atr_multiplier.setSingleStep(0.1)
        trade_atr_layout.addWidget(self.trade_atr_multiplier, 1, 1)
        trade_atr_group.setLayout(trade_atr_layout)
        trade_layout.addWidget(trade_atr_group, 8, 0, 1, 2)
        self.trade_param_groups['ATR 기반 변동성 돌파'] = trade_atr_group
        
        # ShortPercent 파라미터
        trade_short_group = QGroupBox("ShortPercent 파라미터")
        trade_short_layout = QGridLayout()
        trade_short_layout.addWidget(QLabel('총 투자 금액(원):'), 0, 0)
        self.trade_short_total_investment = QSpinBox()
        self.trade_short_total_investment.setRange(100000, 10000000)
        self.trade_short_total_investment.setValue(1000000)
        self.trade_short_total_investment.setSingleStep(100000)
        trade_short_layout.addWidget(self.trade_short_total_investment, 0, 1)
        trade_short_layout.addWidget(QLabel('일회 투자 금액(원):'), 1, 0)
        self.trade_short_single_investment = QSpinBox()
        self.trade_short_single_investment.setRange(10000, 1000000)
        self.trade_short_single_investment.setValue(100000)
        self.trade_short_single_investment.setSingleStep(10000)
        trade_short_layout.addWidget(self.trade_short_single_investment, 1, 1)
        trade_short_layout.addWidget(QLabel('매수 기준 하락률(%):'), 2, 0)
        self.trade_short_buy_percent = QDoubleSpinBox()
        self.trade_short_buy_percent.setRange(0.1, 5.0)
        self.trade_short_buy_percent.setValue(0.5)
        self.trade_short_buy_percent.setSingleStep(0.1)
        trade_short_layout.addWidget(self.trade_short_buy_percent, 2, 1)
        trade_short_layout.addWidget(QLabel('매도 기준 상승률(%):'), 3, 0)
        self.trade_short_sell_percent = QDoubleSpinBox()
        self.trade_short_sell_percent.setRange(0.1, 5.0)
        self.trade_short_sell_percent.setValue(0.5)
        self.trade_short_sell_percent.setSingleStep(0.1)
        trade_short_layout.addWidget(self.trade_short_sell_percent, 3, 1)
        trade_short_group.setLayout(trade_short_layout)
        trade_layout.addWidget(trade_short_group, 9, 0, 1, 2)
        self.trade_param_groups['ShortPercent'] = trade_short_group
        
        # 전략 변경 시 파라미터 그룹 표시/숨김 처리
        self.trade_strategy_combo.currentTextChanged.connect(self.update_trade_param_groups)
        
        # 초기 파라미터 그룹 표시
        self.update_trade_param_groups(self.trade_strategy_combo.currentText())
        
        trade_group.setLayout(trade_layout)
        auto_trade_layout.addWidget(trade_group)
        
        # 자동매매 시작/정지 버튼
        self.trade_start_btn = QPushButton('자동매매 시작')
        self.trade_start_btn.clicked.connect(self.toggle_auto_trading)
        auto_trade_layout.addWidget(self.trade_start_btn)
        
        # 자동매매 상태 및 로그
        self.trade_status = QTextEdit()
        self.trade_status.setReadOnly(True)
        auto_trade_layout.addWidget(self.trade_status)
        
        auto_trade_tab.setLayout(auto_trade_layout)
        tab.addTab(auto_trade_tab, '자동매매')
        
        vbox.addWidget(tab)
        dlg.setLayout(vbox)
        dlg.exec_()

    def calculate_macd(self, prices, fast_period, slow_period, signal_period):
        exp1 = prices.ewm(span=fast_period, adjust=False).mean()
        exp2 = prices.ewm(span=slow_period, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        return macd, signal

    def calculate_moving_averages(self, prices, short_period, long_period):
        short_ma = prices.rolling(window=short_period).mean()
        long_ma = prices.rolling(window=long_period).mean()
        return short_ma, long_ma

    def calculate_stochastic(self, high, low, close, period):
        lowest_low = low.rolling(window=period).min()
        highest_high = high.rolling(window=period).max()
        k = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        d = k.rolling(window=3).mean()
        return k, d

    def calculate_atr(self, high, low, close, period):
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def generate_signal(self, data, strategy):
        if strategy == 'ShortPercent':
            # ShortPercent 전략은 시뮬레이션 루프에서 직접 처리
            return 'hold'
            
        elif strategy == 'RSI':
            rsi = data['RSI'].iloc[-1]
            if rsi < 30:
                return 'buy'
            elif rsi > 70:
                return 'sell'
                
        elif strategy == '볼린저밴드':
            price = data['close'].iloc[-1]
            if price < data['BB_lower'].iloc[-1]:
                return 'buy'
            elif price > data['BB_upper'].iloc[-1]:
                return 'sell'
                
        elif strategy == 'RSI + 볼린저밴드':
            rsi = data['RSI'].iloc[-1]
            price = data['close'].iloc[-1]
            
            if rsi < 30 and price < data['BB_lower'].iloc[-1]:
                return 'buy'
            elif rsi > 70 and price > data['BB_upper'].iloc[-1]:
                return 'sell'
                
        elif strategy == 'MACD':
            macd = data['MACD'].iloc[-1]
            signal = data['MACD_signal'].iloc[-1]
            
            if macd > signal and data['MACD'].iloc[-2] <= data['MACD_signal'].iloc[-2]:
                return 'buy'
            elif macd < signal and data['MACD'].iloc[-2] >= data['MACD_signal'].iloc[-2]:
                return 'sell'
                
        elif strategy == '이동평균선 교차':
            short_ma = data['MA_short'].iloc[-1]
            long_ma = data['MA_long'].iloc[-1]
            
            if short_ma > long_ma and data['MA_short'].iloc[-2] <= data['MA_long'].iloc[-2]:
                return 'buy'
            elif short_ma < long_ma and data['MA_short'].iloc[-2] >= data['MA_long'].iloc[-2]:
                return 'sell'
                
        elif strategy == '스토캐스틱':
            k = data['Stoch_K'].iloc[-1]
            d = data['Stoch_D'].iloc[-1]
            
            if k < 20 and d < 20:
                return 'buy'
            elif k > 80 and d > 80:
                return 'sell'
                
        elif strategy == 'ATR 기반 변동성 돌파':
            atr = data['ATR'].iloc[-1]
            price = data['close'].iloc[-1]
            upper_band = data['close'].iloc[-2] + (atr * self.atr_multiplier.value())
            lower_band = data['close'].iloc[-2] - (atr * self.atr_multiplier.value())
            
            if price > upper_band:
                return 'buy'
            elif price < lower_band:
                return 'sell'
                
        elif strategy == '캔들 패턴':
            # 도지 패턴
            if (data['open'].iloc[-1] > data['close'].iloc[-1] and  # 음봉
                data['open'].iloc[-2] < data['close'].iloc[-2] and  # 양봉
                data['close'].iloc[-1] < data['open'].iloc[-2] and  # 음봉의 종가가 양봉의 시가보다 낮음
                data['open'].iloc[-1] > data['close'].iloc[-2]):    # 음봉의 시가가 양봉의 종가보다 높음
                return 'sell'
                
            # 망치형 패턴
            elif (data['close'].iloc[-1] > data['open'].iloc[-1] and  # 양봉
                  data['high'].iloc[-1] - data['close'].iloc[-1] < data['close'].iloc[-1] - data['open'].iloc[-1] and  # 위꼬리가 짧음
                  data['open'].iloc[-1] - data['low'].iloc[-1] > 2 * (data['close'].iloc[-1] - data['open'].iloc[-1])):  # 아래꼬리가 길음
                return 'buy'
                
        return 'hold'

    def toggle_simulation(self):
        if self.sim_start_btn.text() == '시뮬레이션 시작':
            self.sim_start_btn.setText('시뮬레이션 정지')
            self.start_simulation()
        else:
            self.sim_start_btn.setText('시뮬레이션 시작')
            self.stop_simulation()

    def start_simulation(self):
        self.simulation_enabled = True
        self.sim_status.append("시뮬레이션을 시작합니다...")
        
        # 시뮬레이션 스레드 시작
        self.simulation_thread = threading.Thread(target=self.simulation_loop)
        self.simulation_thread.daemon = True
        self.simulation_thread.start()

    def stop_simulation(self):
        self.simulation_enabled = False
        self.sim_status.append("시뮬레이션을 정지합니다...")

    def simulation_loop(self):
        try:
            # 초기 설정
            coin = self.sim_coin_combo.currentText()
            strategy = self.sim_strategy_combo.currentText()
            initial_balance = self.sim_investment.value()
            balance = initial_balance
            position = 0
            entry_price = 0
            
            # ShortPercent 전략 변수
            if strategy == 'ShortPercent':
                total_investment = self.short_total_investment.value()
                single_investment = self.short_single_investment.value()
                buy_percent = self.short_buy_percent.value() / 100
                sell_percent = self.short_sell_percent.value() / 100
                total_position = 0
                last_buy_price = 0
                last_sell_price = 0
                is_first_buy = True
            
            self.update_sim_status.emit(f"=== 시뮬레이션 시작 ===")
            self.update_sim_status.emit(f"코인: {coin}")
            self.update_sim_status.emit(f"전략: {strategy}")
            
            if strategy == 'ShortPercent':
                self.update_sim_status.emit(f"총 투자 금액: {total_investment:,.0f}원")
                self.update_sim_status.emit(f"일회 투자 금액: {single_investment:,.0f}원")
                self.update_sim_status.emit(f"매수 기준 하락률: {buy_percent*100:.1f}%")
                self.update_sim_status.emit(f"매도 기준 상승률: {sell_percent*100:.1f}%")
            else:
                self.update_sim_status.emit(f"초기 자본금: {initial_balance:,.0f}원")
            
            self.update_sim_status.emit("")
            
            while self.simulation_enabled:
                try:
                    # 현재가 조회
                    current_price = python_bithumb.get_current_price(f"KRW-{coin}")
                    
                    # 현재 상태 표시
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.update_sim_status.emit(f"\n[{current_time}]")
                    self.update_sim_status.emit(f"현재가: {current_price:,.0f}원")
                    
                    if strategy == 'ShortPercent':
                        if is_first_buy:
                            # 첫 매수
                            amount = single_investment / current_price
                            total_position += amount
                            last_buy_price = current_price
                            last_sell_price = current_price
                            is_first_buy = False
                            self.update_sim_status.emit(f"\n[첫 매수] {amount:.8f} {coin} @ {current_price:,.0f}원")
                        else:
                            # 가격이 마지막 매수 가격보다 buy_percent% 이상 하락했고, 
                            # 총 투자 금액을 초과하지 않았다면 매수
                            if (current_price <= last_buy_price * (1 - buy_percent) and 
                                total_position * current_price + single_investment <= total_investment):
                                amount = single_investment / current_price
                                total_position += amount
                                last_buy_price = current_price
                                self.update_sim_status.emit(f"\n[추가 매수] {amount:.8f} {coin} @ {current_price:,.0f}원")
                            
                            # 가격이 마지막 매도 가격보다 sell_percent% 이상 상승했다면 매도
                            elif current_price >= last_sell_price * (1 + sell_percent):
                                amount = single_investment / current_price
                                if amount <= total_position:
                                    total_position -= amount
                                    last_sell_price = current_price
                                    profit = amount * (current_price - last_buy_price)
                                    profit_rate = (current_price - last_buy_price) / last_buy_price * 100
                                    self.update_sim_status.emit(f"\n[매도] {amount:.8f} {coin} @ {current_price:,.0f}원")
                                    self.update_sim_status.emit(f"수익금: {profit:,.0f}원 ({profit_rate:.2f}%)")
                        
                        # 현재 상태 표시
                        total_value = total_position * current_price
                        self.update_sim_status.emit(f"총 보유량: {total_position:.8f} {coin}")
                        self.update_sim_status.emit(f"평가금액: {total_value:,.0f}원")
                        self.update_sim_status.emit(f"남은 투자 가능 금액: {(total_investment - total_value):,.0f}원")
                        
                    else:
                        if position > 0:
                            profit = (current_price - entry_price) * position
                            profit_rate = (profit / (entry_price * position)) * 100
                            self.update_sim_status.emit(f"보유량: {position:.8f} {coin}")
                            self.update_sim_status.emit(f"평가금액: {(position * current_price):,.0f}원")
                            self.update_sim_status.emit(f"수익금: {profit:,.0f}원 ({profit_rate:.2f}%)")
                        else:
                            self.update_sim_status.emit(f"보유 현금: {balance:,.0f}원")
                        
                        # OHLCV 데이터 수집
                        df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval="minute1", count=100)
                        
                        if df is not None and not df.empty:
                            # 기술적 지표 계산
                            if 'RSI' in strategy:
                                df['RSI'] = self.calculate_rsi(df['close'], self.sim_rsi_period.value())
                            
                            if '볼린저밴드' in strategy:
                                df['BB_middle'], df['BB_upper'], df['BB_lower'] = self.calculate_bollinger_bands(
                                    df['close'], self.sim_bb_period.value(), self.sim_bb_std.value())
                            
                            if 'MACD' in strategy:
                                df['MACD'], df['MACD_signal'] = self.calculate_macd(
                                    df['close'], self.sim_macd_fast.value(), self.sim_macd_slow.value(), self.sim_macd_signal.value())
                            
                            if '이동평균선' in strategy:
                                df['MA_short'], df['MA_long'] = self.calculate_moving_averages(
                                    df['close'], self.sim_ma_short.value(), self.sim_ma_long.value())
                            
                            if '스토캐스틱' in strategy:
                                df['Stoch_K'], df['Stoch_D'] = self.calculate_stochastic(
                                    df['high'], df['low'], df['close'], self.sim_stoch_period.value())
                            
                            if 'ATR' in strategy:
                                df['ATR'] = self.calculate_atr(
                                    df['high'], df['low'], df['close'], self.sim_atr_period.value())
                            
                            # 매매 신호 생성
                            signal = self.generate_signal(df.iloc[-2:], strategy)
                            
                            if signal == 'buy' and position == 0:
                                # 매수
                                amount = balance / current_price
                                position = amount
                                balance = 0
                                entry_price = current_price
                                self.update_sim_status.emit(f"\n[매수] {amount:.8f} {coin} @ {current_price:,.0f}원")
                                
                            elif signal == 'sell' and position > 0:
                                # 매도
                                balance = position * current_price
                                profit = balance - (position * entry_price)
                                profit_rate = (profit / (position * entry_price)) * 100
                                self.update_sim_status.emit(f"\n[매도] {position:.8f} {coin} @ {current_price:,.0f}원")
                                self.update_sim_status.emit(f"수익금: {profit:,.0f}원 ({profit_rate:.2f}%)")
                                position = 0
                                entry_price = 0
                    
                    # 1분 대기
                    time.sleep(60)
                    
                except Exception as e:
                    self.update_sim_status.emit(f"오류 발생: {str(e)}")
                    time.sleep(60)  # 오류 발생시 1분 대기
                
        except Exception as e:
            self.update_sim_status.emit(f"시뮬레이션 중 오류 발생: {str(e)}")
            self.update_sim_status.emit(traceback.format_exc())
            time.sleep(60)  # 오류 발생시 1분 대기

    def run_backtest(self):
        try:
            # 파라미터 가져오기
            coin = self.backtest_coin_combo.currentText()
            start_date = self.backtest_start_date.text()
            end_date = self.backtest_end_date.text()
            interval = self.backtest_interval_combo.currentText()
            strategy = self.strategy_combo.currentText()
            
            # 데이터베이스에서 데이터 로드
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            
            # 사용 가능한 테이블 목록 확인
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            available_tables = [table[0] for table in tables]
            
            # 테이블 이름 생성
            interval_db = interval.replace('봉', '')
            if interval_db == '1분':
                interval_db = 'minute1'
            elif interval_db == '3분':
                interval_db = 'minute3'
            elif interval_db == '5분':
                interval_db = 'minute5'
            elif interval_db == '15분':
                interval_db = 'minute15'
            elif interval_db == '30분':
                interval_db = 'minute30'
            elif interval_db == '60분':
                interval_db = 'minute60'
            elif interval_db == '일':
                interval_db = 'day'
                
            table_name = f"{coin}_ohlcv_{interval_db}"
            
            # 테이블이 존재하는지 확인
            if table_name not in available_tables:
                self.backtest_result.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                self.backtest_result.append("사용 가능한 테이블 목록:")
                for table in available_tables:
                    self.backtest_result.append(f"- {table}")
                self.backtest_result.append("\n먼저 데이터를 수집해주세요.")
                conn.close()
                return
            
            # 데이터 조회
            query = f"SELECT * FROM {table_name} WHERE [index] BETWEEN '{start_date}' AND '{end_date}'"
            df = pd.read_sql_query(query, conn)
            conn.close()
            
            if df.empty:
                self.backtest_result.append("데이터가 없습니다. 먼저 데이터를 수집해주세요.")
                return
            
            # 백테스팅 실행
            if strategy == 'ShortPercent':
                # ShortPercent 전략 백테스팅
                total_investment = self.short_total_investment.value()
                single_investment = self.short_single_investment.value()
                buy_percent = self.short_buy_percent.value() / 100
                sell_percent = self.short_sell_percent.value() / 100
                
                balance = total_investment
                total_position = 0
                trades = []
                daily_balance = []
                last_buy_price = 0
                last_sell_price = 0
                is_first_buy = True
                
                for i in range(len(df)):
                    current_price = df.iloc[i]['close']
                    current_time = df.iloc[i]['index']
                    
                    if is_first_buy:
                        # 첫 매수
                        amount = single_investment / current_price
                        total_position += amount
                        balance -= single_investment
                        last_buy_price = current_price
                        last_sell_price = current_price
                        is_first_buy = False
                        trades.append({
                            'date': current_time,
                            'type': 'buy',
                            'price': current_price,
                            'amount': amount,
                            'balance': balance,
                            'position': total_position
                        })
                    else:
                        # 가격이 마지막 매수 가격보다 buy_percent% 이상 하락했고,
                        # 총 투자 금액을 초과하지 않았다면 매수
                        if (current_price <= last_buy_price * (1 - buy_percent) and
                            total_position * current_price + single_investment <= total_investment):
                            amount = single_investment / current_price
                            total_position += amount
                            balance -= single_investment
                            last_buy_price = current_price
                            trades.append({
                                'date': current_time,
                                'type': 'buy',
                                'price': current_price,
                                'amount': amount,
                                'balance': balance,
                                'position': total_position
                            })
                        
                        # 가격이 마지막 매도 가격보다 sell_percent% 이상 상승했다면 매도
                        elif current_price >= last_sell_price * (1 + sell_percent):
                            amount = single_investment / current_price
                            if amount <= total_position:
                                total_position -= amount
                                balance += amount * current_price
                                last_sell_price = current_price
                                trades.append({
                                    'date': current_time,
                                    'type': 'sell',
                                    'price': current_price,
                                    'amount': amount,
                                    'balance': balance,
                                    'position': total_position
                                })
                    
                    # 일별 잔고 기록
                    daily_balance.append({
                        'date': current_time,
                        'balance': balance + (total_position * current_price),
                        'position': total_position,
                        'price': current_price
                    })
                
                # 최종 평가
                final_balance = balance + (total_position * df.iloc[-1]['close'])
                profit = final_balance - total_investment
                profit_rate = (profit / total_investment) * 100
                
                # 거래 통계
                buy_trades = [t for t in trades if t['type'] == 'buy']
                sell_trades = [t for t in trades if t['type'] == 'sell']
                
                # 결과 출력
                self.backtest_result.clear()
                self.backtest_result.append(f"=== ShortPercent 백테스팅 결과 ===")
                self.backtest_result.append(f"테스트 기간: {start_date} ~ {end_date}")
                self.backtest_result.append(f"총 투자 금액: {total_investment:,.0f}원")
                self.backtest_result.append(f"일회 투자 금액: {single_investment:,.0f}원")
                self.backtest_result.append(f"매수 기준 하락률: {buy_percent*100:.1f}%")
                self.backtest_result.append(f"매도 기준 상승률: {sell_percent*100:.1f}%")
                self.backtest_result.append(f"\n=== 수익 분석 ===")
                self.backtest_result.append(f"최종 자본금: {final_balance:,.0f}원")
                self.backtest_result.append(f"수익금: {profit:,.0f}원")
                self.backtest_result.append(f"수익률: {profit_rate:.2f}%")
                self.backtest_result.append(f"\n=== 거래 분석 ===")
                self.backtest_result.append(f"총 거래 횟수: {len(trades)}회")
                self.backtest_result.append(f"매수 횟수: {len(buy_trades)}회")
                self.backtest_result.append(f"매도 횟수: {len(sell_trades)}회")
                
                if sell_trades:
                    avg_profit_rate = sum((t['price'] - last_buy_price) / last_buy_price * 100 
                                       for t in sell_trades) / len(sell_trades)
                    self.backtest_result.append(f"평균 수익률: {avg_profit_rate:.2f}%")
                
                # 차트 그리기
                self.plot_backtest_results(df, trades, daily_balance)
                
            else:
                # 기존 전략 백테스팅
                initial_balance = 1000000
                balance = initial_balance
                position = 0
                trades = []
                daily_balance = []
                
                # 기술적 지표 계산
                if 'RSI' in strategy:
                    df['RSI'] = self.calculate_rsi(df['close'], self.rsi_period.value())
                
                if '볼린저밴드' in strategy:
                    df['BB_middle'], df['BB_upper'], df['BB_lower'] = self.calculate_bollinger_bands(
                        df['close'], self.bb_period.value(), self.bb_std.value())
                
                if 'MACD' in strategy:
                    df['MACD'], df['MACD_signal'] = self.calculate_macd(
                        df['close'], self.macd_fast.value(), self.macd_slow.value(), self.macd_signal.value())
                
                if '이동평균선' in strategy:
                    df['MA_short'], df['MA_long'] = self.calculate_moving_averages(
                        df['close'], self.ma_short.value(), self.ma_long.value())
                
                if '스토캐스틱' in strategy:
                    df['Stoch_K'], df['Stoch_D'] = self.calculate_stochastic(
                        df['high'], df['low'], df['close'], self.stoch_period.value())
                
                if 'ATR' in strategy:
                    df['ATR'] = self.calculate_atr(
                        df['high'], df['low'], df['close'], self.atr_period.value())
                
                for i in range(1, len(df)):
                    signal = self.generate_signal(df.iloc[i-1:i+1], strategy)
                    
                    if signal == 'buy' and position == 0:
                        # 매수
                        price = df.iloc[i]['close']
                        amount = balance / price
                        position = amount
                        balance = 0
                        trades.append({
                            'date': df.iloc[i]['index'],
                            'type': 'buy',
                            'price': price,
                            'amount': amount,
                            'balance': balance,
                            'position': position
                        })
                        
                    elif signal == 'sell' and position > 0:
                        # 매도
                        price = df.iloc[i]['close']
                        balance = position * price
                        position = 0
                        trades.append({
                            'date': df.iloc[i]['index'],
                            'type': 'sell',
                            'price': price,
                            'amount': position,
                            'balance': balance,
                            'position': position
                        })
                    
                    # 일별 잔고 기록
                    daily_balance.append({
                        'date': df.iloc[i]['index'],
                        'balance': balance + (position * df.iloc[i]['close']),
                        'position': position,
                        'price': df.iloc[i]['close']
                    })
                
                # 최종 평가
                final_balance = balance + (position * df.iloc[-1]['close'])
                profit = final_balance - initial_balance
                profit_rate = (profit / initial_balance) * 100
                
                # 거래 통계
                buy_trades = [t for t in trades if t['type'] == 'buy']
                sell_trades = [t for t in trades if t['type'] == 'sell']
                
                # 결과 출력
                self.backtest_result.clear()
                self.backtest_result.append(f"=== 백테스팅 결과 ===")
                self.backtest_result.append(f"테스트 기간: {start_date} ~ {end_date}")
                self.backtest_result.append(f"초기 자본금: {initial_balance:,.0f}원")
                self.backtest_result.append(f"최종 자본금: {final_balance:,.0f}원")
                self.backtest_result.append(f"수익금: {profit:,.0f}원")
                self.backtest_result.append(f"수익률: {profit_rate:.2f}%")
                self.backtest_result.append(f"\n=== 거래 분석 ===")
                self.backtest_result.append(f"총 거래 횟수: {len(trades)}회")
                self.backtest_result.append(f"매수 횟수: {len(buy_trades)}회")
                self.backtest_result.append(f"매도 횟수: {len(sell_trades)}회")
                
                if sell_trades:
                    avg_profit_rate = sum((t['price'] - buy_trades[i]['price']) / buy_trades[i]['price'] * 100 
                                       for i, t in enumerate(sell_trades)) / len(sell_trades)
                    self.backtest_result.append(f"평균 수익률: {avg_profit_rate:.2f}%")
                
                # 차트 그리기
                self.plot_backtest_results(df, trades, daily_balance)
            
        except Exception as e:
            self.backtest_result.append(f"백테스팅 중 오류 발생: {str(e)}")
            self.backtest_result.append(traceback.format_exc())

    def plot_backtest_results(self, df, trades, daily_balance):
        # 새로운 창에 차트 표시
        chart_window = QDialog(self)
        chart_window.setWindowTitle('백테스팅 결과 차트')
        chart_window.setGeometry(300, 200, 1200, 800)
        
        layout = QVBoxLayout()
        
        # 차트 생성
        figure = Figure(figsize=(12, 8))
        canvas = FigureCanvas(figure)
        layout.addWidget(canvas)
        
        # 가격 차트
        ax1 = figure.add_subplot(311)
        ax1.plot(df['index'], df['close'], label='가격')
        
        # 볼린저밴드가 있는 경우 표시
        if 'BB_upper' in df.columns:
            ax1.plot(df['index'], df['BB_upper'], 'r--', label='상단밴드')
            ax1.plot(df['index'], df['BB_middle'], 'g--', label='중간밴드')
            ax1.plot(df['index'], df['BB_lower'], 'r--', label='하단밴드')
        
        # 매수/매도 포인트 표시
        for trade in trades:
            if trade['type'] == 'buy':
                ax1.scatter(trade['date'], trade['price'], color='red', marker='^', s=100)
            else:
                ax1.scatter(trade['date'], trade['price'], color='blue', marker='v', s=100)
        
        ax1.set_title('가격 차트')
        ax1.legend()
        ax1.grid(True)
        
        # 자본금 차트
        ax2 = figure.add_subplot(312)
        daily_balance_df = pd.DataFrame(daily_balance)
        ax2.plot(daily_balance_df['date'], daily_balance_df['balance'], label='자본금')
        ax2.set_title('자본금 변화')
        ax2.legend()
        ax2.grid(True)
        
        # 수익률 차트
        ax3 = figure.add_subplot(313)
        initial_balance = daily_balance_df['balance'].iloc[0]
        daily_balance_df['profit_rate'] = (daily_balance_df['balance'] - initial_balance) / initial_balance * 100
        ax3.plot(daily_balance_df['date'], daily_balance_df['profit_rate'], label='수익률')
        ax3.axhline(y=0, color='r', linestyle='--')
        ax3.set_title('수익률 변화')
        ax3.set_ylabel('수익률 (%)')
        ax3.legend()
        ax3.grid(True)
        
        # x축 시간 포맷 설정
        for ax in [ax1, ax2, ax3]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        figure.tight_layout()
        canvas.draw()
        
        chart_window.setLayout(layout)
        chart_window.exec_()

    def calculate_rsi(self, prices, period):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_bollinger_bands(self, prices, period, std):
        middle = prices.rolling(window=period).mean()
        std_dev = prices.rolling(window=period).std()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        return middle, upper, lower

    def toggle_auto_trading(self):
        if not self.is_connected:
            QMessageBox.warning(self, '경고', 'API 연결이 필요합니다.')
            return
            
        if self.trade_start_btn.text() == '자동매매 시작':
            self.trade_start_btn.setText('자동매매 정지')
            self.start_auto_trading()
        else:
            self.trade_start_btn.setText('자동매매 시작')
            self.stop_auto_trading()

    def start_auto_trading(self):
        self.trading_enabled = True
        self.trade_status.append("자동매매를 시작합니다...")
        
        # 자동매매 스레드 시작
        self.trading_thread = threading.Thread(target=self.auto_trading_loop)
        self.trading_thread.daemon = True
        self.trading_thread.start()

    def stop_auto_trading(self):
        self.trading_enabled = False
        self.trade_status.append("자동매매를 정지합니다...")

    def auto_trading_loop(self):
        try:
            # 초기 설정
            coin = self.trade_coin_combo.currentText()
            strategy = self.trade_strategy_combo.currentText()
            initial_balance = self.trade_investment.value()
            balance = initial_balance
            position = 0
            entry_price = 0
            
            # ShortPercent 전략 변수
            if strategy == 'ShortPercent':
                total_investment = self.trade_short_total_investment.value()
                single_investment = self.trade_short_single_investment.value()
                buy_percent = self.trade_short_buy_percent.value() / 100
                sell_percent = self.trade_short_sell_percent.value() / 100
                total_position = 0
                last_buy_price = 0
                last_sell_price = 0
                is_first_buy = True
            
            self.trade_status.append(f"=== 자동매매 시작 ===")
            self.trade_status.append(f"코인: {coin}")
            self.trade_status.append(f"전략: {strategy}")
            
            if strategy == 'ShortPercent':
                self.trade_status.append(f"총 투자 금액: {total_investment:,.0f}원")
                self.trade_status.append(f"일회 투자 금액: {single_investment:,.0f}원")
                self.trade_status.append(f"매수 기준 하락률: {buy_percent*100:.1f}%")
                self.trade_status.append(f"매도 기준 상승률: {sell_percent*100:.1f}%")
            else:
                self.trade_status.append(f"초기 자본금: {initial_balance:,.0f}원")
            
            self.trade_status.append("")
            
            while self.trading_enabled:
                try:
                    # 현재가 조회
                    current_price = python_bithumb.get_current_price(f"KRW-{coin}")
                    
                    # 현재 상태 표시
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.trade_status.append(f"\n[{current_time}]")
                    self.trade_status.append(f"현재가: {current_price:,.0f}원")
                    
                    if strategy == 'ShortPercent':
                        if is_first_buy:
                            # 첫 매수
                            amount = single_investment / current_price
                            order = self.bithumb.buy_market_order(coin, amount)
                            if order and 'error' not in order:
                                total_position += amount
                                last_buy_price = current_price
                                last_sell_price = current_price
                                is_first_buy = False
                                self.trade_status.append(f"\n[첫 매수] {amount:.8f} {coin} @ {current_price:,.0f}원")
                        else:
                            # 가격이 마지막 매수 가격보다 buy_percent% 이상 하락했고, 
                            # 총 투자 금액을 초과하지 않았다면 매수
                            if (current_price <= last_buy_price * (1 - buy_percent) and 
                                total_position * current_price + single_investment <= total_investment):
                                amount = single_investment / current_price
                                order = self.bithumb.buy_market_order(coin, amount)
                                if order and 'error' not in order:
                                    total_position += amount
                                    last_buy_price = current_price
                                    self.trade_status.append(f"\n[추가 매수] {amount:.8f} {coin} @ {current_price:,.0f}원")
                            
                            # 가격이 마지막 매도 가격보다 sell_percent% 이상 상승했다면 매도
                            elif current_price >= last_sell_price * (1 + sell_percent):
                                amount = single_investment / current_price
                                if amount <= total_position:
                                    order = self.bithumb.sell_market_order(coin, amount)
                                    if order and 'error' not in order:
                                        total_position -= amount
                                        last_sell_price = current_price
                                        profit = amount * (current_price - last_buy_price)
                                        profit_rate = (current_price - last_buy_price) / last_buy_price * 100
                                        self.trade_status.append(f"\n[매도] {amount:.8f} {coin} @ {current_price:,.0f}원")
                                        self.trade_status.append(f"수익금: {profit:,.0f}원 ({profit_rate:.2f}%)")
                        
                        # 현재 상태 표시
                        total_value = total_position * current_price
                        self.trade_status.append(f"총 보유량: {total_position:.8f} {coin}")
                        self.trade_status.append(f"평가금액: {total_value:,.0f}원")
                        self.trade_status.append(f"남은 투자 가능 금액: {(total_investment - total_value):,.0f}원")
                        
                    else:
                        # 잔고 조회
                        balance_info = self.bithumb.get_balance(coin)
                        available_krw = float(balance_info['available_krw'])
                        total_coin = float(balance_info['total'])
                        
                        if total_coin > 0:
                            profit = (current_price - entry_price) * total_coin
                            profit_rate = (profit / (entry_price * total_coin)) * 100
                            self.trade_status.append(f"보유량: {total_coin:.8f} {coin}")
                            self.trade_status.append(f"평가금액: {(total_coin * current_price):,.0f}원")
                            self.trade_status.append(f"수익금: {profit:,.0f}원 ({profit_rate:.2f}%)")
                        else:
                            self.trade_status.append(f"보유 현금: {available_krw:,.0f}원")
                        
                        # OHLCV 데이터 수집
                        df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval="minute1", count=100)
                        
                        if df is not None and not df.empty:
                            # 기술적 지표 계산
                            if 'RSI' in strategy:
                                df['RSI'] = self.calculate_rsi(df['close'], self.trade_rsi_period.value())
                            
                            if '볼린저밴드' in strategy:
                                df['BB_middle'], df['BB_upper'], df['BB_lower'] = self.calculate_bollinger_bands(
                                    df['close'], self.trade_bb_period.value(), self.trade_bb_std.value())
                            
                            if 'MACD' in strategy:
                                df['MACD'], df['MACD_signal'] = self.calculate_macd(
                                    df['close'], self.trade_macd_fast.value(), self.trade_macd_slow.value(), self.trade_macd_signal.value())
                            
                            if '이동평균선' in strategy:
                                df['MA_short'], df['MA_long'] = self.calculate_moving_averages(
                                    df['close'], self.trade_ma_short.value(), self.trade_ma_long.value())
                            
                            if '스토캐스틱' in strategy:
                                df['Stoch_K'], df['Stoch_D'] = self.calculate_stochastic(
                                    df['high'], df['low'], df['close'], self.trade_stoch_period.value())
                            
                            if 'ATR' in strategy:
                                df['ATR'] = self.calculate_atr(
                                    df['high'], df['low'], df['close'], self.trade_atr_period.value())
                            
                            # 매매 신호 생성
                            signal = self.generate_signal(df.iloc[-2:], strategy)
                            
                            if signal == 'buy' and available_krw >= self.trade_investment.value():
                                # 매수
                                amount = self.trade_investment.value() / current_price
                                order = self.bithumb.buy_market_order(coin, amount)
                                if order and 'error' not in order:
                                    entry_price = current_price
                                    self.trade_status.append(f"\n[매수] {amount:.8f} {coin} @ {current_price:,.0f}원")
                                
                            elif signal == 'sell' and total_coin > 0:
                                # 매도
                                order = self.bithumb.sell_market_order(coin, total_coin)
                                if order and 'error' not in order:
                                    profit = total_coin * (current_price - entry_price)
                                    profit_rate = (profit / (entry_price * total_coin)) * 100
                                    self.trade_status.append(f"\n[매도] {total_coin:.8f} {coin} @ {current_price:,.0f}원")
                                    self.trade_status.append(f"수익금: {profit:,.0f}원 ({profit_rate:.2f}%)")
                                    entry_price = 0
                    
                    # 1분 대기
                    time.sleep(60)
                    
                except Exception as e:
                    self.trade_status.append(f"오류 발생: {str(e)}")
                    time.sleep(60)  # 오류 발생시 1분 대기
                
        except Exception as e:
            self.trade_status.append(f"자동매매 중 오류 발생: {str(e)}")
            self.trade_status.append(traceback.format_exc())
            time.sleep(60)  # 오류 발생시 1분 대기

    def get_current_price(self):
        try:
            coin = self.coin_combo.currentText()
            price = python_bithumb.get_current_price(f"KRW-{coin}")
            self.result_text.append(f"\n=== {coin} 현재가 ===")
            self.result_text.append(f"가격: {price:,.0f}원")
            self.current_price = price
            self.price_label.setText(f'현재가: {price:,.0f}원')
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
            coin = self.coin_combo.currentText()
            volume = python_bithumb.get_volume(f"KRW-{coin}")
            self.result_text.append(f"\n=== {coin} 거래량 ===")
            self.result_text.append(f"24시간 거래량: {volume:,.0f}")
        except Exception as e:
            self.result_text.append(f"거래량 조회 실패: {str(e)}")

    def get_market_codes(self):
        try:
            markets = python_bithumb.get_market_codes()
            self.result_text.append("\n=== 마켓 코드 목록 ===")
            for market in markets:
                self.result_text.append(market)
        except Exception as e:
            self.result_text.append(f"마켓 코드 조회 실패: {str(e)}")

    def get_virtual_asset_warning(self):
        try:
            warnings = python_bithumb.get_virtual_asset_warning()
            self.result_text.append("\n=== 가상자산 경고 목록 ===")
            for warning in warnings:
                self.result_text.append(warning)
        except Exception as e:
            self.result_text.append(f"가상자산 경고 조회 실패: {str(e)}")

    def get_balance(self):
        if not self.is_connected:
            self.result_text.append("API 연결이 필요합니다.")
            return
        try:
            balance = self.bithumb.get_balance(self.coin_combo.currentText())
            self.result_text.append(f"\n=== {self.coin_combo.currentText()} 잔고 ===")
            self.result_text.append(f"보유량: {balance['total']}")
            self.result_text.append(f"사용 가능: {balance['available']}")
            self.result_text.append(f"거래 중: {balance['in_use']}")
            self.balance_label.setText(f'보유량: {balance["total"]}')
        except Exception as e:
            self.result_text.append(f"잔고 조회 실패: {str(e)}")

    def get_order_chance(self):
        if not self.is_connected:
            self.result_text.append("API 연결이 필요합니다.")
            return
        try:
            chance = self.bithumb.get_order_chance(self.coin_combo.currentText())
            self.result_text.append(f"\n=== {self.coin_combo.currentText()} 주문 가능 정보 ===")
            self.result_text.append(f"최소 주문 금액: {chance['min_total']}원")
            self.result_text.append(f"최소 주문 수량: {chance['min_amount']}")
            self.result_text.append(f"수수료율: {chance['fee_rate']}%")
        except Exception as e:
            self.result_text.append(f"주문 가능 정보 조회 실패: {str(e)}")

    def buy_limit_order(self):
        if not self.is_connected:
            self.result_text.append("API 연결이 필요합니다.")
            return
        try:
            price = float(self.calc_price_input.value())
            amount = float(self.calc_amt_input.value())
            order = self.bithumb.buy_limit_order(self.coin_combo.currentText(), price, amount)
            self.result_text.append(f"\n=== 지정가 매수 주문 ===")
            self.result_text.append(f"주문 ID: {order['uuid']}")
            self.result_text.append(f"가격: {price:,.0f}원")
            self.result_text.append(f"수량: {amount}")
        except Exception as e:
            self.result_text.append(f"매수 주문 실패: {str(e)}")

    def sell_limit_order(self):
        if not self.is_connected:
            self.result_text.append("API 연결이 필요합니다.")
            return
        try:
            price = float(self.calc_price_input.value())
            amount = float(self.calc_amt_input.value())
            order = self.bithumb.sell_limit_order(self.coin_combo.currentText(), price, amount)
            self.result_text.append(f"\n=== 지정가 매도 주문 ===")
            self.result_text.append(f"주문 ID: {order['uuid']}")
            self.result_text.append(f"가격: {price:,.0f}원")
            self.result_text.append(f"수량: {amount}")
        except Exception as e:
            self.result_text.append(f"매도 주문 실패: {str(e)}")

    def buy_market_order(self):
        if not self.is_connected:
            self.result_text.append("API 연결이 필요합니다.")
            return
        try:
            amount = float(self.calc_amt_input.value())
            order = self.bithumb.buy_market_order(self.coin_combo.currentText(), amount)
            self.result_text.append(f"\n=== 시장가 매수 주문 ===")
            self.result_text.append(f"주문 ID: {order['uuid']}")
            self.result_text.append(f"수량: {amount}")
        except Exception as e:
            self.result_text.append(f"매수 주문 실패: {str(e)}")

    def sell_market_order(self):
        if not self.is_connected:
            self.result_text.append("API 연결이 필요합니다.")
            return
        try:
            amount = float(self.calc_amt_input.value())
            order = self.bithumb.sell_market_order(self.coin_combo.currentText(), amount)
            self.result_text.append(f"\n=== 시장가 매도 주문 ===")
            self.result_text.append(f"주문 ID: {order['uuid']}")
            self.result_text.append(f"수량: {amount}")
        except Exception as e:
            self.result_text.append(f"매도 주문 실패: {str(e)}")

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
            
            # 데이터 저장
            self.price_data.extend(df['close'].values)
            self.time_data.extend(df.index.values)
            
        except Exception as e:
            self.result_text.append(f"캔들 데이터 수집 실패: {str(e)}")

    def update_chart(self):
        if not self.price_data:
            return
        
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot(self.time_data, self.price_data)
        ax.set_title(f'{self.coin_combo.currentText()} 가격 차트')
        ax.set_xlabel('시간')
        ax.set_ylabel('가격')
        ax.grid(True)
        self.figure.tight_layout()
        self.canvas.draw()

    def fetch_realtime_data(self):
        try:
            coin = self.coin_combo.currentText()
            price = python_bithumb.get_current_price(f"KRW-{coin}")
            volume = python_bithumb.get_volume(f"KRW-{coin}")
            
            self.realtime_price_data.append(price)
            self.realtime_time_data.append(datetime.now())
            self.realtime_volume_data.append(volume)
            
            # 최대 100개 데이터만 유지
            if len(self.realtime_price_data) > 100:
                self.realtime_price_data.pop(0)
                self.realtime_time_data.pop(0)
                self.realtime_volume_data.pop(0)
            
            self.update_realtime_chart()
            
        except Exception as e:
            print(f"실시간 데이터 수집 실패: {str(e)}")

    def update_realtime_chart(self):
        if not self.realtime_chart_window or not self.realtime_price_data:
            return
        
        self.realtime_chart_window.figure.clear()
        
        # 가격 차트
        ax1 = self.realtime_chart_window.figure.add_subplot(211)
        ax1.plot(self.realtime_time_data, self.realtime_price_data, 'b-')
        ax1.set_title(f'{self.coin_combo.currentText()} 실시간 가격')
        ax1.set_ylabel('가격')
        ax1.grid(True)
        
        # 거래량 차트
        ax2 = self.realtime_chart_window.figure.add_subplot(212)
        ax2.bar(self.realtime_time_data, self.realtime_volume_data, color='g', alpha=0.7)
        ax2.set_title('실시간 거래량')
        ax2.set_xlabel('시간')
        ax2.set_ylabel('거래량')
        ax2.grid(True)
        
        # x축 시간 포맷 설정
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        self.realtime_chart_window.figure.tight_layout()
        self.realtime_chart_window.canvas.draw()

    def open_realtime_chart_window(self):
        if self.realtime_chart_window is None:
            self.realtime_chart_window = QDialog(self)
            self.realtime_chart_window.setWindowTitle('실시간 차트')
            self.realtime_chart_window.setGeometry(300, 200, 800, 600)
            
            layout = QVBoxLayout()
            
            # 차트 영역
            self.realtime_chart_window.figure = Figure(figsize=(8, 6))
            self.realtime_chart_window.canvas = FigureCanvas(self.realtime_chart_window.figure)
            layout.addWidget(self.realtime_chart_window.canvas)
            
            # 컨트롤 버튼
            control_layout = QHBoxLayout()
            
            self.realtime_start_btn = QPushButton('시작')
            self.realtime_start_btn.clicked.connect(self.toggle_realtime_chart)
            control_layout.addWidget(self.realtime_start_btn)
            
            self.realtime_stop_btn = QPushButton('정지')
            self.realtime_stop_btn.clicked.connect(self.toggle_realtime_chart)
            self.realtime_stop_btn.setEnabled(False)
            control_layout.addWidget(self.realtime_stop_btn)
            
            layout.addLayout(control_layout)
            self.realtime_chart_window.setLayout(layout)
        
        self.realtime_chart_window.show()

    def toggle_realtime_chart(self):
        if not self.realtime_running:
            self.realtime_running = True
            self.realtime_timer.start(1000)  # 1초마다 업데이트
            self.realtime_start_btn.setEnabled(False)
            self.realtime_stop_btn.setEnabled(True)
        else:
            self.realtime_running = False
            self.realtime_timer.stop()
            self.realtime_start_btn.setEnabled(True)
            self.realtime_stop_btn.setEnabled(False)

    def fetch_and_store_ohlcv(self):
        import pandas as pd
        import sqlite3
        import python_bithumb
        from datetime import datetime, timedelta
        
        coin = self.data_coin_combo.currentText()
        start_date = self.data_start_date.text()
        end_date = self.data_end_date.text()
        db_path = 'ohlcv.db'
        conn = sqlite3.connect(db_path)
        
        # 거래소 선택 다이얼로그
        exchange_dlg = QDialog(self)
        exchange_dlg.setWindowTitle('거래소 선택')
        exchange_dlg.setGeometry(300, 200, 300, 200)
        layout = QVBoxLayout()
        
        # 거래소 선택 라디오 버튼
        bithumb_radio = QRadioButton('빗썸 (최근 200개)')
        upbit_radio = QRadioButton('업비트 (2017년 9월부터)')
        bithumb_radio.setChecked(True)
        layout.addWidget(bithumb_radio)
        layout.addWidget(upbit_radio)
        
        # 시간 단위 선택
        interval_group = QGroupBox("시간 단위")
        interval_layout = QVBoxLayout()
        day_radio = QRadioButton("일봉")
        minute1_radio = QRadioButton("1분봉")
        minute3_radio = QRadioButton("3분봉")
        minute5_radio = QRadioButton("5분봉")
        minute15_radio = QRadioButton("15분봉")
        day_radio.setChecked(True)
        interval_layout.addWidget(day_radio)
        interval_layout.addWidget(minute1_radio)
        interval_layout.addWidget(minute3_radio)
        interval_layout.addWidget(minute5_radio)
        interval_layout.addWidget(minute15_radio)
        interval_group.setLayout(interval_layout)
        layout.addWidget(interval_group)
        
        # 확인 버튼
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(btns)
        exchange_dlg.setLayout(layout)
        
        btns.accepted.connect(exchange_dlg.accept)
        btns.rejected.connect(exchange_dlg.reject)
        
        if exchange_dlg.exec_() != QDialog.Accepted:
            conn.close()
            return
            
        use_upbit = upbit_radio.isChecked()
        
        # 시간 단위 설정
        interval = "day"
        if minute1_radio.isChecked():
            interval = "minute1"
        elif minute3_radio.isChecked():
            interval = "minute3"
        elif minute5_radio.isChecked():
            interval = "minute5"
        elif minute15_radio.isChecked():
            interval = "minute15"
        
        if use_upbit:
            # 업비트 데이터 수집
            self.data_result.append(f"업비트에서 {coin} {interval} 데이터 수집 시작...")
            try:
                upbit_symbol = f"KRW-{coin}"
                
                # 시작일부터 종료일까지 데이터 수집
                df = pyupbit.get_ohlcv(upbit_symbol, 
                                     interval=interval,
                                     to=end_date,
                                     count=2000)
                
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        'open': 'open',
                        'high': 'high',
                        'low': 'low',
                        'close': 'close',
                        'volume': 'volume'
                    })
                    
                    df = df.loc[start_date:end_date]
                    df = df.reset_index()
                    table_name = f"{coin}_ohlcv_{interval}"
                    df.to_sql(table_name, conn, if_exists='replace', index=False)
                    
                    self.data_result.append(f"{coin} {interval} 데이터 {len(df)}개 저장 완료")
                    self.data_result.append(f"날짜 범위: {df['index'].min()} ~ {df['index'].max()}")
                    self.data_result.append(f"저장된 컬럼: {list(df.columns)}")
                    self.data_result.append(f"상위 3개:\n{df.head(3).to_string(index=False)}")
                    self.data_result.append(f"하위 3개:\n{df.tail(3).to_string(index=False)}")
                else:
                    self.data_result.append("업비트에서 데이터를 가져올 수 없습니다.")
                    
            except Exception as e:
                self.data_result.append(f"업비트 데이터 수집 중 오류 발생: {str(e)}")
                self.data_result.append(f"상세 오류: {traceback.format_exc()}")
                
        else:
            # 빗썸 데이터 수집
            self.data_result.append(f"빗썸에서 {coin} {interval} 데이터 수집 시작...")
            try:
                df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval=interval, count=200)
                
                if df is not None and not df.empty:
                    df = df.reset_index()
                    table_name = f"{coin}_ohlcv_{interval}"
                    df.to_sql(table_name, conn, if_exists='replace', index=False)
                    
                    self.data_result.append(f"{coin} {interval} 데이터 {len(df)}개 저장 완료")
                    self.data_result.append(f"날짜 범위: {df['index'].min()} ~ {df['index'].max()}")
                    self.data_result.append(f"저장된 컬럼: {list(df.columns)}")
                    self.data_result.append(f"상위 3개:\n{df.head(3).to_string(index=False)}")
                    self.data_result.append(f"하위 3개:\n{df.tail(3).to_string(index=False)}")
                else:
                    self.data_result.append("빗썸에서 데이터를 가져올 수 없습니다.")
                    
            except Exception as e:
                self.data_result.append(f"빗썸 데이터 수집 중 오류 발생: {str(e)}")
                self.data_result.append(f"상세 오류: {traceback.format_exc()}")
        
        conn.close()

    def update_simulation_status(self, message):
        self.sim_status.append(message)
        # 스크롤을 항상 최신 메시지로 이동
        self.sim_status.verticalScrollBar().setValue(
            self.sim_status.verticalScrollBar().maximum()
        )

    def update_param_groups(self, strategy):
        # 모든 파라미터 그룹 숨기기
        for group in self.param_groups.values():
            group.hide()
        
        # 선택된 전략의 파라미터 그룹만 표시
        if strategy in self.param_groups:
            self.param_groups[strategy].show()
        
        # RSI + 볼린저밴드 전략인 경우 두 그룹 모두 표시
        if strategy == 'RSI + 볼린저밴드':
            self.param_groups['RSI'].show()
            self.param_groups['볼린저밴드'].show()

    def update_sim_param_groups(self, strategy):
        # 모든 파라미터 그룹 숨기기
        for group in self.sim_param_groups.values():
            group.hide()
        
        # 선택된 전략의 파라미터 그룹만 표시
        if strategy in self.sim_param_groups:
            self.sim_param_groups[strategy].show()
        
        # RSI + 볼린저밴드 전략인 경우 두 그룹 모두 표시
        if strategy == 'RSI + 볼린저밴드':
            self.sim_param_groups['RSI'].show()
            self.sim_param_groups['볼린저밴드'].show()

    def update_trade_param_groups(self, strategy):
        # 모든 파라미터 그룹 숨기기
        for group in self.trade_param_groups.values():
            group.hide()
        
        # 선택된 전략의 파라미터 그룹만 표시
        if strategy in self.trade_param_groups:
            self.trade_param_groups[strategy].show()
        
        # RSI + 볼린저밴드 전략인 경우 두 그룹 모두 표시
        if strategy == 'RSI + 볼린저밴드':
            self.trade_param_groups['RSI'].show()
            self.trade_param_groups['볼린저밴드'].show()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BithumbTrader()
    ex.show()
    sys.exit(app.exec_())
