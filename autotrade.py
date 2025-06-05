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
from strategies import StrategyFactory, BacktestEngine
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
        self.setWindowTitle("자동매매 시스템")
        self.setGeometry(100, 100, 1200, 800)
        
        # UI 로드
        uic.loadUi('autotrade.ui', self)
        
        # 차트 초기화
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        
        # 로깅 시스템 초기화
        self.setup_logging()
        
        # 백테스트 엔진 초기화
        self.backtest_engine = BacktestEngine()
        
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
        
        # 전략 설명 표시 (초기화)
        self.update_strategy_description(self.strategyCombo.currentText())
        
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
        
        # # __init__에서 버튼 추가 및 연결
        # self.fullFetchBtn = QPushButton('전체 1분봉 데이터 수집')
        # if hasattr(self, 'horizontalLayout'):
        #     self.horizontalLayout.addWidget(self.fullFetchBtn)
        # self.fullFetchBtn.clicked.connect(self.fetch_and_store_ohlcv_full)
        
        # Optuna 최적화 버튼 연결
        self.optunaOptimizeBtn.clicked.connect(self.run_optuna_optimization)
        
        # # 전략 콤보박스 항목 추가
        # strategies = [
        #     "RSI", "볼린저밴드", "MACD", "이동평균선 교차", "스토캐스틱",
        #     "ATR 기반 변동성 돌파", "거래량 프로파일", "머신러닝"
        # ]
        
        # # 각 콤보박스에 전략 추가
        # self.strategyCombo.addItems(strategies)
        # self.simStrategyCombo.addItems(strategies)
        # self.tradeStrategyCombo.addItems(strategies)
        
        self.setup_logging()  # 반드시 __init__에서 호출

        # __init__ 내에 추가
        self.strategyCombo.currentTextChanged.connect(self.update_backtest_param_page)

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
            fee_rate = float(self.feeRateSpinBox.value())
            
            # 데이터 가져오기
            df = self.backtest_engine._fetch_historical_data(start_date, end_date, interval)
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
                    'trend_period': self.atrTrendPeriod.value(),
                    'stop_loss_multiplier': self.atrStopLossMultiplier.value(),
                    'position_size_multiplier': self.atrPositionSizeMultiplier.value()
                }
            elif strategy == '거래량 프로파일':
                params = {
                    'num_bins': self.volumeProfileBins.value()
                }
            elif strategy == '머신러닝':
                params = {
                    'n_estimators': self.mlNEstimators.value(),
                    'max_depth': self.mlMaxDepth.value(),
                    'random_state': self.mlRandomState.value()
                }
            
            # 백테스트 실행
            results = None
            if strategy == 'ATR 기반 변동성 돌파':
                results = self.backtest_engine.backtest_atr(params, df, interval, initial_capital)
            elif strategy == '머신러닝':
                results = self.backtest_engine.backtest_ml(params, df, interval, initial_capital)
            elif strategy == '거래량 프로파일':
                results = self.backtest_engine.backtest_volume_profile(params, df, interval, initial_capital)
            else:
                results = self.backtest_engine.backtest_strategy(strategy, params, df, interval, initial_capital)
            
            if results is None:
                QMessageBox.warning(self, "오류", "백테스트 실행 중 오류가 발생했습니다.")
                return
                
            # 결과 처리
            self.handle_backtest_results(df, results, initial_capital)
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"백테스트 실행 중 오류가 발생했습니다: {str(e)}")
            traceback.print_exc()

    def optimize_with_optuna(self, strategy, df, n_trials=100):
        """Optuna를 사용한 파라미터 최적화"""
        try:
            def objective(trial):
                # 전략별 파라미터 범위 설정
                if strategy == 'RSI':
                    params = {
                        'period': trial.suggest_int('period', 5, 30),
                        'overbought': trial.suggest_int('overbought', 60, 90),
                        'oversold': trial.suggest_int('oversold', 10, 40)
                    }
                elif strategy == '볼린저밴드':
                    params = {
                        'period': trial.suggest_int('period', 10, 50),
                        'std': trial.suggest_float('std', 1.0, 3.0)
                    }
                elif strategy == 'MACD':
                    params = {
                        'fast_period': trial.suggest_int('fast_period', 5, 20),
                        'slow_period': trial.suggest_int('slow_period', 20, 50),
                        'signal_period': trial.suggest_int('signal_period', 5, 20)
                    }
                elif strategy == '이동평균선 교차':
                    params = {
                        'short_period': trial.suggest_int('short_period', 5, 20),
                        'long_period': trial.suggest_int('long_period', 20, 50)
                    }
                elif strategy == '스토캐스틱':
                    params = {
                        'period': trial.suggest_int('period', 5, 30),
                        'k_period': trial.suggest_int('k_period', 1, 10),
                        'd_period': trial.suggest_int('d_period', 1, 10),
                        'overbought': trial.suggest_int('overbought', 60, 90),
                        'oversold': trial.suggest_int('oversold', 10, 40)
                    }
                elif strategy == 'ATR 기반 변동성 돌파':
                    params = {
                        'period': trial.suggest_int('period', 5, 30),
                        'multiplier': trial.suggest_float('multiplier', 1.0, 3.0),
                        'trend_period': trial.suggest_int('trend_period', 10, 50),
                        'stop_loss_multiplier': trial.suggest_float('stop_loss_multiplier', 1.0, 3.0),
                        'position_size_multiplier': trial.suggest_float('position_size_multiplier', 0.5, 2.0)
                    }
                elif strategy == '거래량 프로파일':
                    params = {
                        'num_bins': trial.suggest_int('num_bins', 5, 20)
                    }
                elif strategy == '머신러닝':
                    params = {
                        'n_estimators': trial.suggest_int('n_estimators', 50, 200),
                        'max_depth': trial.suggest_int('max_depth', 3, 10),
                        'random_state': 42
                    }
                
                # 백테스트 실행
                interval = self.intervalCombo.currentText()
                initial_capital = float(self.initialCapital.text())
                
                results = None
                if strategy == 'ATR 기반 변동성 돌파':
                    results = self.backtest_engine.backtest_atr(params, df, interval, initial_capital)
                elif strategy == '머신러닝':
                    results = self.backtest_engine.backtest_ml(params, df, interval, initial_capital)
                elif strategy == '거래량 프로파일':
                    results = self.backtest_engine.backtest_volume_profile(params, df, interval, initial_capital)
                else:
                    results = self.backtest_engine.backtest_strategy(strategy, params, df, interval, initial_capital)
                
                if results is None:
                    return float('-inf')
                    
                return results['profit_rate']
            
            # Optuna 스터디 생성 및 최적화 실행
            study = optuna.create_study(direction='maximize')
            study.optimize(objective, n_trials=n_trials)
            
            return study.best_params, study.best_value
            
        except Exception as e:
            print(f"Optuna 최적화 오류: {str(e)}")
            traceback.print_exc()
            return None, None

    def run_optuna_optimization(self):
        """Optuna 최적화 실행"""
        try:
            # 파라미터 가져오기
            strategy = self.strategyCombo.currentText()
            start_date = self.startDate.date().toPyDate()
            end_date = self.endDate.date().toPyDate()
            interval = self.intervalCombo.currentText()
            n_trials = int(self.optunaTrials.text())
            
            # 데이터 가져오기
            df = self.backtest_engine._fetch_historical_data(start_date, end_date, interval)
            if df is None:
                QMessageBox.warning(self, "오류", "데이터를 가져올 수 없습니다.")
                return
                
            # 최적화 실행
            best_params, best_value = self.optimize_with_optuna(strategy, df, n_trials)
            
            if best_params is None:
                QMessageBox.warning(self, "오류", "최적화 실행 중 오류가 발생했습니다.")
                return
                
            # 결과 표시
            self.show_optuna_results(best_params, best_value)
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"최적화 실행 중 오류가 발생했습니다: {str(e)}")
            traceback.print_exc()

    def handle_backtest_results(self, df, result, initial_capital):
        """백테스트 결과 처리"""
        try:
            if result is None:
                return
                
            # 현재 시간
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 전략 이름과 파라미터 가져오기
            strategy = self.strategyCombo.currentText()
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
                    'trend_period': self.atrTrendPeriod.value(),
                    'stop_loss_multiplier': self.atrStopLossMultiplier.value(),
                    'position_size_multiplier': self.atrPositionSizeMultiplier.value()
                }
            elif strategy == '거래량 프로파일':
                params = {
                    'num_bins': self.volumeProfileBins.value()
                }
            elif strategy == '머신러닝':
                params = {
                    'n_estimators': self.mlNEstimators.value(),
                    'max_depth': self.mlMaxDepth.value(),
                    'random_state': self.mlRandomState.value()
                }
            
            # 파라미터를 문자열로 변환
            params_str = json.dumps(params, ensure_ascii=False)
            
            # CSV에 결과 저장
            with open('backtest_results_log.csv', 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    current_time,  # 실행 시간
                    strategy,      # 전략 이름
                    params_str,    # 파라미터
                    initial_capital,  # 초기자본
                    result['final_capital'],  # 최종자본
                    result['profit_rate'],    # 수익률
                    result['win_rate'],       # 승률
                    result['total_trades'],   # 총 거래 횟수
                    df.index[0].date(),       # 시작일
                    df.index[-1].date(),      # 종료일
                    df.index[0],              # 시작 시간
                    df.index[-1],             # 종료 시간
                    self.backtestIntervalCombo.currentText(),  # 시간단위
                    'BTC'                      # 코인
                ])
            
            # 결과 표시
            self.backtestStatus.append(f"=== 백테스트 결과 ===")
            self.backtestStatus.append(f"전략: {strategy}")
            self.backtestStatus.append(f"파라미터: {params_str}")
            self.backtestStatus.append(f"초기자본: {initial_capital:,.0f}원")
            self.backtestStatus.append(f"최종자본: {result['final_capital']:,.0f}원")
            self.backtestStatus.append(f"수익률: {result['profit_rate']:.2f}%")
            self.backtestStatus.append(f"승률: {result['win_rate']:.2f}%")
            self.backtestStatus.append(f"총 거래 횟수: {result['total_trades']}회")
            
            # 차트 표시
            self.plot_backtest_results(df, result['trades'], result['final_capital'], result['daily_balance'])
            
            # 거래 내역 표시
            if result['trades']:
                self.show_trade_log_dialog(result['trades'])
                
        except Exception as e:
            self.backtestStatus.append(f"결과 처리 중 오류 발생: {str(e)}")
            traceback.print_exc()

    def calculate_backtest_results_with_fee(self, df, date_col='index', trades=None, daily_balance=None, final_capital=None, fee_rate=0.0005, show_ui=True):
        try:
            # 초기 자본금
            initial_capital = self.backtestInvestment.value()  # UI에서 입력받은 투자금액 사용
            capital = initial_capital
            position = 0
            max_capital = initial_capital
            min_capital = initial_capital
            total_fees = 0

            if trades is not None and daily_balance is not None and final_capital is not None:
                # 수수료 적용
                for trade in trades:
                    trade = self.apply_fee_to_trade(trade, fee_rate)
                    total_fees += trade['fee']
            else:
                trades = []
                daily_balance = []
                # 매매 기록
                for i in range(1, len(df)):
                    current_balance = capital + (position * df['close'].iloc[i])
                    daily_balance.append({
                        'date': df.index[i],
                        'balance': current_balance,
                        'position': position
                    })
                    if 'signal' in df.columns:
                        if df['signal'].iloc[i] == 1 and position == 0:  # 매수
                            price = df['close'].iloc[i]
                            amount = capital / price
                            fee = self.calculate_fee(amount, price, fee_rate)
                            total_fees += fee
                            position = amount
                            capital = 0
                            trades.append({
                                'date': df.index[i],
                                'type': 'buy',
                                'price': price,
                                'amount': amount,
                                'fee': fee,
                                'total_cost': amount * price + fee,
                                'balance': capital,
                                'position': position
                            })
                        elif df['signal'].iloc[i] == -1 and position > 0:  # 매도
                            price = df['close'].iloc[i]
                            fee = self.calculate_fee(position, price, fee_rate)
                            total_fees += fee
                            capital = position * price - fee
                            trades.append({
                                'date': df.index[i],
                                'type': 'sell',
                                'price': price,
                                'amount': position,
                                'fee': fee,
                                'total_revenue': position * price - fee,
                                'balance': capital,
                                'position': 0
                            })
                            position = 0
                    # 최대/최소 자본금 업데이트
                    max_capital = max(max_capital, current_balance)
                    min_capital = min(min_capital, current_balance)
                # 최종 자본금 계산
                if position > 0:
                    final_capital = position * df['close'].iloc[-1] - self.calculate_fee(position, df['close'].iloc[-1], fee_rate)
                else:
                    final_capital = capital

            # 수익률 계산 (수수료 포함)
            profit_rate = (final_capital - initial_capital) / initial_capital * 100
            # MDD 계산
            mdd = (max_capital - min_capital) / max_capital * 100
            # 승률 계산
            sell_trades = [t for t in trades if t['type'] == 'sell']
            if sell_trades:
                profitable_trades = sum(1 for t in sell_trades if t.get('total_revenue', 0) > t.get('total_cost', 0))
                win_rate = profitable_trades / len(sell_trades) * 100
            else:
                win_rate = 0
            # 평균 수익률 계산
            if trades:
                profit_rates = []
                for i in range(1, len(trades)):
                    if trades[i]['type'] == 'sell':
                        buy_cost = trades[i-1]['total_cost']
                        sell_revenue = trades[i]['total_revenue']
                        profit_rate = (sell_revenue - buy_cost) / buy_cost * 100
                        profit_rates.append(profit_rate)
                avg_profit_rate = sum(profit_rates) / len(profit_rates) if profit_rates else 0
            else:
                avg_profit_rate = 0

            # 결과 출력
            result_text = f"""=== 백테스팅 결과 (수수료 포함) ===
초기 자본금: {initial_capital:,.0f}원
최종 자본금: {final_capital:,.0f}원
총 수수료: {total_fees:,.0f}원
수익률: {profit_rate:.2f}%
MDD: {mdd:.2f}%
승률: {win_rate:.2f}%
평균 수익률: {avg_profit_rate:.2f}%
총 거래 횟수: {len(trades)}회"""

            self.backtestStatus.append(result_text)
            
            # 거래 내역 저장
            if show_ui:
                if trades:
                    try:
                        trades_df = pd.DataFrame(trades)
                        conn = sqlite3.connect('backtest_results.db')
                        table_name = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        trades_df.to_sql(table_name, conn, if_exists='replace', index=False)
                        results_df = pd.DataFrame([{
                            'initial_capital': initial_capital,
                            'final_capital': final_capital,
                            'total_fees': total_fees,
                            'profit_rate': profit_rate,
                            'mdd': mdd,
                            'win_rate': win_rate,
                            'avg_profit_rate': avg_profit_rate,
                            'total_trades': len(trades),
                            'start_date': df.index[0],
                            'end_date': df.index[-1]
                        }])
                        results_df.to_sql(f"results_{table_name}", conn, if_exists='replace', index=False)
                        conn.close()
                        self.backtestStatus.append(f"\n거래 내역이 {table_name} 테이블에 저장되었습니다.")
                    except Exception as e:
                        self.backtestStatus.append(f"\n거래 내역 저장 중 오류 발생: {str(e)}")
                    self.show_trade_log_signal.emit(trades)
                self.plot_backtest_results(df, trades, final_capital, daily_balance)

            # 결과 반환
            # 성과지표 계산
            returns = pd.Series([b['balance'] for b in daily_balance]).pct_change().dropna()
            if len(returns) > 1 and returns.std() != 0:
                sharpe_ratio = (returns.mean() / returns.std()) * (252 ** 0.5)
            else:
                sharpe_ratio = 0.0
            result = {
                'initial_capital': initial_capital,
                'final_capital': final_capital,
                'total_fees': total_fees,
                'profit_rate': profit_rate,
                'mdd': mdd,
                'win_rate': win_rate,
                'avg_profit_rate': avg_profit_rate,
                'total_trades': len(trades),
                'trades': trades,
                'daily_balance': daily_balance,
                'sharpe_ratio': sharpe_ratio
            }
            return result

        except Exception as e:
            self.backtestStatus.append(f"백테스팅 결과 계산 실패: {str(e)}")
            traceback.print_exc()
            return None

    def update_param_groups_visibility(self, strategy, groups):
        """전략 선택에 따라 파라미터 그룹 표시/숨김 처리"""
        for group in groups:
            group.hide()
        
        if strategy == "RSI":
            self.rsiGroup.show()
        elif strategy == "볼린저밴드":
            self.bbGroup.show()
        elif strategy == "MACD":
            self.macdGroup.show()
        elif strategy == "이동평균선 교차":
            self.maGroup.show()
        elif strategy == "스토캐스틱":
            self.stochGroup.show()
        elif strategy == "ATR 기반 변동성 돌파":
            self.atrGroup.show()

    def update_param_groups(self, strategy):
        """백테스팅 탭의 파라미터 그룹 업데이트"""
        self.update_param_groups_visibility(strategy, [
            self.rsiGroup, self.bbGroup, self.macdGroup,
            self.maGroup, self.stochGroup, self.atrGroup
        ])

    def update_sim_param_groups(self, strategy):
        """시뮬레이션 탭의 파라미터 그룹 업데이트"""
        self.update_param_groups_visibility(strategy, [
            self.rsiGroup, self.bbGroup, self.macdGroup,
            self.maGroup, self.stochGroup, self.atrGroup
        ])

    def update_trade_param_groups(self, strategy):
        """자동매매 탭의 파라미터 그룹 업데이트"""
        self.update_param_groups_visibility(strategy, [
            self.rsiGroup, self.bbGroup, self.macdGroup,
            self.maGroup, self.stochGroup, self.atrGroup
        ])

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
        self.simFeeLabel = QLabel("수수료율:")
        self.simFeeRateSpinBox = QDoubleSpinBox()
        self.simFeeRateSpinBox.setRange(0.0001, 0.01)
        self.simFeeRateSpinBox.setSingleStep(0.0001)
        self.simFeeRateSpinBox.setDecimals(4)
        self.simFeeRateSpinBox.setValue(0.00025)
        self.simFeeRangeLabel = QLabel("(0.01% ~ 1%)")
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
        self.tradeFeeLabel = QLabel("수수료율:")
        self.tradeFeeRateSpinBox = QDoubleSpinBox()
        self.tradeFeeRateSpinBox.setRange(0.0001, 0.01)
        self.tradeFeeRateSpinBox.setSingleStep(0.0001)
        self.tradeFeeRateSpinBox.setDecimals(4)
        self.tradeFeeRateSpinBox.setValue(0.00025)
        self.tradeFeeRangeLabel = QLabel("(0.01% ~ 1%)")
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
            fee_rate = self.simFeeRateSpinBox.value() if hasattr(self, 'simFeeRateSpinBox') else 0.00025
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
        dialog = QDialog(self)
        dialog.setWindowTitle('시뮬레이션 결과 차트')
        dialog.setGeometry(200, 200, 1200, 800)
        layout = QVBoxLayout()
        figure = Figure(figsize=(12, 8))
        canvas = FigureCanvas(figure)
        layout.addWidget(canvas)

        # 가격 차트
        ax1 = figure.add_subplot(211)
        if price_history:
            ax1.plot([t[0] for t in price_history], [t[1] for t in price_history], 'b-', label='가격')
        for t in trade_history:
            if t['type'] == 'buy':
                ax1.scatter(t['time'], t['price'], color='r', marker='^', s=100)
            elif t['type'] == 'sell':
                ax1.scatter(t['time'], t['price'], color='g', marker='v', s=100)
        ax1.set_title('가격 및 매매 시점')
        ax1.set_ylabel('가격')
        ax1.grid(True, alpha=0.3)

        # 자본금 차트
        ax2 = figure.add_subplot(212)
        if balance_history:
            ax2.plot([b[0] for b in balance_history], [b[1] for b in balance_history], 'g-', label='자본금')
        ax2.set_title('자본금 변화')
        ax2.set_xlabel('시간')
        ax2.set_ylabel('자본금')
        ax2.grid(True, alpha=0.3)

        figure.tight_layout()
        canvas.draw()
        close_btn = QPushButton('닫기')
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        dialog.setLayout(layout)
        dialog.exec_()

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

    def generate_rsi_signal(self, price):
        try:
            df = python_bithumb.get_ohlcv(f"KRW-{self.tradeCoinCombo.currentText()}", interval="minute1", count=14)
            if df.empty:
                return None
                
            # RSI 계산
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            if rsi.iloc[-1] < 30:  # 과매도
                return 'buy'
            elif rsi.iloc[-1] > 70:  # 과매수
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"RSI 신호 생성 오류: {str(e)}")
            return None
            
    def generate_bb_signal(self, price):
        try:
            df = python_bithumb.get_ohlcv(f"KRW-{self.tradeCoinCombo.currentText()}", interval="minute1", count=20)
            if df.empty:
                return None
                
            # 볼린저 밴드 계산
            ma20 = df['close'].rolling(window=20).mean()
            std = df['close'].rolling(window=20).std()
            upper = ma20 + (std * 2)
            lower = ma20 - (std * 2)
            
            if price < lower.iloc[-1]:  # 하단 밴드 터치
                return 'buy'
            elif price > upper.iloc[-1]:  # 상단 밴드 터치
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"볼린저 밴드 신호 생성 오류: {str(e)}")
            return None
            
    def generate_macd_signal(self, price):
        try:
            df = python_bithumb.get_ohlcv(f"KRW-{self.tradeCoinCombo.currentText()}", interval="minute1", count=26)
            if df.empty:
                return None
                
            # MACD 계산
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = exp1.ewm(span=9, adjust=False).mean()
            
            if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:  # 골든크로스
                return 'buy'
            elif macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-2] >= signal.iloc[-2]:  # 데드크로스
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"MACD 신호 생성 오류: {str(e)}")
            return None
            
    def generate_ma_signal(self, price):
        try:
            df = python_bithumb.get_ohlcv(f"KRW-{self.tradeCoinCombo.currentText()}", interval="minute1", count=20)
            if df.empty:
                return None
                
            # 이동평균선 계산
            ma5 = df['close'].rolling(window=5).mean()
            ma20 = df['close'].rolling(window=20).mean()
            
            if ma5.iloc[-1] > ma20.iloc[-1] and ma5.iloc[-2] <= ma20.iloc[-2]:  # 골든크로스
                return 'buy'
            elif ma5.iloc[-1] < ma20.iloc[-1] and ma5.iloc[-2] >= ma20.iloc[-2]:  # 데드크로스
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"이동평균선 신호 생성 오류: {str(e)}")
            return None
            
    def generate_stochastic_signal(self, price):
        try:
            df = python_bithumb.get_ohlcv(f"KRW-{self.tradeCoinCombo.currentText()}", interval="minute1", count=14)
            if df.empty:
                return None
                
            # 스토캐스틱 계산
            low_min = df['low'].rolling(window=14).min()
            high_max = df['high'].rolling(window=14).max()
            k = 100 * ((df['close'] - low_min) / (high_max - low_min))
            d = k.rolling(window=3).mean()
            
            if k.iloc[-1] < 20 and d.iloc[-1] < 20:  # 과매도
                return 'buy'
            elif k.iloc[-1] > 80 and d.iloc[-1] > 80:  # 과매수
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"스토캐스틱 신호 생성 오류: {str(e)}")
            return None
            
    def generate_atr_signal(self, price):
        """ATR 기반 변동성 돌파 전략 시그널 생성"""
        try:
            # ATR 계산
            atr = self.calculate_atr(price['high'], price['low'], price['close'], self.atrPeriod.value())
            
            # 변동성 계수 계산 (최근 20일 기준)
            volatility = atr / price['close'][-1]
            
            # 동적 승수 조정 (변동성에 따라)
            base_multiplier = self.atrMultiplier.value()
            dynamic_multiplier = base_multiplier * (1 + volatility * 10)
            
            # 상단/하단 돌파선 계산
            upper_band = price['close'][-1] + (atr * dynamic_multiplier)
            lower_band = price['close'][-1] - (atr * dynamic_multiplier)
            
            # RSI 추가 (과매수/과매도 확인)
            rsi = self.calculate_rsi(price['close'], 14)
            current_rsi = rsi[-1]
            
            # 볼린저 밴드 추가 (추가 필터)
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(price['close'], 20, 2)
            
            signal = 0
            reason = []
            
            # 매수 조건
            if (price['close'][-1] < lower_band and 
                current_rsi < 30 and 
                price['close'][-1] < bb_lower[-1]):
                signal = 1
                reason.append(f"ATR 하단 돌파 (동적 승수: {dynamic_multiplier:.2f})")
                reason.append(f"RSI 과매도 ({current_rsi:.1f})")
                reason.append("볼린저 밴드 하단 돌파")
            
            # 매도 조건
            elif (price['close'][-1] > upper_band and 
                  current_rsi > 70 and 
                  price['close'][-1] > bb_upper[-1]):
                signal = -1
                reason.append(f"ATR 상단 돌파 (동적 승수: {dynamic_multiplier:.2f})")
                reason.append(f"RSI 과매수 ({current_rsi:.1f})")
                reason.append("볼린저 밴드 상단 돌파")
            
            return signal, reason
            
        except Exception as e:
            print(f"ATR 시그널 생성 중 오류: {str(e)}")
            return 0, ["오류 발생"]

    def generate_short_percent_signal(self, price):
        try:
            if len(self.realtime_price_data) >= 2:
                price_change = (price - self.realtime_price_data[-2]) / self.realtime_price_data[-2] * 100
                
                if price_change < -0.5:  # 0.5% 이상 하락
                    return 'buy'
                elif price_change > 0.5:  # 0.5% 이상 상승
                    return 'sell'
                    
            return None
            
        except Exception as e:
            print(f"ShortPercent 신호 생성 오류: {str(e)}")
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
            
    def buy_market_order(self, investment):
        try:
            coin = self.tradeCoinCombo.currentText()
            price = python_bithumb.get_current_price(f"KRW-{coin}")
            if not price:
                return
                
            quantity = investment / price
            # 실제 매수 주문 실행
            # python_bithumb.buy_market_order(f"KRW-{coin}", quantity)
            
        except Exception as e:
            print(f"매수 주문 오류: {str(e)}")
            
    def sell_market_order(self, investment):
        try:
            coin = self.tradeCoinCombo.currentText()
            price = python_bithumb.get_current_price(f"KRW-{coin}")
            if not price:
                return
                
            quantity = investment / price
            # 실제 매도 주문 실행
            # python_bithumb.sell_market_order(f"KRW-{coin}", quantity)
            
        except Exception as e:
            print(f"매도 주문 오류: {str(e)}")
            
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
        low_min = low.rolling(window=period).min()
        high_max = high.rolling(window=period).max()
        k = 100 * ((close - low_min) / (high_max - low_min))
        d = k.rolling(window=3).mean()
        return k, d
        
    def calculate_atr(self, high, low, close, period):
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean()
        return atr
        
    def calculate_rsi(self, prices, period):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
        
    def calculate_bollinger_bands(self, prices, period, std):
        ma = prices.rolling(window=period).mean()
        std_dev = prices.rolling(window=period).std()
        upper = ma + (std_dev * std)
        lower = ma - (std_dev * std)
        return ma, upper, lower

    def backtest_rsi(self, period, overbought, oversold, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = 'RSI'
            self.last_backtest_params = {'period': period, 'overbought': overbought, 'oversold': oversold}
            # 데이터베이스에서 데이터 로드
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            # RSI 계산 및 신호 생성
            rsi = self.calculate_rsi(df['close'], period)
            df['signal'] = 0
            df.loc[rsi < oversold, 'signal'] = 1
            df.loc[rsi > overbought, 'signal'] = -1
            return self.calculate_backtest_results_with_fee(df, fee_rate=fee_rate)
        except Exception as e:
            self.backtestStatus.append(f"RSI 백테스팅 실패: {str(e)}")
            traceback.print_exc()
            return None

    def backtest_bollinger_bands(self, period, std, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = '볼린저밴드'
            self.last_backtest_params = {'period': period, 'std': std}
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            ma, upper, lower = self.calculate_bollinger_bands(df['close'], period, std)
            df['signal'] = 0
            df.loc[df['close'] < lower, 'signal'] = 1
            df.loc[df['close'] > upper, 'signal'] = -1
            return self.calculate_backtest_results_with_fee(df, fee_rate=fee_rate)
        except Exception as e:
            self.backtestStatus.append(f"볼린저 밴드 백테스팅 실패: {str(e)}")
            traceback.print_exc()
            return None

    def backtest_macd(self, fast_period, slow_period, signal_period, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = 'MACD'
            self.last_backtest_params = {'fast_period': fast_period, 'slow_period': slow_period, 'signal_period': signal_period}
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            macd, signal = self.calculate_macd(df['close'], fast_period, slow_period, signal_period)
            df['signal'] = 0
            df.loc[(macd > signal) & (macd.shift(1) <= signal.shift(1)), 'signal'] = 1
            df.loc[(macd < signal) & (macd.shift(1) >= signal.shift(1)), 'signal'] = -1
            return self.calculate_backtest_results_with_fee(df, fee_rate=fee_rate)
        except Exception as e:
            self.backtestStatus.append(f"MACD 백테스팅 실패: {str(e)}")
            traceback.print_exc()
            return None

    def backtest_moving_averages(self, short_period, long_period, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = '이동평균선 교차'
            self.last_backtest_params = {'short_period': short_period, 'long_period': long_period}
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            short_ma, long_ma = self.calculate_moving_averages(df['close'], short_period, long_period)
            df['signal'] = 0
            df.loc[(short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1)), 'signal'] = 1
            df.loc[(short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1)), 'signal'] = -1
            return self.calculate_backtest_results_with_fee(df, fee_rate=fee_rate)
        except Exception as e:
            self.backtestStatus.append(f"이동평균선 백테스팅 실패: {str(e)}")
            traceback.print_exc()
            return None

    def backtest_stochastic(self, period, k_period, d_period, overbought, oversold, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = '스토캐스틱'
            self.last_backtest_params = {'period': period, 'k_period': k_period, 'd_period': d_period, 'overbought': overbought, 'oversold': oversold}
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            k, d = self.calculate_stochastic(df['high'], df['low'], df['close'], period)
            df['signal'] = 0
            df.loc[(k < oversold) & (d < oversold), 'signal'] = 1
            df.loc[(k > overbought) & (d > overbought), 'signal'] = -1
            return self.calculate_backtest_results_with_fee(df, fee_rate=fee_rate)
        except Exception as e:
            self.backtestStatus.append(f"스토캐스틱 백테스팅 실패: {str(e)}")
            traceback.print_exc()
            return None

    def backtest_atr(self, period, multiplier, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = 'ATR 기반 변동성 돌파'
            self.last_backtest_params = {'period': period, 'multiplier': multiplier}
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            atr = self.calculate_atr(df['high'], df['low'], df['close'], period)
            df['signal'] = 0
            df.loc[df['close'] < df['close'].shift(1) - multiplier * atr, 'signal'] = 1
            df.loc[df['close'] > df['close'].shift(1) + multiplier * atr, 'signal'] = -1
            return self.calculate_backtest_results_with_fee(df, fee_rate=fee_rate)
        except Exception as e:
            self.backtestStatus.append(f"ATR 백테스팅 실패: {str(e)}")
            traceback.print_exc()
            return None

    def calculate_backtest_results(self, df, date_col='index', trades=None, daily_balance=None, final_capital=None, fee_rate=0.0005):
        try:
            # 초기 자본금
            initial_capital = 10000000  # 1000만원
            capital = initial_capital
            position = 0
            max_capital = initial_capital
            min_capital = initial_capital
            total_fee = 0  # 총 수수료

            # trades, daily_balance, final_capital이 인자로 주어지면 그대로 사용
            if trades is not None and daily_balance is not None and final_capital is not None:
                pass  # 아래에서 그대로 사용
            else:
                trades = []
                daily_balance = []
                # 매매 기록
                for i in range(1, len(df)):
                    current_balance = capital + (position * df['close'].iloc[i])
                    daily_balance.append({
                        'date': df.index[i],
                        'balance': current_balance,
                        'position': position
                    })
                    if 'signal' in df.columns:
                        if df['signal'].iloc[i] == 1 and position == 0:  # 매수
                            position = capital / df['close'].iloc[i]
                            fee = self.calculate_fee(capital, df['close'].iloc[i], fee_rate)
                            total_fee += fee
                            capital = 0
                            trades.append({
                                'date': df.index[i],
                                'type': 'buy',
                                'price': df['close'].iloc[i],
                                'position': position,
                                'balance': capital,
                                'fee': fee
                            })
                        elif df['signal'].iloc[i] == -1 and position > 0:  # 매도
                            capital = position * df['close'].iloc[i]
                            fee = self.calculate_fee(capital, df['close'].iloc[i], fee_rate)
                            total_fee += fee
                            capital -= fee
                            trades.append({
                                'date': df.index[i],
                                'type': 'sell',
                                'price': df['close'].iloc[i],
                                'capital': capital,
                                'position': 0,
                                'fee': fee
                            })
                            position = 0
                    # 최대/최소 자본금 업데이트
                    max_capital = max(max_capital, current_balance)
                    min_capital = min(min_capital, current_balance)
                # 최종 자본금 계산
                if position > 0:
                    final_capital = position * df['close'].iloc[-1]
                else:
                    final_capital = capital

            # 수익률 계산 (수수료 포함)
            profit_rate = (final_capital - initial_capital - total_fee) / initial_capital * 100
            # MDD (Maximum Drawdown) 계산
            mdd = (max_capital - min_capital) / max_capital * 100
            # 승률 계산
            sell_trades = [t for t in trades if t['type'] == 'sell']
            if sell_trades:
                profitable_trades = sum(1 for t in sell_trades if t.get('capital', 0) > initial_capital)
                win_rate = profitable_trades / len(sell_trades) * 100
            else:
                win_rate = 0
            # 평균 수익률 계산
            if trades:
                profit_rates = []
                for i in range(1, len(trades)):
                    if trades[i]['type'] == 'sell':
                        buy_price = trades[i-1]['price']
                        sell_price = trades[i]['price']
                        profit_rate = (sell_price - buy_price) / buy_price * 100
                        profit_rates.append(profit_rate)
                avg_profit_rate = sum(profit_rates) / len(profit_rates) if profit_rates else 0
            else:
                avg_profit_rate = 0

            # 결과 출력
            self.backtestStatus.append(f"\n=== 백테스팅 결과 ===")
            self.backtestStatus.append(f"초기 자본금: {initial_capital:,.0f}원")
            self.backtestStatus.append(f"최종 자본금: {final_capital:,.0f}원")
            self.backtestStatus.append(f"총 수수료: {total_fee:,.0f}원")
            self.backtestStatus.append(f"수익률: {profit_rate:.2f}%")
            self.backtestStatus.append(f"MDD: {mdd:.2f}%")
            self.backtestStatus.append(f"승률: {win_rate:.2f}%")
            self.backtestStatus.append(f"평균 수익률: {avg_profit_rate:.2f}%")
            self.backtestStatus.append(f"총 거래 횟수: {len(trades)}회")

            # 거래 내역 저장
            if trades:
                try:
                    # 거래 내역을 DataFrame으로 변환
                    trades_df = pd.DataFrame(trades)
                    # 거래 내역 저장
                    conn = sqlite3.connect('backtest_results.db')
                    table_name = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    trades_df.to_sql(table_name, conn, if_exists='replace', index=False)
                    # 백테스팅 결과 저장
                    results_df = pd.DataFrame([{
                        'initial_capital': initial_capital,
                        'final_capital': final_capital,
                        'total_fee': total_fee,
                        'profit_rate': profit_rate,
                        'mdd': mdd,
                        'win_rate': win_rate,
                        'avg_profit_rate': avg_profit_rate,
                        'total_trades': len(trades),
                        'start_date': df.index[0],
                        'end_date': df.index[-1]
                    }])
                    results_df.to_sql(f"results_{table_name}", conn, if_exists='replace', index=False)
                    conn.close()
                    self.backtestStatus.append(f"\n거래 내역이 {table_name} 테이블에 저장되었습니다.")
                except Exception as e:
                    self.backtestStatus.append(f"\n거래 내역 저장 중 오류 발생: {str(e)}")

                # 거래 내역 표시
                self.show_trade_log_signal.emit(trades)

            # 차트 표시
            self.plot_backtest_results(df, trades, final_capital, daily_balance)

        except Exception as e:
            self.backtestStatus.append(f"백테스팅 결과 계산 실패: {str(e)}")
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
            gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1])
            ax1 = fig.add_subplot(gs[0])
            ax2 = fig.add_subplot(gs[1], sharex=ax1)

            # 가격 차트
            ax1.plot(df.index, df['close'], label='가격', color='blue', alpha=0.5)
            # 매매 신호 표시 (매수/매도)
            for trade in trades:
                if trade['type'] == 'buy':
                    ax1.scatter(trade['date'], trade['price'], color='red', marker='^', s=100, label='매수')
                    if 'exit_date' in trade and 'exit_price' in trade:
                        ax1.scatter(trade['exit_date'], trade['exit_price'], color='green', marker='v', s=100, label='매도')
            # 중복 label 제거
            handles, labels = ax1.get_legend_handles_labels()
            by_label = dict(zip(labels, handles))
            ax1.legend(by_label.values(), by_label.keys())

            # 자본금 변화 그래프
            has_balance = False
            if isinstance(daily_balance, list):
                try:
                    daily_balance_df = pd.DataFrame(daily_balance)
                    if 'date' in daily_balance_df.columns and 'balance' in daily_balance_df.columns and not daily_balance_df.empty:
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

            ax1.set_title('가격 및 매매 시점')
            ax1.set_ylabel('가격')
            ax1.grid(True)
            ax2.set_title('자본금 변화')
            ax2.set_xlabel('날짜')
            ax2.set_ylabel('자본금')
            ax2.grid(True)
            fig.autofmt_xdate()
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

    def fetch_and_store_ohlcv_full(self):
        """2013년부터 오늘까지 1분봉 전체 데이터를 받아 DB에 저장하고, 이후에는 DB에 없는 구간만 추가로 저장"""
        def run_data_collection():
            try:
                import time
                from datetime import datetime, timedelta
                coin = self.dataCoinCombo.currentText()
                exchange = self.exchangeCombo.currentText()
                interval = '1분봉'
                interval_value = '1m'
                interval_db = 'minute1'
                duplicate_handling = self.duplicateCombo.currentText()
                duplicate_mapping = {
                    '덮어쓰기': 'replace',
                    '건너뛰기': 'skip',
                    '오류 발생': 'error'
                }
                duplicate_value = duplicate_mapping.get(duplicate_handling, 'error')
                db_file = 'ohlcv.db'
                table_name = f"{coin}_ohlcv_{interval_db}"
                
                self.update_data_result.emit("데이터 수집 시작...")
                
                conn = sqlite3.connect(db_file)
                cursor = conn.cursor()
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        date TEXT PRIMARY KEY,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL
                    )
                """)
                
                # DB에서 가장 최근 date 구하기
                cursor.execute(f"SELECT MAX(date) FROM {table_name}")
                last_date = cursor.fetchone()[0]
                if last_date:
                    since_dt = datetime.strptime(last_date, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=1)
                else:
                    since_dt = datetime(2013, 1, 1, 0, 0, 0)
                end_dt = datetime.now()
                
                self.update_data_result.emit(f"수집 기간: {since_dt} ~ {end_dt}")
                self.update_data_result.emit("데이터 수집 중... (잠시만 기다려주세요)")
                
                # 업비트 기준, 1회 200개 제한, 최신부터 과거로
                count = 0
                current_dt = end_dt
                total_days = (end_dt - since_dt).days
                processed_days = 0
                last_processed_dt = None
                error_count = 0
                max_retries = 3
                
                while current_dt > since_dt:
                    try:
                        # 진행률 계산 및 표시
                        processed_days = (end_dt - current_dt).days
                        progress = (processed_days / total_days) * 100 if total_days > 0 else 0
                        self.update_data_result.emit(f"진행률: {progress:.1f}% ({processed_days}/{total_days}일)")
                        self.update_data_result.emit(f"현재 처리 중인 시간: {current_dt}")
                        self.update_data_result.emit(f"수집된 데이터 수: {count}개")
                        self.update_data_result.emit(f"다음 요청까지 1초 대기 중...")
                        
                        # API 호출 시 to 파라미터는 현재 시간부터 과거로 가져오기
                        url = f"https://api.upbit.com/v1/candles/minutes/1"
                        params = {
                            'market': f"KRW-{coin}",
                            'to': current_dt.strftime('%Y-%m-%d %H:%M:%S'),
                            'count': 200  # 최대 200개씩 가져오기
                        }
                        
                        # 재시도 로직 추가
                        retry_count = 0
                        while retry_count < max_retries:
                            try:
                                response = requests.get(url, params=params)
                                if response.status_code == 429:  # Too Many Requests
                                    wait_time = int(response.headers.get('Retry-After', 60))
                                    self.update_data_result.emit(f"API 요청 제한 도달. {wait_time}초 대기...")
                                    time.sleep(wait_time)
                                    retry_count += 1
                                    continue
                                response.raise_for_status()
                                data = response.json()
                                break
                            except requests.exceptions.RequestException as e:
                                retry_count += 1
                                if retry_count == max_retries:
                                    raise
                                wait_time = 2 ** retry_count  # 지수 백오프
                                self.update_data_result.emit(f"API 요청 실패. {wait_time}초 후 재시도... ({retry_count}/{max_retries})")
                                time.sleep(wait_time)
                        
                        if not data:
                            self.update_data_result.emit(f"데이터가 없습니다. 다음 구간으로 이동합니다. (현재: {current_dt})")
                            current_dt = current_dt - timedelta(hours=1)  # 1시간씩 과거로 이동
                            continue
                            
                        # 데이터를 시간순으로 정렬
                        data.sort(key=lambda x: x['candle_date_time_kst'])
                        
                        batch_count = 0
                        oldest_dt = None
                        
                        for candle in data:
                            dt = datetime.strptime(candle['candle_date_time_kst'], '%Y-%m-%dT%H:%M:%S')
                            if dt < since_dt:
                                continue
                                
                            if oldest_dt is None or dt < oldest_dt:
                                oldest_dt = dt
                                
                            date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                            try:
                                cursor.execute(f'''
                                    INSERT INTO {table_name} (date, open, high, low, close, volume)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                ''', (
                                    date_str,
                                    candle['opening_price'],
                                    candle['high_price'],
                                    candle['low_price'],
                                    candle['trade_price'],
                                    candle['candle_acc_trade_volume']
                                ))
                                count += 1
                                batch_count += 1
                            except sqlite3.IntegrityError:
                                if duplicate_value == 'replace':
                                    cursor.execute(f'''
                                        UPDATE {table_name}
                                        SET open = ?, high = ?, low = ?, close = ?, volume = ?
                                        WHERE date = ?
                                    ''', (
                                        candle['opening_price'],
                                        candle['high_price'],
                                        candle['low_price'],
                                        candle['trade_price'],
                                        candle['candle_acc_trade_volume'],
                                        date_str
                                    ))
                                    count += 1
                                    batch_count += 1
                                elif duplicate_value == 'error':
                                    self.update_data_result.emit(f"[에러] {date_str} 중복 데이터 오류")
                                    raise
                                else:
                                    continue
                        
                        if batch_count > 0:
                            self.update_data_result.emit(f"현재 구간 저장 완료: {batch_count}건")
                            conn.commit()  # 배치 단위로 커밋
                        
                        # 다음 조회를 위한 시간 설정
                        if oldest_dt:
                            current_dt = oldest_dt - timedelta(minutes=1)  # 가장 오래된 데이터의 1분 전으로 이동
                        else:
                            current_dt = current_dt - timedelta(hours=1)  # 데이터가 없는 경우 1시간씩 과거로 이동
                            
                        # 무한 루프 방지
                        if last_processed_dt and current_dt >= last_processed_dt:
                            current_dt = last_processed_dt - timedelta(hours=1)
                        last_processed_dt = current_dt
                            
                        time.sleep(1)  # API rate limit 대응
                        
                    except Exception as e:
                        error_count += 1
                        self.update_data_result.emit(f"데이터 수집 중 오류 발생: {str(e)}")
                        if error_count >= 10:  # 연속 10번 오류 발생 시 중단
                            self.update_data_result.emit("연속 오류 발생으로 데이터 수집을 중단합니다.")
                            break
                        time.sleep(5)  # 오류 발생 시 5초 대기
                        continue
                        
                conn.commit()
                conn.close()
                self.update_data_result.emit(f"전체 1분봉 데이터 저장 완료: 총 {count}건")
                if error_count > 0:
                    self.update_data_result.emit(f"주의: {error_count}개의 오류가 발생했습니다.")
                
            except Exception as e:
                self.update_data_result.emit(f"데이터 수집 중 치명적 오류 발생: {str(e)}")
                traceback.print_exc()
        
        # 데이터 수집을 별도 스레드로 실행
        collection_thread = threading.Thread(target=run_data_collection)
        collection_thread.daemon = True
        collection_thread.start()

    def optimize_parameters(self, strategy, df, param_ranges):
        """파라미터 최적화 함수 개선"""
        best_sharpe = -float('inf')
        best_params = None
        results = []
        
        # 그리드 서치를 통한 파라미터 최적화
        param_combinations = self.generate_param_combinations(param_ranges)
        total_combinations = len(param_combinations)
        
        for i, params in enumerate(param_combinations):
            try:
                # 진행률 표시
                progress = (i + 1) / total_combinations * 100
                self.backtestStatus.append(f"최적화 진행률: {progress:.1f}%")
                
                # 파라미터 적용
                if strategy == 'ATR 기반 변동성 돌파':
                    df_copy = df.copy()
                    atr = self.calculate_atr(df_copy['high'], df_copy['low'], df_copy['close'], params['atr_period'])
                    multiplier = params['atr_multiplier']
                    
                    # 동적 승수 적용
                    volatility = atr / df_copy['close']
                    dynamic_multiplier = multiplier * (1 + volatility * 10)
                    
                    upper_band = df_copy['close'] + (atr * dynamic_multiplier)
                    lower_band = df_copy['close'] - (atr * dynamic_multiplier)
                    
                    # RSI 계산
                    rsi = self.calculate_rsi(df_copy['close'], 14)
                    
                    # 볼린저 밴드 계산
                    bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df_copy['close'], 20, 2)
                    
                    # 시그널 생성
                    signals = []
                    for i in range(len(df_copy)):
                        if (df_copy['close'].iloc[i] < lower_band.iloc[i] and 
                            rsi.iloc[i] < 30 and 
                            df_copy['close'].iloc[i] < bb_lower.iloc[i]):
                            signals.append(1)
                        elif (df_copy['close'].iloc[i] > upper_band.iloc[i] and 
                              rsi.iloc[i] > 70 and 
                              df_copy['close'].iloc[i] > bb_upper.iloc[i]):
                            signals.append(-1)
                        else:
                            signals.append(0)
                    
                    df_copy['signal'] = signals
                
                # 백테스트 실행
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value())
                
                # 결과 저장
                results.append({
                    'params': params,
                    'performance': performance
                })
                
                # 최적 파라미터 업데이트
                if performance['sharpe_ratio'] > best_sharpe:
                    best_sharpe = performance['sharpe_ratio']
                    best_params = params
                    
            except Exception as e:
                print(f"파라미터 최적화 중 오류 발생: {str(e)}")
                continue
        
        return best_params, results

    def generate_param_combinations(self, param_ranges):
        """파라미터 조합을 생성하는 메서드"""
        import itertools
        
        # 파라미터 범위를 리스트로 변환
        param_lists = {}
        for param, range_info in param_ranges.items():
            if isinstance(range_info, dict):
                start = range_info['start']
                end = range_info['end']
                step = range_info.get('step', 1)
                param_lists[param] = list(np.arange(start, end + step, step))
            else:
                param_lists[param] = range_info

        # 모든 조합 생성
        keys = param_lists.keys()
        values = param_lists.values()
        for combination in itertools.product(*values):
            yield dict(zip(keys, combination))

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

    def cross_validate_strategy(self, strategy, df, n_splits=5):
        """교차 검증을 수행하는 메서드"""
        try:
            # 데이터를 n_splits 개의 구간으로 나누기
            split_size = len(df) // n_splits
            results = []
            
            for i in range(n_splits):
                # 테스트 데이터 선택
                test_start = i * split_size
                test_end = (i + 1) * split_size
                test_df = df.iloc[test_start:test_end].copy()
                
                # 학습 데이터 선택 (테스트 데이터를 제외한 나머지)
                train_df = pd.concat([df.iloc[:test_start], df.iloc[test_end:]]).copy()
                
                # 학습 데이터로 파라미터 최적화
                param_ranges = self.get_param_ranges(strategy)
                best_params, _ = self.optimize_parameters(strategy, train_df, param_ranges)
                
                # 최적화된 파라미터로 테스트 데이터 검증
                if strategy == 'RSI':
                    self.backtest_rsi(test_df, best_params['period'], best_params['overbought'], best_params['oversold'])
                elif strategy == '볼린저밴드':
                    self.backtest_bollinger_bands(test_df, best_params['period'], best_params['std'])
                # ... 다른 전략들도 추가 ...
                
                # 성과 지표 계산
                performance = self.calculate_performance_metrics(test_df)
                results.append({
                    'split': i + 1,
                    'params': best_params,
                    'performance': performance
                })
            
            # 전체 결과 요약
            summary = {
                'avg_sharpe': np.mean([r['performance']['sharpe_ratio'] for r in results]),
                'avg_sortino': np.mean([r['performance']['sortino_ratio'] for r in results]),
                'avg_mdd': np.mean([r['performance']['mdd'] for r in results]),
                'avg_win_rate': np.mean([r['performance']['win_rate'] for r in results]),
                'avg_profit_factor': np.mean([r['performance']['profit_factor'] for r in results]),
                'avg_annual_return': np.mean([r['performance']['annual_return'] for r in results])
            }
            
            return results, summary
            
        except Exception as e:
            print(f"교차 검증 중 오류 발생: {str(e)}")
            return None, None

    def get_param_ranges(self, strategy):
        """전략별 파라미터 범위 설정"""
        if strategy == 'ATR 기반 변동성 돌파':
            return {
                'atr_period': range(5, 31, 5),  # 5~30
                'atr_multiplier': [x/10 for x in range(10, 51, 5)]  # 1.0~5.0
            }
        # ... 다른 전략들의 파라미터 범위 ...
        return {}

    def show_optimization_results(self, results, summary):
        """최적화 결과를 표시하는 메서드 개선"""
        dialog = QDialog(self)
        dialog.setWindowTitle('파라미터 최적화 결과')
        dialog.setGeometry(300, 200, 1000, 800)
        
        layout = QVBoxLayout()
        
        # 요약 정보 표시
        summary_group = QGroupBox("전체 성과 요약")
        summary_layout = QFormLayout()
        summary_layout.addRow("평균 샤프 비율:", QLabel(f"{summary['avg_sharpe']:.2f}"))
        summary_layout.addRow("평균 소르티노 비율:", QLabel(f"{summary['avg_sortino']:.2f}"))
        summary_layout.addRow("평균 최대 낙폭:", QLabel(f"{summary['avg_mdd']:.2%}"))
        summary_layout.addRow("평균 승률:", QLabel(f"{summary['avg_win_rate']:.2%}"))
        summary_layout.addRow("평균 손익비:", QLabel(f"{summary['avg_profit_factor']:.2f}"))
        summary_layout.addRow("평균 연간 수익률:", QLabel(f"{summary['avg_annual_return']:.2%}"))
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        # 상위 10개 결과 표시
        top_results_group = QGroupBox("상위 10개 파라미터 조합")
        top_results_layout = QVBoxLayout()
        
        results_table = QTableWidget()
        results_table.setColumnCount(8)
        results_table.setHorizontalHeaderLabels([
            "순위", "파라미터", "샤프 비율", "소르티노 비율", 
            "최대 낙폭", "승률", "손익비", "연간 수익률"
        ])
        
        # 결과 정렬
        sorted_results = sorted(results, key=lambda x: x['performance']['sharpe_ratio'], reverse=True)
        
        # 상위 10개 결과 표시
        results_table.setRowCount(min(10, len(sorted_results)))
        for i, result in enumerate(sorted_results[:10]):
            params = result['params']
            perf = result['performance']
            
            results_table.setItem(i, 0, QTableWidgetItem(str(i+1)))
            results_table.setItem(i, 1, QTableWidgetItem(str(params)))
            results_table.setItem(i, 2, QTableWidgetItem(f"{perf['sharpe_ratio']:.2f}"))
            results_table.setItem(i, 3, QTableWidgetItem(f"{perf['sortino_ratio']:.2f}"))
            results_table.setItem(i, 4, QTableWidgetItem(f"{perf['max_drawdown']:.2%}"))
            results_table.setItem(i, 5, QTableWidgetItem(f"{perf['win_rate']:.2%}"))
            results_table.setItem(i, 6, QTableWidgetItem(f"{perf['profit_factor']:.2f}"))
            results_table.setItem(i, 7, QTableWidgetItem(f"{perf['annual_return']:.2%}"))
        
        top_results_layout.addWidget(results_table)
        top_results_group.setLayout(top_results_layout)
        layout.addWidget(top_results_group)
        
        # 확인 버튼
        ok_button = QPushButton("확인")
        ok_button.clicked.connect(dialog.accept)
        layout.addWidget(ok_button)
        
        dialog.setLayout(layout)
        dialog.exec_()

    def calculate_fee(self, amount, price, fee_rate=0.0005):
        """거래 수수료 계산 (기본값 0.05%)"""
        return amount * price * fee_rate

    def apply_fee_to_trade(self, trade, fee_rate=0.0005):
        """거래에 수수료 적용"""
        if trade['type'] == 'buy':
            fee = self.calculate_fee(trade['amount'], trade['price'], fee_rate)
            trade['fee'] = fee
            trade['total_cost'] = trade['amount'] * trade['price'] + fee
        else:  # sell
            fee = self.calculate_fee(trade['amount'], trade['price'], fee_rate)
            trade['fee'] = fee
            trade['total_revenue'] = trade['amount'] * trade['price'] - fee
        return trade

    def optimize_fee_rate(self, df, strategy, fee_range=(0.0001, 0.001, 0.0001)):
        """수수료율 최적화"""
        best_fee_rate = None
        best_sharpe = -float('inf')
        results = []

        for fee_rate in np.arange(fee_range[0], fee_range[1], fee_range[2]):
            try:
                df_copy = df.copy()
                self.calculate_backtest_results_with_fee(df_copy, fee_rate=fee_rate)
                performance = self.calculate_performance_metrics(df_copy)
                
                results.append({
                    'fee_rate': fee_rate,
                    'performance': performance
                })

                if performance['sharpe_ratio'] > best_sharpe:
                    best_sharpe = performance['sharpe_ratio']
                    best_fee_rate = fee_rate

            except Exception as e:
                print(f"수수료율 최적화 중 오류 발생: {str(e)}")
                continue

        return best_fee_rate, results

    def optimize_with_optuna(self, strategy, df, n_trials=100):
        import optuna
        best_trial = {'sharpe_ratio': -float('inf'), 'params': None}
        self.backtestStatus.append(f"[Optuna 최적화 시작] 총 {n_trials}회 시도 예정...")
        def objective(trial):
            trial_num = trial.number + 1
            if strategy == 'ATR 기반 변동성 돌파':
                atr_period = trial.suggest_int('atr_period', 5, 30)
                atr_multiplier = trial.suggest_float('atr_multiplier', 1.0, 5.0)
                df_copy = df.copy()
                atr = self.calculate_atr(df_copy['high'], df_copy['low'], df_copy['close'], atr_period)
                volatility = atr / df_copy['close']
                dynamic_multiplier = atr_multiplier * (1 + volatility * 10)
                upper_band = df_copy['close'] + (atr * dynamic_multiplier)
                lower_band = df_copy['close'] - (atr * dynamic_multiplier)
                rsi = self.calculate_rsi(df_copy['close'], 14)
                bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df_copy['close'], 20, 2)
                signals = []
                for i in range(len(df_copy)):
                    if (df_copy['close'].iloc[i] < lower_band.iloc[i] and rsi.iloc[i] < 30 and df_copy['close'].iloc[i] < bb_lower.iloc[i]):
                        signals.append(1)
                    elif (df_copy['close'].iloc[i] > upper_band.iloc[i] and rsi.iloc[i] > 70 and df_copy['close'].iloc[i] > bb_upper.iloc[i]):
                        signals.append(-1)
                    else:
                        signals.append(0)
                df_copy['signal'] = signals
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                # 거래가 2회 미만이면 무효
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == 'RSI':
                rsi_period = trial.suggest_int('rsi_period', 5, 30)
                overbought = trial.suggest_int('overbought', 60, 90)
                oversold = trial.suggest_int('oversold', 10, 40)
                df_copy = df.copy()
                rsi = self.calculate_rsi(df_copy['close'], rsi_period)
                df_copy['signal'] = 0
                df_copy.loc[rsi < oversold, 'signal'] = 1
                df_copy.loc[rsi > overbought, 'signal'] = -1
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                # 거래가 2회 미만이면 무효
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == '볼린저밴드':
                bb_period = trial.suggest_int('bb_period', 5, 30)
                bb_std = trial.suggest_float('bb_std', 1.0, 3.0)
                df_copy = df.copy()
                ma, upper, lower = self.calculate_bollinger_bands(df_copy['close'], bb_period, bb_std)
                df_copy['signal'] = 0
                df_copy.loc[df_copy['close'] < lower, 'signal'] = 1
                df_copy.loc[df_copy['close'] > upper, 'signal'] = -1
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == 'MACD':
                fast_period = trial.suggest_int('fast_period', 5, 20)
                slow_period = trial.suggest_int('slow_period', 21, 40)
                signal_period = trial.suggest_int('signal_period', 5, 20)
                df_copy = df.copy()
                macd, signal = self.calculate_macd(df_copy['close'], fast_period, slow_period, signal_period)
                df_copy['signal'] = 0
                df_copy.loc[(macd > signal) & (macd.shift(1) <= signal.shift(1)), 'signal'] = 1
                df_copy.loc[(macd < signal) & (macd.shift(1) >= signal.shift(1)), 'signal'] = -1
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == '이동평균선 교차':
                short_period = trial.suggest_int('short_period', 5, 20)
                long_period = trial.suggest_int('long_period', 21, 60)
                df_copy = df.copy()
                short_ma, long_ma = self.calculate_moving_averages(df_copy['close'], short_period, long_period)
                df_copy['signal'] = 0
                df_copy.loc[(short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1)), 'signal'] = 1
                df_copy.loc[(short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1)), 'signal'] = -1
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == '스토캐스틱':
                stoch_period = trial.suggest_int('stoch_period', 5, 20)
                k_period = trial.suggest_int('k_period', 3, 10)
                d_period = trial.suggest_int('d_period', 3, 10)
                overbought = trial.suggest_int('overbought', 60, 90)
                oversold = trial.suggest_int('oversold', 10, 40)
                df_copy = df.copy()
                k, d = self.calculate_stochastic(df_copy['high'], df_copy['low'], df_copy['close'], stoch_period)
                df_copy['signal'] = 0
                df_copy.loc[(k < oversold) & (d < oversold), 'signal'] = 1
                df_copy.loc[(k > overbought) & (d > overbought), 'signal'] = -1
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == '거래량 프로파일':
                num_bins = trial.suggest_int('num_bins', 10, 30)
                threshold = trial.suggest_float('threshold', 0.1, 0.3)
                df_copy = df.copy()
                bins, volume_profile = self.calculate_volume_profile(df_copy, num_bins)
                volume_threshold = np.percentile(volume_profile, 100 * (1 - threshold))
                signals = []
                for i in range(len(df_copy)):
                    price = df_copy['close'].iloc[i]
                    bin_idx = np.digitize(price, bins) - 1
                    if bin_idx < 0 or bin_idx >= len(volume_profile):
                        signals.append(0)
                        continue
                    if volume_profile[bin_idx] >= volume_threshold:
                        signals.append(1)
                    else:
                        signals.append(-1)
                df_copy['signal'] = signals
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            elif strategy == '머신러닝':
                n_estimators = trial.suggest_int('n_estimators', 50, 200)
                max_depth = trial.suggest_int('max_depth', 3, 10)
                random_state = 42
                df_copy = df.copy()
                from sklearn.ensemble import RandomForestClassifier
                from sklearn.preprocessing import StandardScaler
                df_copy['returns'] = df_copy['close'].pct_change()
                df_copy['volume_change'] = df_copy['volume'].pct_change()
                df_copy['rsi'] = self.calculate_rsi(df_copy['close'], 14)
                df_copy['macd'], _ = self.calculate_macd(df_copy['close'], 12, 26, 9)
                df_copy['bb_upper'], df_copy['bb_middle'], df_copy['bb_lower'] = self.calculate_bollinger_bands(df_copy['close'], 20, 2)
                df_copy['target'] = (df_copy['close'].shift(-1) > df_copy['close']).astype(int)
                features = ['returns', 'volume_change', 'rsi', 'macd', 'bb_upper', 'bb_middle', 'bb_lower']
                X = df_copy[features].dropna()
                y = df_copy['target'].dropna()
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)
                model = RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, random_state=random_state)
                model.fit(X_scaled[:-1], y[:-1])
                signals = []
                for i in range(30, len(df_copy)):
                    current_data = df_copy.iloc[:i+1]
                    if len(current_data) < 30:
                        signals.append(0)
                        continue
                    X_pred = current_data[features].iloc[[-1]].values
                    X_pred_scaled = scaler.transform(X_pred)
                    prediction = model.predict_proba(X_pred_scaled)[0]
                    if prediction[1] > 0.7:
                        signals.append(1)
                    elif prediction[0] > 0.7:
                        signals.append(-1)
                    else:
                        signals.append(0)
                df_copy['signal'] = [0]*30 + signals  # 앞 30개는 신호 없음
                performance = self.calculate_backtest_results_with_fee(df_copy, fee_rate=self.feeRateSpinBox.value(), show_ui=False)
                if performance.get('total_trades', 0) < 2:
                    return -9999
                sharpe = performance.get('sharpe_ratio', 0.0)
            else:
                sharpe = 0.0
            if sharpe > best_trial['sharpe_ratio']:
                best_trial['sharpe_ratio'] = sharpe
                best_trial['params'] = trial.params.copy()
            self.backtestStatus.append(f"{trial_num}/{n_trials}: 샤프비율 {sharpe:.4f} (파라미터: {trial.params}, 거래수: {performance.get('total_trades', 0)})")
            return sharpe
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials)
        self.backtestStatus.append("\n[최적화 결과 요약]")
        self.backtestStatus.append(f"최고 샤프비율: {best_trial['sharpe_ratio']:.4f}")
        self.backtestStatus.append(f"최적 파라미터: {best_trial['params']}")
        return best_trial['params'], best_trial['sharpe_ratio']

    def show_optuna_results(self, best_params, best_value):
        """Optuna 최적화 결과 표시"""
        dialog = QDialog(self)
        dialog.setWindowTitle('Optuna 최적화 결과')
        dialog.setGeometry(300, 200, 600, 400)
        
        layout = QVBoxLayout()
        
        # 최적 파라미터 표시
        params_group = QGroupBox("최적 파라미터")
        params_layout = QFormLayout()
        
        for param, value in best_params.items():
            params_layout.addRow(f"{param}:", QLabel(f"{value:.4f}"))
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # 최적 성과 지표 표시
        performance_group = QGroupBox("최적 성과")
        performance_layout = QFormLayout()
        performance_layout.addRow("최고 샤프 비율:", QLabel(f"{best_value:.4f}"))
        
        performance_group.setLayout(performance_layout)
        layout.addWidget(performance_group)
        
        # 확인 버튼
        ok_button = QPushButton("확인")
        ok_button.clicked.connect(dialog.accept)
        layout.addWidget(ok_button)
        
        dialog.setLayout(layout)
        dialog.exec_()

    def run_optuna_optimization(self):
        try:
            # 데이터 가져오기
            start_date = self.backtestStartDate.date().toPyDate()
            end_date = self.backtestEndDate.date().toPyDate()
            interval = self.backtestIntervalCombo.currentText()
            strategy = self.strategyCombo.currentText()
            conn = sqlite3.connect('ohlcv.db')
            cursor = conn.cursor()
            table_name = self.get_table_name(self.backtestCoinCombo.currentText(), interval)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.backtestStatus.append(f"테이블 '{table_name}'이 존재하지 않습니다.")
                conn.close()
                return
            start_datetime = f"{start_date} 00:00:00"
            end_datetime = f"{end_date} 23:59:59"
            df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE date BETWEEN ? AND ?", conn, params=(start_datetime, end_datetime))
            conn.close()
            if df.empty:
                self.backtestStatus.append(f"선택한 기간({start_date} ~ {end_date})의 데이터가 없습니다.")
                return
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            n_trials = 50  # 기본값, 필요시 UI에서 조정 가능
            best_params, best_value = self.optimize_with_optuna(strategy, df, n_trials=n_trials)
            # self.show_optuna_results(best_params, best_value)  # 팝업 제거
        except Exception as e:
            self.backtestStatus.append(f"Optuna 최적화 중 오류 발생: {str(e)}")
            traceback.print_exc()

    def calculate_vwap(self, df):
        """거래량 가중 평균가격(VWAP) 계산"""
        vwap = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
        return vwap

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

    def generate_volume_signal(self, price, volume, df):
        """거래량 기반 매매 신호 생성"""
        try:
            # VWAP 계산
            vwap = self.calculate_vwap(df)
            current_vwap = vwap.iloc[-1]
            
            # 거래량 프로파일 계산
            bins, volume_profile = self.calculate_volume_profile(df)
            
            # 거래량 급증 감지
            volume_ma = df['volume'].rolling(window=20).mean()
            volume_std = df['volume'].rolling(window=20).std()
            current_volume = volume
            volume_zscore = (current_volume - volume_ma.iloc[-1]) / volume_std.iloc[-1]
            
            # 가격이 VWAP 아래이고 거래량이 급증하면 매수
            if price < current_vwap and volume_zscore > 2:
                return 'buy'
            # 가격이 VWAP 위이고 거래량이 급증하면 매도
            elif price > current_vwap and volume_zscore > 2:
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"거래량 신호 생성 오류: {str(e)}")
            return None

    def generate_ml_signal(self, price, df):
        """머신러닝 기반 매매 신호 생성"""
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.preprocessing import StandardScaler
            
            # 특성 생성
            df['returns'] = df['close'].pct_change()
            df['volume_change'] = df['volume'].pct_change()
            df['rsi'] = self.calculate_rsi(df['close'], 14)
            df['macd'], _ = self.calculate_macd(df['close'], 12, 26, 9)
            df['bb_upper'], df['bb_middle'], df['bb_lower'] = self.calculate_bollinger_bands(df['close'], 20, 2)
            
            # 타겟 변수 생성 (1: 상승, 0: 하락)
            df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
            
            # 특성 선택
            features = ['returns', 'volume_change', 'rsi', 'macd', 
                       'bb_upper', 'bb_middle', 'bb_lower']
            
            # 데이터 전처리
            X = df[features].dropna()
            y = df['target'].dropna()
            
            # 데이터 스케일링
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            # 모델 학습
            model = RandomForestClassifier(n_estimators=100, random_state=42)
            model.fit(X_scaled[:-1], y[:-1])
            
            # 현재 데이터로 예측
            current_features = scaler.transform(X.iloc[[-1]])
            prediction = model.predict_proba(current_features)[0]
            
            # 예측 확률이 0.7 이상이면 매수/매도 신호 생성
            if prediction[1] > 0.7:  # 상승 확률이 70% 이상
                return 'buy'
            elif prediction[0] > 0.7:  # 하락 확률이 70% 이상
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"머신러닝 신호 생성 오류: {str(e)}")
            return None

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

    # --- 파라미터 값 접근도 탭별로 분리 예시 (start_backtest 등에서) ---
    # 예시: 백테스팅 탭에서
    # if strategy == "RSI":
    #     params = {
    #         'period': self.rsiPeriod.value(),
    #         'overbought': self.rsiOverbought.value(),
    #         'oversold': self.rsiOversold.value()
    #     }
    # 시뮬레이션 탭에서는 self.simRsiPeriod.value() 등 사용
    # 자동매매 탭에서는 self.tradeRsiPeriod.value() 등 사용

    def backtest_volume_profile(self, num_bins, threshold, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = '거래량 프로파일'
            self.last_backtest_params = {'num_bins': num_bins, 'threshold': threshold}
            engine = BacktestEngine(fee_rate=fee_rate)
            df = engine._fetch_historical_data(start_date, end_date, interval)
            if df is None or len(df) < 30:
                return None
            # 거래량 프로파일 계산
            bins, volume_profile = self.calculate_volume_profile(df, num_bins)
            volume_threshold = np.percentile(volume_profile, 100 * (1 - threshold))
            # --- 전략 엔진으로 백테스트 실행 ---
            result = engine.backtest_volume_profile(
                num_bins, start_date, end_date, interval, initial_capital, fee_rate
            )
            self.handle_backtest_results(df, result, initial_capital)
            return result
        except Exception as e:
            print(f"거래량 프로파일 백테스팅 오류: {str(e)}")
            return None

    def backtest_ml(self, n_estimators, max_depth, random_state, start_date, end_date, interval, initial_capital, fee_rate):
        try:
            self.last_backtest_strategy = '머신러닝'
            self.last_backtest_params = {'n_estimators': n_estimators, 'max_depth': max_depth, 'random_state': random_state}
            engine = BacktestEngine(fee_rate=fee_rate)
            df = engine._fetch_historical_data(start_date, end_date, interval)
            if df is None or len(df) < 30:
                return None
            # --- 전략 엔진으로 백테스트 실행 ---
            result = engine.backtest_ml(
                n_estimators, random_state, start_date, end_date, interval, initial_capital, fee_rate
            )
            self.handle_backtest_results(df, result, initial_capital)
            return result
        except Exception as e:
            print(f"머신러닝 백테스팅 오류: {str(e)}")
            return None

    def handle_backtest_results(self, df, result, initial_capital):
        """백테스트 결과 처리"""
        try:
            if result is None:
                return
                
            # 현재 시간
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 전략 이름과 파라미터 가져오기
            strategy = self.strategyCombo.currentText()
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
                    'trend_period': self.atrTrendPeriod.value(),
                    'stop_loss_multiplier': self.atrStopLossMultiplier.value(),
                    'position_size_multiplier': self.atrPositionSizeMultiplier.value()
                }
            elif strategy == '거래량 프로파일':
                params = {
                    'num_bins': self.volumeProfileBins.value()
                }
            elif strategy == '머신러닝':
                params = {
                    'n_estimators': self.mlNEstimators.value(),
                    'max_depth': self.mlMaxDepth.value(),
                    'random_state': self.mlRandomState.value()
                }
            
            # 파라미터를 문자열로 변환
            params_str = json.dumps(params, ensure_ascii=False)
            
            # CSV에 결과 저장
            with open('backtest_results_log.csv', 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    current_time,  # 실행 시간
                    strategy,      # 전략 이름
                    params_str,    # 파라미터
                    initial_capital,  # 초기자본
                    result['final_capital'],  # 최종자본
                    result['profit_rate'],    # 수익률
                    result['win_rate'],       # 승률
                    result['total_trades'],   # 총 거래 횟수
                    df.index[0].date(),       # 시작일
                    df.index[-1].date(),      # 종료일
                    df.index[0],              # 시작 시간
                    df.index[-1],             # 종료 시간
                    self.backtestIntervalCombo.currentText(),  # 시간단위
                    'BTC'                      # 코인
                ])
            
            # 결과 표시
            self.backtestStatus.append(f"=== 백테스트 결과 ===")
            self.backtestStatus.append(f"전략: {strategy}")
            self.backtestStatus.append(f"파라미터: {params_str}")
            self.backtestStatus.append(f"초기자본: {initial_capital:,.0f}원")
            self.backtestStatus.append(f"최종자본: {result['final_capital']:,.0f}원")
            self.backtestStatus.append(f"수익률: {result['profit_rate']:.2f}%")
            self.backtestStatus.append(f"승률: {result['win_rate']:.2f}%")
            self.backtestStatus.append(f"총 거래 횟수: {result['total_trades']}회")
            
            # 차트 표시
            self.plot_backtest_results(df, result['trades'], result['final_capital'], result['daily_balance'])
            
            # 거래 내역 표시
            if result['trades']:
                self.show_trade_log_dialog(result['trades'])
                
        except Exception as e:
            self.backtestStatus.append(f"결과 처리 중 오류 발생: {str(e)}")
            traceback.print_exc()

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

    def setup_logging(self):
        """로깅 설정"""
        try:
            # 로그 디렉토리 생성
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            # 로그 파일 경로 설정
            log_file = os.path.join(log_dir, 'autotrade.log')
            print(f"[DEBUG] 로그 파일 경로: {log_file}")  # 디버그용 출력
            
            # 로거 설정
            self.logger = logging.getLogger('AutoTrade')
            self.logger.setLevel(logging.DEBUG)
            
            # 파일 핸들러 설정
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            
            # 포맷터 설정
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            
            # 핸들러 추가
            self.logger.addHandler(file_handler)
            
            # 초기 로그 메시지
            self.logger.info('로깅 시스템 초기화 완료')
            print("[DEBUG] 로깅 시스템 초기화 완료")  # 디버그용 출력
            
        except Exception as e:
            print(f"[ERROR] 로깅 설정 중 오류 발생: {str(e)}")
            # 로깅 설정 실패 시에도 기본 로거 생성
            self.logger = logging.getLogger('AutoTrade')
            self.logger.setLevel(logging.DEBUG)
            # 콘솔 핸들러 추가
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
            self.logger.error(f'로깅 설정 실패: {str(e)}')

    def update_backtest_param_page(self, strategy):
        strategy_to_index = {
            "RSI": 0,
            "볼린저밴드": 1,
            "MACD": 2,
            "이동평균선 교차": 3,
            "스토캐스틱": 4,
            "ATR 기반 변동성 돌파": 5,
            "거래량 프로파일": 6,
            "머신러닝": 7
        }
        idx = strategy_to_index.get(strategy, 0)
        self.backtestParamStackedWidget.setCurrentIndex(idx)
