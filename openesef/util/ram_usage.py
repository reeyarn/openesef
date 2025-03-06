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
"""

import psutil
import os
#import time
#import gc


def get_process_memory():
    """Get current process memory usage in GB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024 / 1024  # Convert bytes to GB

def check_memory_usage(threshold_gb=16, sleep_sec=1):
    """
    Check if memory usage is approaching dangerous levels
    
    Args:
        threshold_gb (float): Maximum allowed memory usage in GB
        sleep_sec (int): Seconds to sleep before checking again
    
    Raises:
        MemoryError: If memory usage exceeds threshold
    """
    process = psutil.Process(os.getpid())
    memory_gb = process.memory_info().rss / 1024 / 1024 / 1024  # Convert bytes to GB
    if memory_gb > threshold_gb:
        # # Sleep briefly to allow other cleanup processes to run
        # time.sleep(sleep_sec)
        # # Check again after sleep
        # memory_gb = get_process_memory()
        # if memory_gb > threshold_gb:
        raise MemoryError(f"Process memory usage ({memory_gb:.1f}GB) exceeded threshold ({threshold_gb}GB)")
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
