"""Durable owner-scoped metadata/metrics refresh, independent of web sessions."""
import os
import logging
from datetime import datetime,timezone,timedelta


def interval_hours():
    try:value=int(os.environ.get('PM_ANALYTICS_SYNC_HOURS','12'))
    except ValueError:value=12
    return value if value in (12,24) else 12


def enqueue_due(central,workspaces):
    hours=interval_hours();now=datetime.now(timezone.utc);queued=0
    with central() as db:
        rows={row['user_id']:row for row in db.execute('''SELECT s.* FROM public.pm_sync_requests s
            JOIN public.pm_users u ON u.id=s.user_id WHERE u.active''').fetchall()}
        for owner,workspace in workspaces.items():
            try:
                row=rows.get(owner)
                if row:
                    if row['processed_at'] is None or row['requested_at']>row['processed_at']:continue
                    due=row['next_auto_at'] or (row['finished_at'] or row['requested_at'])+timedelta(hours=hours)
                    if due>now:continue
                # Roll back only this owner's queue operation if it fails.
                with db.transaction():
                    with workspace.manager.store.connect() as store:
                        eligible=store.execute("SELECT 1 FROM connections WHERE connected=1 AND encrypted_token IS NOT NULL AND status NOT IN ('invalid','api_access_blocked') LIMIT 1").fetchone()
                    accepted=eligible and db.execute("SELECT pm_request_sync(%s,'auto',%s) queued",(owner,hours)).fetchone()['queued']
                queued+=int(bool(accepted))
            except Exception as error:logging.getLogger(__name__).warning('Workspace %s automatic sync check failed (%s)',owner,type(error).__name__)
    return queued
