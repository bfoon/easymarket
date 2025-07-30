# marketplace/background.py
from concurrent.futures import ThreadPoolExecutor

# A small pool is usually enough; tune as needed
executor = ThreadPoolExecutor(max_workers=4)

def submit(fn, *args, **kwargs):
    # Helper so callers don’t import executor directly
    return executor.submit(fn, *args, **kwargs)
