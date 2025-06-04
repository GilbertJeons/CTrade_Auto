from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5 import uic
import pyupbit
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sqlite3
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import mplfinance as mpf
import matplotlib.dates as mdates
import python_bithumb
import matplotlib.pyplot as plt

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

class ChartWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('차트')
        self.setGeometry(100, 100, 1200, 800)
        
        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 상단 컨트롤 영역
        control_layout = QHBoxLayout()
        
        # 코인 선택
        self.coin_combo = QComboBox()
        self.coin_combo.addItems(['BTC', 'ETH', 'XRP', 'SOL', 'ADA'])
        control_layout.addWidget(QLabel('코인:'))
        control_layout.addWidget(self.coin_combo)
        
        # 시간 간격 선택
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(['1분', '3분', '5분', '15분', '30분', '60분', '240분', '일', '주', '월'])
        control_layout.addWidget(QLabel('시간 간격:'))
        control_layout.addWidget(self.interval_combo)
        
        # 데이터 개수 선택
        self.count_combo = QComboBox()
        self.count_combo.addItems(['30', '50', '100', '200'])
        control_layout.addWidget(QLabel('데이터 개수:'))
        control_layout.addWidget(self.count_combo)
        
        # 차트 조회 버튼
        self.candle_btn = QPushButton('차트 조회')
        self.candle_btn.clicked.connect(self.get_candle_data)
        control_layout.addWidget(self.candle_btn)
        
        # 실시간 차트 버튼
        self.realtime_btn = QPushButton('실시간 차트')
        self.realtime_btn.clicked.connect(self.open_realtime_chart_window)
        control_layout.addWidget(self.realtime_btn)
        
        # 레이아웃에 위젯 추가
        layout.addLayout(control_layout)
        
        # 차트 영역
        self.chart_widget = QWidget()
        chart_layout = QVBoxLayout(self.chart_widget)
        
        # 캔들 차트
        self.figure = Figure(figsize=(12, 6))
        self.canvas = FigureCanvas(self.figure)
        chart_layout.addWidget(self.canvas)
        
        layout.addWidget(self.chart_widget)
        
        # 정보 표시 영역
        self.info_text = QTextEdit()
        self.info_text.setMaximumHeight(100)
        layout.addWidget(self.info_text)
        
        # 실시간 차트 관련 변수
        self.realtime_chart_window = None
        self.realtime_running = False
        self.realtime_timer = QTimer()
        self.realtime_timer.timeout.connect(self.fetch_realtime_data)
        self.realtime_price_data = []
        self.realtime_time_data = []
        self.realtime_volume_data = []
        self.realtime_ycenter = None
        
    def get_candle_data(self):
        try:
            coin = self.coin_combo.currentText()
            interval_text = self.interval_combo.currentText()
            count = int(self.count_combo.currentText())
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
            market = f"KRW-{coin}"
            interval = interval_map.get(interval_text, "minute1")
            df = python_bithumb.get_ohlcv(market, interval=interval, count=count)
            
            if df is not None and not df.empty:
                self.figure.clear()
                ax = self.figure.add_subplot(111)
                mc = mpf.make_marketcolors(up='red', down='blue', edge='inherit', wick='inherit', volume='in')
                s = mpf.make_mpf_style(marketcolors=mc, gridstyle='dotted', y_on_right=False)
                mpf.plot(df, type='candle', style=s, ax=ax, volume=False, show_nontrading=True)
                ax.set_title(f"{market} {interval_text} 캔들스틱 차트")
                ax.set_xlabel('시간')
                ax.set_ylabel('가격')
                self.figure.autofmt_xdate()
                ax.grid(True, linestyle='--', alpha=0.7)
                self.figure.tight_layout()
                self.canvas.draw()
                self.update_info(df)
        except Exception as e:
            self.info_text.append(f"캔들 데이터 조회 실패: {str(e)}")
            
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
        self.realtime_ycenter = None
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
            coin = self.coin_combo.currentText()
            price = python_bithumb.get_current_price(f"KRW-{coin}")
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
            
    def update_realtime_chart(self):
        if not self.realtime_running or self.realtime_figure is None:
            return
        try:
            self.realtime_figure.clear()
            # 가격 차트
            ax1 = self.realtime_figure.add_subplot(211)
            ax1.plot(self.realtime_time_data, self.realtime_price_data, 'b-', label='현재가')
            ax1.set_title(f'{self.coin_combo.currentText()} 실시간 차트')
            ax1.set_ylabel('가격')
            ax1.grid(True, alpha=0.3)
            # x축 포맷: 날짜/시간 자동
            if len(self.realtime_time_data) > 0:
                if (self.realtime_time_data[-1] - self.realtime_time_data[0]).days >= 1:
                    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                else:
                    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
            # 거래량 차트
            ax2 = self.realtime_figure.add_subplot(212)
            if len(self.realtime_volume_data) > 0:
                ax2.bar(self.realtime_time_data[1:], self.realtime_volume_data, color='g', alpha=0.5, label='거래량')
            ax2.set_xlabel('시간')
            ax2.set_ylabel('거래량')
            ax2.grid(True, alpha=0.3)
            if len(self.realtime_time_data) > 0:
                if (self.realtime_time_data[-1] - self.realtime_time_data[0]).days >= 1:
                    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                else:
                    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
            self.realtime_figure.tight_layout()
            self.realtime_canvas.draw()
        except Exception as e:
            print(f'실시간 차트 업데이트 실패: {str(e)}')
            
    def update_info(self, df):
        try:
            coin = self.coin_combo.currentText()
            current_price = python_bithumb.get_current_price(f"KRW-{coin}")
            
            info_text = f"\n=== {coin} 차트 정보 ===\n"
            info_text += f"현재가: {current_price:,.0f}원\n"
            info_text += f"시작가: {df.iloc[0]['open']:,.0f}원\n"
            info_text += f"종가: {df.iloc[-1]['close']:,.0f}원\n"
            info_text += f"고가: {df['high'].max():,.0f}원\n"
            info_text += f"저가: {df['low'].min():,.0f}원\n"
            info_text += f"거래량: {df['volume'].sum():,.0f}\n"
            
            # 가격 변동률 계산
            price_change = ((current_price - df.iloc[0]['open']) / df.iloc[0]['open']) * 100
            info_text += f"변동률: {price_change:+.2f}%\n"
            
            self.info_text.setText(info_text)
            
        except Exception as e:
            self.info_text.append(f"정보 업데이트 실패: {str(e)}") 