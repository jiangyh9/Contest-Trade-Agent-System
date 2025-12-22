"""
Alpha Vantage 的工具函数

缓存客户端类，提供API请求缓存功能
"""
import json
import requests
from pathlib import Path
import hashlib
import pickle
import time
from config.config import cfg

DEFAULT_ALPHA_VANTAGE_CACHE_DIR = Path(__file__).parent / "alpha_vantage_cache"

class CachedAlphaVantageClient:
    def __init__(self, cache_dir=None, api_key=None):
        if not cache_dir:
            self.cache_dir = DEFAULT_ALPHA_VANTAGE_CACHE_DIR
        else:
            self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取API密钥
        if not api_key:
            api_key = getattr(cfg, 'alpha_vantage_key', None)
        
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"
        self.rate_limit_delay = 0.5  # API限制，每秒最多5次请求

    def run(self, params: dict, verbose: bool = False):
        """
        运行Alpha Vantage API请求并缓存结果
        
        Args:
            params: 请求参数
            verbose: 是否输出详细信息
        """
        params_str = json.dumps(params, sort_keys=True)
        return self.run_with_cache(params_str, verbose)
    
    def run_with_cache(self, params_str: str, verbose: bool = False):
        params = json.loads(params_str)
        
        # 创建缓存文件路径
        function_name = params.get('function', 'unknown')
        cache_key = f"{function_name}_{hashlib.md5(params_str.encode()).hexdigest()}"
        function_cache_dir = self.cache_dir / function_name
        if not function_cache_dir.exists():
            function_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = function_cache_dir / f"{cache_key}.pkl"
        
        # 尝试从缓存加载
        if cache_file.exists():
            if verbose:
                print(f"📁 从缓存加载: {cache_file}")
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        else:
            if verbose:
                print(f"🌐 API请求: {params}")
            
            # 限制API请求频率
            time.sleep(self.rate_limit_delay)
            
            try:
                # 添加API密钥到参数
                params['apikey'] = self.api_key
                
                # 发送请求
                response = requests.get(self.base_url, params=params)
                response.raise_for_status()
                result = response.json()
                
                # 检查API错误响应
                if 'Error Message' in result:
                    raise Exception(f"Alpha Vantage API错误: {result['Error Message']}")
                if 'Note' in result:
                    raise Exception(f"Alpha Vantage API限制: {result['Note']}")
                
                # 保存到缓存
                if verbose:
                    print(f"💾 保存缓存: {cache_file}")
                with open(cache_file, "wb") as f:
                    pickle.dump(result, f)
                
                return result
            except Exception as e:
                if verbose:
                    print(f"❌ API请求失败: {e}")
                raise e

# 创建全局缓存客户端
alpha_vantage_cached = CachedAlphaVantageClient()

if __name__ == "__main__":
    # 简单测试
    test_params = {
        'function': 'TIME_SERIES_DAILY',
        'symbol': 'AAPL',
    }
    
    try:
        result = alpha_vantage_cached.run(test_params, verbose=True)
        print(result)
        print("测试成功，返回数据键:", list(result.keys()) if isinstance(result, dict) else type(result))
    except Exception as e:
        print(f"测试失败: {e}")