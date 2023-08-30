from __future__ import annotations

from typing import TypedDict
from zoneinfo import ZoneInfo
import uuid

from tasksync.models import (
    TaskwarriorDatetime,
    TaskwarriorDict,
    TaskwarriorPriority,
    TaskwarriorStatus,
    TaskwarriorTask,
)
from tasksync.sync import TodoistSyncDataStore

TODOIST_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'

class TodoistSyncDue(TypedDict, total=False):
    date : str
    timezone : str | None
    string : str | None
    lang : str
    is_recurring : bool

def date_from_taskwarrior(date : TaskwarriorDatetime, timezone : str) -> TodoistSyncDue:
    out = TodoistSyncDue({
        'timezone': timezone,
        'is_recurring': False,
    })
    due_datetime = date.astimezone(ZoneInfo(timezone))
    if due_datetime.hour == 0 and due_datetime.minute == 0:
        out['date'] = date.strftime('%Y-%m-%d')
    else:
        out['date'] = date.strftime(TODOIST_DATETIME_FORMAT)
    return out

def add_item(task: TaskwarriorTask, store: TodoistSyncDataStore) -> list:
    ops = []
    data = {
        'type': 'item_add',
        'temp_id': str(uuid.uuid4()),
        'uuid': str(uuid.uuid4()),
        'args': {
            'content': task.description,
        }
    }
    if task.project and (project := store.find('projects', name=task.project)):
        data['args']['project_id'] = project['id']
    if task.due:
        data['args']['due'] = date_from_taskwarrior(task.due, task.timezone)
    if task.priority:
        data['args']['priority'] = task.priority.to_todoist()
    if len(task.tags) > 0:
        data['args']['labels'] = task.tags
    ops.append(data)
    return ops

def update_item(task_old: TaskwarriorTask, task_new: TaskwarriorTask, store: TodoistSyncDataStore) -> list:
    ops = []
    args = {}

    # Description
    if task_old.description != task_new.description:
        args['content'] = task_new.description

    # Due date
    if _check_update(task_old, task_new, 'due'):
        args['due'] = date_from_taskwarrior(task_new.due, task_new.timezone)  # type: ignore
    elif _check_remove(task_old, task_new, 'due'):
        args['due'] = None

    # Priority
    if _check_update(task_old, task_new, 'priority'):
        args['priority'] = task_new.priority.to_todoist() # type: ignore
    elif _check_remove(task_old, task_new, 'priority'):
        args['priority'] = 1

    # Labels
    if _check_update(task_old, task_new, 'tags'):
        args['labels'] = task_new.tags

    # Build payload
    if len(args) > 0:
        data = {
            'type': 'item_update',
            'uuid': str(uuid.uuid4()),
            'args': {
                'id': str(task_new.todoist),
                **args,
            }
        }
        ops.append(data)
    return ops

def move_item(task_old: TaskwarriorTask, task_new: TaskwarriorTask, store: TodoistSyncDataStore) -> list:
    ops = []
    data = {
        'type': 'item_move',
        'uuid': str(uuid.uuid4()),
        'args': {
            'id': str(task_new.todoist),
        }
    }

    # Project 
    if _check_update(task_old, task_new, 'project'):
        if project := store.find('projects', name=task_new.project):
            data['args']['project_id'] = project['id']
        else:
            # Project does not exist -- we need to create it
            ops.extend(create_project(name=task_new.project, temp_id=str(uuid.uuid4()))) # type: ignore
            data['args']['project_id'] = ops[-1]['temp_id']
    elif _check_remove(task_old, task_new, 'project'):
        if project := store.find('projects', name='Inbox'):
            data['args']['project_id'] = project['id']
        else:
            raise RuntimeError(
                'Attempting to move task to Inbox, but Inbox project not found in data store!'
            )
    ops.append(data)
    return ops

def delete_item(task_old: TaskwarriorTask, task_new: TaskwarriorTask, store: TodoistSyncDataStore) -> list:
    ops = []
    if task_old.status != TaskwarriorStatus.DELETED and task_new.status == TaskwarriorStatus.DELETED:
        data = {
            'type': 'item_delete',
            'uuid': str(uuid.uuid4()),
            'args': {
                'id': str(task_new.todoist),
            }
        }
        ops.append(data)
    return ops

def complete_item(task_old: TaskwarriorTask, task_new: TaskwarriorTask, store: TodoistSyncDataStore) -> list:
    ops = []
    if task_old.status != TaskwarriorStatus.COMPLETED and task_new.status == TaskwarriorStatus.COMPLETED:
        data = {
            'type': 'item_complete',
            'uuid': str(uuid.uuid4()),
            'args': {
                'id': str(task_new.todoist),
            }
        }
        if task_new.end is not None:
            data['args']['date_completed'] = task_new.end.strftime(TODOIST_DATETIME_FORMAT)
        ops.append(data)
    return ops

def uncomplete_item(task_old: TaskwarriorTask, task_new: TaskwarriorTask, store: TodoistSyncDataStore) -> list:
    ops = []
    if task_old.status == TaskwarriorStatus.COMPLETED and task_new.status != TaskwarriorStatus.COMPLETED:
        data = {
            'type': 'item_uncomplete',
            'uuid': str(uuid.uuid4()),
            'args': {
                'id': str(task_new.todoist),
            }
        }
        ops.append(data)
    return ops

def create_project(name : str,
                   temp_id : str | None = None,
                   color : str | None = None,
                   parent_id : str | None = None,
                   child_order : int | None = None,
                   is_favorite : bool | None = None,
                   view_style : str | None = None
                   ) -> list:
    ops = []
    data = {
        'type': 'project_add',
        'uuid': str(uuid.uuid4()),
        'args': {
            'name': name,
        }
    }
    if temp_id:
        data['temp_id'] = temp_id
    if color:
        data['args']['color'] = color
    if parent_id:
        data['args']['parent_id'] = parent_id
    if child_order is not None:
        data['args']['child_order'] = child_order
    if is_favorite is not None:
        data['args']['is_favorite'] = is_favorite
    if view_style is not None:
        data['args']['view_style'] = view_style
    ops.append(data) 
    return ops

def _check_update(task_old: TaskwarriorTask, task_new: TaskwarriorTask, attr : str) -> bool:
    oldval = getattr(task_old, attr)
    newval = getattr(task_new, attr)
    return newval is not None and (oldval is None or (oldval != newval))

def _check_remove(task_old: TaskwarriorTask, task_new: TaskwarriorTask, attr: str) -> bool:
    oldval = getattr(task_old, attr)
    newval = getattr(task_new, attr)
    return oldval is not None and newval is None