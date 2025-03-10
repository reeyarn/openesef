"""
Let me explain the performance implications of check_memory_usage():
Cost Analysis:
The main operation is calling psutil.Process(os.getpid()) and getting memory info
This is a relatively lightweight operation that typically takes microseconds to low milliseconds
It doesn't scan through memory or perform any heavy calculations
The commented-out sleep code (which is currently disabled) would have added 1 second delay, but it's not active

requency Recommendations:
For most applications, checking every few seconds is more than sufficient
Common patterns:
Every 5-10 seconds for memory-intensive applications
Every 30-60 seconds for normal applications
Before/after large operations that might cause memory spikes
If you're running very memory-intensive operations, you might want to check more frequently (e.g., every second)
If memory usage changes slowly in your application, checking less frequently (every minute) might be fine
Best Practices:
Don't check on every iteration of tight loops
Consider implementing a cooldown period (e.g., minimum time between checks)
Focus checks around operations that you know might cause memory spikes
The function is efficient enough that even checking it frequently won't cause significant performance overhead, 
but there's usually no need to check more often than every second or two unless you have specific requirements.


main.openesf.util.ram_usage.INFO: [ Top 60 ]
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:45: size=28.8 MiB, count=54879, average=549 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/miniconda3/lib/python3.11/site-packages/fs/memoryfs.py:202: size=4332 KiB, count=6, average=722 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:336: size=3017 KiB, count=18293, average=169 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:12: size=2428 KiB, count=18347, average=135 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/instance/fact.py:12: size=2415 KiB, count=1310, average=1888 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:48: size=2404 KiB, count=18293, average=135 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/ebase.py:33: size=1990 KiB, count=31845, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:9: size=1921 KiB, count=18300, average=107 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:11: size=1920 KiB, count=18295, average=107 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/ebase.py:49: size=1877 KiB, count=20706, average=93 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:10: size=1784 KiB, count=18347, average=100 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/arc.py:22: size=1400 KiB, count=15258, average=94 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/util.py:111: size=1322 KiB, count=16491, average=82 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:19: size=1259 KiB, count=18293, average=70 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/xlink.py:134: size=1258 KiB, count=10062, average=128 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/ebase.py:56: size=1222 KiB, count=21471, average=58 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:52: size=1143 KiB, count=18293, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:46: size=1143 KiB, count=18293, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:44: size=1143 KiB, count=18293, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:43: size=1143 KiB, count=18293, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:16: size=1060 KiB, count=18293, average=59 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/xlink.py:137: size=1058 KiB, count=10826, average=100 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/ebase.py:38: size=1044 KiB, count=5698, average=188 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/ebase.py:36: size=1019 KiB, count=16158, average=65 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:17: size=1014 KiB, count=18293, average=57 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/util.py:107: size=1001 KiB, count=17281, average=59 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/schema.py:100: size=1000 KiB, count=18293, average=56 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/ebase.py:35: size=840 KiB, count=16158, average=53 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/util.py:127: size=809 KiB, count=5464, average=152 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/arc.py:21: size=752 KiB, count=8219, average=94 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/locator.py:19: size=648 KiB, count=5413, average=123 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/xlink.py:109: size=645 KiB, count=6108, average=108 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/arc.py:9: size=599 KiB, count=5031, average=122 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/engines/tax_pres.py:869: size=596 KiB, count=1466, average=416 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/arc.py:8: size=592 KiB, count=5031, average=121 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/locator.py:20: size=553 KiB, count=5413, average=105 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/locator.py:21: size=505 KiB, count=5413, average=96 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/engines/tax_pres.py:1020: size=470 KiB, count=1203, average=400 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/arc.py:10: size=465 KiB, count=5031, average=95 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:13: size=435 KiB, count=7, average=62.1 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:49: size=434 KiB, count=8, average=54.3 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/base/element.py:15: size=434 KiB, count=8, average=54.3 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/concept.py:18: size=411 KiB, count=7729, average=54 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:341: size=405 KiB, count=1, average=405 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:339: size=405 KiB, count=1, average=405 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:337: size=405 KiB, count=1, average=405 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:334: size=405 KiB, count=1, average=405 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/xlink.py:44: size=385 KiB, count=948, average=416 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/instance/m_xbrl.py:103: size=336 KiB, count=2776, average=124 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/miniconda3/lib/python3.11/site-packages/pandas/core/dtypes/concat.py:78: size=333 KiB, count=17, average=19.6 KiB
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/resource.py:9: size=305 KiB, count=3054, average=102 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/resource.py:11: size=285 KiB, count=3054, average=95 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:550: size=262 KiB, count=3054, average=88 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/resource.py:10: size=260 KiB, count=3054, average=87 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/engines/tax_pres.py:776: size=238 KiB, count=1794, average=136 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/engines/tax_pres.py:315: size=195 KiB, count=1470, average=136 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/resource.py:7: size=191 KiB, count=3054, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/taxonomy.py:548: size=176 KiB, count=2217, average=81 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/instance/fact.py:17: size=174 KiB, count=2780, average=64 B
main.openesf.util.ram_usage.INFO: /Users/mbp16/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/openesef/taxonomy/resource.py:15: size=170 KiB, count=2766, average=63 B
"""

