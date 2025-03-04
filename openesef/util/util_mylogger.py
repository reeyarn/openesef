import logging
import datetime
#import inspect
#import sys

import logging
import datetime
import os

def setup_logger(name, level=logging.INFO, level_file=None, log_dir="/tmp", include_console=True, full_format=True, formatter_string=None, pid=None):
    """
    Set up logger with file handler including date and PID
    
    Args:
        name: Logger name
        log_dir: Directory for log files
        include_console: Whether to add console handler
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True) 

    if not level_file:
        level_file = level 

    # Get current date and PID
    today = datetime.datetime.now().strftime('%Y%m%d')
    if pid is None:
        pid = os.getpid()
    
    # Create log filename
    log_filename = os.path.join(log_dir, f"log_{name}_{today}_p{pid}.log")
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Clear any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Create file handler
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(level_file)
    
    # Create formatter
    if full_format:
        if formatter_string is None:
            formatter_string = '%(asctime)s - %(name)s - PID:%(process)d - %(levelname)s - %(message)s'
        
        formatter = logging.Formatter(formatter_string)
    else:
        formatter = logging.Formatter(
            '%(message)s'
        )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Add console handler if requested
    if include_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    #return logger, log_filename
    return logger
# Set up logger
if __name__ == "__main__":
    logger, log_file = setup_logger(__name__)
    logger.info(f"Logging to: {log_file}")
    logger.info("Starting application")
    #do_something()
