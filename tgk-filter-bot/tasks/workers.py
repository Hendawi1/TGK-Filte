import asyncio
import logging
from tasks.queue import task_queue
from services.messaging import send_message_task

logger = logging.getLogger(__name__)

worker_tasks = []

async def worker(bot_client):
    while True:
        try:
            task = await task_queue.get()
            
            # إنشاء نسخة من task وإزالة bot_client منها
            task_data = task.copy()
            task_data.pop('bot_client', None)
            
            await send_message_task(bot_client, **task_data)
        except asyncio.CancelledError:
            logger.info("Worker task cancelled")
            break
        except Exception as e:
            logger.error(f"Task failed: {str(e)}", exc_info=True)
        finally:
            task_queue.task_done()

async def start_workers(bot_client, num_workers=10):
    global worker_tasks
    for _ in range(num_workers):
        worker_tasks.append(asyncio.create_task(worker(bot_client)))
    logger.info(f"Started {num_workers} workers")

async def stop_workers():
    global worker_tasks
    if worker_tasks:
        logger.info("Stopping workers...")
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        logger.info("All worker tasks stopped")
        worker_tasks = []