import psutil
import os
import logging
#import time
#import gc
import tracemalloc
from openesef.util.util_mylogger import setup_logger 
if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.util.ram_usage")



import psutil   
from contextlib import contextmanager
@contextmanager
def memory_check(threshold_gb: int):
    try:
        yield
    finally:
        if psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024 / 1024 > threshold_gb:
            raise MemoryError(f"Memory usage exceeded {threshold_gb}GB threshold")


import multiprocessing.pool
import functools


def timeout(max_timeout):
    """Timeout decorator, parameter in seconds."""
    def timeout_decorator(item):
        """Wrap the original function."""
        @functools.wraps(item)
        def func_wrapper(*args, **kwargs):
            """Closure for function."""
            pool = multiprocessing.pool.ThreadPool(processes=1)
            async_result = pool.apply_async(item, args, kwargs)
            try:
                # raises a TimeoutError if execution exceeds max_timeout
                return async_result.get(max_timeout)
            except TimeoutError:
                #logger.warning("Timeout occurred for function: %s", item.__name__)
                parameter_string = ", ".join([repr(arg) for arg in args] + [f"{k}={repr(v)}" for k, v in kwargs.items()])
                logger.warning("Timeout occurred for function: %s, Parameters: %s", item.__name__, parameter_string)                
                # Re-raise the TimeoutError
                raise TimeoutError
        return func_wrapper
    return timeout_decorator

def mem_tops(top_n=10):
    snapshot = tracemalloc.take_snapshot()  
    top_stats = snapshot.statistics('lineno')  # Group by line number

    logger.info(f"[ Top {top_n} ]")
    for stat in top_stats[:top_n]:
        logger.info(stat)   

def get_process_memory():
    """Get current process memory usage in GB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024 / 1024  # Convert bytes to GB

def get_system_memory():
    """Get system memory usage including swap"""
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        'total_gb': vm.total / 1024 / 1024 / 1024,
        'available_gb': vm.available / 1024 / 1024 / 1024,
        'used_gb': vm.used / 1024 / 1024 / 1024,
        'swap_used_gb': swap.used / 1024 / 1024 / 1024,
        'swap_free_gb': swap.free / 1024 / 1024 / 1024
    }

def check_memory_usage(threshold_gb=8, swap_threshold_gb=0):
    """
    Check if memory usage is approaching dangerous levels
    
    Args:
        threshold_gb (float): Maximum allowed RAM usage in GB
        swap_threshold_gb (float): Maximum allowed swap usage in GB
    
    Raises:
        MemoryError: If memory usage exceeds threshold
    """
    if threshold_gb is None or threshold_gb <= 0:
        return None
    process = psutil.Process(os.getpid())
    memory_gb = process.memory_info().rss / 1024 / 1024 / 1024
    
    # Get system memory stats
    sys_memory = get_system_memory()
    
    # Log memory status
    logger.info(f"Process memory: {memory_gb:.1f}GB")
    logger.info(f"System memory - Available: {sys_memory['available_gb']:.1f}GB, "
               f"Swap used: {sys_memory['swap_used_gb']:.1f}GB")
    
    # Check process memory
    if memory_gb > threshold_gb:
        msg = f"Process memory usage ({memory_gb:.1f}GB) exceeded threshold ({threshold_gb}GB)"
        logger.error(msg)
        raise MemoryError(msg)
    
    if swap_threshold_gb>0:    
        # Check swap usage
        if sys_memory['swap_used_gb'] > swap_threshold_gb:
            msg = (f"System swap usage ({sys_memory['swap_used_gb']:.1f}GB) "
                f"exceeded threshold ({swap_threshold_gb}GB)")
            logger.error(msg)
            raise MemoryError(msg)
    
    return memory_gb

def safe_numeric_conversion(value, default=None):
    """
    Safely convert a value to a numeric type, handling large integers.
    
    Args:
        value: The value to convert
        default: Default value to return if conversion fails
        
    Returns:
        float or default value if conversion fails
    """
    if value is None:
        return default
        
    try:
        # First try float conversion
        return float(value)
    except (ValueError, OverflowError):
        try:
            # For very large integers, try scientific notation
            return float(f"{float(value):.2e}")
        except (ValueError, OverflowError):
            return default
