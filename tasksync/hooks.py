import json
import os

from tasksync.models import TaskwarriorTask, TaskwarriorStatus
from todoist_api_python.api import TodoistAPI
import tzlocal

def on_add(task_json_input, api) -> tuple[str, str]:
    '''
    on-add hook for Taskwarrior

    Parameters
    ----------
    task_json_input : str
        Input str emitted by Taskwarrior on task add
    api : TodoistAPI
        api object

    Returns
    -------
    task_json_final : str
        Updated input str with newly added fields
    feedback : str
        Feedback str, printed by Taskwarrior after hook is completed
    '''
    # Preallocate output
    feedback = ''

    # Read input
    task = TaskwarriorTask.from_taskwarrior(json.loads(task_json_input))

    # Create task
    res = api.add_task(**task.to_todoist_api_kwargs())
    task.todoist = res.id
    task.timezone = tzlocal.get_localzone_name()
    feedback = 'Todoist: task created'
    return (task.to_json(), feedback)


def on_modify(task_json_input, task_json_output, api) -> tuple[str, str]:
    '''
    on-modify hook for Taskwarrior to sync local changes to Todoist

    Parameters
    ----------
    task_json_input : str
        Original JSON str of task emitted by Taskwarrior
    task_json_output : str
        Modified JSON str of task emitted by Taskwarrior
    api : TodoistAPI
        api object

    Returns
    -------
    task_json_final : str
        Updated JSON str with newly updated fields
    feedback : str
        Feedback str, printed by Taskwarrior after hook is completed
    '''
    # Preallocate output
    feedback = ''

    # Read inputs
    task_input = TaskwarriorTask.from_taskwarrior(json.loads(task_json_input))
    task_output = TaskwarriorTask.from_taskwarrior(json.loads(task_json_output))
    
    # Only perform API calls if there's something worth updating
    # - Update required if task was deleted
    # - Update required if any supported fields were modified
    # - No update required otherwise
    if task_output.status == TaskwarriorStatus.DELETED and task_output.todoist:
        res = api.delete_task(task_id=task_output.todoist)
        feedback += 'Todoist: task deleted'
    elif check_supported_todoist_fields(task_input, task_output):
        if task_output.todoist is not None:
            res = api.update_task(**task_output.to_todoist_api_kwargs())
            feedback += 'Todoist: task updated'
        else:
            kwargs = task_output.to_todoist_api_kwargs()
            res = api.add_task(**kwargs)
            task_output.todoist = res.id
            task_output.timezone = tzlocal.get_localzone_name()
            feedback += 'Todoist: task created (did not exist)'
    else:
        feedback += 'Todoist: update not required'
    return (task_output.to_json(exclude_id=True), feedback)

def check_supported_todoist_fields(task_input, task_output):
    '''
    Check if any supported Todoist fields have been updated

    Parameters
    ----------
    task_input : TaskwarriorTask
        object created from original JSON str input
    task_output : TaskwarriorTask
        object created from updated JSON str input

    Returns
    -------
    updated : bool
        indicates whether Todoist should be updated
    '''
    task_input_kwargs = task_input.to_todoist_api_kwargs()
    task_output_kwargs = task_output.to_todoist_api_kwargs()
    keys_triggering_update = set(task_input_kwargs.keys()).union(set(task_output_kwargs.keys()))
    for key in keys_triggering_update:
        if task_input_kwargs.get(key, None) != task_output_kwargs.get(key, None):
            return True
    return False
