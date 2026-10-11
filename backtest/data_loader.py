"""
================================================================================
数据加载模块
================================================================================
【功能】
    加载和预处理回测所需的所有数据

================================================================================
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime

# 数据路径（Sprint 0: 自适应本地/服务器，支持 FINBACK_BASE_DIR 环境变量覆盖）
_BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getenv("FINBACK_BASE_DIR"):
    DATA_DIR = os.path.join(os.environ["FINBACK_BASE_DIR"], 'data')
elif os.path.isdir(os.path.join(_BACKTEST_DIR, "..", "data")):
    DATA_DIR = os.path.normpath(os.path.join(_BACKTEST_DIR, "..", "data"))
else:
    DATA_DIR = '/home/ubuntu/FinTech/data'
PROCESSED_DIR = os.path.join(DATA_DIR, 'processed')
RAW_DIR = os.path.join(DATA_DIR, 'raw')


class DataLoader:
    """数据加载器"""
    
    def __init__(self):
        self.stock_data = None
        self.index_data = None
        self.industry_mapping = None
        self.industry_returns = None
        self.financial_data = None
        
    def load_all(self):
        """加载所有数据"""
        print("正在加载数据...")
        
        # 1. 加载股票日K线数据
        # Sprint 0-2: 优先使用前复权数据 hs300_daily_qfq.csv（消除除权除息跳空假收益）
        # 若复权文件尚未生成，回退到未复权 hs300_daily_cleaned.csv
        print("  加载股票日K线数据...")
        qfq_file = os.path.join(PROCESSED_DIR, 'hs300_daily_qfq.csv.gz')
        if not os.path.exists(qfq_file):
            qfq_file = os.path.join(PROCESSED_DIR, 'hs300_daily_qfq.csv')
        if os.path.exists(qfq_file):
            self.stock_data = pd.read_csv(
                qfq_file,
                dtype={'stock_code': str}
            )
            self.price_basis = 'qfq'  # 前复权
            print("  ✓ 使用前复权数据 (hs300_daily_qfq.csv)")
        else:
            self.stock_data = pd.read_csv(
                os.path.join(PROCESSED_DIR, 'hs300_daily_cleaned.csv'),
                dtype={'stock_code': str}
            )
            self.price_basis = 'raw'  # 未复权
            print("  ⚠ 未找到复权数据，回退到未复权 hs300_daily_cleaned.csv")
        self.stock_data['date'] = pd.to_datetime(self.stock_data['date'])
        self.stock_data = self.stock_data.sort_values(['stock_code', 'date']).reset_index(drop=True)
        print(f"    ✓ {len(self.stock_data):,} 条记录, {self.stock_data['stock_code'].nunique()} 只股票")
        
        # 2. 加载沪深300指数
        print("  加载沪深300指数...")
        self.index_data = pd.read_csv(
            os.path.join(PROCESSED_DIR, 'hs300_index_daily.csv')
        )
        self.index_data['date'] = pd.to_datetime(self.index_data['date'])
        self.index_data = self.index_data.sort_values('date').reset_index(drop=True)
        print(f"    ✓ {len(self.index_data):,} 条记录")
        
        # 3. 加载行业分类
        print("  加载行业分类...")
        self.industry_mapping = pd.read_csv(
            os.path.join(PROCESSED_DIR, 'stock_industry_mapping.csv'),
            dtype={'stock_code': str}
        )
        print(f"    ✓ {len(self.industry_mapping)} 只股票, {self.industry_mapping['industry'].nunique()} 个行业")
        
        # 4. 加载行业收益率
        print("  加载行业收益率...")
        self.industry_returns = pd.read_csv(
            os.path.join(PROCESSED_DIR, 'industry_returns_daily.csv')
        )
        self.industry_returns['date'] = pd.to_datetime(self.industry_returns['date'])
        print(f"    ✓ {len(self.industry_returns):,} 条记录")
        
        # 5. 加载财务数据（历史PE/PB）
        # Sprint 0-3: 使用清洗后数据（删除2026未来数据 + winsorize异常值）
        # 优先加载 financial_monthly_clean.csv，回退到原始文件
        print("  加载历史财务数据...")
        financial_file = os.path.join(PROCESSED_DIR, 'financial_monthly_clean.csv.gz')
        if not os.path.exists(financial_file):
            financial_file = os.path.join(PROCESSED_DIR, 'financial_monthly_clean.csv')
        if not os.path.exists(financial_file):
            financial_file = os.path.join(PROCESSED_DIR, 'financial_monthly.csv')
            print("  ⚠ 未找到 financial_monthly_clean.csv，回退到原始文件（含未来数据）")
        self.financial_data = pd.read_csv(
            financial_file,
            dtype={'stock_code': str}
        )
        self.financial_data['date'] = pd.to_datetime(self.financial_data['date'])
        print(f"    ✓ {len(self.financial_data):,} 条记录")
        
        # 6. 计算股票收益率
        print("  计算股票收益率...")
        self.stock_data['return'] = self.stock_data.groupby('stock_code')['close'].pct_change()
        
        print("\n数据加载完成！")
        return self
    
    def get_stock_returns_pivot(self, start_date=None, end_date=None):
        """获取股票收益率透视表"""
        df = self.stock_data.copy()
        
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]
        
        # 创建收益率透视表
        returns_pivot = df.pivot_table(
            index='date', 
            columns='stock_code', 
            values='return'
        )
        
        return returns_pivot
    
    def get_index_returns(self, start_date=None, end_date=None):
        """获取指数收益率序列"""
        df = self.index_data.copy()
        
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]
        
        return df.set_index('date')['pct_change'] / 100
    
    def get_industry_returns_pivot(self, start_date=None, end_date=None):
        """获取行业收益率透视表"""
        df = self.industry_returns.copy()
        
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]
        
        returns_pivot = df.pivot_table(
            index='date',
            columns='industry',
            values='industry_return'
        )
        
        return returns_pivot / 100  # 转换为小数
    
    def get_stock_industry_map(self):
        """获取股票-行业映射字典"""
        return dict(zip(
            self.industry_mapping['stock_code'],
            self.industry_mapping['industry']
        ))
    
    def get_financial_data_pivot(self, field='pe_ttm'):
        """获取财务数据透视表"""
        df = self.financial_data.copy()
        
        pivot = df.pivot_table(
            index='date',
            columns='stock_code',
            values=field
        )
        
        return pivot


def main():
    """测试数据加载"""
    loader = DataLoader()
    loader.load_all()
    
    # 测试各种数据获取方法
    print("\n=== 数据测试 ===")
    
    stock_returns = loader.get_stock_returns_pivot(start_date='2023-01-01')
    print(f"股票收益率矩阵: {stock_returns.shape}")
    
    index_returns = loader.get_index_returns(start_date='2023-01-01')
    print(f"指数收益率序列: {len(index_returns)}")
    
    industry_returns = loader.get_industry_returns_pivot(start_date='2023-01-01')
    print(f"行业收益率矩阵: {industry_returns.shape}")
    
    industry_map = loader.get_stock_industry_map()
    print(f"行业映射: {len(industry_map)} 只股票")


if __name__ == '__main__':
    main()
