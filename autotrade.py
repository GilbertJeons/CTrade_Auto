import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5 import uic
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
import requests
import itertools
import matplotlib.gridspec as gridspec
import optuna
from strategies import StrategyFactory, BacktestEngine, OptunaOptimizer
import logging
import csv
from PyQt5.QtCore import QObject, QThread, pyqtSignal
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'

class AutoTradeWindow(QDialog):
    # 시그널 정의
    update_sim_status = pyqtSignal(str)
    show_sim_chart_signal = pyqtSignal(list, list, list, list)
    show_trade_log_signal = pyqtSignal(list)
    update_data_result = pyqtSignal(str)  # 데이터 수집 결과 업데이트를 위한 시그널 추가
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # 부모 윈도우 저장
        self.bithumb = python_bithumb.Bithumb(None, None)  # 테스트용 API 객체 생성
        self.is_connected = True  # 테스트를 위해 True로 설정
        
        self.setWindowTitle("자동매매 시스템")
        self.setGeometry(100, 100, 1200, 800)
        
        # UI 로드
        uic.loadUi('autotrade.ui', self)
        
        # 거래 상태 초기화
        self.trading_enabled = False
        
        # 차트 초기화
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)                
        
        # 시뮬레이션 관련 변수
        self.simulation_running = False
        self.simulation_thread = None
        self.simulation_stop_event = threading.Event()
        
        # 자동매매 관련 변수
        self.auto_trading_running = False
        self.auto_trading_thread = None
        self.auto_trading_stop_event = threading.Event()
        
        # 차트 관련 변수
        self.chart_window = None
        self.chart_update_timer = None
        self.realtime_chart_window = None
        
        # 데이터 수집 관련 변수
        self.data_collection_running = False
        self.data_collection_thread = None
        self.data_collection_stop_event = threading.Event()
        
        # API 연결 상태
        self.is_connected = False
        
        # 파라미터 그룹 설정
        self.setup_param_groups()
        self.setup_sim_param_groups()
        self.setup_trade_param_groups()
        
        # 시그널 연결
        self.setup_connections()
        self.update_sim_status.connect(self.simStatus.append)
        self.show_sim_chart_signal.connect(self.show_simulation_chart)
        self.show_trade_log_signal.connect(self.show_trade_log_dialog)
        self.update_data_result.connect(self.append_data_result)
        
        # 코인 리스트 초기화
        self.init_coin_list()
        
        # 실시간 데이터 저장용 변수
        self.realtime_price_data = []
        self.realtime_time_data = []
        self.realtime_volume_data = []
        self.realtime_ycenter = None  # 기준값 변수 추가

        # 전략 파라미터 그룹
        self.param_groups = {}
        self.sim_param_groups = {}
        self.trade_param_groups = {}
        
        # --- 전략 콤보박스 중복 방지 및 파라미터 그룹 초기 표시 ---
        # (AutoTradeWindow __init__ 내)
        strategies = [
            "RSI", "볼린저밴드", "MACD", "이동평균선 교차", "스토캐스틱",
            "ATR 기반 변동성 돌파", "거래량 프로파일", "머신러닝",
            "BB+RSI", "MACD+EMA"  # 새로운 전략 추가
        ]
        self.backtestStrategyCombo.clear()
        self.simStrategyCombo.clear()
        self.tradeStrategyCombo.clear()
        self.backtestStrategyCombo.addItems(strategies)
        self.simStrategyCombo.addItems(strategies)
        self.tradeStrategyCombo.addItems(strategies)

        # 전략 설명 라벨을 .ui에서 findChild로 연결
        self.strategyDescriptionLabel = self.findChild(QLabel, 'strategyDescriptionLabel')

        # 각 탭의 현재 선택된 전략에 맞는 파라미터 그룹을 표시 (초기화)
        self.update_backtest_param_groups_visibility(self.backtestStrategyCombo.currentText())
        self.update_sim_param_groups_visibility(self.simStrategyCombo.currentText())
        self.update_trade_param_groups_visibility(self.tradeStrategyCombo.currentText())
        
        # 날짜 입력란을 오늘 날짜로 초기화
        from PyQt5.QtCore import QDate
        today = QDate.currentDate()
        self.dataStartDate.setDate(today)
        self.dataEndDate.setDate(today)
        # 백테스팅 날짜 초기화
        # self.backtestStartDate.setDate(today.addDays(-30))  # 기본값: 30일 전
        self.backtestStartDate.setDate(today)  # 기본값: 30일 전
        self.backtestEndDate.setDate(today)
        
        # 초기 거래소 선택에 따라 날짜 입력란 상태 설정
        if self.exchangeCombo.currentText() == '빗썸':
            self.dataStartDate.setEnabled(False)
            self.dataEndDate.setEnabled(False)
            self.update_data_result.emit('빗썸은 날짜 범위 지정이 불가능합니다. 최신 200개만 저장됩니다.')
        else:
            self.dataStartDate.setEnabled(True)
            self.dataEndDate.setEnabled(True)
            self.update_data_result.emit('업비트는 날짜 범위 지정이 가능합니다.')
        
        # 시간 단위 콤보박스 항목 통일 및 추가
        interval_items = [
            "1분봉", "3분봉", "5분봉", "15분봉", "30분봉",
            "1시간봉", "4시간봉", "일봉", "주봉", "월봉"
        ]
        # 실시간 차트 새창 옵션
        if hasattr(self, 'interval_combo'):
            self.interval_combo.clear()
            self.interval_combo.addItems(interval_items)
        # 백테스팅 옵션
        if hasattr(self, 'backtestIntervalCombo'):
            self.backtestIntervalCombo.clear()
            self.backtestIntervalCombo.addItems(interval_items)
        # 메인 차트 등 다른 곳도 동일하게 적용 (예: self.mainIntervalCombo)
        if hasattr(self, 'mainIntervalCombo'):
            self.mainIntervalCombo.clear()
            self.mainIntervalCombo.addItems(interval_items)
        # 메인 차트(차트 조회 메뉴) 시간 간격 콤보박스 항목 추가
        if hasattr(self, 'spIntervalCombo'):
            sp_interval_items = [
                "1분", "3분", "5분", "15분", "30분", "60분", "240분", "일", "주", "월"
            ]
            self.spIntervalCombo.clear()
            self.spIntervalCombo.addItems(sp_interval_items)        
          
        # Optuna 최적화 버튼 연결
        self.optunaOptimizeBtn.clicked.connect(self.run_optuna_optimization)
        

    def init_coin_list(self):
        try:
            # 기본 코인 목록 설정
            default_coins = ['BTC', 'ETH', 'XRP', 'ADA', 'DOGE', 'SOL', 'DOT', 'AVAX', 'MATIC', 'LINK']
            
            # 콤보박스에 코인 목록 추가
            self.dataCoinCombo.addItems(default_coins)
            self.backtestCoinCombo.addItems(default_coins)
            self.simCoinCombo.addItems(default_coins)
            self.tradeCoinCombo.addItems(default_coins)
            
        except Exception as e:
            print(f"코인 목록 초기화 오류: {str(e)}")
            
    def setup_connections(self):
        # 데이터 수집/저장 탭
        self.dataFetchBtn.clicked.connect(self.fetch_and_store_ohlcv)
        # 거래소 콤보박스 변경 시 날짜 입력란 활성/비활성화
        self.exchangeCombo.currentTextChanged.connect(self.toggle_date_inputs_by_exchange)
        # 시간단위 콤보박스 값 변경 시 로그
        self.dataIntervalCombo.currentTextChanged.connect(self.on_interval_changed)
        # 백테스팅 탭
        self.backtestStartBtn.clicked.connect(self.start_backtest)
        self.backtestStrategyCombo.currentTextChanged.connect(lambda text: self.update_param_groups(text))
        self.backtestStrategyCombo.currentTextChanged.connect(self.update_strategy_description)
        # 시뮬레이션 탭
        self.simStartBtn.clicked.connect(self.toggle_simulation)
        self.simStrategyCombo.currentTextChanged.connect(lambda text: self.update_sim_param_groups(text))
        # 자동매매 탭
        self.tradeStartBtn.clicked.connect(self.toggle_auto_trading)
        self.tradeStrategyCombo.currentTextChanged.connect(lambda text: self.update_trade_param_groups(text))

    def on_interval_changed(self, value):
        print(f"[DEBUG] interval 콤보박스 값 변경: {value}")
        self.update_data_result.emit(f"[DEBUG] interval 콤보박스 값 변경: {value}")

    def toggle_date_inputs_by_exchange(self):
        exchange = self.exchangeCombo.currentText()
        print(f"[DEBUG] toggle_date_inputs_by_exchange 호출, exchange={exchange}")
        self.update_data_result.emit(f"[DEBUG] toggle_date_inputs_by_exchange 호출, exchange={exchange}")
        if exchange == '빗썸':
            self.dataStartDate.setEnabled(False)
            self.dataEndDate.setEnabled(False)
            self.update_data_result.emit('빗썸은 날짜 범위 지정이 불가능합니다. 최신 200개만 저장됩니다.')
        else:
            self.dataStartDate.setEnabled(True)
            self.dataEndDate.setEnabled(True)
            self.update_data_result.emit('업비트는 날짜 범위 지정이 가능합니다.')

    def get_table_name(self, coin, interval):
        """코인명과 봉단위로 테이블명 생성"""
        interval_db_map = {
            '1분봉': 'minute1', '3분봉': 'minute3', '5분봉': 'minute5', '15분봉': 'minute15', '30분봉': 'minute30',
            '1시간봉': 'hour1', '4시간봉': 'hour4', '일봉': 'day', '주봉': 'week', '월봉': 'month',
            '1m': 'minute1', '3m': 'minute3', '5m': 'minute5', '15m': 'minute15', '30m': 'minute30',
            '1h': 'hour1', '4h': 'hour4', '1d': 'day', '1w': 'week', '1M': 'month',
            'minute1': 'minute1', 'minute3': 'minute3', 'minute5': 'minute5', 'minute15': 'minute15', 'minute30': 'minute30',
            'minute60': 'hour1', 'minute240': 'hour4', 'day': 'day', 'week': 'week', 'month': 'month'
        }
        interval_db = interval_db_map.get(interval, 'minute1')
        return f"{coin}_ohlcv_{interval_db}"

    def fetch_and_store_ohlcv(self):
        try:
            exchange = self.exchangeCombo.currentText()
            coin = self.dataCoinCombo.currentText()
            interval = self.dataIntervalCombo.currentText()
            
            # 거래소별 interval 매핑
            bithumb_interval_map = {
                "1분봉": "minute1",
                "3분봉": "minute3",
                "5분봉": "minute5",
                "15분봉": "minute15",
                "30분봉": "minute30",
                "1시간봉": "minute60",
                "4시간봉": "minute240",
                "일봉": "day",
                "주봉": "week",
                "월봉": "month"
            }
            
            upbit_interval_map = {
                "1분봉": "minute1",
                "3분봉": "minute3",
                "5분봉": "minute5",
                "15분봉": "minute15",
                "30분봉": "minute30",
                "1시간봉": "minute60",
                "4시간봉": "minute240",
                "일봉": "day",
                "주봉": "week",
                "월봉": "month"
            }
            
            # 테이블 이름 생성
            table_name = self.get_table_name(coin, interval)
            
            # 날짜 범위 설정
            if exchange == "업비트":
                start_date = self.dataStartDate.date().toPyDate()
                end_date = self.dataEndDate.date().toPyDate()
                start_datetime = datetime.combine(start_date, datetime.min.time())
                end_datetime = datetime.combine(end_date, datetime.max.time())
            else:  # 빗썸
                start_datetime = None
                end_datetime = None
            
            # 데이터 수집 시작 메시지
            if exchange == "업비트":
                self.append_data_result(f"[시작] 거래소: {exchange}, 시간단위: {interval}, 코인: {coin}, 날짜: {start_datetime} ~ {end_datetime}")
            else:
                self.append_data_result(f"[시작] 거래소: {exchange}, 시간단위: {interval}, 코인: {coin}, 날짜: (날짜 지정 불가, 최신 200개만 저장)")
            
            # 거래소별 데이터 수집
            if exchange == "업비트":
                upbit_interval = upbit_interval_map[interval]
                max_retries = 3
                retry_delay = 1  # 초
                
                for attempt in range(max_retries):
                    try:
                        self.append_data_result(f"데이터 수집 시도 {attempt + 1}/{max_retries}...")
                        df = pyupbit.get_ohlcv_from(
                            ticker=f"KRW-{coin}",
                            interval=upbit_interval,
                            fromDatetime=start_datetime,
                            to=end_datetime,
                            period=0.1  # API 호출 간격
                        )
                        
                        if df is not None and not df.empty:
                            break
                        else:
                            if attempt < max_retries - 1:
                                self.append_data_result(f"데이터 수집 실패. {retry_delay}초 후 재시도...")
                                time.sleep(retry_delay)
                                retry_delay *= 2  # 지수 백오프
                            else:
                                self.append_data_result("[오류] 데이터 수집 실패")
                                return
                    except Exception as e:
                        if attempt < max_retries - 1:
                            self.append_data_result(f"오류 발생: {str(e)}. {retry_delay}초 후 재시도...")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            raise
            else:  # 빗썸
                bithumb_interval = bithumb_interval_map[interval]
                # python_bithumb 라이브러리 사용
                df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval=bithumb_interval, count=200)
                
                if df is None or df.empty:
                    self.append_data_result(f"[오류] 빗썸 데이터 조회 실패")
                    return
            
            if df is not None and not df.empty:
                # 데이터베이스 연결
                conn = sqlite3.connect('ohlcv.db')
                cursor = conn.cursor()
                
                # 테이블 생성
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        date TEXT PRIMARY KEY,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL
                    )
                ''')
                
                # 데이터 저장
                total_rows = len(df)
                self.append_data_result(f"총 {total_rows}개의 데이터 저장 시작...")
                
                for i, (index, row) in enumerate(df.iterrows(), 1):
                    timestamp = index.strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute(f'''
                        INSERT OR REPLACE INTO {table_name} (date, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (timestamp, row['open'], row['high'], row['low'], row['close'], row['volume']))
                    
                    # 진행률 표시 (10% 단위)
                    if i % max(1, total_rows // 10) == 0:
                        progress = (i / total_rows) * 100
                        self.append_data_result(f"저장 진행률: {progress:.1f}% ({i}/{total_rows})")
                
                conn.commit()
                conn.close()
                
                # 저장된 데이터 수와 기간 출력
                start_time = df.index[0].strftime('%Y-%m-%d %H:%M:%S')
                end_time = df.index[-1].strftime('%Y-%m-%d %H:%M:%S')
                self.append_data_result(f"[완료] {exchange} 데이터 저장: {len(df)}건, {start_time} ~ {end_time}")
                
                # 차트 표시
                self.show_data_chart(df, coin)
            else:
                self.append_data_result(f"[오류] {exchange} 데이터 조회 실패")
                
        except Exception as e:
            self.append_data_result(f"[오류] 데이터 수집 실패: {str(e)}")
            traceback.print_exc()

    def show_data_chart(self, df, coin):
        try:
            print("차트 생성 시작...")
            
            # 차트 창 생성
            chart_window = QDialog(self)
            chart_window.setWindowTitle(f'{coin} 데이터 차트')
            chart_window.setGeometry(200, 200, 1200, 800)
            
            layout = QVBoxLayout()
            
            # 차트 생성
            figure = Figure(figsize=(12, 8))
            canvas = FigureCanvas(figure)
            layout.addWidget(canvas)
            
            # 가격 차트
            ax1 = figure.add_subplot(211)
            ax1.plot(df.index, df['close'], 'b-', label='종가')
            ax1.set_title(f'{coin} 가격 차트')
            ax1.set_ylabel('가격')
            ax1.grid(True, alpha=0.3)
            
            # 거래량 차트
            ax2 = figure.add_subplot(212)
            ax2.bar(df.index, df['volume'], color='g', alpha=0.5, label='거래량')
            ax2.set_title('거래량 차트')
            ax2.set_xlabel('날짜')
            ax2.set_ylabel('거래량')
            ax2.grid(True, alpha=0.3)
            ax2.legend()

            # 차트를 UI에 추가
            figure.tight_layout()
            chart_window.setLayout(layout)
            chart_window.show()
            
            print("차트 생성 완료")
            
        except Exception as e:
            print(f"차트 표시 오류: {str(e)}")
            traceback.print_exc()
    
    def start_backtest(self):
        """백테스트 시작"""
        try:
            # 파라미터 가져오기
            strategy = self.backtestStrategyCombo.currentText()
            start_date = self.backtestStartDate.date().toPyDate()
            end_date = self.backtestEndDate.date().toPyDate()
            interval = self.backtestIntervalCombo.currentText()
            initial_capital = float(self.backtestInvestment.text())
            fee_rate = float(self.feeRateSpinBox.value()) / 100
            # 데이터 가져오기
            df = self.fetch_historical_data(start_date, end_date, interval)
            if df is None:
                QMessageBox.warning(self, "오류", "데이터를 가져올 수 없습니다.")
                return
            # 전략별 파라미터 준비
            params = {}
            if strategy == 'RSI':
                params = {
                    'period': self.rsiPeriod.value(),
                    'overbought': self.rsiOverbought.value(),
                    'oversold': self.rsiOversold.value()
                }
            elif strategy == '볼린저밴드':
                params = {
                    'period': self.bbPeriod.value(),
                    'std': self.bbStd.value()
                }
            elif strategy == 'MACD':
                params = {
                    'fast_period': self.macdFastPeriod.value(),
                    'slow_period': self.macdSlowPeriod.value(),
                    'signal_period': self.macdSignalPeriod.value()
                }
            elif strategy == '이동평균선 교차':
                params = {
                    'short_period': self.maShortPeriod.value(),
                    'long_period': self.maLongPeriod.value()
                }
            elif strategy == '스토캐스틱':
                params = {
                    'period': self.stochPeriod.value(),
                    'k_period': self.stochKPeriod.value(),
                    'd_period': self.stochDPeriod.value(),
                    'overbought': self.stochOverbought.value(),
                    'oversold': self.stochOversold.value()
                }
            elif strategy == 'ATR 기반 변동성 돌파':
                params = {
                    'period': self.atrPeriod.value(),
                    'multiplier': self.atrMultiplier.value(),
                    'trend_period': self.trendPeriod.value(),
                    'stop_loss_multiplier': self.stopLossMultiplier.value(),
                    'position_size_multiplier': self.positionSizeMultiplier.value()
                }
            elif strategy == '거래량 프로파일':
                params = {
                    'num_bins': self.numBins.value(),
                    'volume_threshold': self.volumeThreshold.value(),
                    'volume_zscore_threshold': self.volumeZscoreThreshold.value(),
                    'window_size': self.windowSize.value()
                }
            elif strategy == '머신러닝':
                params = {
                    'prediction_period': self.predictionPeriod.value(),
                    'training_period': self.trainingPeriod.value()
                }
            elif strategy == 'BB+RSI':
                params = {
                    'bb_period': self.bbRsiPeriod.value(),
                    'bb_std': self.bbRsiStd.value(),
                    'rsi_period': self.bbRsiRsiPeriod.value(),
                    'rsi_high': self.bbRsiHigh.value(),
                    'rsi_low': self.bbRsiLow.value()
                }
            elif strategy == 'MACD+EMA':
                params = {
                    'macd_fast': self.macdEmaFast.value(),
                    'macd_slow': self.macdEmaSlow.value(),
                    'macd_signal': self.macdEmaSignal.value(),
                    'ema_period': self.macdEmaEmaPeriod.value()
                }
            # 파라미터 저장 (최소 수정)
            self.last_backtest_params = params
            # 백테스트 엔진을 fee_rate와 함께 새로 생성
            engine = BacktestEngine(fee_rate=fee_rate)            
            results = engine.backtest_strategy(strategy, params, df, interval, initial_capital)
            if results is None:
                QMessageBox.warning(self, "오류", "백테스트 실행 중 오류가 발생했습니다.")
                return
            self.handle_backtest_results(df, results, initial_capital)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"백테스트 실행 중 오류가 발생했습니다: {str(e)}")
            traceback.print_exc()
    
    def setup_param_groups(self):
        """백테스팅 파라미터 그룹 설정"""
        # 파라미터 그룹 딕셔너리 초기화
        self.param_groups = {}

        # 수수료 그룹
        self.feeGroup = self.create_param_group("수수료 설정")
        self.feeRateSpinBox = QDoubleSpinBox()
        self.feeRateSpinBox.setRange(0.01, 20.0)
        self.feeRateSpinBox.setSingleStep(0.005)
        self.feeRateSpinBox.setDecimals(3)
        self.feeRateSpinBox.setValue(0.04)
        self.feeGroup.layout().addRow("수수료율(%):", self.feeRateSpinBox)
        self.backtestParamLayout.addWidget(self.feeGroup, 1, 0, 1, 2)
        self.param_groups['수수료 설정'] = self.feeGroup

        # RSI 파라미터 그룹
        self.rsiGroup = self.create_param_group('RSI')
        self.rsiPeriod = QSpinBox(); self.rsiPeriod.setRange(1, 100); self.rsiPeriod.setValue(14)
        self.rsiOverbought = QSpinBox(); self.rsiOverbought.setRange(50, 100); self.rsiOverbought.setValue(70)
        self.rsiOversold = QSpinBox(); self.rsiOversold.setRange(0, 50); self.rsiOversold.setValue(30)
        self.rsiGroup.layout().addRow("기간:", self.rsiPeriod)
        self.rsiGroup.layout().addRow("과매수:", self.rsiOverbought)
        self.rsiGroup.layout().addRow("과매도:", self.rsiOversold)
        self.rsiGroup.hide()
        self.backtestParamLayout.addWidget(self.rsiGroup, 2, 0, 1, 2)
        self.param_groups['RSI'] = self.rsiGroup

        # 볼린저밴드 파라미터 그룹
        self.bbGroup = self.create_param_group('볼린저밴드')
        self.bbPeriod = QSpinBox(); self.bbPeriod.setRange(1, 100); self.bbPeriod.setValue(20)
        self.bbStd = QDoubleSpinBox(); self.bbStd.setRange(0.1, 5.0); self.bbStd.setValue(2.0); self.bbStd.setSingleStep(0.1)
        self.bbGroup.layout().addRow("기간:", self.bbPeriod)
        self.bbGroup.layout().addRow("표준편차:", self.bbStd)
        self.bbGroup.hide()
        self.backtestParamLayout.addWidget(self.bbGroup, 3, 0, 1, 2)
        self.param_groups['볼린저밴드'] = self.bbGroup

        # MACD 파라미터 그룹
        self.macdGroup = self.create_param_group('MACD')
        self.macdFastPeriod = QSpinBox(); self.macdFastPeriod.setRange(1, 100); self.macdFastPeriod.setValue(12)
        self.macdSlowPeriod = QSpinBox(); self.macdSlowPeriod.setRange(1, 100); self.macdSlowPeriod.setValue(26)
        self.macdSignalPeriod = QSpinBox(); self.macdSignalPeriod.setRange(1, 100); self.macdSignalPeriod.setValue(9)
        self.macdGroup.layout().addRow("빠른 기간:", self.macdFastPeriod)
        self.macdGroup.layout().addRow("느린 기간:", self.macdSlowPeriod)
        self.macdGroup.layout().addRow("시그널 기간:", self.macdSignalPeriod)
        self.macdGroup.hide()
        self.backtestParamLayout.addWidget(self.macdGroup, 4, 0, 1, 2)
        self.param_groups['MACD'] = self.macdGroup

        # 이동평균선 파라미터 그룹
        self.maGroup = self.create_param_group('이동평균선 교차')
        self.maShortPeriod = QSpinBox(); self.maShortPeriod.setRange(1, 100); self.maShortPeriod.setValue(5)
        self.maLongPeriod = QSpinBox(); self.maLongPeriod.setRange(1, 200); self.maLongPeriod.setValue(20)
        self.maGroup.layout().addRow("단기 기간:", self.maShortPeriod)
        self.maGroup.layout().addRow("장기 기간:", self.maLongPeriod)
        self.maGroup.hide()
        self.backtestParamLayout.addWidget(self.maGroup, 5, 0, 1, 2)
        self.param_groups['이동평균선 교차'] = self.maGroup

        # 스토캐스틱 파라미터 그룹
        self.stochGroup = self.create_param_group('스토캐스틱')
        self.stochKPeriod = QSpinBox(); self.stochKPeriod.setRange(1, 100); self.stochKPeriod.setValue(14)
        self.stochDPeriod = QSpinBox(); self.stochDPeriod.setRange(1, 100); self.stochDPeriod.setValue(3)
        self.stochOverbought = QSpinBox();
        self.stochOversold = QSpinBox(); self.stochOversold.setRange(0, 50); self.stochOversold.setValue(20)
        self.stochGroup.layout().addRow("K 기간:", self.stochKPeriod)
        self.stochGroup.layout().addRow("D 기간:", self.stochDPeriod)
        self.stochGroup.layout().addRow("과매수:", self.stochOverbought)
        self.stochGroup.layout().addRow("과매도:", self.stochOversold)
        self.stochGroup.hide()
        self.backtestParamLayout.addWidget(self.stochGroup, 6, 0, 1, 2)
        self.param_groups['스토캐스틱'] = self.stochGroup

        # ATR 파라미터 그룹
        self.atrGroup = self.create_param_group('ATR 기반 변동성 돌파')
        self.atrPeriod = QSpinBox(); self.atrPeriod.setRange(1, 100); self.atrPeriod.setValue(14)
        self.atrMultiplier = QDoubleSpinBox(); self.atrMultiplier.setRange(0.1, 5.0); self.atrMultiplier.setValue(2.0); self.atrMultiplier.setSingleStep(0.1)
        self.trendPeriod = QSpinBox(); self.trendPeriod.setRange(1, 100); self.trendPeriod.setValue(20)
        self.stopLossMultiplier = QDoubleSpinBox(); self.stopLossMultiplier.setRange(0.1, 10.0); self.stopLossMultiplier.setValue(1.5); self.stopLossMultiplier.setSingleStep(0.1)
        self.positionSizeMultiplier = QDoubleSpinBox(); self.positionSizeMultiplier.setRange(0.1, 10.0); self.positionSizeMultiplier.setValue(1.0); self.positionSizeMultiplier.setSingleStep(0.1)
        self.atrGroup.layout().addRow("기간:", self.atrPeriod)
        self.atrGroup.layout().addRow("승수:", self.atrMultiplier)
        self.atrGroup.layout().addRow("추세 기간:", self.trendPeriod)
        self.atrGroup.layout().addRow("스탑로스 승수:", self.stopLossMultiplier)
        self.atrGroup.layout().addRow("포지션 사이징 승수:", self.positionSizeMultiplier)
        self.atrGroup.hide()
        self.backtestParamLayout.addWidget(self.atrGroup, 7, 0, 1, 2)
        self.param_groups['ATR 기반 변동성 돌파'] = self.atrGroup

        # 거래량 프로파일 파라미터 그룹
        self.volumeProfileGroup = self.create_param_group('거래량 프로파일')
        self.numBins = QSpinBox(); self.numBins.setRange(5, 50); self.numBins.setValue(10)
        self.volumeThreshold = QSpinBox(); self.volumeThreshold.setRange(100, 1000000); self.volumeThreshold.setValue(5000)
        self.volumeZscoreThreshold = QDoubleSpinBox(); self.volumeZscoreThreshold.setRange(0.5, 5.0); self.volumeZscoreThreshold.setValue(1.0); self.volumeZscoreThreshold.setSingleStep(0.1)
        self.windowSize = QSpinBox(); self.windowSize.setRange(10, 100); self.windowSize.setValue(20)
        self.volumeProfileGroup.layout().addRow("구간 개수:", self.numBins)
        self.volumeProfileGroup.layout().addRow("거래량 임계값:", self.volumeThreshold)
        self.volumeProfileGroup.layout().addRow("Z-Score 임계값:", self.volumeZscoreThreshold)
        self.volumeProfileGroup.layout().addRow("이동평균 윈도우:", self.windowSize)
        self.volumeProfileGroup.hide()
        self.backtestParamLayout.addWidget(self.volumeProfileGroup, 8, 0, 1, 2)
        self.param_groups['거래량 프로파일'] = self.volumeProfileGroup

        # 머신러닝 파라미터 그룹
        self.mlGroup = self.create_param_group('머신러닝')
        self.predictionPeriod = QSpinBox(); self.predictionPeriod.setRange(1, 30); self.predictionPeriod.setValue(5)
        self.trainingPeriod = QSpinBox(); self.trainingPeriod.setRange(10, 365); self.trainingPeriod.setValue(30)
        self.mlGroup.layout().addRow("예측 기간:", self.predictionPeriod)
        self.mlGroup.layout().addRow("학습 기간:", self.trainingPeriod)
        self.mlGroup.hide()
        self.backtestParamLayout.addWidget(self.mlGroup, 9, 0, 1, 2)
        self.param_groups['머신러닝'] = self.mlGroup

        # BB+RSI 파라미터 그룹
        self.bbRsiGroup = self.create_param_group('BB+RSI')
        self.bbRsiPeriod = QSpinBox(); self.bbRsiPeriod.setRange(5, 100); self.bbRsiPeriod.setValue(20)
        self.bbRsiStd = QDoubleSpinBox(); self.bbRsiStd.setRange(0.1, 5.0); self.bbRsiStd.setValue(2.0); self.bbRsiStd.setSingleStep(0.1)
        self.bbRsiRsiPeriod = QSpinBox(); self.bbRsiRsiPeriod.setRange(5, 50); self.bbRsiRsiPeriod.setValue(14)
        self.bbRsiHigh = QSpinBox(); self.bbRsiHigh.setRange(50, 90); self.bbRsiHigh.setValue(70)
        self.bbRsiLow = QSpinBox(); self.bbRsiLow.setRange(10, 50); self.bbRsiLow.setValue(30)
        self.bbRsiGroup.layout().addRow("BB 기간:", self.bbRsiPeriod)
        self.bbRsiGroup.layout().addRow("BB 표준편차:", self.bbRsiStd)
        self.bbRsiGroup.layout().addRow("RSI 기간:", self.bbRsiRsiPeriod)
        self.bbRsiGroup.layout().addRow("RSI 상단:", self.bbRsiHigh)
        self.bbRsiGroup.layout().addRow("RSI 하단:", self.bbRsiLow)
        self.bbRsiGroup.hide()
        self.backtestParamLayout.addWidget(self.bbRsiGroup, 9, 0, 1, 2)
        self.param_groups['BB+RSI'] = self.bbRsiGroup

        # MACD+EMA 파라미터 그룹
        self.macdEmaGroup = self.create_param_group('MACD+EMA')
        self.macdEmaFast = QSpinBox(); self.macdEmaFast.setRange(5, 50); self.macdEmaFast.setValue(12)
        self.macdEmaSlow = QSpinBox(); self.macdEmaSlow.setRange(10, 100); self.macdEmaSlow.setValue(26)
        self.macdEmaSignal = QSpinBox(); self.macdEmaSignal.setRange(5, 30); self.macdEmaSignal.setValue(9)
        self.macdEmaEmaPeriod = QSpinBox(); self.macdEmaEmaPeriod.setRange(5, 50); self.macdEmaEmaPeriod.setValue(20)
        self.macdEmaGroup.layout().addRow("MACD 단기:", self.macdEmaFast)
        self.macdEmaGroup.layout().addRow("MACD 장기:", self.macdEmaSlow)
        self.macdEmaGroup.layout().addRow("MACD 신호:", self.macdEmaSignal)
        self.macdEmaGroup.layout().addRow("EMA 기간:", self.macdEmaEmaPeriod)
        self.macdEmaGroup.hide()
        self.backtestParamLayout.addWidget(self.macdEmaGroup, 10, 0, 1, 2)
        self.param_groups['MACD+EMA'] = self.macdEmaGroup

    def setup_sim_param_groups(self):
        # 시뮬레이션 탭 전용 그룹만 생성 및 addWidget
        self.simFeeGroup = QGroupBox("수수료 설정")
        simFeeLayout = QHBoxLayout()
        self.simFeeLabel = QLabel("수수료율(%)")
        self.simFeeRateSpinBox = QDoubleSpinBox()
        self.simFeeRateSpinBox.setRange(0.01, 20.0)
        self.simFeeRateSpinBox.setSingleStep(0.005)
        self.simFeeRateSpinBox.setDecimals(3)
        self.simFeeRateSpinBox.setValue(0.04)
        self.simFeeRangeLabel = QLabel("(0.01% ~ 20%)")
        simFeeLayout.addWidget(self.simFeeLabel)
        simFeeLayout.addWidget(self.simFeeRateSpinBox)
        simFeeLayout.addWidget(self.simFeeRangeLabel)
        self.simFeeGroup.setLayout(simFeeLayout)
        self.simParamLayout.addWidget(self.simFeeGroup)

        self.simRsiGroup = self.create_param_group('RSI')
        self.simRsiPeriod = QSpinBox(); self.simRsiPeriod.setRange(1, 100); self.simRsiPeriod.setValue(14)
        self.simRsiOverbought = QSpinBox(); self.simRsiOverbought.setRange(50, 100); self.simRsiOverbought.setValue(70)
        self.simRsiOversold = QSpinBox(); self.simRsiOversold.setRange(0, 50); self.simRsiOversold.setValue(30)
        self.simRsiGroup.layout().addRow("기간:", self.simRsiPeriod)
        self.simRsiGroup.layout().addRow("과매수:", self.simRsiOverbought)
        self.simRsiGroup.layout().addRow("과매도:", self.simRsiOversold)
        self.simRsiGroup.hide()
        self.simParamLayout.addWidget(self.simRsiGroup)

        self.simBbGroup = self.create_param_group('볼린저밴드')
        self.simBbPeriod = QSpinBox(); self.simBbPeriod.setRange(1, 100); self.simBbPeriod.setValue(20)
        self.simBbStd = QDoubleSpinBox(); self.simBbStd.setRange(0.1, 5.0); self.simBbStd.setValue(2.0); self.simBbStd.setSingleStep(0.1)
        self.simBbGroup.layout().addRow("기간:", self.simBbPeriod)
        self.simBbGroup.layout().addRow("표준편차:", self.simBbStd)
        self.simBbGroup.hide()
        self.simParamLayout.addWidget(self.simBbGroup)

        self.simMacdGroup = self.create_param_group('MACD')
        self.simMacdFastPeriod = QSpinBox(); self.simMacdFastPeriod.setRange(1, 100); self.simMacdFastPeriod.setValue(12)
        self.simMacdSlowPeriod = QSpinBox(); self.simMacdSlowPeriod.setRange(1, 100); self.simMacdSlowPeriod.setValue(26)
        self.simMacdSignalPeriod = QSpinBox(); self.simMacdSignalPeriod.setRange(1, 100); self.simMacdSignalPeriod.setValue(9)
        self.simMacdGroup.layout().addRow("빠른 기간:", self.simMacdFastPeriod)
        self.simMacdGroup.layout().addRow("느린 기간:", self.simMacdSlowPeriod)
        self.simMacdGroup.layout().addRow("시그널 기간:", self.simMacdSignalPeriod)
        self.simMacdGroup.hide()
        self.simParamLayout.addWidget(self.simMacdGroup)

        self.simMaGroup = self.create_param_group('이동평균선')
        self.simMaShortPeriod = QSpinBox(); self.simMaShortPeriod.setRange(1, 100); self.simMaShortPeriod.setValue(5)
        self.simMaLongPeriod = QSpinBox(); self.simMaLongPeriod.setRange(1, 200); self.simMaLongPeriod.setValue(20)
        self.simMaGroup.layout().addRow("단기 기간:", self.simMaShortPeriod)
        self.simMaGroup.layout().addRow("장기 기간:", self.simMaLongPeriod)
        self.simMaGroup.hide()
        self.simParamLayout.addWidget(self.simMaGroup)

        self.simStochGroup = self.create_param_group('스토캐스틱')
        self.simStochPeriod = QSpinBox(); self.simStochPeriod.setRange(1, 100); self.simStochPeriod.setValue(14)
        self.simStochKPeriod = QSpinBox(); self.simStochKPeriod.setRange(1, 100); self.simStochKPeriod.setValue(3)
        self.simStochDPeriod = QSpinBox(); self.simStochDPeriod.setRange(1, 100); self.simStochDPeriod.setValue(3)
        self.simStochOverbought = QSpinBox(); self.simStochOverbought.setRange(50, 100); self.simStochOverbought.setValue(80)
        self.simStochOversold = QSpinBox(); self.simStochOversold.setRange(0, 50); self.simStochOversold.setValue(20)
        self.simStochGroup.layout().addRow("기간:", self.simStochPeriod)
        self.simStochGroup.layout().addRow("K 기간:", self.simStochKPeriod)
        self.simStochGroup.layout().addRow("D 기간:", self.simStochDPeriod)
        self.simStochGroup.layout().addRow("과매수:", self.simStochOverbought)
        self.simStochGroup.layout().addRow("과매도:", self.simStochOversold)
        self.simStochGroup.hide()
        self.simParamLayout.addWidget(self.simStochGroup)

        self.simAtrGroup = self.create_param_group('ATR')
        self.simAtrPeriod = QSpinBox(); self.simAtrPeriod.setRange(1, 100); self.simAtrPeriod.setValue(14)
        self.simAtrMultiplier = QDoubleSpinBox(); self.simAtrMultiplier.setRange(0.1, 5.0); self.simAtrMultiplier.setValue(2.0); self.simAtrMultiplier.setSingleStep(0.1)
        self.simAtrGroup.layout().addRow("기간:", self.simAtrPeriod)
        self.simAtrGroup.layout().addRow("승수:", self.simAtrMultiplier)
        self.simAtrGroup.hide()
        self.simParamLayout.addWidget(self.simAtrGroup)

        # ATR 기반 변동성 돌파 추가 파라미터
        self.simTrendPeriod = QSpinBox(); self.simTrendPeriod.setRange(1, 100); self.simTrendPeriod.setValue(14)
        self.simStopLossMultiplier = QDoubleSpinBox(); self.simStopLossMultiplier.setRange(0.1, 10.0); self.simStopLossMultiplier.setValue(2.0); self.simStopLossMultiplier.setSingleStep(0.1)
        self.simPositionSizeMultiplier = QDoubleSpinBox(); self.simPositionSizeMultiplier.setRange(0.1, 10.0); self.simPositionSizeMultiplier.setValue(1.0); self.simPositionSizeMultiplier.setSingleStep(0.1)
        self.simAtrGroup.layout().addRow("추세 기간:", self.simTrendPeriod)
        self.simAtrGroup.layout().addRow("스탑로스 승수:", self.simStopLossMultiplier)
        self.simAtrGroup.layout().addRow("포지션 크기 승수:", self.simPositionSizeMultiplier)

        # 거래량 프로파일 파라미터
        self.simVolumeProfileGroup = self.create_param_group('거래량 프로파일')
        self.simNumBins = QSpinBox(); self.simNumBins.setRange(1, 100); self.simNumBins.setValue(10)
        self.simVolumeThreshold = QSpinBox(); self.simVolumeThreshold.setRange(1, 1000000); self.simVolumeThreshold.setValue(10000)
        self.simVolumeZscoreThreshold = QDoubleSpinBox(); self.simVolumeZscoreThreshold.setRange(0.0, 10.0); self.simVolumeZscoreThreshold.setValue(2.0); self.simVolumeZscoreThreshold.setSingleStep(0.1)
        self.simWindowSize = QSpinBox(); self.simWindowSize.setRange(1, 1000); self.simWindowSize.setValue(100)
        self.simVolumeProfileGroup.layout().addRow("빈 개수:", self.simNumBins)
        self.simVolumeProfileGroup.layout().addRow("거래량 임계값:", self.simVolumeThreshold)
        self.simVolumeProfileGroup.layout().addRow("Z-score 임계값:", self.simVolumeZscoreThreshold)
        self.simVolumeProfileGroup.layout().addRow("윈도우 크기:", self.simWindowSize)
        self.simVolumeProfileGroup.hide()
        self.simParamLayout.addWidget(self.simVolumeProfileGroup)

        # 머신러닝 파라미터
        self.simMLGroup = self.create_param_group('머신러닝')
        self.simPredictionPeriod = QSpinBox(); self.simPredictionPeriod.setRange(1, 100); self.simPredictionPeriod.setValue(5)
        self.simTrainingPeriod = QSpinBox(); self.simTrainingPeriod.setRange(1, 1000); self.simTrainingPeriod.setValue(100)
        self.simMLGroup.layout().addRow("예측 기간:", self.simPredictionPeriod)
        self.simMLGroup.layout().addRow("학습 기간:", self.simTrainingPeriod)
        self.simMLGroup.hide()
        self.simParamLayout.addWidget(self.simMLGroup)

        # BB+RSI 파라미터 그룹
        self.simBbRsiGroup = self.create_param_group('BB+RSI')
        self.simBbRsiPeriod = QSpinBox(); self.simBbRsiPeriod.setRange(5, 100); self.simBbRsiPeriod.setValue(20)
        self.simBbRsiStd = QDoubleSpinBox(); self.simBbRsiStd.setRange(0.1, 5.0); self.simBbRsiStd.setValue(2.0); self.simBbRsiStd.setSingleStep(0.1)
        self.simBbRsiRsiPeriod = QSpinBox(); self.simBbRsiRsiPeriod.setRange(5, 50); self.simBbRsiRsiPeriod.setValue(14)
        self.simBbRsiHigh = QSpinBox(); self.simBbRsiHigh.setRange(50, 90); self.simBbRsiHigh.setValue(70)
        self.simBbRsiLow = QSpinBox(); self.simBbRsiLow.setRange(10, 50); self.simBbRsiLow.setValue(30)
        self.simBbRsiGroup.layout().addRow("BB 기간:", self.simBbRsiPeriod)
        self.simBbRsiGroup.layout().addRow("BB 표준편차:", self.simBbRsiStd)
        self.simBbRsiGroup.layout().addRow("RSI 기간:", self.simBbRsiRsiPeriod)
        self.simBbRsiGroup.layout().addRow("RSI 상단:", self.simBbRsiHigh)
        self.simBbRsiGroup.layout().addRow("RSI 하단:", self.simBbRsiLow)
        self.simBbRsiGroup.hide()
        self.simParamLayout.addWidget(self.simBbRsiGroup)

        # MACD+EMA 파라미터 그룹
        self.simMacdEmaGroup = self.create_param_group('MACD+EMA')
        self.simMacdEmaFast = QSpinBox(); self.simMacdEmaFast.setRange(5, 50); self.simMacdEmaFast.setValue(12)
        self.simMacdEmaSlow = QSpinBox(); self.simMacdEmaSlow.setRange(10, 100); self.simMacdEmaSlow.setValue(26)
        self.simMacdEmaSignal = QSpinBox(); self.simMacdEmaSignal.setRange(5, 30); self.simMacdEmaSignal.setValue(9)
        self.simMacdEmaEmaPeriod = QSpinBox(); self.simMacdEmaEmaPeriod.setRange(5, 50); self.simMacdEmaEmaPeriod.setValue(20)
        self.simMacdEmaGroup.layout().addRow("MACD 단기:", self.simMacdEmaFast)
        self.simMacdEmaGroup.layout().addRow("MACD 장기:", self.simMacdEmaSlow)
        self.simMacdEmaGroup.layout().addRow("MACD 신호:", self.simMacdEmaSignal)
        self.simMacdEmaGroup.layout().addRow("EMA 기간:", self.simMacdEmaEmaPeriod)
        self.simMacdEmaGroup.hide()
        self.simParamLayout.addWidget(self.simMacdEmaGroup)

    def setup_trade_param_groups(self):
        # 자동매매 탭 전용 그룹만 생성 및 addWidget
        self.tradeFeeGroup = QGroupBox("수수료 설정")
        tradeFeeLayout = QHBoxLayout()
        self.tradeFeeLabel = QLabel("수수료율(%)")
        self.tradeFeeRateSpinBox = QDoubleSpinBox()
        self.tradeFeeRateSpinBox.setRange(0.01, 20.0)
        self.tradeFeeRateSpinBox.setSingleStep(0.005)
        self.tradeFeeRateSpinBox.setDecimals(3)
        self.tradeFeeRateSpinBox.setValue(0.04)
        self.tradeFeeRangeLabel = QLabel("(0.01% ~ 20%)")
        tradeFeeLayout.addWidget(self.tradeFeeLabel)
        tradeFeeLayout.addWidget(self.tradeFeeRateSpinBox)
        tradeFeeLayout.addWidget(self.tradeFeeRangeLabel)
        self.tradeFeeGroup.setLayout(tradeFeeLayout)
        self.tradeParamLayout.addWidget(self.tradeFeeGroup)

        self.tradeRsiGroup = self.create_param_group('RSI')
        self.tradeRsiPeriod = QSpinBox(); self.tradeRsiPeriod.setRange(1, 100); self.tradeRsiPeriod.setValue(14)
        self.tradeRsiOverbought = QSpinBox(); self.tradeRsiOverbought.setRange(50, 100); self.tradeRsiOverbought.setValue(70)
        self.tradeRsiOversold = QSpinBox(); self.tradeRsiOversold.setRange(0, 50); self.tradeRsiOversold.setValue(30)
        self.tradeRsiGroup.layout().addRow("기간:", self.tradeRsiPeriod)
        self.tradeRsiGroup.layout().addRow("과매수:", self.tradeRsiOverbought)
        self.tradeRsiGroup.layout().addRow("과매도:", self.tradeRsiOversold)
        self.tradeRsiGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeRsiGroup)

        self.tradeBbGroup = self.create_param_group('볼린저밴드')
        self.tradeBbPeriod = QSpinBox(); self.tradeBbPeriod.setRange(1, 100); self.tradeBbPeriod.setValue(20)
        self.tradeBbStd = QDoubleSpinBox(); self.tradeBbStd.setRange(0.1, 5.0); self.tradeBbStd.setValue(2.0); self.tradeBbStd.setSingleStep(0.1)
        self.tradeBbGroup.layout().addRow("기간:", self.tradeBbPeriod)
        self.tradeBbGroup.layout().addRow("표준편차:", self.tradeBbStd)
        self.tradeBbGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeBbGroup)

        self.tradeMacdGroup = self.create_param_group('MACD')
        self.tradeMacdFastPeriod = QSpinBox(); self.tradeMacdFastPeriod.setRange(1, 100); self.tradeMacdFastPeriod.setValue(12)
        self.tradeMacdSlowPeriod = QSpinBox(); self.tradeMacdSlowPeriod.setRange(1, 100); self.tradeMacdSlowPeriod.setValue(26)
        self.tradeMacdSignalPeriod = QSpinBox(); self.tradeMacdSignalPeriod.setRange(1, 100); self.tradeMacdSignalPeriod.setValue(9)
        self.tradeMacdGroup.layout().addRow("빠른 기간:", self.tradeMacdFastPeriod)
        self.tradeMacdGroup.layout().addRow("느린 기간:", self.tradeMacdSlowPeriod)
        self.tradeMacdGroup.layout().addRow("시그널 기간:", self.tradeMacdSignalPeriod)
        self.tradeMacdGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeMacdGroup)

        self.tradeMaGroup = self.create_param_group('이동평균선')
        self.tradeMaShortPeriod = QSpinBox(); self.tradeMaShortPeriod.setRange(1, 100); self.tradeMaShortPeriod.setValue(5)
        self.tradeMaLongPeriod = QSpinBox(); self.tradeMaLongPeriod.setRange(1, 200); self.tradeMaLongPeriod.setValue(20)
        self.tradeMaGroup.layout().addRow("단기 기간:", self.tradeMaShortPeriod)
        self.tradeMaGroup.layout().addRow("장기 기간:", self.tradeMaLongPeriod)
        self.tradeMaGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeMaGroup)

        self.tradeStochGroup = self.create_param_group('스토캐스틱')
        self.tradeStochPeriod = QSpinBox(); self.tradeStochPeriod.setRange(1, 100); self.tradeStochPeriod.setValue(14)
        self.tradeStochKPeriod = QSpinBox(); self.tradeStochKPeriod.setRange(1, 100); self.tradeStochKPeriod.setValue(3)
        self.tradeStochDPeriod = QSpinBox(); self.tradeStochDPeriod.setRange(1, 100); self.tradeStochDPeriod.setValue(3)
        self.tradeStochOverbought = QSpinBox(); self.tradeStochOverbought.setRange(50, 100); self.tradeStochOverbought.setValue(80)
        self.tradeStochOversold = QSpinBox(); self.tradeStochOversold.setRange(0, 50); self.tradeStochOversold.setValue(20)
        self.tradeStochGroup.layout().addRow("기간:", self.tradeStochPeriod)
        self.tradeStochGroup.layout().addRow("K 기간:", self.tradeStochKPeriod)
        self.tradeStochGroup.layout().addRow("D 기간:", self.tradeStochDPeriod)
        self.tradeStochGroup.layout().addRow("과매수:", self.tradeStochOverbought)
        self.tradeStochGroup.layout().addRow("과매도:", self.tradeStochOversold)
        self.tradeStochGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeStochGroup)

        self.tradeAtrGroup = self.create_param_group('ATR')
        self.tradeAtrPeriod = QSpinBox(); self.tradeAtrPeriod.setRange(1, 100); self.tradeAtrPeriod.setValue(14)
        self.tradeAtrMultiplier = QDoubleSpinBox(); self.tradeAtrMultiplier.setRange(0.1, 5.0); self.tradeAtrMultiplier.setValue(2.0); self.tradeAtrMultiplier.setSingleStep(0.1)
        self.tradeAtrGroup.layout().addRow("기간:", self.tradeAtrPeriod)
        self.tradeAtrGroup.layout().addRow("승수:", self.tradeAtrMultiplier)
        self.tradeAtrGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeAtrGroup)

        # ATR 기반 변동성 돌파 추가 파라미터
        self.tradeTrendPeriod = QSpinBox(); self.tradeTrendPeriod.setRange(1, 100); self.tradeTrendPeriod.setValue(14)
        self.tradeStopLossMultiplier = QDoubleSpinBox(); self.tradeStopLossMultiplier.setRange(0.1, 10.0); self.tradeStopLossMultiplier.setValue(2.0); self.tradeStopLossMultiplier.setSingleStep(0.1)
        self.tradePositionSizeMultiplier = QDoubleSpinBox(); self.tradePositionSizeMultiplier.setRange(0.1, 10.0); self.tradePositionSizeMultiplier.setValue(1.0); self.tradePositionSizeMultiplier.setSingleStep(0.1)
        self.tradeAtrGroup.layout().addRow("추세 기간:", self.tradeTrendPeriod)
        self.tradeAtrGroup.layout().addRow("스탑로스 승수:", self.tradeStopLossMultiplier)
        self.tradeAtrGroup.layout().addRow("포지션 크기 승수:", self.tradePositionSizeMultiplier)

        # 거래량 프로파일 파라미터
        self.tradeVolumeProfileGroup = self.create_param_group('거래량 프로파일')
        self.tradeNumBins = QSpinBox(); self.tradeNumBins.setRange(1, 100); self.tradeNumBins.setValue(10)
        self.tradeVolumeThreshold = QSpinBox(); self.tradeVolumeThreshold.setRange(1, 1000000); self.tradeVolumeThreshold.setValue(10000)
        self.tradeVolumeZscoreThreshold = QDoubleSpinBox(); self.tradeVolumeZscoreThreshold.setRange(0.0, 10.0); self.tradeVolumeZscoreThreshold.setValue(2.0); self.tradeVolumeZscoreThreshold.setSingleStep(0.1)
        self.tradeWindowSize = QSpinBox(); self.tradeWindowSize.setRange(1, 1000); self.tradeWindowSize.setValue(100)
        self.tradeVolumeProfileGroup.layout().addRow("빈 개수:", self.tradeNumBins)
        self.tradeVolumeProfileGroup.layout().addRow("거래량 임계값:", self.tradeVolumeThreshold)
        self.tradeVolumeProfileGroup.layout().addRow("Z-score 임계값:", self.tradeVolumeZscoreThreshold)
        self.tradeVolumeProfileGroup.layout().addRow("윈도우 크기:", self.tradeWindowSize)
        self.tradeVolumeProfileGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeVolumeProfileGroup)

        # 머신러닝 파라미터
        self.tradeMLGroup = self.create_param_group('머신러닝')
        self.tradePredictionPeriod = QSpinBox(); self.tradePredictionPeriod.setRange(1, 100); self.tradePredictionPeriod.setValue(5)
        self.tradeTrainingPeriod = QSpinBox(); self.tradeTrainingPeriod.setRange(1, 1000); self.tradeTrainingPeriod.setValue(100)
        self.tradeMLGroup.layout().addRow("예측 기간:", self.tradePredictionPeriod)
        self.tradeMLGroup.layout().addRow("학습 기간:", self.tradeTrainingPeriod)
        self.tradeMLGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeMLGroup)

        # BB+RSI 파라미터 그룹
        self.tradeBbRsiGroup = self.create_param_group('BB+RSI')
        self.tradeBbRsiPeriod = QSpinBox(); self.tradeBbRsiPeriod.setRange(5, 100); self.tradeBbRsiPeriod.setValue(20)
        self.tradeBbRsiStd = QDoubleSpinBox(); self.tradeBbRsiStd.setRange(0.1, 5.0); self.tradeBbRsiStd.setValue(2.0); self.tradeBbRsiStd.setSingleStep(0.1)
        self.tradeBbRsiRsiPeriod = QSpinBox(); self.tradeBbRsiRsiPeriod.setRange(5, 50); self.tradeBbRsiRsiPeriod.setValue(14)
        self.tradeBbRsiHigh = QSpinBox(); self.tradeBbRsiHigh.setRange(50, 90); self.tradeBbRsiHigh.setValue(70)
        self.tradeBbRsiLow = QSpinBox(); self.tradeBbRsiLow.setRange(10, 50); self.tradeBbRsiLow.setValue(30)
        self.tradeBbRsiGroup.layout().addRow("BB 기간:", self.tradeBbRsiPeriod)
        self.tradeBbRsiGroup.layout().addRow("BB 표준편차:", self.tradeBbRsiStd)
        self.tradeBbRsiGroup.layout().addRow("RSI 기간:", self.tradeBbRsiRsiPeriod)
        self.tradeBbRsiGroup.layout().addRow("RSI 상단:", self.tradeBbRsiHigh)
        self.tradeBbRsiGroup.layout().addRow("RSI 하단:", self.tradeBbRsiLow)
        self.tradeBbRsiGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeBbRsiGroup)

        # MACD+EMA 파라미터 그룹
        self.tradeMacdEmaGroup = self.create_param_group('MACD+EMA')
        self.tradeMacdEmaFast = QSpinBox(); self.tradeMacdEmaFast.setRange(5, 50); self.tradeMacdEmaFast.setValue(12)
        self.tradeMacdEmaSlow = QSpinBox(); self.tradeMacdEmaSlow.setRange(10, 100); self.tradeMacdEmaSlow.setValue(26)
        self.tradeMacdEmaSignal = QSpinBox(); self.tradeMacdEmaSignal.setRange(5, 30); self.tradeMacdEmaSignal.setValue(9)
        self.tradeMacdEmaEmaPeriod = QSpinBox(); self.tradeMacdEmaEmaPeriod.setRange(5, 50); self.tradeMacdEmaEmaPeriod.setValue(20)
        self.tradeMacdEmaGroup.layout().addRow("MACD 단기:", self.tradeMacdEmaFast)
        self.tradeMacdEmaGroup.layout().addRow("MACD 장기:", self.tradeMacdEmaSlow)
        self.tradeMacdEmaGroup.layout().addRow("MACD 신호:", self.tradeMacdEmaSignal)
        self.tradeMacdEmaGroup.layout().addRow("EMA 기간:", self.tradeMacdEmaEmaPeriod)
        self.tradeMacdEmaGroup.hide()
        self.tradeParamLayout.addWidget(self.tradeMacdEmaGroup)

    def create_param_group(self, name=''):
        """파라미터 그룹 생성"""
        group = QGroupBox(name)
        group.setLayout(QFormLayout())
        return group

    def toggle_simulation(self):
        if not self.parent.is_connected:
            QMessageBox.warning(self, "경고", "API 연결이 필요합니다.")
            return
            
        self.trading_enabled = not self.trading_enabled
        if self.trading_enabled:
            self.simStartBtn.setText("시뮬레이션 중지")
            self.start_simulation()
        else:
            self.simStartBtn.setText("시뮬레이션 시작")
            self.stop_simulation()
            
    def toggle_auto_trading(self):
        if not self.parent.is_connected:
            QMessageBox.warning(self, "경고", "API 연결이 필요합니다.")
            return
            
        self.trading_enabled = not self.trading_enabled
        if self.trading_enabled:
            self.tradeStartBtn.setText("자동매매 중지")
            self.start_auto_trading()
        else:
            self.tradeStartBtn.setText("자동매매 시작")
            self.stop_auto_trading()
            
    def start_simulation(self):
        """시뮬레이션 시작"""
        try:
            self.simStatus.append("시뮬레이션 시작 시도...")
            
            # 필요한 파라미터 수집
            strategy = self.simStrategyCombo.currentText()
            coin = self.simCoinCombo.currentText()
            initial_capital = float(self.simInvestment.value())
            fee_rate = float(self.simFeeRateSpinBox.value()) / 100
            
            print(f"[DEBUG-SIM-1] 기본 파라미터 수집: {strategy}, {coin}, {initial_capital}")
            
            # 전략별 파라미터 수집
            params = {}
            if strategy == 'RSI':
                params = {
                    'period': self.simRsiPeriod.value(),
                    'overbought': self.simRsiOverbought.value(),
                    'oversold': self.simRsiOversold.value()
                }
            elif strategy == '볼린저밴드':
                params = {
                    'period': self.simBbPeriod.value(),
                    'std': self.simBbStd.value()
                }
            elif strategy == 'MACD':
                params = {
                    'fast_period': self.simMacdFastPeriod.value(),
                    'slow_period': self.simMacdSlowPeriod.value(),
                    'signal_period': self.simMacdSignalPeriod.value()
                }
            elif strategy == '이동평균선 교차':
                params = {
                    'short_period': self.simMaShortPeriod.value(),
                    'long_period': self.simMaLongPeriod.value()
                }
            elif strategy == '스토캐스틱':
                params = {
                    'period': self.simStochPeriod.value(),
                    'k_period': self.simStochKPeriod.value(),
                    'd_period': self.simStochDPeriod.value(),
                    'overbought': self.simStochOverbought.value(),
                    'oversold': self.simStochOversold.value()
                }
            elif strategy == 'ATR 기반 변동성 돌파':
                params = {
                    'period': self.simAtrPeriod.value(),
                    'multiplier': self.simAtrMultiplier.value(),
                    'trend_period': self.simTrendPeriod.value(),
                    'stop_loss_multiplier': self.simStopLossMultiplier.value(),
                    'position_size_multiplier': self.simPositionSizeMultiplier.value()
                }
            elif strategy == '거래량 프로파일':
                params = {
                    'num_bins': self.simNumBins.value(),
                    'volume_threshold': self.simVolumeThreshold.value(),
                    'volume_zscore_threshold': self.simVolumeZscoreThreshold.value(),
                    'window_size': self.simWindowSize.value()
                }
            elif strategy == 'BB+RSI':
                params = {
                    'bb_period': self.simBbRsiPeriod.value(),
                    'bb_std': self.simBbRsiStd.value(),
                    'rsi_period': self.simBbRsiRsiPeriod.value(),
                    'rsi_high': self.simBbRsiHigh.value(),
                    'rsi_low': self.simBbRsiLow.value()
                }
            elif strategy == 'MACD+EMA':
                params = {
                    'macd_fast': self.simMacdEmaFast.value(),
                    'macd_slow': self.simMacdEmaSlow.value(),
                    'macd_signal': self.simMacdEmaSignal.value(),
                    'ema_period': self.simMacdEmaEmaPeriod.value()
                }
            
            # 기존 워커가 있다면 정리
            if hasattr(self, 'simulation_worker') and self.simulation_worker:
                self.simulation_worker.stop_simulation()
                self.simulation_worker.deleteLater()
            
            # 새 워커 생성 및 시작
            self.simulation_worker = AutoTradeWorker(self)
            self.simulation_worker.update_status_signal.connect(self.simStatus.append)
            self.simulation_worker.show_data_chart_signal.connect(self.show_simulation_chart)
            
            # 빈 차트 생성을 위해 시그널 발생
            self.simulation_worker.show_data_chart_signal.emit([], [], [], [])
            
            # 시뮬레이션 시작
            self.simulation_worker.run_simulation(strategy, coin, params, initial_capital, fee_rate)
            
            # UI 업데이트
            self.simStartBtn.setText("시뮬레이션 중지")
            self.simStatus.append("시뮬레이션이 시작되었습니다.")
            
        except Exception as e:
            self.simStatus.append(f"시뮬레이션 시작 실패: {str(e)}")
            traceback.print_exc()

    def show_simulation_chart(self, price_history, trade_history, balance_history, volume_history=None):
        """시뮬레이션 차트 표시"""
        try:
            # 차트 창이 없을 때만 새로 생성
            if not hasattr(self, 'sim_chart_window') or self.sim_chart_window is None:
                self.sim_chart_window = QDialog(self)
                self.sim_chart_window.setWindowTitle('시뮬레이션 결과 차트')
                self.sim_chart_window.setGeometry(100, 100, 1200, 800)
                
                # 차트 생성
                self.fig = Figure(figsize=(12, 8))
                self.gs = gridspec.GridSpec(3, 1, height_ratios=[2, 1, 1], hspace=0.4)
                
                # 차트를 UI에 추가
                self.canvas = FigureCanvas(self.fig)
                layout = QVBoxLayout()
                layout.addWidget(self.canvas)
                self.sim_chart_window.setLayout(layout)
                self.sim_chart_window.show()
            
            # 기존 서브플롯 제거
            self.fig.clear()
            
            # 가격 차트
            ax1 = self.fig.add_subplot(self.gs[0])
            ax1.plot([t[0] for t in price_history], [t[1] for t in price_history], 'b-', label='가격')
            
            # 매수/매도 포인트를 위한 변수
            buy_scatter = None
            sell_scatter = None
            
            if trade_history:
                for t in trade_history:
                    if t['type'] == 'buy':
                        buy_scatter = ax1.scatter(t['time'], t['price'], color='r', marker='^', s=100)
                    elif t['type'] == 'sell':
                        sell_scatter = ax1.scatter(t['time'], t['price'], color='g', marker='v', s=100)
            
            # 범례 설정
            legend_elements = [Line2D([0], [0], color='b', label='가격')]
            if buy_scatter:
                legend_elements.append(Line2D([0], [0], color='r', marker='^', linestyle='None', label='매수'))
            if sell_scatter:
                legend_elements.append(Line2D([0], [0], color='g', marker='v', linestyle='None', label='매도'))
            
            ax1.legend(handles=legend_elements)
            ax1.set_title('가격 및 거래', pad=0)
            ax1.set_xlabel('시간')
            ax1.set_ylabel('가격')
            ax1.grid(True)
            ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: format(int(x), ',')))
            
            # 거래량 차트
            ax2 = self.fig.add_subplot(self.gs[1], sharex=ax1)
            if volume_history is not None and len(volume_history) > 0:
                times = [t[0] for t in volume_history]
                volumes = [float(t[1]) for t in volume_history]
                print(f"[DEBUG-VOLUME] 시간: {times[-1]}, 거래량: {volumes[-1]}")  # 가장 최근 거래량 출력
                ax2.scatter(times, volumes, color='limegreen', s=15, alpha=0.5, label='거래량')
                ax2.legend()
                
                # 거래량 y축 범위 설정
                if volumes:
                    max_volume = max(volumes)
                    print(f"[DEBUG-VOLUME] 최대 거래량: {max_volume}")  # 최대 거래량 출력
                    if max_volume > 0:
                        # y축 범위를 0부터 최대값의 120%로 설정
                        ax2.set_ylim(0, max_volume * 1.2)
                        # 적절한 간격으로 눈금 설정 (5개 정도의 눈금)
                        ax2.yaxis.set_major_locator(ticker.MaxNLocator(5))
                    else:
                        ax2.set_ylim(0, 1)
            else:
                ax2.text(0.5, 0.5, '거래량 데이터 없음', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('거래량', pad=0)
            ax2.set_ylabel('거래량')
            ax2.grid(True, alpha=0.3)
            ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: format(int(x), ',')))
            
            # 자본금 차트
            ax3 = self.fig.add_subplot(self.gs[2], sharex=ax1)
            ax3.plot([t[0] for t in balance_history], [t[1] for t in balance_history], 'g-', label='자본금')
            ax3.set_title('자본금 변화', pad=0)
            ax3.set_xlabel('시간')
            ax3.set_ylabel('자본금')
            ax3.grid(True)
            ax3.legend()
            ax3.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: format(int(x), ',')))
            
            # 차트 업데이트
            self.canvas.draw()
            
        except Exception as e:
            print(f"차트 생성 중 오류 발생: {str(e)}")
            traceback.print_exc()
    
    def stop_simulation(self):
        """시뮬레이션 중지"""
        try:
            self.simStatus.append("시뮬레이션 중지 시도...")
            
            if hasattr(self, 'simulation_worker') and self.simulation_worker:
                self.simulation_worker.stop_simulation()
                self.simulation_worker.deleteLater()
                self.simulation_worker = None
                
            self.simStartBtn.setText("시뮬레이션 시작")
            self.simStatus.append("시뮬레이션이 중지되었습니다.")
            
        except Exception as e:
            self.simStatus.append(f"시뮬레이션 중지 실패: {str(e)}")
            traceback.print_exc()

    def start_auto_trading(self):
        """자동매매 시작"""
        try:
            print("[DEBUG-1] 자동매매 시작 시도")
            
            # 필요한 파라미터 수집
            strategy = self.tradeStrategyCombo.currentText()
            coin = self.tradeCoinCombo.currentText()
            initial_capital = float(self.tradeInvestment.value())
            fee_rate = float(self.tradeFeeRateSpinBox.value()) / 100
            
            print(f"[DEBUG-4] 기본 파라미터 수집: {strategy}, {coin}, {initial_capital}")
            
            # 전략별 파라미터 수집
            params = {}
            if strategy == 'RSI':
                params = {
                    'period': self.tradeRsiPeriod.value(),
                    'overbought': self.tradeRsiOverbought.value(),
                    'oversold': self.tradeRsiOversold.value()
                }
            elif strategy == '볼린저밴드':
                params = {
                    'period': self.tradeBbPeriod.value(),
                    'std': self.tradeBbStd.value()
                }
            elif strategy == 'MACD':
                params = {
                    'fast_period': self.tradeMacdFastPeriod.value(),
                    'slow_period': self.tradeMacdSlowPeriod.value(),
                    'signal_period': self.tradeMacdSignalPeriod.value()
                }
            elif strategy == '이동평균선 교차':
                params = {
                    'short_period': self.tradeMaShortPeriod.value(),
                    'long_period': self.tradeMaLongPeriod.value()
                }
            elif strategy == '스토캐스틱':
                params = {
                    'k_period': self.tradeStochKPeriod.value(),
                    'd_period': self.tradeStochDPeriod.value(),
                    'overbought': self.tradeStochOverbought.value(),
                    'oversold': self.tradeStochOversold.value()
                }
            elif strategy == 'ATR 기반 변동성 돌파':
                params = {
                    'period': self.tradeAtrPeriod.value(),
                    'multiplier': self.tradeAtrMultiplier.value(),
                    'trend_period': self.tradeTrendPeriod.value(),
                    'stop_loss_multiplier': self.tradeStopLossMultiplier.value(),
                    'position_size_multiplier': self.tradePositionSizeMultiplier.value()
                }
            elif strategy == '거래량 프로파일':
                params = {
                    'num_bins': self.tradeNumBins.value(),
                    'volume_threshold': self.tradeVolumeThreshold.value(),
                    'volume_zscore_threshold': self.tradeVolumeZscoreThreshold.value(),
                    'window_size': self.tradeWindowSize.value()
                }
            elif strategy == 'BB+RSI':
                params = {
                    'bb_period': self.tradeBbRsiPeriod.value(),
                    'bb_std': self.tradeBbRsiStd.value(),
                    'rsi_period': self.tradeBbRsiRsiPeriod.value(),
                    'rsi_high': self.tradeBbRsiHigh.value(),
                    'rsi_low': self.tradeBbRsiLow.value()
                }
            elif strategy == 'MACD+EMA':
                params = {
                    'macd_fast': self.tradeMacdEmaFast.value(),
                    'macd_slow': self.tradeMacdEmaSlow.value(),
                    'macd_signal': self.tradeMacdEmaSignal.value(),
                    'ema_period': self.tradeMacdEmaEmaPeriod.value()
                }
            
            # 기존 워커가 있다면 정리
            if hasattr(self, 'trading_worker') and self.trading_worker:
                self.trading_worker.stop_auto_trading()
                self.trading_worker.deleteLater()
            
            # 새 워커 생성 및 시작
            self.trading_worker = AutoTradeWorker(self)
            self.trading_worker.update_status_signal.connect(self.tradeStatus.append)
            self.trading_worker.show_data_chart_signal.connect(self.show_simulation_chart)  # show_simulation_chart로 연결
            
            # 빈 차트 생성을 위해 시그널 발생
            self.trading_worker.show_data_chart_signal.emit([], [], [], [])
            
            # 자동매매 시작
            self.trading_worker.run_auto_trading(strategy, coin, params, initial_capital, fee_rate)
            
            # UI 업데이트
            self.tradeStartBtn.setText("자동매매 중지")
            self.tradeStatus.append("자동매매가 시작되었습니다.")
            
        except Exception as e:
            self.tradeStatus.append(f"자동매매 시작 실패: {str(e)}")
            traceback.print_exc()

    def stop_auto_trading(self):
        """자동매매 중지"""
        try:
            self.tradeStatus.append("자동매매 중지 시도...")
            
            if hasattr(self, 'trading_worker') and self.trading_worker:
                self.trading_worker.stop_auto_trading()
                self.trading_worker.deleteLater()
                self.trading_worker = None
                
            self.tradeStartBtn.setText("자동매매 시작")
            self.tradeStatus.append("자동매매가 중지되었습니다.")
            
        except Exception as e:
            self.tradeStatus.append(f"자동매매 중지 실패: {str(e)}")
            traceback.print_exc()

    def plot_backtest_results(self, df, trades, final_capital, daily_balance):
        try:
            chart_window = QDialog(self)
            chart_window.setWindowTitle("백테스팅 결과 차트")
            chart_window.setGeometry(100, 100, 1200, 800)
            layout = QVBoxLayout()
            fig = Figure(figsize=(12, 8))
            canvas = FigureCanvas(fig)
            layout.addWidget(canvas)
            gs = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1])
            ax1 = fig.add_subplot(gs[0])
            ax2 = fig.add_subplot(gs[1], sharex=ax1)
            ax3 = fig.add_subplot(gs[2], sharex=ax1)

            # 가격 차트
            ax1.plot(df.index, df['close'], label='가격', color='blue', alpha=0.5)
            for trade in trades:
                buy_date = pd.to_datetime(trade['date'])
                ax1.scatter(buy_date, trade['price'], color='red', marker='^', s=100, label='매수')
                if 'exit_date' in trade and 'exit_price' in trade:
                    sell_date = pd.to_datetime(trade['exit_date'])
                    ax1.scatter(sell_date, trade['exit_price'], color='green', marker='v', s=100, label='매도')
            handles, labels = ax1.get_legend_handles_labels()
            by_label = dict(zip(labels, handles))
            ax1.legend(by_label.values(), by_label.keys())
            ax1.xaxis_date()
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            fig.autofmt_xdate()
            ax1.set_title('가격 및 매매 시점')
            ax1.set_ylabel('가격')
            ax1.grid(True)

            # 자본금 변화 그래프
            has_balance = False
            if isinstance(daily_balance, list):
                try:
                    daily_balance_df = pd.DataFrame(daily_balance)
                    if 'date' in daily_balance_df.columns and 'balance' in daily_balance_df.columns and not daily_balance_df.empty:
                        daily_balance_df['date'] = pd.to_datetime(daily_balance_df['date'])
                        daily_balance_df.set_index('date', inplace=True)
                        ax2.plot(daily_balance_df.index, daily_balance_df['balance'], label='자본금', color='purple')
                        has_balance = True
                except Exception:
                    pass
            elif hasattr(daily_balance, 'index') and hasattr(daily_balance, 'values') and len(daily_balance) > 0:
                ax2.plot(daily_balance.index, daily_balance.values, label='자본금', color='purple')
                has_balance = True
            if has_balance:
                ax2.legend()
            else:
                ax2.text(0.5, 0.5, '자본금 데이터 없음', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('자본금 변화')
            ax2.set_xlabel('날짜')
            ax2.set_ylabel('자본금')
            ax2.grid(True)

            # 거래량 차트 (점으로 표시)
            if 'volume' in df.columns:
                ax3.scatter(df.index, df['volume'], color='limegreen', s=15, label='거래량')
                ax3.set_ylabel('거래량')
                ax3.set_xlabel('날짜')
                ax3.grid(True, alpha=0.3)
                ax3.legend()
            else:
                ax3.text(0.5, 0.5, '거래량 데이터 없음', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('거래량')

            fig.tight_layout()
            chart_window.setLayout(layout)
            chart_window.show()
        except Exception as e:
            print(f"백테스팅 결과 차트 표시 오류: {str(e)}")
            traceback.print_exc()

    def show_trade_log_dialog(self, trades):
        try:
            # 거래 내역을 표로 보여주는 팝업
            dialog = QDialog(self)
            dialog.setWindowTitle("거래 내역")
            dialog.setGeometry(100, 100, 800, 400)
        
            # 테이블 위젯 생성
            table = QTableWidget()
            table.setColumnCount(6)
            table.setHorizontalHeaderLabels(['진입 시간', '진입 가격', '퇴출 시간', '퇴출 가격', '수익금', '수익률'])
        
            # 데이터 채우기
            table.setRowCount(len(trades))
            for i, trade in enumerate(trades):
                table.setItem(i, 0, QTableWidgetItem(str(trade['date'])))
                table.setItem(i, 1, QTableWidgetItem(f"{trade['price']:,.0f}"))
                table.setItem(i, 2, QTableWidgetItem(str(trade['exit_date'])))
                table.setItem(i, 3, QTableWidgetItem(f"{trade['exit_price']:,.0f}"))
                table.setItem(i, 4, QTableWidgetItem(f"{trade['profit']:,.0f}"))
                table.setItem(i, 5, QTableWidgetItem(f"{trade['profit_rate']:.2f}%"))
            
                # 컬럼 너비 자동 조정
            table.resizeColumnsToContents()
            
            # 레이아웃 설정
            layout = QVBoxLayout()
            layout.addWidget(table)
            dialog.setLayout(layout)
            
            # 다이얼로그 표시 (비모달)
            dialog.show()
            
        except Exception as e:
            print(f"거래 내역 표시 오류: {str(e)}")
            traceback.print_exc()

    def append_data_result(self, message):
        """데이터 수집 결과를 UI에 안전하게 추가하는 슬롯"""
        self.dataResult.append(message)
        # 스크롤을 항상 최신 메시지로 이동
        self.dataResult.verticalScrollBar().setValue(
            self.dataResult.verticalScrollBar().maximum()
        )    
    
    # --- 파라미터 그룹 표시/숨김 함수 분리 ---
    def update_backtest_param_groups_visibility(self, strategy):
        # 모든 파라미터 그룹 리스트
        all_groups = [
            self.rsiGroup, self.bbGroup, self.macdGroup, self.maGroup,
            self.stochGroup, self.atrGroup, self.volumeProfileGroup, self.mlGroup,
            self.bbRsiGroup, self.macdEmaGroup
        ]
            
        # 현재 레이아웃에서 모든 그룹 제거 (빈 공간 방지)
        for group in all_groups:
            group.hide()
            
        # 선택된 전략에 맞는 그룹만 다시 레이아웃에 추가
        group_to_show = None
        if strategy == "RSI":
            group_to_show = self.rsiGroup
        elif strategy == "볼린저밴드":
            group_to_show = self.bbGroup
        elif strategy == "MACD":
            group_to_show = self.macdGroup
        elif strategy == "이동평균선 교차":
            group_to_show = self.maGroup
        elif strategy == "스토캐스틱":
            group_to_show = self.stochGroup
        elif strategy == "ATR 기반 변동성 돌파":
            group_to_show = self.atrGroup
        elif strategy == "거래량 프로파일" and hasattr(self, 'volumeProfileGroup'):
            group_to_show = self.volumeProfileGroup
        elif strategy == "머신러닝" and hasattr(self, 'mlGroup'):
            group_to_show = self.mlGroup
        elif strategy == "BB+RSI":
            group_to_show = self.bbRsiGroup
        elif strategy == "MACD+EMA":
            group_to_show = self.macdEmaGroup
            
        if group_to_show is not None:
            group_to_show.show()
            self.backtestParamLayout.addWidget(group_to_show, 2, 0, 1, 2)  # 수수료 그룹 아래에 배치

    def update_sim_param_groups_visibility(self, strategy):
        # 모든 파라미터 그룹 리스트
        all_groups = [
            self.simRsiGroup, self.simBbGroup, self.simMacdGroup, self.simMaGroup,
            self.simStochGroup, self.simAtrGroup, self.simVolumeProfileGroup, self.simMLGroup,
            self.simBbRsiGroup, self.simMacdEmaGroup
        ]
        
        # 현재 레이아웃에서 모든 그룹 제거 (빈 공간 방지)
        for group in all_groups:
            group.hide()
            
        # 선택된 전략에 맞는 그룹만 다시 레이아웃에 추가
        group_to_show = None
        if strategy == "RSI":
            group_to_show = self.simRsiGroup
        elif strategy == "볼린저밴드":
            group_to_show = self.simBbGroup
        elif strategy == "MACD":
            group_to_show = self.simMacdGroup
        elif strategy == "이동평균선 교차":
            group_to_show = self.simMaGroup
        elif strategy == "스토캐스틱":
            group_to_show = self.simStochGroup
        elif strategy == "ATR 기반 변동성 돌파":
            group_to_show = self.simAtrGroup
        elif strategy == "거래량 프로파일" and hasattr(self, 'simVolumeProfileGroup'):
            group_to_show = self.simVolumeProfileGroup
        elif strategy == "머신러닝" and hasattr(self, 'simMLGroup'):
            group_to_show = self.simMLGroup
        elif strategy == "BB+RSI":
            group_to_show = self.simBbRsiGroup
        elif strategy == "MACD+EMA":
            group_to_show = self.simMacdEmaGroup
            
        if group_to_show is not None:
            group_to_show.show()
            self.simParamLayout.addWidget(group_to_show)

    def update_trade_param_groups_visibility(self, strategy):
        # 모든 파라미터 그룹 리스트
        all_groups = [
            self.tradeRsiGroup, self.tradeBbGroup, self.tradeMacdGroup, self.tradeMaGroup,
            self.tradeStochGroup, self.tradeAtrGroup, self.tradeVolumeProfileGroup, self.tradeMLGroup,
            self.tradeBbRsiGroup, self.tradeMacdEmaGroup
        ]
        
        # 현재 레이아웃에서 모든 그룹 제거 (빈 공간 방지)
        for group in all_groups:
            group.hide()
            
        # 선택된 전략에 맞는 그룹만 다시 레이아웃에 추가
        group_to_show = None
        if strategy == "RSI":
            group_to_show = self.tradeRsiGroup
        elif strategy == "볼린저밴드":
            group_to_show = self.tradeBbGroup
        elif strategy == "MACD":
            group_to_show = self.tradeMacdGroup
        elif strategy == "이동평균선 교차":
            group_to_show = self.tradeMaGroup
        elif strategy == "스토캐스틱":
            group_to_show = self.tradeStochGroup
        elif strategy == "ATR 기반 변동성 돌파":
            group_to_show = self.tradeAtrGroup
        elif strategy == "거래량 프로파일" and hasattr(self, 'tradeVolumeProfileGroup'):
            group_to_show = self.tradeVolumeProfileGroup
        elif strategy == "머신러닝" and hasattr(self, 'tradeMLGroup'):
            group_to_show = self.tradeMLGroup
        elif strategy == "BB+RSI":
            group_to_show = self.tradeBbRsiGroup
        elif strategy == "MACD+EMA":
            group_to_show = self.tradeMacdEmaGroup
            
        if group_to_show is not None:
            group_to_show.show()
            self.tradeParamLayout.addWidget(group_to_show)

    # --- 콤보박스 변경 시 연결 함수도 분리 ---
    def update_param_groups(self, strategy):
        self.update_backtest_param_groups_visibility(strategy)

    def update_sim_param_groups(self, strategy):
        self.update_sim_param_groups_visibility(strategy)

    def update_trade_param_groups(self, strategy):
        self.update_trade_param_groups_visibility(strategy)
  
    def handle_backtest_results(self, df, results, initial_capital):
        """백테스트 결과 처리 및 로그 파일 저장"""
        try:
            import csv, os, json
            from datetime import datetime
            # 이전 결과 지우기
            self.backtestStatus.clear()
            
            # 기본 정보 표시
            self.backtestStatus.append(f"=== 백테스팅 결과 요약 ===")
            self.backtestStatus.append(f"테스트 기간: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
            self.backtestStatus.append(f"초기 자본금: {initial_capital:,.0f}원")
            self.backtestStatus.append(f"최종 자본금: {results['final_capital']:,.0f}원")
            self.backtestStatus.append(f"총 수익금: {results['final_capital'] - initial_capital:,.0f}원")
            self.backtestStatus.append(f"총 수익률: {results['profit_rate']:.2f}%")
            self.backtestStatus.append(f"총 거래 횟수: {results['total_trades']}회")
            self.backtestStatus.append(f"승률: {results['win_rate']:.2f}%")
            
            # 수수료 정보 표시
            self.backtestStatus.append(f"\n=== 수수료 분석 ===")
            self.backtestStatus.append(f"총 수수료: {results['total_fees']:,.0f}원")
            self.backtestStatus.append(f"수수료 비율: {results['fee_rate']:.2f}%")
            self.backtestStatus.append(f"수수료 제외 순수익: {results['net_profit']:,.0f}원")
            self.backtestStatus.append(f"수수료 제외 순수익률: {results['net_profit_rate']:.2f}%")
            
            # 성과 지표 표시
            self.backtestStatus.append(f"\n=== 성과 지표 ===")
            self.backtestStatus.append(f"연간화 변동성: {results.get('volatility', 0):.2f}%")
            self.backtestStatus.append(f"샤프 비율: {results.get('sharpe_ratio', 0):.2f}")
            self.backtestStatus.append(f"최대 낙폭 (MDD): {results.get('mdd', 0):.2f}%")
            
            # 거래 상세 분석 표시
            self.backtestStatus.append(f"\n=== 거래 상세 분석 ===")
            self.backtestStatus.append(f"평균 수익 거래: {results['avg_win']:,.0f}원")
            self.backtestStatus.append(f"평균 손실 거래: {results['avg_loss']:,.0f}원")
            self.backtestStatus.append(f"손익비: {abs(results['avg_win'] / results['avg_loss']):.2f}" if results['avg_loss'] != 0 else "손익비: N/A")
            self.backtestStatus.append(f"수익 팩터: {results['profit_factor']:.2f}")
            self.backtestStatus.append(f"최대 연속 수익: {results['max_consecutive_wins']}회")
            self.backtestStatus.append(f"최대 연속 손실: {results['max_consecutive_losses']}회")
            
            # 차트 표시 (plot_backtest_results로 변경)
            self.plot_backtest_results(df, results['trades'], results['final_capital'], results['daily_balance'])
            
            # 거래 로그 표시
            self.show_trade_log_signal.emit(results['trades'])

            # ===== 결과를 backtest_results_log.csv에 저장 =====
            log_path = 'backtest_results_log.csv'
            file_exists = os.path.isfile(log_path)
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            strategy_name = self.backtestStrategyCombo.currentText() if hasattr(self, 'backtestStrategyCombo') else ''
            # 파라미터를 항상 실제 값으로 저장
            params = getattr(self, 'last_backtest_params', {})
            params_str = json.dumps(params, ensure_ascii=False)
            coin = self.backtestCoinCombo.currentText() if hasattr(self, 'backtestCoinCombo') else ''
            interval = self.backtestIntervalCombo.currentText() if hasattr(self, 'backtestIntervalCombo') else ''
            first_candle = df.index[0].strftime('%Y-%m-%d %H:%M:%S') if len(df) > 0 else ''
            last_candle = df.index[-1].strftime('%Y-%m-%d %H:%M:%S') if len(df) > 0 else ''
            start_date = df.index[0].strftime('%Y-%m-%d') if len(df) > 0 else ''
            end_date = df.index[-1].strftime('%Y-%m-%d') if len(df) > 0 else ''
            row = [
                now,
                strategy_name,
                params_str,
                initial_capital,
                results['final_capital'],
                results['profit_rate'],
                results['win_rate'],
                results['total_trades'],
                start_date,
                end_date,
                first_candle,
                last_candle,
                interval,
                coin
            ]
            header = [
                '실행시각','전략명','파라미터','초기자본','최종자본','수익률','승률','거래수',
                '시작일','종료일','첫캔들','마지막캔들','인터벌','코인'
            ]
            with open(log_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(header)
                writer.writerow(row)
        except Exception as e:
            self.backtestStatus.append(f"결과 처리 중 오류 발생: {str(e)}")
            traceback.print_exc()

    def run_optuna_optimization(self):
        """Optuna를 사용한 전략 최적화 실행"""
        try:
            import time
            strategy_name = self.backtestStrategyCombo.currentText()
            strategy = StrategyFactory.create_strategy(strategy_name)
            
            if strategy is None:
                QMessageBox.warning(self, "경고", "전략을 선택해주세요.")
                return
                
            df = self.fetch_historical_data(
                self.backtestStartDate.date().toPyDate(),
                self.backtestEndDate.date().toPyDate(),
                self.backtestIntervalCombo.currentText()
            )
            
            if df is None or len(df) < 30:
                QMessageBox.warning(self, "경고", "충분한 데이터가 없습니다.")
                return
            
            # 최적화 시작 메시지
            self.backtestStatus.clear()
            self.backtestStatus.append("=== Optuna 최적화 시작 ===")
            self.backtestStatus.append(f"전략: {strategy_name}")
            self.backtestStatus.append(f"테스트 기간: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
            self.backtestStatus.append(f"데이터 포인트 수: {len(df)}개")
            self.backtestStatus.append(f"최적화 시도 횟수: 100회")
            self.backtestStatus.append("\n최적화 진행 중...")
            
            start_time = time.time()
            fee_rate = float(self.feeRateSpinBox.value()) / 100
            optimizer = OptunaOptimizer(strategy, strategy_name, df, 100, fee_rate=fee_rate)
            result = optimizer.optimize()
            elapsed = time.time() - start_time
            
            if result is None:
                QMessageBox.warning(self, "경고", "최적화 실행 중 오류가 발생했습니다.")
                return
            
            best_params = result['best_params']
            best_value = result['best_value']
            study = result['study']
            n_trials = len([t for t in study.trials if t.state.name == 'COMPLETE'])
            
            # 최적화 결과 상세 표시 (로그창)
            self.backtestStatus.append("\n=== Optuna 최적화 결과 ===")
            self.backtestStatus.append(f"최적 파라미터: {best_params}")
            self.backtestStatus.append(f"최적 목적함수 값: {best_value:.4f}")
            self.backtestStatus.append(f"최적화 시도 횟수: {n_trials}회")
            self.backtestStatus.append(f"최적화 소요 시간: {int(elapsed//60):02d}:{int(elapsed%60):02d}")
            
            # 중요 참고 정보
            # 최적 파라미터로 백테스트 결과도 요약해서 보여주기
            backtest_result = None
            try:
                engine = BacktestEngine(fee_rate=fee_rate)
                backtest_result = engine.backtest_strategy(
                    strategy_name, best_params, df, self.backtestIntervalCombo.currentText(), 1000000)
            except Exception as e:
                backtest_result = None
            if backtest_result:
                self.backtestStatus.append("\n[최적 파라미터 백테스트 요약]")
                self.backtestStatus.append(f"수익률: {backtest_result['profit_rate']:.2f}% | 거래수: {backtest_result['total_trades']}회 | 승률: {backtest_result['win_rate']:.2f}%")
                if backtest_result['total_trades'] < 5:
                    self.backtestStatus.append("[경고] 거래 횟수가 너무 적습니다. 과최적화 가능성!")
                if backtest_result['profit_rate'] < 0:
                    self.backtestStatus.append("[경고] 수익률이 음수입니다. 실제 적용에 주의!")
            
            self.backtestStatus.append("\n(파라미터는 직접 입력란에 복사해 사용하세요)")
            
            # 자동 백테스트 실행 제거 (자동 실행 X)
            # self.start_backtest()  # 기존 자동 실행 부분 주석 처리
        except Exception as e:
            QMessageBox.critical(self, "오류", f"최적화 실행 중 오류가 발생했습니다: {str(e)}")
            self.backtestStatus.append(f"\n오류 발생: {str(e)}")
            traceback.print_exc()

    def fetch_historical_data(self, start_date, end_date, interval):
        """히스토리컬 데이터 가져오기"""
        try:
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            coin = self.backtestCoinCombo.currentText()
            table_name = self.get_table_name(coin, interval)
            # 날짜 포맷 맞추기
            start_date_str = datetime.combine(start_date, datetime.min.time()).strftime('%Y-%m-%d %H:%M:%S')
            end_date_str = datetime.combine(end_date, datetime.max.time()).strftime('%Y-%m-%d %H:%M:%S')
            query = f"""
                SELECT date, open, high, low, close, volume
                FROM {table_name}
                WHERE date BETWEEN ? AND ?
                ORDER BY date
            """
            print(f"쿼리 테이블: {table_name}, 기간: {start_date_str} ~ {end_date_str}")
            cursor.execute(query, (start_date_str, end_date_str))
            rows = cursor.fetchall()
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df
        except Exception as e:
            QMessageBox.critical(self, "오류", f"데이터 조회 중 오류가 발생했습니다: {str(e)}")
            return None
        finally:
            if 'conn' in locals():
                conn.close()

    def update_strategy_description(self, strategy):
        descriptions = {
            'RSI': 'RSI(상대강도지수) 전략: 최근 일정 기간의 상승/하락 강도를 비교해 과매수(매도), 과매도(매수) 신호를 포착합니다.',
            '볼린저밴드': '볼린저밴드 전략: 가격이 이동평균선 기준 상단/하단 밴드를 돌파할 때 반전 신호로 진입/청산합니다.',
            'MACD': 'MACD 전략: 두 이동평균선의 차이와 신호선의 교차(골든/데드크로스)로 매수/매도 신호를 포착합니다.',
            '이동평균선 교차': '이동평균선 교차 전략: 단기선이 장기선을 위로 돌파(골든크로스)하면 매수, 아래로 하락(데드크로스)하면 매도합니다.',
            '스토캐스틱': '스토캐스틱 전략: 최근 고가/저가 대비 현재 가격 위치로 과매수/과매도 구간을 판단해 진입/청산합니다.',
            'ATR 기반 변동성 돌파': 'ATR 변동성 돌파 전략: 최근 변동성(ATR)만큼 가격이 돌파하면 진입/청산하는 추세 추종 전략입니다.',
            '거래량 프로파일': '거래량 프로파일 전략: 가격대별 거래량 분포를 분석해 거래량이 집중된 구간에서 반등/반락을 노립니다.',
            '머신러닝': '머신러닝 전략: 과거 데이터(가격, 거래량, 지표 등)를 학습해 상승/하락 확률을 예측하여 매매합니다.'
        }
        desc = descriptions.get(strategy, '전략 설명이 없습니다.')
        if self.strategyDescriptionLabel:
            self.strategyDescriptionLabel.setText(desc)
        print(f'[DEBUG] 전략 설명 라벨 업데이트: {strategy} → {desc}')  
    
class AutoTradeWorker(QObject):
    # 시그널 정의
    show_data_chart_signal = pyqtSignal(list, list, list, list)  # price_history, trade_history, balance_history, volume_history
    update_status_signal = pyqtSignal(str)  # 상태 메시지 업데이트용 시그널
    
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.bithumb = parent.bithumb if parent else None
        self.is_connected = True  # 테스트를 위해 True로 설정
        self.trading_enabled = False
        
        # QTimer 초기화
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.trading_loop)
        
        # 트레이딩 상태 변수들
        self.balance = 0
        self.position = 0
        self.last_signal = None
        self.price_history = []
        self.trade_history = []
        self.balance_history = []
        self.volume_history = []
        self.strategy = None
        self.coin = None
        self.params = None
        self.initial_capital = 0
        self.fee_rate = 0
        self.min_candle = 30
        
        # 시뮬레이션 관련 변수 추가
        self.simulation_enabled = False
        self.simulation_timer = QTimer(self)
        self.simulation_timer.timeout.connect(self.simulation_loop)

    def run_simulation(self, strategy, coin, params, initial_capital, fee_rate):
        """시뮬레이션 실행"""
        try:
            print("[DEBUG-SIM-1] 시뮬레이션 시작")
            
            # 초기 설정
            self.strategy = strategy
            self.coin = coin
            self.params = params
            self.initial_capital = initial_capital
            self.fee_rate = fee_rate
            self.balance = initial_capital
            self.position = 0
            self.last_signal = None
            self.price_history = []
            self.trade_history = []
            self.balance_history = []
            self.volume_history = []
            
            # 전략별로 필요한 최소 캔들 개수 계산
            self.min_candle = self.calculate_min_candles()
            print(f"[DEBUG-SIM-2] 전략: {strategy}, 코인: {coin}, 필요 캔들 수: {self.min_candle}")
            print(f"[DEBUG-SIM-3] 타이머 시작 시도")
            
            # 타이머 시작 (1초 간격)
            self.simulation_enabled = True
            self.simulation_timer.start(1000)  # 1000ms = 1초
            print("[DEBUG-SIM-4] 타이머 시작 완료")
            
        except Exception as e:
            print(f"[DEBUG-SIM-ERR] 오류 발생: {str(e)}")
            self.update_status_signal.emit(f"시뮬레이션 실행 중 오류 발생: {str(e)}")
            traceback.print_exc()

    def stop_simulation(self):
        """시뮬레이션 중지"""
        self.simulation_enabled = False
        self.simulation_timer.stop()
        self.update_status_signal.emit("시뮬레이션이 중지되었습니다.")

    def simulation_loop(self):
        """시뮬레이션 루프"""
        try:
            # 실시간 현재가 조회
            current_price = python_bithumb.get_current_price(f"KRW-{self.coin}")
            if current_price is None:
                self.update_status_signal.emit("현재가 조회 실패")
                return

            # OHLCV 데이터는 전략 계산용으로만 사용
            df = python_bithumb.get_ohlcv(f"KRW-{self.coin}", interval="minute1", count=self.min_candle)
            if df.empty or len(df) < self.min_candle:
                self.update_status_signal.emit(f"캔들 데이터 부족: {len(df)}개")
                return

            now = datetime.now()
            volume = df.iloc[-1]['volume']  # 거래량은 캔들 데이터에서 가져옴

            # 전략 객체 생성 및 신호 생성
            strategy_obj = StrategyFactory.create_strategy(self.strategy)
            if strategy_obj is None:
                return

            signal = strategy_obj.generate_signal(df, **self.params)

            # 상태 업데이트
            self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원, 신호: {signal if signal else '없음'}, 잔고: {self.balance:,.0f}원, 포지션: {self.position:.6f}")
            self.price_history.append((now, current_price))
            self.balance_history.append((now, self.balance + self.position * current_price))
            self.volume_history.append((now, volume))

            # 매매 신호에 따른 거래 실행
            if signal == 'buy' and self.last_signal != 'buy':
                amount = self.initial_capital / current_price
                fee = amount * current_price * self.fee_rate
                self.position += amount
                self.balance -= (self.initial_capital + fee)
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매수 신호! {self.initial_capital:,.0f}원 매수, 보유: {self.position:.6f} (수수료: {fee:,.0f}원)")
                self.trade_history.append({
                    'time': now,
                    'type': 'buy',
                    'price': current_price,
                    'amount': amount,
                    'balance': self.balance,
                    'position': self.position,
                    'fee': fee
                })
                self.last_signal = 'buy'
            elif signal == 'sell' and self.position > 0 and self.last_signal != 'sell':
                sell_value = self.position * current_price
                fee = sell_value * self.fee_rate
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매도 신호! {sell_value:,.0f}원 매도, 보유: 0 (수수료: {fee:,.0f}원)")
                self.trade_history.append({
                    'time': now,
                    'type': 'sell',
                    'price': current_price,
                    'amount': self.position,
                    'balance': self.balance + sell_value - fee,
                    'position': 0,
                    'fee': fee
                })
                self.balance += (sell_value - fee)
                self.position = 0
                self.last_signal = 'sell'
            else:
                self.last_signal = None

            # 차트 업데이트
            self.show_data_chart_signal.emit(self.price_history, self.trade_history, self.balance_history, self.volume_history)

        except Exception as e:
            self.update_status_signal.emit(f"시뮬레이션 오류: {str(e)}")
            traceback.print_exc()

    def check_api_connection(self):
        """API 연결 상태 확인"""
        try:
            print("[DEBUG-CHECK-1] API 연결 확인 시작")
            if not self.parent or not self.parent.bithumb:
                print("[DEBUG-CHECK-2] 메인 윈도우 또는 API 객체 없음")
                self.update_status_signal.emit("메인 윈도우의 API 연결이 필요합니다.")
                return False
            
            print("[DEBUG-CHECK-3] API 객체 업데이트")
            self.bithumb = self.parent.bithumb
            # self.is_connected = self.parent.is_connected  # 이 줄 제거
            
            print(f"[DEBUG-CHECK-4] 연결 상태: {self.is_connected}")
            if not self.is_connected:
                self.update_status_signal.emit("API가 연결되지 않았습니다.")
                return False
                
            print("[DEBUG-CHECK-5] API 연결 확인 완료")
            return True
            
        except Exception as e:
            print(f"[DEBUG-CHECK-ERR] API 연결 확인 실패: {str(e)}")
            self.update_status_signal.emit(f"API 연결 확인 실패: {str(e)}")
            return False

    def run_auto_trading(self, strategy, coin, params, initial_capital, fee_rate):
        """자동매매 실행"""
        try:
            print("[DEBUG-AT-1] 자동매매 워커 실행 시작")
            print(f"[DEBUG-AT-2] 전략: {strategy}, 코인: {coin}")
            print(f"[DEBUG-AT-3] 파라미터: {params}")
            print(f"[DEBUG-AT-4] 초기자본: {initial_capital}, 수수료율: {fee_rate}")
            
            print("[DEBUG-AT-5] API 연결 체크 시작")
            if not self.check_api_connection():
                print("[DEBUG-AT-6] API 연결 실패")
                self.update_status_signal.emit("API 연결이 필요합니다.")
                return
            print("[DEBUG-AT-7] API 연결 체크 완료")
            
            # 초기 설정
            self.strategy = strategy
            self.coin = coin
            self.params = params
            self.initial_capital = initial_capital
            self.fee_rate = fee_rate
            self.balance = initial_capital
            self.position = 0
            self.last_signal = None
            self.price_history = []
            self.trade_history = []
            self.balance_history = []
            self.volume_history = []
            
            # 전략별로 필요한 최소 캔들 개수 계산
            self.min_candle = self.calculate_min_candles()
            print(f"[DEBUG-AT-8] 전략: {strategy}, 코인: {coin}, 필요 캔들 수: {self.min_candle}")
            print(f"[DEBUG-AT-9] 타이머 시작 시도")
            
            # 타이머 시작 (1분 간격)
            self.trading_enabled = True
            self.timer.start(1000)  # 60000ms = 1분
            print("[DEBUG-AT-10] 타이머 시작 완료")
            
        except Exception as e:
            print(f"[DEBUG-AT-ERR] 오류 발생: {str(e)}")
            self.update_status_signal.emit(f"자동매매 실행 중 오류 발생: {str(e)}")
            traceback.print_exc()

    def stop_auto_trading(self):
        """자동매매 중지"""
        self.trading_enabled = False
        self.timer.stop()
        self.update_status_signal.emit("자동매매가 중지되었습니다.")

    def calculate_min_candles(self):
        """전략별 필요한 최소 캔들 수 계산"""
        min_candle = 30
        if self.strategy == 'RSI':
            min_candle = max(30, self.params.get('period', 14) + 1)
        elif self.strategy == '볼린저밴드':
            min_candle = max(30, self.params.get('period', 20) + 1)
        elif self.strategy == 'MACD':
            min_candle = max(30, self.params.get('slow_period', 26) + self.params.get('signal_period', 9))
        elif self.strategy == '이동평균선 교차':
            min_candle = max(30, self.params.get('long_period', 20) + 1)
        elif self.strategy == '스토캐스틱':
            min_candle = max(30, self.params.get('period', 14) + self.params.get('d_period', 3))
        elif self.strategy == 'ATR 기반 변동성 돌파':
            min_candle = max(30, self.params.get('period', 14) + 1)
        elif self.strategy == '거래량 프로파일':
            min_candle = max(30, self.params.get('num_bins', 10) * 2)
        elif self.strategy == 'BB+RSI':
            min_candle = max(30, self.params.get('bb_period', 20) + 1, self.params.get('rsi_period', 14) + 1)
        elif self.strategy == 'MACD+EMA':
            min_candle = max(30, self.params.get('macd_slow', 26) + self.params.get('macd_signal', 9), self.params.get('ema_period', 20))
        return min_candle

    def trading_loop(self):
        """트레이딩 루프 - QTimer에 의해 1분마다 호출됨"""
        if not self.trading_enabled:
            return
            
        try:
            if not self.check_api_connection():
                self.update_status_signal.emit("API 연결이 끊어졌습니다. 재연결을 시도합니다.")
                return
                
            # 실시간 현재가 조회
            current_price = python_bithumb.get_current_price(f"KRW-{self.coin}")
            if current_price is None:
                self.update_status_signal.emit("현재가 조회 실패")
                return
                
            # OHLCV 데이터 조회
            df = python_bithumb.get_ohlcv(f"KRW-{self.coin}", interval="minute1", count=self.min_candle)
            if df.empty or len(df) < self.min_candle:
                self.update_status_signal.emit(f"캔들 데이터 부족: {len(df)}개")
                return
                
            now = datetime.now()
            volume_btc = df.iloc[-1]['volume']
            # 거래량을 원화로 변환 (현재가 기준)
            volume_krw = volume_btc * current_price
            
            # 전략 객체 생성 및 신호 생성
            strategy_obj = StrategyFactory.create_strategy(self.strategy)
            if strategy_obj is None:
                return
                
            signal = strategy_obj.generate_signal(df, **self.params)
            
            # 상태 업데이트
            status_msg = f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원, 신호: {signal if signal else '없음'}, 잔고: {self.balance:,.0f}원, 포지션: {self.position:.6f}"
            self.update_status_signal.emit(status_msg)
            self.price_history.append((now, current_price))
            self.balance_history.append((now, self.balance + self.position * current_price))
            self.volume_history.append((now, volume_krw))  # 원화 거래량 저장
            
            # 매매 신호에 따른 거래 실행
            if signal == 'buy' and self.last_signal != 'buy':
                self.execute_buy_order(current_price, now)
            elif signal == 'sell' and self.position > 0 and self.last_signal != 'sell':
                self.execute_sell_order(current_price, now)
            else:
                self.last_signal = None
                
            # 차트 업데이트
            self.show_data_chart_signal.emit(self.price_history, self.trade_history, self.balance_history, self.volume_history)
            
        except Exception as e:
            self.update_status_signal.emit(f"자동매매 오류: {str(e)}")
            traceback.print_exc()

    def execute_buy_order(self, current_price, now):
        """매수 주문 실행 (원화 금액으로 주문)"""
        try:
            # 매수 가능한 금액 계산 (잔고의 100%)
            available_amount = self.balance
            if available_amount < 5000:  # 최소 주문 금액
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 잔고 부족으로 매수 불가 (최소 주문금액: 5,000원)")
                return
                
            # 수수료를 고려한 실제 매수 가능 금액
            fee = available_amount * self.fee_rate
            actual_amount = available_amount - fee
            
            # 매수할 코인 수량 계산 (실제 주문에는 사용하지 않고 기록용으로만 사용)
            coin_amount = actual_amount / current_price
            
            # 실제 매수 주문 실행 (주석 처리) - 원화 금액으로 주문
            # order = self.bithumb.buy_market_order(f"KRW-{self.coin}", actual_amount)  # 원화 금액으로 주문
            
            # 가상 주문 (테스트용)
            order = {'price': current_price, 'status': 'success'}  # 가상의 성공한 주문
            
            if order and order.get('status') == 'success':
                self.position += coin_amount
                self.balance -= (actual_amount + fee)
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매수 주문 성공! {actual_amount:,.0f}원 매수, 보유: {self.position:.6f} (수수료: {fee:,.0f}원)")
                self.trade_history.append({
                    'time': now,
                    'type': 'buy',
                    'price': current_price,
                    'amount': coin_amount,
                    'balance': self.balance,
                    'position': self.position,
                    'fee': fee
                })
                self.last_signal = 'buy'
            else:
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매수 주문 실패: {order.get('error', '알 수 없는 오류')}")
        except Exception as e:
            self.update_status_signal.emit(f"매수 주문 중 오류 발생: {str(e)}")

    def execute_sell_order(self, current_price, now):
        """매도 주문 실행 (코인 수량으로 주문)"""
        try:
            # 매도할 수량 계산 (포지션의 100%)
            coin_amount = self.position
            sell_value = coin_amount * current_price
            
            if sell_value < 5000:  # 최소 주문 금액
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매도 금액이 너무 작습니다 (최소 주문금액: 5,000원)")
                return
                
            fee = sell_value * self.fee_rate
            
            # 실제 매도 주문 실행 (주석 처리) - 코인 수량으로 주문
            # order = self.bithumb.sell_market_order(f"KRW-{self.coin}", coin_amount)  # 코인 수량으로 주문
            
            # 가상 주문 (테스트용)
            order = {'price': current_price, 'status': 'success'}  # 가상의 성공한 주문
            
            if order and order.get('status') == 'success':
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매도 주문 성공! {sell_value:,.0f}원 매도, 보유: 0 (수수료: {fee:,.0f}원)")
                self.trade_history.append({
                    'time': now,
                    'type': 'sell',
                    'price': current_price,
                    'amount': coin_amount,
                    'balance': self.balance + sell_value - fee,
                    'position': 0,
                    'fee': fee
                })
                self.balance += (sell_value - fee)
                self.position = 0
                self.last_signal = 'sell'
            else:
                self.update_status_signal.emit(f"[{now.strftime('%H:%M:%S')}] 매도 주문 실패: {order.get('error', '알 수 없는 오류')}")
        except Exception as e:
            self.update_status_signal.emit(f"매도 주문 중 오류 발생: {str(e)}")