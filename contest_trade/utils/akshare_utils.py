"""
akshare 的工具函数

"""
import json
import hashlib
import pickle
from pathlib import Path
from datetime import datetime
from config.config import cfg

import akshare as ak

DEFAULT_AKSHARE_CACHE_DIR = Path(__file__).parent / "akshare_cache"

class CachedAksharePro:
    def __init__(self, cache_dir=None):
        if not cache_dir:
            self.cache_dir = DEFAULT_AKSHARE_CACHE_DIR
        else:
            self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def run(self, func_name: str, func_kwargs: dict, verbose: bool = False):
        func_kwargs_str = json.dumps(func_kwargs)
        return self.run_with_cache(func_name, func_kwargs_str, verbose)

    def run_with_cache(self, func_name: str, func_kwargs: str, verbose: bool = False):
        func_kwargs = json.loads(func_kwargs)
        args_hash = hashlib.md5(str(func_kwargs).encode()).hexdigest()
        trigger_time = datetime.now().strftime("%Y%m%d%H")
        args_hash = f"{args_hash}_{trigger_time}"
        func_cache_dir = self.cache_dir / func_name
        if not func_cache_dir.exists():
            func_cache_dir.mkdir(parents=True, exist_ok=True)
        func_cache_file = func_cache_dir / f"{args_hash}.pkl"
        if func_cache_file.exists():
            if verbose:
                print(f"load result from {func_cache_file}")
            with open(func_cache_file, "rb") as f:
                return pickle.load(f)
        else:
            if verbose:
                print(f"cache miss for {func_name} with args: {func_kwargs}")
            result = getattr(ak, func_name)(**func_kwargs)
            if verbose:
                print(f"save result to {func_cache_file}")
            with open(func_cache_file, "wb") as f:
                pickle.dump(result, f)
            return result

akshare_cached = CachedAksharePro()

if __name__ == "__main__":
    stock_sse_summary_df = akshare_cached.run(
        func_name="stock_sse_summary", 
        func_kwargs={},
        verbose=True
    )
    print(stock_sse_summary_df)