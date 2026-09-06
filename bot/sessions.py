from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

GMT7 = pytz.timezone('Asia/Jakarta')

def schedule_session_reminders(scheduler: AsyncIOScheduler, send_fn):
    sessions = {"Asia": "06:00", "London": "14:00", "NewYork": "20:30"}
    for name, t_str in sessions.items():
        h, m = map(int, t_str.split(":"))
        
        rh, rm = (h - 1, m - 30)
        if rm < 0: rh -= 1; rm += 60
        if rh < 0: rh += 24
            
        scheduler.add_job(send_fn, 'cron', hour=rh % 24, minute=rm, args=[name], timezone=GMT7, id=f"session_reminder_{name}")
        
        rh2, rm2 = (h - 1, m - 5) if m >= 5 else (h - 2, 55 + m)
        if rh2 < 0: rh2 += 24
        scheduler.add_job(send_fn, 'cron', hour=rh2 % 24, minute=rm2, args=[name + "_5min"], timezone=GMT7, id=f"session_reminder_{name}_5")