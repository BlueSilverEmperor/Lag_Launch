"""
core/queue.py
-------------
Local Multiprocessing Task Queue.

Decouples long-running inference and hashing tasks from the Flask UI thread
using a robust ProcessPoolExecutor, preventing deadlocks and SSE starvation.
"""

import queue
from concurrent.futures import ThreadPoolExecutor
import time

class TaskQueue:
    def __init__(self, max_workers=2):
        # We enforce a ThreadPoolExecutor since Embedded local Qdrant 
        # utilizes aggressive File Locking forbidding multi-process concurrency
        # PyTorch cleanly releases the GIL natively, so Threads are optimal.
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Real-time message buses for SSE streams
        self.buses = {}
    
    def get_bus(self, job_id: str):
        """Get or create an IPC proxy queue for real time logging."""
        if job_id not in self.buses:
            self.buses[job_id] = queue.Queue()
        return self.buses[job_id]
        
    def enqueue(self, job_id: str, func, *args, **kwargs):
        """Submit a job to a background process."""
        q = self.get_bus(job_id) # ensure bus exists
        # Execute func async
        future = self.executor.submit(func, q, job_id, *args, **kwargs)
        
        # Optionally cleanup buses after job finishes
        def _cleanup(f):
             # Small delay to let SSE clear events
             time.sleep(5)
             self.buses.pop(job_id, None)
        future.add_done_callback(_cleanup)
        return future

# Global singleton
_queue = None

def get_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue(max_workers=3) # Allow 3 heavy inference jobs
    return _queue
