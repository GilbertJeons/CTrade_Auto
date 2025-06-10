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

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'

class AutoTradeWindow(QDialog):
    # 시그널 정의
    update_sim_status = pyqtSignal(str)
    show_sim_chart_signal = pyqtSignal(list, list, list)
    show_trade_log_signal = pyqtSignal(list)
    update_data_result = pyqtSignal(str)  # 데이터 수집 결과 업데이트를 위한 시그널 추가
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # 부모 윈도우 저장
        
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
        
        # 실시간 데이터 저장용 변수
        self.realtime_data = []
        self.realtime_timer = QTimer()
        self.realtime_timer.timeout.connect(self.fetch_realtime_data)
        
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
        
        # 실시간 차트 상태 변수
        self.realtime_running = False
        self.realtime_timer = QTimer()
        self.realtime_timer.timeout.connect(self.fetch_realtime_data)
        
        # 전략 파라미터 그룹
        self.param_groups = {}
        self.sim_param_groups = {}
        self.trade_param_groups = {}
        
        # --- 전략 콤보박스 중복 방지 및 파라미터 그룹 초기 표시 ---
        # (AutoTradeWindow __init__ 내)
        strategies = [
            "RSI", "볼린저밴드", "MACD", "이동평균선 교차", "스토캐스틱",
            "ATR 기반 변동성 돌파", "거래량 프로파일", "머신러닝"
        ]
        self.strategyCombo.clear()
        self.simStrategyCombo.clear()
        self.tradeStrategyCombo.clear()
        self.strategyCombo.addItems(strategies)
        self.simStrategyCombo.addItems(strategies)
        self.tradeStrategyCombo.addItems(strategies)

        # 전략 설명 라벨을 .ui에서 findChild로 연결
        self.strategyDescriptionLabel = self.findChild(QLabel, 'strategyDescriptionLabel')

        # 각 탭의 현재 선택된 전략에 맞는 파라미터 그룹을 표시 (초기화)
        self.update_backtest_param_groups_visibility(self.strategyCombo.currentText())
        self.update_sim_param_groups_visibility(self.simStrategyCombo.currentText())
        self.update_trade_param_groups_visibility(self.tradeStrategyCombo.currentText())
        
        # 날짜 입력란을 오늘 날짜로 초기화
        from PyQt5.QtCore import QDate
        today = QDate.currentDate()
        self.dataStartDate.setDate(today)
        self.dataEndDate.setDate(today)
        self.backtestStartDate.setDate(today)
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
        self.strategyCombo.currentTextChanged.connect(lambda text: self.update_param_groups(text))
        self.strategyCombo.currentTextChanged.connect(self.update_strategy_description)
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
            
            # x축 포맷 설정
            for ax in [ax1, ax2]:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
                
            figure.tight_layout()
            canvas.draw()
            
            # 닫기 버튼
            close_btn = QPushButton('닫기')
            close_btn.clicked.connect(chart_window.close)
            layout.addWidget(close_btn)
            
            chart_window.setLayout(layout)
            chart_window.exec_()
            
            print("차트 생성 완료")
            
        except Exception as e:
            print(f"차트 표시 오류: {str(e)}")
            traceback.print_exc()
    
    def start_backtest(self):
        """백테스트 시작"""
        try:
            # 파라미터 가져오기
            strategy = self.strategyCombo.currentText()
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
            # 파라미터 저장 (최소 수정)
            self.last_backtest_params = params
            # 백테스트 엔진을 fee_rate와 함께 새로 생성
            engine = BacktestEngine(fee_rate=fee_rate)
            if strategy == 'ATR 기반 변동성 돌파':
                results = engine.backtest_atr(params, df, interval, initial_capital)
            elif strategy == '머신러닝':
                results = engine.backtest_ml(params, df, interval, initial_capital)
            elif strategy == '거래량 프로파일':
                results = engine.backtest_volume_profile(params, df, interval, initial_capital)
            else:
                results = engine.backtest_strategy(strategy, params, df, interval, initial_capital)
            if results is None:
                QMessageBox.warning(self, "오류", "백테스트 실행 중 오류가 발생했습니다.")
                return
            self.handle_backtest_results(df, results, initial_capital)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"백테스트 실행 중 오류가 발생했습니다: {str(e)}")
            traceback.print_exc()
    
    def setup_param_groups(self):
        # UI에 이미 존재하는 파라미터 그룹/위젯을 findChild로 연결
        self.feeGroup = self.findChild(QGroupBox, 'feeGroup')
        self.feeRateSpinBox = self.findChild(QDoubleSpinBox, 'feeRateSpinBox')
        self.rsiGroup = self.findChild(QGroupBox, 'rsiGroup')
        self.rsiPeriod = self.findChild(QSpinBox, 'rsiPeriod')
        self.rsiOverbought = self.findChild(QSpinBox, 'rsiOverbought')
        self.rsiOversold = self.findChild(QSpinBox, 'rsiOversold')
        self.bbGroup = self.findChild(QGroupBox, 'bbGroup')
        self.bbPeriod = self.findChild(QSpinBox, 'bbPeriod')
        self.bbStd = self.findChild(QDoubleSpinBox, 'bbStd')
        self.macdGroup = self.findChild(QGroupBox, 'macdGroup')
        self.macdFastPeriod = self.findChild(QSpinBox, 'macdFastPeriod')
        self.macdSlowPeriod = self.findChild(QSpinBox, 'macdSlowPeriod')
        self.macdSignalPeriod = self.findChild(QSpinBox, 'macdSignalPeriod')
        self.maGroup = self.findChild(QGroupBox, 'maGroup')
        self.maShortPeriod = self.findChild(QSpinBox, 'maShortPeriod')
        self.maLongPeriod = self.findChild(QSpinBox, 'maLongPeriod')
        self.stochGroup = self.findChild(QGroupBox, 'stochGroup')
        self.stochPeriod = self.findChild(QSpinBox, 'stochPeriod')
        self.stochKPeriod = self.findChild(QSpinBox, 'stochKPeriod')
        self.stochDPeriod = self.findChild(QSpinBox, 'stochDPeriod')
        self.stochOverbought = self.findChild(QSpinBox, 'stochOverbought')
        self.stochOversold = self.findChild(QSpinBox, 'stochOversold')
        self.atrGroup = self.findChild(QGroupBox, 'atrGroup')
        self.atrPeriod = self.findChild(QSpinBox, 'atrPeriod')
        self.atrMultiplier = self.findChild(QDoubleSpinBox, 'atrMultiplier')
        self.trendPeriod = self.findChild(QSpinBox, 'trendPeriod')
        self.stopLossMultiplier = self.findChild(QDoubleSpinBox, 'stopLossMultiplier')
        self.positionSizeMultiplier = self.findChild(QDoubleSpinBox, 'positionSizeMultiplier')
        self.volumeProfileGroup = self.findChild(QGroupBox, 'volumeProfileGroup')
        self.volumeThreshold = self.findChild(QSpinBox, 'volumeThreshold')
        self.mlGroup = self.findChild(QGroupBox, 'mlGroup')
        self.predictionPeriod = self.findChild(QSpinBox, 'predictionPeriod')
        self.trainingPeriod = self.findChild(QSpinBox, 'trainingPeriod')

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
            self.start_price_updates()
            self.start_auto_trading()
        else:
            self.tradeStartBtn.setText("자동매매 시작")
            self.stop_price_updates()
            self.stop_auto_trading()
            
    def start_simulation(self):
        def run_simulation():
            balance = self.simInvestment.value()
            position = 0
            last_signal = None
            price_history = []
            trade_history = []
            balance_history = []
            is_first_buy = True
            fee_rate = self.simFeeRateSpinBox.value() / 100 if hasattr(self, 'simFeeRateSpinBox') else 0.0004
            while self.trading_enabled:
                try:
                    coin = self.simCoinCombo.currentText()
                    strategy = self.simStrategyCombo.currentText()
                    investment = self.simInvestment.value()
                    price = python_bithumb.get_current_price(f"KRW-{coin}")
                    now = datetime.now()
                    if not price:
                        self.update_sim_status.emit(f"[{now}] 현재가 조회 실패")
                        time.sleep(1)
                        continue
                    df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval="minute1", count=1)
                    if df.empty:
                        self.update_sim_status.emit(f"[{now}] 거래량 데이터 없음")
                        time.sleep(1)
                        continue
                    volume = df.iloc[0]['volume']
                    signal = self.generate_signal(price, volume, strategy)
                    self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 현재가: {price:,.0f}원, 신호: {signal if signal else '없음'}, 잔고: {balance:,.0f}원, 포지션: {position:.6f}")
                    price_history.append((now, price))
                    balance_history.append((now, balance + position * price))

                    # ShortPercent 전략: 최초 1회 무조건 매수
                    if strategy == 'ShortPercent' and is_first_buy:
                        amount = investment / price
                        fee = amount * price * fee_rate
                        position += amount
                        balance -= (investment + fee)
                        self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 최초 매수! {investment:,.0f}원 매수, 보유: {position:.6f} (수수료: {fee:,.0f}원)")
                        trade_history.append({'time': now, 'type': 'buy', 'price': price, 'amount': amount, 'balance': balance, 'position': position, 'fee': fee})
                        is_first_buy = False
                        time.sleep(1)
                        continue

                    # 기존 신호 기반 매수/매도 로직
                    if signal == 'buy':
                        amount = investment / price
                        fee = amount * price * fee_rate
                        position += amount
                        balance -= (investment + fee)
                        self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 매수 신호! {investment:,.0f}원 매수, 보유: {position:.6f} (수수료: {fee:,.0f}원)")
                        trade_history.append({'time': now, 'type': 'buy', 'price': price, 'amount': amount, 'balance': balance, 'position': position, 'fee': fee})
                    elif signal == 'sell' and position > 0:
                        sell_value = position * price
                        fee = sell_value * fee_rate
                        self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 매도 신호! {sell_value:,.0f}원 매도, 보유: 0 (수수료: {fee:,.0f}원)")
                        trade_history.append({'time': now, 'type': 'sell', 'price': price, 'amount': position, 'balance': balance + sell_value - fee, 'position': 0, 'fee': fee})
                        balance += (sell_value - fee)
                        position = 0
                    time.sleep(1)
                except Exception as e:
                    self.update_sim_status.emit(f"시뮬레이션 오류: {str(e)}")
                    time.sleep(5)
            # 시뮬레이션 종료 후 차트 표시 (시그널로 메인스레드에서 실행)
            self.show_sim_chart_signal.emit(price_history, trade_history, balance_history)
        self.simulation_thread = threading.Thread(target=run_simulation)
        self.simulation_thread.daemon = True
        self.simulation_thread.start()

    def show_simulation_chart(self, price_history, trade_history, balance_history):
        """시뮬레이션 차트 표시"""
        try:
            # 기존 차트 창이 있으면 닫기
            if hasattr(self, 'sim_chart_window') and self.sim_chart_window is not None:
                self.sim_chart_window.close()
            # 새 차트 창 생성
            self.sim_chart_window = QDialog(self)
            self.sim_chart_window.setWindowTitle('시뮬레이션 결과 차트')
            self.sim_chart_window.setGeometry(100, 100, 1200, 800)
            # 차트 생성
            fig = Figure(figsize=(12, 8))
            gs = gridspec.GridSpec(3, 1, height_ratios=[2, 1, 1])
            # 가격 차트
            ax1 = fig.add_subplot(gs[0])
            ax1.plot([t[0] for t in price_history], [t[1] for t in price_history], 'b-', label='가격')
            for t in trade_history:
                if t['type'] == 'buy':
                    ax1.scatter(t['date'], t['price'], color='r', marker='^', s=100)
                else:
                    ax1.scatter(t['exit_date'], t['exit_price'], color='g', marker='v', s=100)
            ax1.set_title('가격 및 거래')
            ax1.set_xlabel('시간')
            ax1.set_ylabel('가격')
            ax1.grid(True)
            ax1.legend()
            # 거래량 차트
            ax2 = fig.add_subplot(gs[1], sharex=ax1)
            # price_history: (datetime, price), balance_history: (datetime, balance)
            # 거래량은 price_history의 price 변화량으로 계산
            volumes = [abs(price_history[i][1] - price_history[i-1][1]) if i > 0 else 0 for i in range(len(price_history))]
            ax2.bar([t[0] for t in price_history], volumes, color='gray', label='거래량')
            ax2.set_ylabel('거래량')
            ax2.grid(True, alpha=0.3)
            ax2.legend()
            # 자본금 차트
            ax3 = fig.add_subplot(gs[2], sharex=ax1)
            ax3.plot([t[0] for t in balance_history], [t[1] for t in balance_history], 'g-', label='자본금')
            ax3.set_title('자본금 변화')
            ax3.set_xlabel('시간')
            ax3.set_ylabel('자본금')
            ax3.grid(True)
            ax3.legend()
            # 차트를 UI에 추가
            canvas = FigureCanvas(fig)
            layout = QVBoxLayout()
            layout.addWidget(canvas)
            self.sim_chart_window.setLayout(layout)
            # 차트 창 표시
            self.sim_chart_window.show()
        except Exception as e:
            print(f"차트 생성 중 오류 발생: {str(e)}")
            traceback.print_exc()

    def stop_simulation(self):
        self.trading_enabled = False
        if hasattr(self, 'simulation_thread') and self.simulation_thread is not None:
            self.simulation_thread.join()
            self.simulation_thread = None
            
    def start_price_updates(self):
        def update_price():
            while self.trading_enabled:
                try:
                    price = python_bithumb.get_current_price(f"KRW-{self.tradeCoinCombo.currentText()}")
                    if price:
                        self.tradeStatus.append(f"[{datetime.now()}] 현재가: {price:,.0f}원")
                    time.sleep(1)
                except Exception as e:
                    self.tradeStatus.append(f"가격 업데이트 오류: {str(e)}")
                    time.sleep(5)
                    
        self.price_update_thread = threading.Thread(target=update_price)
        self.price_update_thread.daemon = True
        self.price_update_thread.start()

    def stop_price_updates(self):
        self.trading_enabled = False
        if hasattr(self, 'price_update_thread') and self.price_update_thread is not None:
            self.price_update_thread.join()
            self.price_update_thread = None

    def start_auto_trading(self):
        def run_auto_trading():
            while self.trading_enabled:
                try:
                    coin = self.tradeCoinCombo.currentText()
                    strategy = self.tradeStrategyCombo.currentText()
                    investment = self.tradeInvestment.value()
                    
                    # 현재가 조회
                    price = python_bithumb.get_current_price(f"KRW-{coin}")
                    if not price:
                        continue
                        
                    # 거래량 조회
                    df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval="minute1", count=1)
                    if df.empty:
                        continue
                        
                    volume = df.iloc[0]['volume']
                    
                    # 매매 신호 생성
                    signal = self.generate_signal(price, volume, strategy)
                    
                    # 매매 실행
                    if signal == 'buy':
                        self.buy_market_order(investment)
                        self.tradeStatus.append(f"[{datetime.now()}] 매수 실행: {price:,.0f}원")
                    elif signal == 'sell':
                        self.sell_market_order(investment)
                        self.tradeStatus.append(f"[{datetime.now()}] 매도 실행: {price:,.0f}원")
                        
                    time.sleep(1)
                    
                except Exception as e:
                    self.tradeStatus.append(f"자동매매 오류: {str(e)}")
                    time.sleep(5)
                    
        self.trading_thread = threading.Thread(target=run_auto_trading)
        self.trading_thread.daemon = True
        self.trading_thread.start()
        
    def stop_auto_trading(self):
        self.trading_enabled = False
        if hasattr(self, 'trading_thread') and self.trading_thread is not None:
            self.trading_thread.join()
            self.trading_thread = None
            
    def generate_signal(self, price, volume, strategy):
        try:
            df = self.fetch_realtime_data()
            if df is None or len(df) < 30:
                return None
                
            strategy_obj = StrategyFactory.create_strategy(strategy)
            if strategy_obj is None:
                return None
                
            return strategy_obj.generate_signal(df)
            
        except Exception as e:
            print(f"신호 생성 오류: {str(e)}")
            return None 
            
    def fetch_realtime_data(self):
        if not self.realtime_running:
            return
        try:
            coin = self.tradeCoinCombo.currentText()
            interval = self.interval_combo.currentText() if hasattr(self, 'interval_combo') else "1분봉"
            interval_map = {
                "1분봉": "minute1", "3분봉": "minute3", "5분봉": "minute5",
                "15분봉": "minute15", "30분봉": "minute30",
                "1시간봉": "hour1", "4시간봉": "hour4",
                "일봉": "day", "주봉": "week", "월봉": "month"
            }
            api_interval = interval_map.get(interval, "minute1")
            df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval=api_interval, count=100)
            if df is not None and not df.empty:
                df = df.reset_index()
                self.realtime_ohlcv_data = []
                self.realtime_price_data = []
                self.realtime_time_data = []
                self.realtime_volume_data = []
                for i in range(len(df)):
                    ohlcv = {
                        'time': df.iloc[i][df.columns[0]],
                        'open': df.iloc[i]['open'],
                        'high': df.iloc[i]['high'],
                        'low': df.iloc[i]['low'],
                        'close': df.iloc[i]['close'],
                        'volume': df.iloc[i]['volume']
                    }
                    self.realtime_ohlcv_data.append(ohlcv)
                    self.realtime_price_data.append(ohlcv['close'])
                    self.realtime_time_data.append(ohlcv['time'])
                    self.realtime_volume_data.append(ohlcv['volume'])
                self.update_chart()
        except Exception as e:
            print(f"실시간 데이터 수집 오류: {str(e)}")
            traceback.print_exc()

    def update_chart(self):
        try:
            self.figure.clear()
            chart_type = self.chart_type_combo.currentText() if hasattr(self, 'chart_type_combo') else "라인차트"
            interval = self.interval_combo.currentText() if hasattr(self, 'interval_combo') else "1분봉"
            period = self.period_combo.currentText() if hasattr(self, 'period_combo') else "1일"
            indicator = self.indicator_combo.currentText() if hasattr(self, 'indicator_combo') else "없음"
            ax1 = self.figure.add_subplot(211)
            if chart_type == "캔들차트" and len(self.realtime_ohlcv_data) > 0:
                for ohlcv in self.realtime_ohlcv_data:
                    time = ohlcv['time']
                    open_price = ohlcv['open']
                    high = ohlcv['high']
                    low = ohlcv['low']
                    close = ohlcv['close']
                    if close >= open_price:
                        color = 'red'
                        body_bottom = open_price
                        body_top = close
                    else:
                        color = 'blue'
                        body_bottom = close
                        body_top = open_price
                    ax1.plot([time, time], [low, high], color=color, linewidth=1)
                    ax1.plot([time, time], [body_bottom, body_top], color=color, linewidth=3)
            else:
                if len(self.realtime_price_data) > 0:
                    ax1.plot(self.realtime_time_data, self.realtime_price_data, 'b-', label='가격')
            # 기술적 지표 추가 (생략, 기존 코드 유지)
            ax1.set_ylabel('가격')
            ax1.grid(True, alpha=0.3)
            ax1.legend()
            ax2 = self.figure.add_subplot(212)
            if len(self.realtime_volume_data) > 0:
                ax2.bar(self.realtime_time_data, self.realtime_volume_data, color='g', alpha=0.5, label='거래량')
            ax2.set_xlabel('시간')
            ax2.set_ylabel('거래량')
            ax2.grid(True, alpha=0.3)
            # x축 포맷 설정
            for ax in [ax1, ax2]:
                if interval in ["주봉", "월봉", "일봉"]:
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                else:
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
            self.figure.tight_layout()
            self.canvas.draw()
        except Exception as e:
            print(f"차트 업데이트 오류: {str(e)}")
            traceback.print_exc()

    def open_realtime_chart_window(self):
        if self.realtime_chart_window is not None:
            self.realtime_chart_window.close()
            
        self.realtime_chart_window = QDialog(self)
        self.realtime_chart_window.setWindowTitle('실시간 차트')
        self.realtime_chart_window.setGeometry(200, 200, 1200, 800)
        
        layout = QVBoxLayout()
        
        # 차트 옵션 그룹
        options_group = QGroupBox("차트 옵션")
        options_layout = QHBoxLayout()
        
        # 차트 타입 선택
        chart_type_label = QLabel("차트 타입:")
        self.chart_type_combo = QComboBox()
        self.chart_type_combo.addItems(["캔들차트", "라인차트"])
        self.chart_type_combo.currentTextChanged.connect(self.update_chart)
        
        # 시간대 선택
        interval_label = QLabel("시간대:")
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1분봉", "3분봉", "5분봉", "15분봉", "30분봉", "1시간봉", "4시간봉", "일봉", "주봉", "월봉"])
        self.interval_combo.currentTextChanged.connect(self.update_chart)
        
        # 기간 선택
        period_label = QLabel("기간:")
        self.period_combo = QComboBox()
        self.period_combo.addItems(["1일", "3일", "1주", "2주", "1개월", "3개월", "6개월", "1년"])
        self.period_combo.currentTextChanged.connect(self.update_chart)
        
        # 기술적 지표 선택
        indicator_label = QLabel("기술적 지표:")
        self.indicator_combo = QComboBox()
        self.indicator_combo.addItems(["없음", "이동평균선", "볼린저밴드", "MACD", "RSI"])
        self.indicator_combo.currentTextChanged.connect(self.update_chart)
        
        options_layout.addWidget(chart_type_label)
        options_layout.addWidget(self.chart_type_combo)
        options_layout.addWidget(interval_label)
        options_layout.addWidget(self.interval_combo)
        options_layout.addWidget(period_label)
        options_layout.addWidget(self.period_combo)
        options_layout.addWidget(indicator_label)
        options_layout.addWidget(self.indicator_combo)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # 차트 생성
        self.realtime_figure = Figure(figsize=(12, 8))
        self.realtime_canvas = FigureCanvas(self.realtime_figure)
        layout.addWidget(self.realtime_canvas)
        
        # 하단 버튼
        button_layout = QHBoxLayout()
        stop_btn = QPushButton('실시간 차트 중지 및 창 닫기')
        stop_btn.clicked.connect(self.close_realtime_chart_window)
        save_btn = QPushButton('차트 저장')
        save_btn.clicked.connect(self.save_chart)
        button_layout.addWidget(stop_btn)
        button_layout.addWidget(save_btn)
        layout.addLayout(button_layout)
        
        self.realtime_chart_window.setLayout(layout)
        self.realtime_running = True
        self.realtime_price_data = []
        self.realtime_time_data = []
        self.realtime_volume_data = []
        self.realtime_ohlcv_data = []  # OHLCV 데이터 추가
        self.realtime_ycenter = None
        self.realtime_timer.start(1000)
        self.realtime_chart_window.finished.connect(self.close_realtime_chart_window)
        self.realtime_chart_window.show()

    def save_chart(self):
        try:
            file_name, _ = QFileDialog.getSaveFileName(
                self.realtime_chart_window,
                "차트 저장",
                "",
                "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*.*)"
            )
            if file_name:
                self.realtime_canvas.figure.savefig(file_name)
                QMessageBox.information(self.realtime_chart_window, "저장 완료", "차트가 성공적으로 저장되었습니다.")
        except Exception as e:
            QMessageBox.warning(self.realtime_chart_window, "저장 실패", f"차트 저장 중 오류가 발생했습니다: {str(e)}")

    def close_realtime_chart_window(self):
        self.realtime_running = False
        self.realtime_timer.stop()
        if self.realtime_chart_window is not None:
            self.realtime_chart_window.close()
            self.realtime_chart_window = None
            
    def calculate_fee(self, amount, price):
        """거래 수수료 계산"""
        fee_rate = float(self.feeRateInput.text()) / 100  # UI에서 수수료율을 가져와서 계산
        return amount * price * fee_rate

    def apply_fee_to_trade(self, trade):
        """거래에 수수료 적용"""
        fee_rate = float(self.feeRateInput.text()) / 100  # UI에서 수수료율을 가져와서 계산
        trade['fee'] = self.calculate_fee(trade['amount'], trade['price'])
        trade['net_amount'] = trade['amount'] - trade['fee']
        return trade

    def buy_market_order(self, investment):
        """시장가 매수 주문"""
        try:
            current_price = float(self.currentPriceLabel.text().replace(',', ''))
            fee_rate = float(self.feeRateInput.text()) / 100  # UI에서 수수료율을 가져와서 계산
            fee = investment * fee_rate
            amount = (investment - fee) / current_price
            
            return {
                'type': 'buy',
                'price': current_price,
                'amount': amount,
                'fee': fee,
                'timestamp': datetime.now()
            }
        except Exception as e:
            print(f"매수 주문 오류: {str(e)}")
            return None

    def sell_market_order(self, investment):
        """시장가 매도 주문"""
        try:
            current_price = float(self.currentPriceLabel.text().replace(',', ''))
            fee_rate = float(self.feeRateInput.text()) / 100  # UI에서 수수료율을 가져와서 계산
            fee = investment * current_price * fee_rate
            amount = investment / current_price
            
            return {
                'type': 'sell',
                'price': current_price,
                'amount': amount,
                'fee': fee,
                'timestamp': datetime.now()
            }
        except Exception as e:
            print(f"매도 주문 오류: {str(e)}")
            return None

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

            # 거래량 차트 (추가)
            if 'volume' in df.columns:
                ax3.bar(df.index, df['volume'], color='gray', alpha=0.5, label='거래량')
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


    def calculate_performance_metrics(self, df):
        """성과 지표를 계산하는 메서드"""
        try:
            # 일별 수익률 계산
            df['returns'] = df['close'].pct_change()
            
            # 샤프 비율 계산
            risk_free_rate = 0.02  # 연간 무위험 수익률 (예: 2%)
            excess_returns = df['returns'] - risk_free_rate/252  # 일별 무위험 수익률
            sharpe_ratio = np.sqrt(252) * excess_returns.mean() / excess_returns.std()
            
            # 소르티노 비율 계산
            downside_returns = df['returns'][df['returns'] < 0]
            sortino_ratio = np.sqrt(252) * excess_returns.mean() / downside_returns.std()
            
            # 최대 낙폭(MDD) 계산
            cumulative_returns = (1 + df['returns']).cumprod()
            rolling_max = cumulative_returns.expanding().max()
            drawdowns = cumulative_returns / rolling_max - 1
            mdd = drawdowns.min()
            
            # 승률 계산
            trades = df[df['signal'] != 0]
            if len(trades) > 0:
                winning_trades = trades[trades['returns'] > 0]
                win_rate = len(winning_trades) / len(trades)
            else:
                win_rate = 0
            
            # 손익비 계산
            if len(trades) > 0:
                avg_win = trades[trades['returns'] > 0]['returns'].mean()
                avg_loss = abs(trades[trades['returns'] < 0]['returns'].mean())
                profit_factor = avg_win / avg_loss if avg_loss != 0 else float('inf')
            else:
                profit_factor = 0
            
            # 연간 수익률 계산
            annual_return = (1 + df['returns']).prod() ** (252/len(df)) - 1
            
            return {
                'sharpe_ratio': sharpe_ratio,
                'sortino_ratio': sortino_ratio,
                'mdd': mdd,
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'annual_return': annual_return
            }
            
        except Exception as e:
            print(f"성과 지표 계산 중 오류 발생: {str(e)}")
            return None    

    def calculate_fee(self, amount, price, fee_rate=0.0005):
        """수수료 계산"""
        return amount * price * fee_rate

    def apply_fee_to_trade(self, trade, fee_rate=0.0005):
        """거래에 수수료 적용"""
        if trade['type'] == 'buy':
            trade['price'] *= (1 + fee_rate)
        else:
            trade['price'] *= (1 - fee_rate)
        return trade

    def calculate_volume_profile(self, df, num_bins=10):
        """거래량 프로파일 계산"""
        price_range = df['high'].max() - df['low'].min()
        bin_size = price_range / num_bins
        bins = np.arange(df['low'].min(), df['high'].max() + bin_size, bin_size)
        volume_profile = np.zeros(num_bins)
        
        for i in range(len(df)):
            price = df['close'].iloc[i]
            volume = df['volume'].iloc[i]
            bin_idx = int((price - df['low'].min()) / bin_size)
            if 0 <= bin_idx < num_bins:
                volume_profile[bin_idx] += volume
                
        return bins, volume_profile
     
    # --- 파라미터 그룹 표시/숨김 함수 분리 ---
    def update_backtest_param_groups_visibility(self, strategy):
        # 모든 파라미터 그룹 리스트
        all_groups = [
            self.rsiGroup, self.bbGroup, self.macdGroup, self.maGroup,
            self.stochGroup, self.atrGroup
        ]
        if hasattr(self, 'volumeProfileGroup'):
            all_groups.append(self.volumeProfileGroup)
        if hasattr(self, 'mlGroup'):
            all_groups.append(self.mlGroup)
        # 현재 레이아웃에서 모든 그룹 제거 (빈 공간 방지)
        for group in all_groups:
            group.setParent(None)
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
        if group_to_show is not None:
            self.backtestParamLayout.addWidget(group_to_show)

    def update_sim_param_groups_visibility(self, strategy):
        groups = [self.simRsiGroup, self.simBbGroup, self.simMacdGroup, self.simMaGroup, self.simStochGroup, self.simAtrGroup]
        for group in groups:
            group.hide()
        if strategy == "RSI":
            self.simRsiGroup.show()
        elif strategy == "볼린저밴드":
            self.simBbGroup.show()
        elif strategy == "MACD":
            self.simMacdGroup.show()
        elif strategy == "이동평균선 교차":
            self.simMaGroup.show()
        elif strategy == "스토캐스틱":
            self.simStochGroup.show()
        elif strategy == "ATR 기반 변동성 돌파":
            self.simAtrGroup.show()

    def update_trade_param_groups_visibility(self, strategy):
        groups = [self.tradeRsiGroup, self.tradeBbGroup, self.tradeMacdGroup, self.tradeMaGroup, self.tradeStochGroup, self.tradeAtrGroup]
        for group in groups:
            group.hide()
        if strategy == "RSI":
            self.tradeRsiGroup.show()
        elif strategy == "볼린저밴드":
            self.tradeBbGroup.show()
        elif strategy == "MACD":
            self.tradeMacdGroup.show()
        elif strategy == "이동평균선 교차":
            self.tradeMaGroup.show()
        elif strategy == "스토캐스틱":
            self.tradeStochGroup.show()
        elif strategy == "ATR 기반 변동성 돌파":
            self.tradeAtrGroup.show()

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
            strategy_name = self.strategyCombo.currentText() if hasattr(self, 'strategyCombo') else ''
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
            strategy_name = self.strategyCombo.currentText()
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

    def run_simulation(self, strategy, coin, params, initial_capital, fee_rate):
        """시뮬레이션 실행"""
        try:
            balance = initial_capital
            position = 0
            last_signal = None
            price_history = []
            trade_history = []
            balance_history = []

            # 전략별로 필요한 최소 캔들 개수 계산
            min_candle = 30  # 기본값
            if strategy == 'RSI':
                min_candle = max(30, params.get('period', 14) + 1)
            elif strategy == '볼린저밴드':
                min_candle = max(30, params.get('period', 20) + 1)
            elif strategy == 'MACD':
                min_candle = max(30, params.get('slow_period', 26) + params.get('signal_period', 9))
            elif strategy == '이동평균선 교차':
                min_candle = max(30, params.get('long_period', 20) + 1)
            elif strategy == '스토캐스틱':
                min_candle = max(30, params.get('period', 14) + params.get('d_period', 3))
            elif strategy == 'ATR 기반 변동성 돌파':
                min_candle = max(30, params.get('period', 14) + 1)
            elif strategy == '거래량 프로파일':
                min_candle = max(30, params.get('num_bins', 10) * 2)

            while self.trading_enabled:
                try:
                    # 실시간 캔들 데이터, 필요한 만큼만 가져오기
                    df = python_bithumb.get_ohlcv(f"KRW-{coin}", interval="minute1", count=min_candle)
                    if df.empty or len(df) < min_candle:
                        self.update_sim_status.emit(f"캔들 데이터 부족: {len(df)}개")
                        time.sleep(1)
                        continue

                    price = df.iloc[-1]['close']
                    now = datetime.now()

                    # 전략 객체 생성 및 신호 생성
                    strategy_obj = StrategyFactory.create_strategy(strategy)
                    if strategy_obj is None:
                        time.sleep(1)
                        continue

                    signal = strategy_obj.generate_signal(df, **params)

                    # 상태 업데이트
                    self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 현재가: {price:,.0f}원, 신호: {signal if signal else '없음'}, 잔고: {balance:,.0f}원, 포지션: {position:.6f}")
                    price_history.append((now, price))
                    balance_history.append((now, balance + position * price))

                    # 매매 신호에 따른 거래 실행
                    if signal == 'buy' and last_signal != 'buy':
                        amount = initial_capital / price
                        fee = amount * price * fee_rate
                        position += amount
                        balance -= (initial_capital + fee)
                        self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 매수 신호! {initial_capital:,.0f}원 매수, 보유: {position:.6f} (수수료: {fee:,.0f}원)")
                        trade_history.append({'time': now, 'type': 'buy', 'price': price, 'amount': amount, 'balance': balance, 'position': position, 'fee': fee})
                        last_signal = 'buy'
                    elif signal == 'sell' and position > 0 and last_signal != 'sell':
                        sell_value = position * price
                        fee = sell_value * fee_rate
                        self.update_sim_status.emit(f"[{now.strftime('%H:%M:%S')}] 매도 신호! {sell_value:,.0f}원 매도, 보유: 0 (수수료: {fee:,.0f}원)")
                        trade_history.append({'time': now, 'type': 'sell', 'price': price, 'amount': position, 'balance': balance + sell_value - fee, 'position': 0, 'fee': fee})
                        balance += (sell_value - fee)
                        position = 0
                        last_signal = 'sell'
                    else:
                        last_signal = None

                    time.sleep(1)
                except Exception as e:
                    self.update_sim_status.emit(f"시뮬레이션 오류: {str(e)}")
                    traceback.print_exc()
                    time.sleep(5)

            # 시뮬레이션 종료 후 차트 표시
            self.show_sim_chart_signal.emit(price_history, trade_history, balance_history)

        except Exception as e:
            self.update_sim_status.emit(f"시뮬레이션 실행 중 오류 발생: {str(e)}")
            traceback.print_exc()